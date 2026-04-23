"""
Monitor de Preços de Ingressos - Neo Química Arena
Busca automaticamente os preços em cada site de parceiro.
"""

import argparse
import asyncio
import json
import os
import re
from datetime import datetime
from playwright.async_api import async_playwright
import mongo_upsert

# ============================================================
# CONFIGURAÇÃO — EDITE AQUI
# ============================================================

def _ler_jogos_config():
    cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        if "jogos" in cfg and isinstance(cfg["jogos"], list) and cfg["jogos"]:
            nomes = []
            for j in cfg["jogos"]:
                if isinstance(j, dict):
                    nomes.append(j.get("nome", ""))
                else:
                    nomes.append(j)
            nomes = [n for n in nomes if n]
            if nomes:
                return nomes
        if "jogo" in cfg and cfg["jogo"]:
            return [cfg["jogo"]]
    except Exception:
        pass
    return ["Corinthians x Internacional"]  # padrão

JOGO_BUSCA = _ler_jogos_config()[0]  # mantido para referências legadas

PARCEIROS = [
    {
        "nome": "Camarote Fielzone",
        "url": "https://camarotefielzone.com.br/",
        "tipo": "fielzone",
        "cor": "#00ff88",
    },
    {
        "nome": "Lounge Brahma",
        "url": "https://loungebrahma.com.br/",
        "tipo": "loungebrahma",
        "cor": "#ffd60a",
    },
    {
        "nome": "Bar do Zeca",
        "url": "https://bardozeca.soudaliga.com.br/",
        "tipo": "soudaliga",
        "cor": "#60a5fa",
    },
    {
        "nome": "Arena Kids",
        "url": "https://arenakidscorinthians.com.br/",
        "tipo": "arenakids",
        "cor": "#f472b6",
    },
    {
        "nome": "Galeria SCCP (Ticket360)",
        "url": "https://www.ticket360.com.br/sub-categoria/1708/camarote-galeria-sccp",
        "tipo": "ticket360",
        "cor": "#a78bfa",
    },
    {
        "nome": "Camarote Fiel Torcedor (Ticket360)",
        "url": "https://www.ticket360.com.br/eventos/pesquisar?s=Fiel+torcedor",
        "tipo": "ticket360_fiel",
        "cor": "#fb923c",
    },
]

# ============================================================
# HELPERS
# ============================================================

def normalizar_jogo(texto):
    import unicodedata
    texto = unicodedata.normalize('NFKD', texto).encode('ascii', 'ignore').decode('ascii')
    texto = re.sub(r'\s*-\s*', '-', texto)  # normaliza "Atletico - MG" → "Atletico-MG"
    return re.sub(r'\s+', ' ', texto.strip().lower())

_ALIASES_JOGO = {
    'atletico-mg':          ['atletico mineiro', 'atletico mg'],
    'atletico mineiro':     ['atletico-mg', 'atletico mg'],
    'athletico-pr':         ['athletico paranaense'],
    'athletico paranaense': ['athletico-pr'],
    'vasco':                ['vasco da gama'],
    'vasco da gama':        ['vasco'],
    'sao paulo':            ['sao paulo fc'],
}

def jogo_corresponde(texto, busca):
    t = normalizar_jogo(texto)
    b = normalizar_jogo(busca)
    partes = b.split(' x ')
    if len(partes) == 2:
        time1, time2 = partes[0].strip(), partes[1].strip()
        time2_variantes = [time2] + _ALIASES_JOGO.get(time2, [])
        return (time1 in t and any(v in t for v in time2_variantes)) or b in t
    return b in t

def extrair_precos_texto(texto):
    padrao = r'R\$\s*[\d.,]+'
    encontrados = re.findall(padrao, texto, re.IGNORECASE)
    return list(dict.fromkeys(encontrados))

def _extrair_nome_jogo(texto: str) -> str:
    """Extrai 'Corinthians x Time' limpando datas e nomes de competição."""
    # Remove tudo após separadores como – | /
    texto = re.split(r'\s*[–\-|/]\s*(?=[A-ZÁÀÃÂÉÊÍÓÔÕÚÇ]{4})', texto)[0].strip()
    # Se texto inteiro for maiúsculo, converte para título para facilitar parsing
    if texto == texto.upper():
        texto = texto.title()
    m = re.search(r'Corinthians\s+x\s+(.+)', texto, re.IGNORECASE)
    if not m:
        return texto
    palavras = m.group(1).split()
    preposicoes = {'da', 'de', 'do', 'das', 'dos'}
    time_parts = []
    for p in palavras:
        if p.isupper() and len(p) >= 3:
            break
        if len(time_parts) >= 3 and p.lower() not in preposicoes:
            break
        time_parts.append(p)
    return f"Corinthians x {' '.join(time_parts)}" if time_parts else texto


_ALIASES_TIMES = {
    'atletico mineiro': 'Atlético-MG',
    'atletico-mg': 'Atlético-MG',
    'atletico mg': 'Atlético-MG',
    'athletico paranaense': 'Athletico-PR',
    'athletico-pr': 'Athletico-PR',
    'vasco da gama': 'Vasco',
    'sao paulo': 'São Paulo',
}

def _normalizar_nome_jogo(nome: str) -> str:
    """Aplica aliases de nomes de times para consistência entre fontes."""
    import unicodedata
    chave = unicodedata.normalize('NFKD', nome).encode('ascii', 'ignore').decode('ascii').lower()
    for alias, canonical in _ALIASES_TIMES.items():
        if alias in chave:
            time_canonical = canonical
            return f"Corinthians x {time_canonical}"
    return nome


def _extrair_data_raw(texto: str) -> str:
    """Extrai string de data de um bloco de texto. Retorna 'dd/mm HHhMM', 'dd/mm' ou ''."""
    # Formato direto: dd/mm HHhMM
    m = re.search(r'(\d{1,2}/\d{2})\s+(\d{1,2}h\d{2})', texto, re.IGNORECASE)
    if m:
        dia_mes = m.group(1)
        partes = dia_mes.split('/')
        return f"{partes[0].zfill(2)}/{partes[1]} {m.group(2)}"
    # Formato Lounge Brahma: dd/mm/yyyy ... JOGO: HHhMM ou HH:MM
    m_data = re.search(r'(\d{1,2}/\d{2})(?:/\d{2,4})?', texto)
    m_hora = re.search(r'JOGO[:\s]+(\d{1,2})[Hh:](\d{2})', texto, re.IGNORECASE)
    if m_data and m_hora:
        partes = m_data.group(1).split('/')
        hora = m_hora.group(1).zfill(2)
        minuto = m_hora.group(2)
        return f"{partes[0].zfill(2)}/{partes[1]} {hora}h{minuto}"
    # Só data: dd/mm ou dd/mm/yyyy
    if m_data:
        partes = m_data.group(1).split('/')
        return f"{partes[0].zfill(2)}/{partes[1]}"
    meses = {
        'janeiro': '01', 'fevereiro': '02', 'março': '03', 'abril': '04',
        'maio': '05', 'junho': '06', 'julho': '07', 'agosto': '08',
        'setembro': '09', 'outubro': '10', 'novembro': '11', 'dezembro': '12',
    }
    for nome_mes, num_mes in meses.items():
        m = re.search(rf'\b(\d{{1,2}})\s+de\s+{nome_mes}\b', texto, re.IGNORECASE)
        if m:
            return f"{m.group(1).zfill(2)}/{num_mes}"
    return ""

def formatar_hora():
    return datetime.now().strftime("%d/%m/%Y %H:%M:%S")

# ============================================================
# SCRAPERS
# ============================================================

async def scrape_fielzone(page, jogo):
    print("  [Fielzone] Abrindo home...")
    await page.goto("https://camarotefielzone.com.br/", wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(2000)

    links = await page.query_selector_all("a")
    url_jogo = None
    for link in links:
        texto = (await link.inner_text()).strip()
        href = await link.get_attribute("href") or ""
        if jogo_corresponde(texto, jogo) or jogo_corresponde(href, jogo):
            if href.startswith("http"):
                url_jogo = href
            elif href.startswith("/"):
                url_jogo = "https://camarotefielzone.com.br" + href
            print(f"  [Fielzone] Jogo encontrado: '{texto}' -> {url_jogo}")
            break

    if not url_jogo:
        return {"erro": f"Jogo '{jogo}' nao encontrado na pagina"}

    print("  [Fielzone] Abrindo pagina do evento e aguardando widget Ingresse...")
    await page.goto(url_jogo, wait_until="networkidle", timeout=40000)

    try:
        await page.wait_for_selector("text=R$", timeout=15000)
        print("  [Fielzone] Widget carregado!")
    except:
        print("  [Fielzone] Timeout - tentando mesmo assim...")

    await page.wait_for_timeout(2000)

    ingressos = []
    for frame in page.frames:
        if "ingresse" in frame.url or "checkout" in frame.url:
            print(f"  [Fielzone] iframe Ingresse: {frame.url}")
            try:
                conteudo_frame = await frame.inner_text("body")
                precos = extrair_precos_texto(conteudo_frame)
                if precos:
                    ingressos = await extrair_setores_precos_frame(frame)
                    if not ingressos:
                        ingressos = [{"setor": f"Opcao {i+1}", "preco": p} for i, p in enumerate(precos[:10])]
                    print(f"  [Fielzone] {len(ingressos)} ingresso(s) encontrado(s)")
                    break
            except Exception as e:
                print(f"  [Fielzone] Erro iframe: {e}")

    if not ingressos:
        ingressos = await extrair_setores_precos_frame(page)
    if not ingressos:
        precos = extrair_precos_texto(await page.inner_text("body"))
        if precos:
            ingressos = [{"setor": f"Opcao {i+1}", "preco": p} for i, p in enumerate(precos[:10])]
    if not ingressos:
        ingressos = [{"setor": "Ver no site", "preco": "-"}]

    return {"ingressos": ingressos, "url_evento": url_jogo}


async def scrape_loungebrahma(page, jogo):
    print("  [Lounge Brahma] Abrindo home...")
    await page.goto("https://loungebrahma.com.br/", wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(2000)

    links = await page.query_selector_all("a")
    url_jogo = None
    for link in links:
        texto = (await link.inner_text()).strip()
        href = await link.get_attribute("href") or ""
        if jogo_corresponde(texto, jogo) or jogo_corresponde(href, jogo):
            url_jogo = href
            print(f"  [Lounge Brahma] Jogo encontrado: {texto}")
            break

    if not url_jogo:
        return {"erro": f"Jogo '{jogo}' nao encontrado"}

    print("  [Lounge Brahma] Abrindo produto WooCommerce...")
    await page.goto(url_jogo, wait_until="networkidle", timeout=30000)
    await page.wait_for_timeout(3000)

    ingressos = []
    select = await page.query_selector("select")
    if select:
        opcoes = await select.query_selector_all("option")
        for opcao in opcoes:
            valor = await opcao.get_attribute("value")
            texto_opcao = (await opcao.inner_text()).strip()
            if not valor or valor == "" or texto_opcao.startswith("Escolha"):
                continue
            await select.select_option(value=valor)
            await page.wait_for_timeout(1000)
            preco = None
            for sel in [".woocommerce-Price-amount", ".price ins .amount", ".price .amount", "span.amount", ".woocommerce-variation-price .amount"]:
                el = await page.query_selector(sel)
                if el:
                    preco = (await el.inner_text()).strip()
                    break
            if preco:
                ingressos.append({"setor": texto_opcao, "preco": preco})
                print(f"  [Lounge Brahma]   {texto_opcao}: {preco}")

    if not ingressos:
        precos = extrair_precos_texto(await page.inner_text("body"))
        if precos:
            ingressos = [{"setor": f"Opcao {i+1}", "preco": p} for i, p in enumerate(precos[:8])]

    return {"ingressos": ingressos, "url_evento": url_jogo}


async def scrape_soudaliga(page, jogo):
    """
    Sou da Liga (SPA React): varre todos os cards da listagem.
    Le cada card pelo texto puro sem regex no JS (evita erros de escape).
    """
    print("  [Sou da Liga] Abrindo site...")
    try:
        await page.goto("https://bardozeca.soudaliga.com.br/", wait_until="domcontentloaded", timeout=30000)
    except Exception as e:
        print(f"  [Sou da Liga] Aviso: {e}")
    await page.wait_for_timeout(6000)

    try:
        await page.wait_for_selector("a, button, h1, h2, h3", timeout=10000)
    except:
        pass

    # Le todos os blocos de texto da pagina via JS simples (sem regex)
    blocos = await page.evaluate("""() => {
        const tags = ['article', 'li', 'div'];
        const vistos = new Set();
        const resultado = [];
        for (const tag of tags) {
            for (const el of document.querySelectorAll(tag)) {
                const t = (el.innerText || '').trim();
                if (t.length < 20 || t.length > 1500) continue;
                if (vistos.has(t)) continue;
                vistos.add(t);
                resultado.push(t);
            }
        }
        return resultado;
    }""")

    print(f"  [Sou da Liga] {len(blocos)} blocos encontrados")

    ingressos = []
    vistos = set()

    for bloco in blocos:
        # Verifica se o bloco eh do jogo certo
        if not jogo_corresponde(bloco, jogo):
            continue

        # Extrai preco do bloco
        precos = extrair_precos_texto(bloco)
        if not precos:
            continue

        # Pega linhas nao vazias
        linhas = [l.strip() for l in bloco.splitlines() if l.strip()]

        # Setor: a linha mais curta relevante (sem data, sem "De ", sem "Neo Quim", sem nome de competicao)
        _filtro_setor = ["r$", "/202", "de ", "neo qu", "abertura", "lote",
                         "libertadores", "brasileiro", "copa do brasil", "paulista", "sul-americana"]
        setor = ""
        for linha in linhas:
            if any(x in linha.lower() for x in _filtro_setor):
                continue
            if 3 < len(linha) < 70:
                setor = linha
                break

        # Se nao achou setor curto, tenta todas as linhas com o mesmo filtro (sem break antecipado)
        if not setor:
            for linha in linhas:
                if any(x in linha.lower() for x in _filtro_setor):
                    continue
                setor = linha.split(" - ")[0].strip()[:60]
                if setor:
                    break

        preco = precos[0]
        chave = setor + preco
        if chave in vistos or not setor:
            continue
        vistos.add(chave)

        ingressos.append({"setor": setor[:60], "preco": preco})
        print(f"  [Sou da Liga]   {setor[:50]}: {preco}")

    if not ingressos:
        return {"erro": f"Jogo '{jogo}' nao encontrado no Bar do Zeca"}

    return {"ingressos": ingressos, "url_evento": "https://bardozeca.soudaliga.com.br/"}


async def scrape_arenakids(page, jogo):
    """
    Arena Kids: pega UUID do site deles -> busca event_id na pagina publica do Ingresse
    -> tenta abrir cart.ingresse.com com browser visivel (passa Cloudflare)
    -> fallback: embedstore.ingresse.com
    """
    print("  [Arena Kids] Abrindo home para pegar UUID...")
    await page.goto("https://arenakidscorinthians.com.br/", wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(2000)

    pares = await page.evaluate("""() => {
        const links = Array.from(document.querySelectorAll('a'));
        const result = [];
        for (const a of links) {
            if (!a.href || a.href.indexOf('ingresse') === -1) continue;
            let el = a; let titulo = ''; let data_texto = ''; let horario = '';
            for (let i = 0; i < 12; i++) {
                el = el.parentElement;
                if (!el) break;
                const h = el.querySelector('h1,h2,h3,h4,h5,h6');
                if (h && h.innerText.trim().length > 3) { titulo = h.innerText.trim(); }
                // Busca data (DD/MM) e horario (NNhNN) nos elementos folha do container
                const folhas = Array.from(el.querySelectorAll('*'))
                    .filter(e => e.childElementCount === 0)
                    .map(e => (e.innerText || '').trim())
                    .filter(t => t);
                for (const t of folhas) {
                    if (!data_texto && /\\d{2}\\/\\d{2}/.test(t)) data_texto = t;
                    if (!horario && /\\d{1,2}h\\d{2}/.test(t)) horario = t;
                }
                if (titulo && data_texto && horario) break;
            }
            result.push({ href: a.href, titulo: titulo, data_texto: data_texto, horario: horario });
        }
        return result;
    }""")

    ingresse_url = None
    data_jogo = ""
    for par in pares:
        if jogo_corresponde(par.get('titulo', ''), jogo):
            ingresse_url = par['href']
            data_jogo = (par.get('data_texto', '') + ' ' + par.get('horario', '')).strip()
            print(f"  [Arena Kids] Link: {ingresse_url}")
            print(f"  [Arena Kids] Data do jogo: {data_jogo}")
            break
    if not ingresse_url:
        adversario = jogo.split(' x ')[-1].strip().lower()
        for par in pares:
            if adversario in par.get('titulo', '').lower():
                ingresse_url = par['href']
                data_jogo = (par.get('data_texto', '') + ' ' + par.get('horario', '')).strip()
                break

    if not ingresse_url:
        return {"ingressos": [{"setor": "Ver no site", "preco": "-"}], "url_evento": "https://arenakidscorinthians.com.br/", "data_jogo": ""}

    uuid_match = re.search(r'cart\.ingresse\.com/([0-9a-f-]{36})/tickets', ingresse_url)
    uuid = uuid_match.group(1) if uuid_match else None
    print(f"  [Arena Kids] UUID: {uuid}")

    event_id = None
    ingressos = []

    # Busca event_id na pagina publica do Ingresse
    print(f"  [Arena Kids] Abrindo pagina publica para inspecionar HTML...")
    import unicodedata as _ud
    def _sem_acento(s):
        return _ud.normalize('NFKD', s).encode('ascii', 'ignore').decode('ascii')
    adversario_slug = _sem_acento(jogo.split(' x ')[-1].strip().lower()).replace(' ', '-')
    slug = f"corinthians-x-{adversario_slug}-camarote-arena-kids"
    url_pub = f"https://www.ingresse.com/{slug}"
    print(f"  [Arena Kids] Slug URL: {url_pub}")
    await page.goto(url_pub, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(4000)
    html = await page.content()

    import re as _re
    from datetime import datetime as _dt

    # Verifica se a pagina publica mostra um evento do ano correto
    # Se estiver esgotado e for de ano passado, ignora e busca datas disponiveis
    ano_atual = _dt.now().year
    corpo_pub = await page.inner_text("body")
    evento_esgotado = "esgotado" in corpo_pub.lower()
    ano_evento_match = _re.search(r'\b(20\d{2})\b', corpo_pub)
    ano_evento = int(ano_evento_match.group(1)) if ano_evento_match else ano_atual
    evento_expirado = evento_esgotado and ano_evento < ano_atual

    if evento_expirado:
        print(f"  [Arena Kids] Pagina publica mostra evento de {ano_evento} esgotado — buscando datas disponiveis...")
        # Tenta links de datas disponiveis na pagina
        links_datas = await page.evaluate("""() => {
            return Array.from(document.querySelectorAll('a[href*="/"], a[href*="ingresse"]'))
                .map(a => a.href).filter(h => h && h.includes('ingresse.com') && !h.includes('corinthians-x-'));
        }""")
        for link_data in links_datas[:5]:
            try:
                print(f"  [Arena Kids] Tentando data: {link_data}")
                await page.goto(link_data, wait_until="domcontentloaded", timeout=20000)
                await page.wait_for_timeout(2000)
                html = await page.content()
                corpo_data = await page.inner_text("body")
                ano_m = _re.search(r'\b(20\d{2})\b', corpo_data)
                if ano_m and int(ano_m.group(1)) >= ano_atual and "esgotado" not in corpo_data.lower():
                    print(f"  [Arena Kids] Data valida encontrada: {link_data}")
                    break
            except:
                continue
        else:
            html = ""  # nenhuma data valida achada

    patterns = [
        r'"eventId"\s*:\s*(\d{4,7})',
        r'"event_id"\s*:\s*(\d{4,7})',
        r'event/posters/(\d{4,7})/',
        r'event/(\d{4,7})/',
        r'/(\d{4,7})/medium/',
    ]
    for pat in patterns:
        m = _re.search(pat, html)
        if m:
            candidate = int(m.group(1))
            if 1000 < candidate < 999999:
                event_id = candidate
                print(f"  [Arena Kids] Event ID {event_id} via padrao: {pat}")
                break

    cart_url = f"https://cart.ingresse.com/{uuid}/tickets" if uuid else None

    if not event_id and not cart_url:
        return {"ingressos": [{"setor": "Ver no site", "preco": "-"}], "url_evento": ingresse_url, "data_jogo": data_jogo}

    # Tenta cart com browser visivel para passar pelo Cloudflare
    if cart_url:
        print(f"  [Arena Kids] Tentando cart: {cart_url}")
        try:
            from playwright.async_api import async_playwright as _ap
            import os as _os
            state_file = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "ingresse_state.json")

            if not _os.path.exists(state_file):
                print("  [Arena Kids] ingresse_state.json nao encontrado. Execute 'python login_arenakids.py' localmente.")
                return {"ingressos": [], "url_evento": ingresse_url, "data_jogo": data_jogo}

            async with _ap() as _p:
                _browser = await _p.chromium.launch(
                    headless=True,
                    args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
                )
                print("  [Arena Kids] Usando sessao salva:", state_file)
                _ctx2 = await _browser.new_context(
                    storage_state=state_file,
                    viewport={"width": 1280, "height": 900},
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                    locale="pt-BR",
                    timezone_id="America/Sao_Paulo",
                )
                await _ctx2.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined}); window.chrome={runtime:{}};")
                _page = await _ctx2.new_page()

                # Abre cart com sessao injetada
                print("  [Arena Kids] Abrindo cart com sessao salva...")
                await _page.goto(cart_url, wait_until="domcontentloaded", timeout=30000)
                await _page.wait_for_timeout(3000)
                corpo = await _page.inner_text("body")

                # Se precisar de login, sessao expirou — encerra graciosamente
                if "Acesse sua conta" in corpo or "acesse sua conta" in corpo.lower():
                    print("  [Arena Kids] Sessao expirada. Execute 'python login_arenakids.py' localmente para renovar.")
                    await _ctx2.close()
                    await _browser.close()
                    return {"ingressos": [], "url_evento": ingresse_url, "data_jogo": data_jogo}
                for _ in range(8):
                    await _page.wait_for_timeout(2000)
                    corpo = await _page.inner_text("body")
                    if "Just a moment" not in corpo and "Acesse sua conta" not in corpo:
                        break
                    print("  [Arena Kids] Aguardando cart carregar...")

                # Recarrega apos login
                await _page.goto(cart_url, wait_until="domcontentloaded", timeout=30000)
                await _page.wait_for_timeout(4000)
                corpo = await _page.inner_text("body")

                if "Acesse sua conta" not in corpo and "Corinthians" in corpo:
                    print("  [Arena Kids] Cart carregou! Clicando aba Combos...")

                    # Clica na aba Combos para exibir os precos
                    try:
                        combos_btn = await _page.query_selector("button:has-text('Combos'), a:has-text('Combos'), [role='tab']:has-text('Combos')")
                        if combos_btn and await combos_btn.is_visible():
                            await combos_btn.click()
                            await _page.wait_for_timeout(2000)
                            print("  [Arena Kids] Aba Combos clicada")
                    except:
                        pass

                    # Aguarda precos aparecerem
                    try:
                        await _page.wait_for_selector("text=R$", timeout=8000)
                    except:
                        pass

                    corpo = await _page.inner_text("body")

                    # Extrai precos linha a linha (nome esta 2 linhas antes do preco)
                    linhas = [l.strip() for l in corpo.splitlines() if l.strip()]
                    ignorar = {'camarote kids', 'detalhes', 'adicionar código ou cupom',
                               'cancelar', 'aplicar', 'compartilhar', 'preciso de ajuda'}
                    for idx, linha in enumerate(linhas):
                        lps = extrair_precos_texto(linha)
                        if not lps:
                            continue
                        try:
                            val = float(lps[0].replace("R$","").replace(".","").replace(",",".").strip())
                            if val <= 0:
                                continue
                        except:
                            continue
                        nome = re.sub(r'R\$\s*[\d.,]+', '', linha).strip(" -:*+()")
                        nome = re.sub(r'\s+', ' ', nome).strip()
                        if not nome or len(nome) < 3:
                            for offset in [1, 2, 3]:
                                if idx >= offset:
                                    cand = linhas[idx - offset].strip()
                                    cand_l = cand.lower()
                                    if (cand and not extrair_precos_texto(cand)
                                            and 3 < len(cand) < 80
                                            and cand_l not in ignorar
                                            and not any(x in cand_l for x in ['dom,', 'seg,', 'ter,', 'qua,', 'qui,', 'sex,', 'sáb,', '18h', '21h', 'abr', 'mai'])):
                                        nome = cand[:70]
                                        break
                        if nome and len(nome) > 3:
                            ingressos.append({"setor": nome, "preco": lps[0]})

                    if ingressos:
                        print(f"  [Arena Kids] {len(ingressos)} ingresso(s) extraidos!")
                    else:
                        print(f"  [Arena Kids] Nenhum preco no body — tentando accordion (Radix UI)...")
                        # Fallback: cart usa accordion Radix — cada item precisa ser clicado
                        botoes = await _page.query_selector_all('button[data-state]')
                        for btn in botoes:
                            try:
                                nome_btn = (await btn.inner_text()).strip().split('\n')[0][:80]
                                if len(nome_btn) < 3:
                                    continue
                                await btn.click()
                                await _page.wait_for_timeout(700)
                                corpo_btn = await _page.inner_text("body")
                                linhas_btn = [l.strip() for l in corpo_btn.splitlines() if l.strip()]
                                for j, linha_b in enumerate(linhas_btn):
                                    if nome_btn[:30] in linha_b:
                                        for k in range(j + 1, min(j + 10, len(linhas_btn))):
                                            lps_b = extrair_precos_texto(linhas_btn[k])
                                            if lps_b:
                                                try:
                                                    val_b = float(lps_b[0].replace("R$","").replace(".","").replace(",",".").strip())
                                                    if val_b > 0:
                                                        ingressos.append({"setor": nome_btn, "preco": lps_b[0]})
                                                except:
                                                    pass
                                                break
                                        break
                                await btn.click()
                                await _page.wait_for_timeout(400)
                            except:
                                continue
                        if ingressos:
                            print(f"  [Arena Kids] {len(ingressos)} ingresso(s) via accordion!")
                        else:
                            print(f"  [Arena Kids] Nenhum preco encontrado. Body snippet: {corpo[:300].replace(chr(10),' ')}")

                else:
                    corpo_debug = corpo[:400].replace("\n"," ")
                    print(f"  [Arena Kids] Cart nao carregou. Body: {corpo_debug}")
                await _ctx2.close()
                await _browser.close()
        except Exception as e:
            print(f"  [Arena Kids] Cart login erro: {e}")

    # Fallback: embedstore
    if not ingressos and event_id:
        embed_url = f"https://embedstore.ingresse.com/tickets/arenakidscorinthians.com.br/event/{event_id}"
        print(f"  [Arena Kids] Embedstore: {embed_url}")
        await page.goto(embed_url, wait_until="networkidle", timeout=35000)
        try:
            await page.wait_for_selector("text=R$", timeout=15000)
            print("  [Arena Kids] Precos!")
        except:
            pass
        await page.wait_for_timeout(2000)
        for frame in page.frames:
            if "ingresse" in frame.url:
                try:
                    fc = await frame.inner_text("body")
                    if extrair_precos_texto(fc):
                        ingressos = await extrair_setores_precos_frame(frame)
                        if ingressos: break
                except:
                    pass
        if not ingressos:
            ingressos = await extrair_setores_precos_frame(page)

    vistos = set()
    unicos = []
    for ing in ingressos:
        chave = (ing.get("setor") or "") + (ing.get("preco") or "")
        if chave and chave not in vistos:
            vistos.add(chave)
            unicos.append(ing)

    if not unicos:
        unicos = [{"setor": "Ver no site", "preco": "-"}]

    return {"ingressos": unicos[:12], "url_evento": ingresse_url, "data_jogo": data_jogo}


async def scrape_ticket360(page, jogo):
    """
    Ticket360: acha os eventos Galeria SCCP do jogo, abre cada pagina de evento,
    clica em COMPRAR e extrai os precos que aparecem na pagina seguinte/modal.
    """
    print("  [Ticket360] Buscando eventos Galeria SCCP...")
    urls_galeria = []

    for url_cat in [
        "https://www.ticket360.com.br/sub-categoria/1708/camarote-galeria-sccp",
        "https://www.ticket360.com.br/sub-categoria/1708/camarote-galeria-sccp",
    ]:
        try:
            print(f"  [Ticket360] Tentando: {url_cat}")
            await page.goto(url_cat, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(4000)

            links = await page.query_selector_all("a")
            for link in links:
                try:
                    texto = (await link.inner_text()).strip()
                    href = await link.get_attribute("href") or ""
                    href_norm = href.replace('-', ' ')
                    eh_galeria = "galeria" in href.lower()
                    eh_jogo = jogo_corresponde(href_norm, jogo)
                    eh_combo = "combo" in href.lower()
                    if eh_galeria and eh_jogo and not eh_combo:
                        url_completa = href if href.startswith("http") else "https://www.ticket360.com.br/" + href.lstrip("/")
                        if url_completa not in [u for _, u in urls_galeria]:
                            urls_galeria.append((texto.strip().replace("\n", " "), url_completa))
                            print(f"  [Ticket360] Evento: {texto[:60].replace(chr(10), ' ')}")
                except:
                    continue

            if urls_galeria:
                break
        except Exception as e:
            print(f"  [Ticket360] Erro em {url_cat}: {e}")

    if not urls_galeria:
        return {"erro": f"Evento Galeria SCCP para '{jogo}' nao encontrado no Ticket360"}

    ingressos = []
    url_evento = urls_galeria[0][1]

    # Deduplica URLs — processa Fiel e Padrao sem limite fixo
    urls_vistas = set()
    urls_unicas = []
    for nome_ev, url_ev in urls_galeria:
        if url_ev not in urls_vistas:
            urls_vistas.add(url_ev)
            urls_unicas.append((nome_ev, url_ev))
    urls_galeria = urls_unicas

    # Sempre usa prefixo quando tem mais de 1 evento
    sempre_prefixo = len(urls_galeria) > 1

    for nome_evento, url in urls_galeria:
        print(f"  [Ticket360] Abrindo evento: {url}")
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(3000)

            # Clica no botao COMPRAR
            btn = await page.query_selector("text=COMPRAR")
            if not btn:
                btn = await page.query_selector("button:has-text('COMPRAR'), a:has-text('COMPRAR'), [class*='comprar']")

            if btn:
                print(f"  [Ticket360] Clicando em COMPRAR...")
                await btn.click()
                await page.wait_for_timeout(4000)
                try:
                    await page.wait_for_selector("text=R$", timeout=8000)
                    print("  [Ticket360] Precos carregados!")
                except:
                    print("  [Ticket360] Timeout esperando R$ apos click")
            else:
                print("  [Ticket360] Botao COMPRAR nao encontrado")

            corpo = await page.inner_text("body")

            # Prefixo: "Fiel" ou "Padrao" para distinguir os 2 cards
            if sempre_prefixo:
                prefixo = "Fiel — " if "fiel" in nome_evento.lower() else "Padrao — "
            else:
                prefixo = ""

            linhas = [l.strip() for l in corpo.splitlines() if l.strip()]
            achou_neste = 0

            for idx, linha in enumerate(linhas):
                ps = extrair_precos_texto(linha)
                if not ps or not (5 < len(linha) < 200):
                    continue
                # Filtra valor zero
                try:
                    val = float(ps[0].replace("R$","").replace(".","").replace(",",".").strip())
                    if val <= 0:
                        continue
                except:
                    pass

                # Tenta extrair nome da propria linha
                nome = re.sub(r'R\$\s*[\d.,]+', '', linha).strip(" -:*+")
                nome = re.sub(r'\s+', ' ', nome).strip()

                # Se nome ficou vazio ou eh so "a partir de" / "Taxas", usa linha anterior
                nome_l = nome.lower()
                nome_ruim = (not nome or len(nome) < 3
                    or nome_l in ['a partir de', 'taxa', 'total', 'subtotal', 'taxas']
                    or nome_l.startswith('a partir')
                    or nome_l.startswith('+ tax'))

                if nome_ruim:
                    # Pega linha anterior que nao tenha preco e seja texto valido
                    nome = ""
                    for offset in [1, 2]:
                        if idx >= offset:
                            cand = linhas[idx - offset].strip()
                            if cand and not extrair_precos_texto(cand) and len(cand) > 2:
                                cand_l = cand.lower()
                                if not any(x in cand_l for x in ['abertura', 'neo qu', 'sao paulo', 'mar ', 'qua ', 'dom ', 'sex ']):
                                    nome = cand[:60]
                                    break

                if not nome or len(nome) < 2:
                    continue

                ingressos.append({"setor": (prefixo + nome)[:70], "preco": ps[0]})
                achou_neste += 1

            if achou_neste:
                print(f"  [Ticket360] {achou_neste} preco(s) extraido(s) de '{nome_evento[:40]}'")
                url_evento = url
            # NAO tem break aqui — processa os 2 eventos!

        except Exception as e:
            print(f"  [Ticket360] Erro: {e}")

    # Remove duplicatas
    vistos = set()
    unicos = []
    for ing in ingressos:
        chave = ing["setor"] + ing["preco"]
        if chave not in vistos:
            vistos.add(chave)
            unicos.append(ing)

    if not unicos:
        unicos = [{"setor": "Ver no site", "preco": "-"}]

    return {"ingressos": unicos[:12], "url_evento": url_evento}


async def scrape_ticket360_fiel(page, jogo):
    """
    Camarote Fiel Torcedor via Ticket360 — mesmo mecanismo do Galeria SCCP
    mas busca por "Fiel Torcedor" + jogo na sub-categoria SP ou Corinthians.
    """
    print("  [Fiel Torcedor] Buscando eventos no Ticket360...")
    urls_evento = []

    for url_cat in [
        "https://www.ticket360.com.br/sub-categoria/211/sao-paulo",
        "https://www.ticket360.com.br/sub-categoria/1456/corinthians",
        "https://www.ticket360.com.br/eventos/pesquisar?s=Fiel+torcedor",
    ]:
        try:
            await page.goto(url_cat, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(3000)
            links = await page.query_selector_all("a")
            for link in links:
                try:
                    texto = (await link.inner_text()).strip().replace("\n", " ")
                    href = await link.get_attribute("href") or ""
                    href_lower = href.lower()
                    texto_lower = texto.lower()
                    href_norm = href.replace('-', ' ')
                    eh_fiel = "fiel" in href_lower
                    eh_galeria = "galeria" in href_lower or "sccp" in href_lower
                    eh_jogo = jogo_corresponde(href_norm, jogo)
                    if eh_fiel and eh_jogo and not eh_galeria:
                        url_completa = href if href.startswith("http") else "https://www.ticket360.com.br/" + href.lstrip("/")
                        if url_completa not in [u for _, u in urls_evento]:
                            urls_evento.append((texto[:60], url_completa))
                            print(f"  [Fiel Torcedor] Evento: {texto[:60]}")
                except:
                    continue
            if urls_evento:
                break
        except Exception as e:
            print(f"  [Fiel Torcedor] Erro {url_cat}: {e}")

    if not urls_evento:
        return {"erro": f"Evento Fiel Torcedor para '{jogo}' nao encontrado no Ticket360"}

    ingressos = []
    url_evento = urls_evento[0][1]
    sempre_prefixo = len(urls_evento) > 1

    for nome_evento, url in urls_evento[:3]:
        print(f"  [Fiel Torcedor] Abrindo: {url}")
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(3000)

            # Fecha modal de informacao obrigatoria se estiver bloqueando
            try:
                modal = await page.query_selector("#informacaoObrigatoria .close, #informacaoObrigatoria [data-dismiss='modal']")
                if modal and await modal.is_visible():
                    await modal.click()
                    await page.wait_for_timeout(800)
                    print("  [Fiel Torcedor] Modal fechado")
            except:
                pass

            btn = await page.query_selector("text=COMPRAR")
            if not btn:
                btn = await page.query_selector("button:has-text('COMPRAR'), a:has-text('COMPRAR')")
            if btn:
                print("  [Fiel Torcedor] Clicando COMPRAR...")
                await btn.click()
                await page.wait_for_timeout(4000)
                try:
                    await page.wait_for_selector("text=R$", timeout=8000)
                    print("  [Fiel Torcedor] Precos carregados!")
                except:
                    pass

            corpo = await page.inner_text("body")
            if sempre_prefixo:
                prefixo = "Fiel — " if "fiel" in nome_evento.lower() else "Excl — "
            else:
                prefixo = ""

            linhas = [l.strip() for l in corpo.splitlines() if l.strip()]
            achou = 0
            for idx, linha in enumerate(linhas):
                ps = extrair_precos_texto(linha)
                if not ps or not (5 < len(linha) < 200):
                    continue
                try:
                    val = float(ps[0].replace("R$","").replace(".","").replace(",",".").strip())
                    if val <= 0:
                        continue
                except:
                    pass
                nome = re.sub(r'R\$\s*[\d.,]+', '', linha).strip(" -:*+")
                nome = re.sub(r'\s+', ' ', nome).strip()
                nome_l = nome.lower()
                nome_ruim = (not nome or len(nome) < 3
                    or nome_l in ['a partir de', 'taxa', 'total', 'subtotal', 'taxas']
                    or nome_l.startswith('a partir')
                    or nome_l.startswith('+ tax'))
                if nome_ruim:
                    nome = ""
                    for offset in [1, 2]:
                        if idx >= offset:
                            cand = linhas[idx - offset].strip()
                            if cand and not extrair_precos_texto(cand) and len(cand) > 2:
                                cand_l = cand.lower()
                                if not any(x in cand_l for x in ['abertura', 'neo qu', 'sao paulo', 'mar ', 'qua ', 'dom ', 'sex ']):
                                    nome = cand[:60]
                                    break
                if not nome or len(nome) < 2:
                    continue
                ingressos.append({"setor": (prefixo + nome)[:70], "preco": ps[0]})
                achou += 1

            if achou:
                print(f"  [Fiel Torcedor] {achou} preco(s) de '{nome_evento[:40]}'")
                url_evento = url

        except Exception as e:
            print(f"  [Fiel Torcedor] Erro: {e}")

    vistos = set()
    unicos = []
    for ing in ingressos:
        chave = ing["setor"] + ing["preco"]
        if chave not in vistos:
            vistos.add(chave)
            unicos.append(ing)

    if not unicos:
        unicos = [{"setor": "Ver no site", "preco": "-"}]

    return {"ingressos": unicos[:12], "url_evento": url_evento}


async def extrair_setores_precos_frame(frame):
    """
    Extrai pares (setor, preco) do iframe do Ingresse.
    O widget Ingresse mostra o nome do setor numa linha e o preco em outra —
    usamos JS para varrer todos os elementos e parear por proximidade no DOM.
    """
    try:
        # Estrategia principal: JS varre o DOM do iframe procurando
        # elementos de nome (sem R$) proximos a elementos de preco (com R$)
        resultado = await frame.evaluate(r"""() => {
            const todos = Array.from(document.querySelectorAll('*'));
            const comPreco = todos.filter(el => {
                const t = el.childElementCount === 0 ? (el.innerText || '').trim() : '';
                return t.match(/R\$\s*[\d.,]+/) && t.length < 50;
            });

            const pares = [];
            const vistos = new Set();

            for (const elPreco of comPreco) {
                const textoPreco = (elPreco.innerText || '').trim();
                // Ignora R$ 0
                const num = parseFloat(textoPreco.replace(/R\$\s*/,'').replace(/\./g,'').replace(',','.'));
                if (!num || num <= 0) continue;

                // Sobe pelo DOM ate 5 niveis procurando um container com nome
                let container = elPreco;
                let nome = '';
                for (let i = 0; i < 5; i++) {
                    container = container.parentElement;
                    if (!container) break;
                    // Procura texto sem R$ dentro do container
                    const filhos = Array.from(container.querySelectorAll('*'));
                    for (const f of filhos) {
                        if (f === elPreco) continue;
                        if (f.childElementCount > 0) continue;
                        const t = (f.innerText || '').trim();
                        if (t && t.length > 3 && t.length < 80 && !t.match(/R\$/) && !t.match(/^\d+$/)) {
                            nome = t;
                            break;
                        }
                    }
                    if (nome) break;
                }

                const chave = nome + textoPreco;
                // Ignora nomes muito curtos, so com simbolos, ou "taxas"
                const nomeValido = nome && nome.length > 4
                    && !nome.match(/^[+\-*•|\s]+$/)
                    && !nome.toLowerCase().includes('taxa')
                    && !nome.toLowerCase().includes('total')
                    && !nome.toLowerCase().includes('subtotal');

                if (!vistos.has(chave) && nomeValido) {
                    vistos.add(chave);
                    pares.push({ setor: nome, preco: textoPreco });
                }
            }
            return pares;
        }""")

        if resultado:
            # Filtra itens None/invalidos que o JS pode retornar
            resultado = [r for r in resultado if r and r.get("setor") and r.get("preco")]
            if resultado:
                return resultado[:10]

        # Fallback: le texto do iframe linha a linha e pareia nome+preco
        # O widget Ingresse tem: linha com nome do setor, linha com preco
        ingressos = []
        try:
            corpo = await frame.inner_text("body")
            linhas = [l.strip() for l in corpo.splitlines() if l.strip()]
            i = 0
            while i < len(linhas):
                linha = linhas[i]
                ps = extrair_precos_texto(linha)
                if ps:
                    try:
                        val = float(ps[0].replace("R$","").replace(".","").replace(",",".").strip())
                    except:
                        val = 0
                    if val > 0:
                        # Estrutura do widget Ingresse:
                        #   i-2: NOME DO SETOR  <-- queremos este
                        #   i-1: ENTRADA | OPEN BAR...  (subtitulo, ignorar)
                        #   i:   R$ 450,00
                        nome = ""
                        for offset in [2, 1]:
                            if i >= offset:
                                candidato = linhas[i - offset].strip()
                                if candidato and not extrair_precos_texto(candidato):
                                    cand_l = candidato.lower()
                                    # Pula subtitulos como "ENTRADA | OPEN BAR"
                                    if any(x in cand_l for x in ['entrada', 'open bar', 'open food', 'taxa', 'fee', '+ fee']):
                                        continue
                                    nome = candidato[:60]
                                    break
                        if not nome:
                            i += 1
                            continue
                        # Nao duplicar
                        nomes_existentes = [x["setor"] for x in ingressos]
                        if nome in nomes_existentes:
                            nome = f"{nome} ({len(ingressos)+1})"
                        ingressos.append({"setor": nome, "preco": ps[0]})
                i += 1
        except:
            pass

        vistos = set()
        unicos = []
        for ing in ingressos:
            chave = (ing.get("setor") or "") + (ing.get("preco") or "")
            if chave not in vistos:
                vistos.add(chave)
                unicos.append(ing)
        return unicos[:10]

    except:
        return []


async def extrair_variacoes_pagina(page):
    ingressos = []
    try:
        elementos = await page.query_selector_all("*:has-text('R$')")
        vistos = set()
        for el in elementos[-50:]:
            try:
                texto = (await el.inner_text()).strip()
                if len(texto) > 200 or texto in vistos:
                    continue
                vistos.add(texto)
                precos = extrair_precos_texto(texto)
                if precos and len(texto) < 100:
                    ingressos.append({"setor": texto.replace(precos[0], "").strip(" -:"), "preco": precos[0]})
            except:
                continue
    except:
        pass
    return ingressos[:10]


# ============================================================
# DESCOBERTA AUTOMÁTICA DE JOGOS
# ============================================================

async def _buscar_jogos_arena_kids() -> list:
    """Abre a página do Arena Kids e retorna os nomes de todos os jogos listados."""
    print("  [Auto] Buscando jogos na pagina do Arena Kids...")
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            )
            ctx = await browser.new_context(
                locale="pt-BR", timezone_id="America/Sao_Paulo",
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            )
            page = await ctx.new_page()
            await page.goto("https://arenakidscorinthians.com.br/", wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2000)

            pares = await page.evaluate(r"""() => {
                const links = Array.from(document.querySelectorAll('a[href*="ingresse"]'));
                const vistos = new Set();
                const jogos = [];
                for (const a of links) {
                    let el = a;
                    let titulo = '';
                    for (let i = 0; i < 12; i++) {
                        el = el.parentElement;
                        if (!el) break;
                        const h = el.querySelector('h1,h2,h3,h4,h5,h6');
                        if (h && h.innerText.trim().length > 3) {
                            titulo = h.innerText.trim();
                            break;
                        }
                    }
                    if (titulo && !vistos.has(titulo)) {
                        vistos.add(titulo);
                        jogos.push(titulo);
                    }
                }
                return jogos;
            }""")

            await browser.close()

            jogos = [j for j in pares if 'corinthians' in j.lower()]
            print(f"  [Auto] {len(jogos)} jogo(s) encontrado(s): {jogos}")
            return jogos
    except Exception as e:
        print(f"  [Auto] Erro ao buscar jogos: {e}")
        return []


async def _buscar_jogos_loungebrahma() -> list:
    """Abre a home do Lounge Brahma e retorna lista de (nome, data_raw)."""
    print("  [Auto] Buscando jogos na pagina do Lounge Brahma...")
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            )
            ctx = await browser.new_context(
                locale="pt-BR", timezone_id="America/Sao_Paulo",
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            )
            page = await ctx.new_page()
            await page.goto("https://loungebrahma.com.br/", wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(2000)

            pares = await page.evaluate(r"""() => {
                const result = [];
                const vistos = new Set();
                for (const a of document.querySelectorAll('a')) {
                    const texto = (a.innerText || '').replace(/\s+/g, ' ').trim();
                    if (!texto.toLowerCase().includes('corinthians') || !texto.toLowerCase().includes(' x ')) continue;
                    if (vistos.has(texto)) continue;
                    vistos.add(texto);
                    // Sobe no DOM procurando container que contenha padrão de data
                    let dataTexto = '';
                    let el = a.parentElement;
                    for (let i = 0; i < 10 && el; i++, el = el.parentElement) {
                        const t = (el.innerText || '').replace(/\s+/g, ' ').trim();
                        if (t.length > 1200) break;
                        if (/\d{1,2}\/\d{2}/.test(t) || /\d{1,2}H\d{2}/i.test(t)) {
                            dataTexto = t;
                            break;
                        }
                    }
                    result.push({ nome: texto, container: dataTexto });
                }
                return result;
            }""")

            await browser.close()
            jogos = [(_normalizar_nome_jogo(_extrair_nome_jogo(p["nome"])), _extrair_data_raw(p["container"])) for p in pares]
            jogos = list({n: d for n, d in jogos}.items())  # deduplica por nome limpo
            print(f"  [Auto] Lounge Brahma: {len(jogos)} jogo(s): {[(n, d) for n, d in jogos]}")
            return jogos
    except Exception as e:
        print(f"  [Auto] Erro ao buscar jogos no Lounge Brahma: {e}")
        return []


async def _buscar_jogos_fielzone() -> list:
    """Abre a home do Fielzone e retorna lista de (nome, data_raw)."""
    print("  [Auto] Buscando jogos na pagina do Fielzone...")
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            )
            ctx = await browser.new_context(
                locale="pt-BR", timezone_id="America/Sao_Paulo",
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            )
            page = await ctx.new_page()
            await page.goto("https://camarotefielzone.com.br/", wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2000)

            pares = await page.evaluate(r"""() => {
                const result = [];
                const vistos = new Set();
                for (const a of document.querySelectorAll('a')) {
                    const texto = (a.innerText || '').replace(/\s+/g, ' ').trim();
                    if (!texto.toLowerCase().includes('corinthians') || !texto.toLowerCase().includes(' x ')) continue;
                    if (vistos.has(texto)) continue;
                    vistos.add(texto);
                    let container = texto;
                    let el = a.parentElement;
                    for (let i = 0; i < 6 && el; i++, el = el.parentElement) {
                        const t = (el.innerText || '').replace(/\s+/g, ' ').trim();
                        if (t.length > texto.length && t.length < 600) { container = t; break; }
                    }
                    result.push({ nome: texto, container });
                }
                return result;
            }""")

            await browser.close()
            jogos = [(_normalizar_nome_jogo(_extrair_nome_jogo(p["nome"])), _extrair_data_raw(p["container"])) for p in pares]
            jogos = list({n: d for n, d in jogos}.items())  # deduplica por nome limpo
            print(f"  [Auto] Fielzone: {len(jogos)} jogo(s): {[(n, d) for n, d in jogos]}")
            return jogos
    except Exception as e:
        print(f"  [Auto] Erro ao buscar jogos no Fielzone: {e}")
        return []


async def _descobrir_jogos() -> tuple:
    """Mescla jogos das 3 fontes. Retorna (lista_nomes, {nome: data_raw})."""
    arena_kids = await _buscar_jogos_arena_kids()
    lounge = await _buscar_jogos_loungebrahma()
    fielzone = await _buscar_jogos_fielzone()

    jogos_merged = []
    data_hints = {}

    # Arena Kids: só nomes (data vem do scraper de compra)
    for nome in arena_kids:
        nome = _normalizar_nome_jogo(nome)
        if not any(jogo_corresponde(nome, j) or jogo_corresponde(j, nome) for j in jogos_merged):
            jogos_merged.append(nome)

    # Lounge Brahma e Fielzone: (nome, data_raw)
    for lista in (lounge, fielzone):
        for nome, data_raw in lista:
            ja_existe = any(jogo_corresponde(nome, j) or jogo_corresponde(j, nome) for j in jogos_merged)
            if not ja_existe:
                jogos_merged.append(nome)
            if data_raw:
                # Guarda hint mesmo para jogos já conhecidos (Arena Kids pode não ter data ainda)
                data_hints[nome] = data_raw

    print(f"  [Auto] Total apos merge: {len(jogos_merged)} jogo(s): {jogos_merged}")
    return jogos_merged, data_hints


# ============================================================
# MAIN
# ============================================================

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--parceiro", type=str, default=None,
        help="Rodar apenas um parceiro específico (ex: arenakids)")
    parser.add_argument("--jogo", type=str, default=None,
        help="Rodar apenas um jogo específico (ex: 'Corinthians x Flamengo')")
    args = parser.parse_args()

    if args.jogo:
        jogos = [args.jogo]
        data_hints = {}
    else:
        jogos, data_hints = await _descobrir_jogos()
        if not jogos:
            print("Erro: nenhum jogo encontrado em nenhuma fonte")
            return

    print("=" * 60)
    print(f"  MONITOR DE INGRESSOS - {formatar_hora()}")
    print(f"  Jogos: {jogos}")
    print("=" * 60)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-web-security",
            ]
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            locale="pt-BR",
            timezone_id="America/Sao_Paulo",
            java_script_enabled=True,
            extra_http_headers={
                "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
            }
        )
        # Mascara sinais de automacao (WebDriver, plugins, etc)
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3,4,5] });
            Object.defineProperty(navigator, 'languages', { get: () => ['pt-BR','pt','en'] });
            window.chrome = { runtime: {} };
        """)

        resultados = {}

        for jogo in jogos:
            global JOGO_BUSCA
            JOGO_BUSCA = jogo

            print(f"\n{'='*60}")
            print(f"  JOGO: {jogo}")
            print(f"{'='*60}")

            parceiros_novos = {}

            for parceiro in PARCEIROS:
                if args.parceiro and parceiro["tipo"] != args.parceiro:
                    continue
                print(f"\n-> Raspando: {parceiro['nome']}")
                page = await context.new_page()
                try:
                    tipo = parceiro["tipo"]
                    if tipo == "fielzone":
                        dados = await scrape_fielzone(page, jogo)
                    elif tipo == "loungebrahma":
                        dados = await scrape_loungebrahma(page, jogo)
                    elif tipo == "soudaliga":
                        dados = await scrape_soudaliga(page, jogo)
                    elif tipo == "arenakids":
                        dados = await scrape_arenakids(page, jogo)
                    elif tipo == "ticket360":
                        dados = await scrape_ticket360(page, jogo)
                    elif tipo == "ticket360_fiel":
                        dados = await scrape_ticket360_fiel(page, jogo)
                    else:
                        dados = {"erro": "Tipo desconhecido"}

                    dados["nome"] = parceiro["nome"]
                    dados["cor"] = parceiro["cor"]
                    dados["url_base"] = parceiro["url"]
                    dados["atualizado_em"] = formatar_hora()

                    if "erro" in dados:
                        print(f"  X Erro: {dados['erro']}")
                    else:
                        for ing in dados.get("ingressos", []):
                            print(f"  OK {ing['setor']}: {ing['preco']}")

                    parceiros_novos[parceiro["nome"]] = dados

                except Exception as e:
                    print(f"  X Erro geral: {e}")
                    parceiros_novos[parceiro["nome"]] = {
                        "nome": parceiro["nome"], "cor": parceiro["cor"],
                        "url_base": parceiro["url"], "erro": str(e),
                        "ingressos": [], "atualizado_em": formatar_hora()
                    }
                finally:
                    await page.close()

            # Propaga data_jogo extraída do Arena Kids (se disponível)
            data_jogo_extraida = ""
            for dados_p in parceiros_novos.values():
                if dados_p.get("data_jogo"):
                    data_jogo_extraida = dados_p["data_jogo"]
                    break

            # Fallback: usa data extraída na descoberta (Lounge Brahma / Fielzone)
            if not data_jogo_extraida:
                for nome_hint, data_hint in data_hints.items():
                    if jogo_corresponde(jogo, nome_hint) and data_hint:
                        data_jogo_extraida = data_hint
                        break

            resultados[jogo] = {
                "parceiros": parceiros_novos,
                "atualizado_em": formatar_hora(),
                "data_jogo": data_jogo_extraida,
            }

        await browser.close()

    try:
        mongo_upsert.upsert_resultados(resultados)
    except Exception as e:
        print(f"[MongoDB] Erro no upsert: {e}")

    print(f"\nScraping concluído — {formatar_hora()}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())