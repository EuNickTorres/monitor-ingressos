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
import db

# ============================================================
# CONFIGURAÇÃO — EDITE AQUI
# ============================================================

def _ler_jogos_config():
    try:
        cfg = db.carregar_config()
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
    return ["Corinthians x Coritiba"]  # padrão

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
    return re.sub(r'\s+', ' ', texto.strip().lower())

def jogo_corresponde(texto, busca):
    t = normalizar_jogo(texto)
    b = normalizar_jogo(busca)
    partes = b.split(' x ')
    if len(partes) == 2:
        time1, time2 = partes[0].strip(), partes[1].strip()
        return (time1 in t and time2 in t) or b in t
    return b in t

def extrair_precos_texto(texto):
    padrao = r'R\$\s*[\d.,]+'
    encontrados = re.findall(padrao, texto, re.IGNORECASE)
    return list(dict.fromkeys(encontrados))

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

        # Setor: a linha mais curta relevante (sem data, sem "De ", sem "Neo Quim")
        setor = ""
        for linha in linhas:
            if any(x in linha for x in ["R$", "/202", "De ", "Neo Qu", "Abertura", "Lote"]):
                continue
            if 3 < len(linha) < 70:
                setor = linha
                # Para na primeira linha curta boa
                break

        # Se nao achou setor curto, pega o trecho antes do primeiro " - "
        if not setor:
            titulo = linhas[0] if linhas else bloco[:60]
            setor = titulo.split(" - ")[0].strip()[:60]

        preco = precos[0]
        chave = setor + preco
        if chave in vistos or not setor:
            continue
        vistos.add(chave)

        ingressos.append({"setor": setor[:60], "preco": preco})
        print(f"  [Sou da Liga]   {setor[:50]}: {preco}")

    if not ingressos:
        # Fallback texto bruto
        conteudo = await page.inner_text("body")
        precos = extrair_precos_texto(conteudo)
        if precos:
            ingressos = [{"setor": f"Ingresso {i+1}", "preco": p} for i, p in enumerate(precos[:10])]
        else:
            return {"erro": f"Jogo '{jogo}' nao encontrado ou site bloqueado"}

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
            let el = a; let titulo = '';
            for (let i = 0; i < 12; i++) {
                el = el.parentElement;
                if (!el) break;
                const h = el.querySelector('h1,h2,h3,h4,h5,h6');
                if (h && h.innerText.trim().length > 3) { titulo = h.innerText.trim(); break; }
            }
            result.push({ href: a.href, titulo: titulo });
        }
        return result;
    }""")

    ingresse_url = None
    for par in pares:
        if jogo_corresponde(par.get('titulo', ''), jogo):
            ingresse_url = par['href']
            print(f"  [Arena Kids] Link: {ingresse_url}")
            break
    if not ingresse_url:
        adversario = jogo.split(' x ')[-1].strip().lower()
        for par in pares:
            if adversario in par.get('titulo', '').lower():
                ingresse_url = par['href']
                break

    if not ingresse_url:
        return {"ingressos": [{"setor": "Ver no site", "preco": "-"}], "url_evento": "https://arenakidscorinthians.com.br/"}

    uuid_match = re.search(r'cart\.ingresse\.com/([0-9a-f-]{36})/tickets', ingresse_url)
    uuid = uuid_match.group(1) if uuid_match else None
    print(f"  [Arena Kids] UUID: {uuid}")

    event_id = None
    ingressos = []

    # Busca event_id na pagina publica do Ingresse
    print(f"  [Arena Kids] Abrindo pagina publica para inspecionar HTML...")
    slug = f"corinthians-x-{jogo.split(' x ')[-1].strip().lower().replace(' ','-')}-camarote-arena-kids"
    url_pub = f"https://www.ingresse.com/{slug}"
    print(f"  [Arena Kids] Slug URL: {url_pub}")
    await page.goto(url_pub, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(4000)
    html = await page.content()

    import re as _re
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

    if not event_id:
        return {"ingressos": [{"setor": "Ver no site", "preco": "-"}], "url_evento": ingresse_url}

    cart_url = f"https://cart.ingresse.com/{uuid}/tickets" if uuid else None

    # Tenta cart com browser visivel para passar pelo Cloudflare
    if cart_url:
        print(f"  [Arena Kids] Tentando cart (browser visivel): {cart_url}")
        try:
            from playwright.async_api import async_playwright as _ap
            INGRESSE_EMAIL = os.environ.get("INGRESSE_EMAIL", "")
            INGRESSE_SENHA = os.environ.get("INGRESSE_SENHA", "")
            async with _ap() as _p:
                _browser = await _p.chromium.launch(
                    headless=True,
                    args=["--disable-blink-features=AutomationControlled"]
                )
                _ctx = await _browser.new_context(
                    viewport={"width": 1280, "height": 900},
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                    locale="pt-BR",
                    timezone_id="America/Sao_Paulo",
                )
                await _ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined}); window.chrome={runtime:{}};")
                _page = await _ctx.new_page()

                INGRESSE_TELEFONE = os.environ.get("INGRESSE_TELEFONE", "")
                # Usa contexto persistente para salvar sessao do Ingresse
                # Apos primeiro login manual, nao pede mais codigo
                import os as _os
                profile_dir = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "ingresse_profile")
                await _browser.close()  # fecha browser temporario
                _browser = None

                print("  [Arena Kids] Usando perfil persistente:", profile_dir)
                _ctx2 = await _p.chromium.launch_persistent_context(
                    profile_dir,
                    headless=False,
                    args=["--disable-blink-features=AutomationControlled", "--start-minimized"],
                    viewport={"width": 1280, "height": 900},
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                    locale="pt-BR",
                    timezone_id="America/Sao_Paulo",
                )
                await _ctx2.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined}); window.chrome={runtime:{}};")
                _page = await _ctx2.new_page()

                # Abre cart diretamente - se sessao salva, entra automaticamente
                print("  [Arena Kids] Abrindo cart com sessao salva...")
                await _page.goto(cart_url, wait_until="domcontentloaded", timeout=30000)
                await _page.wait_for_timeout(3000)
                corpo = await _page.inner_text("body")

                # Se precisar de login, preenche telefone e aguarda codigo do usuario
                if "Acesse sua conta" in corpo or "acesse sua conta" in corpo.lower():
                    print("  [Arena Kids] Sessao expirada - fazendo login...")
                    try:
                        tel_input = await _page.wait_for_selector(
                            "input[type=tel], input[placeholder*=telefone i], input[placeholder*=phone i], input[placeholder*=celular i]",
                            timeout=8000
                        )
                        await tel_input.fill(INGRESSE_TELEFONE)
                        await _page.wait_for_timeout(500)
                        await _page.click("button[type=submit], button:has-text('Continuar'), button:has-text('Próximo')")
                        await _page.wait_for_timeout(2000)
                        # Aguarda usuario digitar o codigo (janela fica visivel)
                        print("  [Arena Kids] ** VERIFIQUE SEU EMAIL E DIGIT O CODIGO NA JANELA DO BROWSER **")
                        print("  [Arena Kids] Aguardando login (60s)...")
                        for _ in range(30):
                            await _page.wait_for_timeout(2000)
                            corpo = await _page.inner_text("body")
                            if "Acesse sua conta" not in corpo and "código" not in corpo.lower():
                                print("  [Arena Kids] Login concluido!")
                                break
                    except Exception as le:
                        print(f"  [Arena Kids] Login form erro: {le}")
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
                    print("  [Arena Kids] Cart carregou! Expandindo tickets...")
                    # Fecha popups/modais antes de expandir
                    for fechar_sel in [
                        "button:has-text('Fechar')", "button:has-text('Cancelar')",
                        "[aria-label='Close']", "[aria-label='Fechar']",
                        "button:has-text('X')", "button:has-text('×')",
                        "[class*='close']", "[class*='dismiss']",
                    ]:
                        try:
                            btn = await _page.query_selector(fechar_sel)
                            if btn and await btn.is_visible():
                                await btn.click()
                                print(f"  [Arena Kids] Popup fechado: {fechar_sel}")
                                await _page.wait_for_timeout(800)
                                break
                        except:
                            pass

                    # Clica em cada item para expandir e revelar o preco
                    # Roda multiplas passagens ate nao aparecer mais itens novos
                    # Estrategia: itera pelos itens fechados, abre um por vez,
                    # extrai o preco que aparece e fecha antes do popup travar tudo
                    precos_coletados = {}  # nome -> preco

                    for passagem in range(4):
                        await _page.keyboard.press("Escape")
                        await _page.wait_for_timeout(300)

                        itens = await _page.query_selector_all("li, [class*='ticket'], [class*='item'], [class*='product'], [class*='card']")
                        novos = 0
                        for item in itens:
                            try:
                                txt = (await item.inner_text()).strip()
                                if not txt or len(txt) < 5 or len(txt) > 300:
                                    continue
                                ps = extrair_precos_texto(txt)
                                if ps:
                                    # Ja expandido — extrai nome+preco
                                    nome = re.sub(r'R\$\s*[\d.,]+', '', txt).strip(" -:*+()\.\n")
                                    nome = re.sub(r'\s+', ' ', nome).strip()[:60]
                                    if nome and len(nome) > 3 and nome not in precos_coletados:
                                        try:
                                            val = float(ps[0].replace("R$","").replace(".","").replace(",",".").strip())
                                            if val > 0:
                                                precos_coletados[nome] = ps[0]
                                                novos += 1
                                        except:
                                            pass
                                else:
                                    # Ainda fechado — clica para abrir
                                    await item.click()
                                    await _page.wait_for_timeout(200)
                                    # Extrai preco que apareceu
                                    txt2 = (await item.inner_text()).strip()
                                    ps2 = extrair_precos_texto(txt2)
                                    if ps2:
                                        nome2 = re.sub(r'R\$\s*[\d.,]+', '', txt2).strip(" -:*+()\.\n")
                                        nome2 = re.sub(r'\s+', ' ', nome2).strip()[:60]
                                        if nome2 and len(nome2) > 3 and nome2 not in precos_coletados:
                                            try:
                                                val = float(ps2[0].replace("R$","").replace(".","").replace(",",".").strip())
                                                if val > 0:
                                                    precos_coletados[nome2] = ps2[0]
                                                    novos += 1
                                            except:
                                                pass
                                    # Fecha popup se apareceu
                                    await _page.keyboard.press("Escape")
                                    await _page.wait_for_timeout(150)
                            except:
                                pass

                        print(f"  [Arena Kids] Passagem {passagem+1}: {len(precos_coletados)} precos ({novos} novos)")
                        if novos == 0:
                            break

                    if precos_coletados:
                        ingressos = [{"setor": k, "preco": v} for k, v in precos_coletados.items()]
                        print(f"  [Arena Kids] {len(ingressos)} ingresso(s) do cart!")

                    corpo_tmp = await _page.inner_text("body")
                    precos_agora = len(extrair_precos_texto(corpo_tmp))
                    print(f"  [Arena Kids] {precos_agora} precos visiveis apos expansao")
                    corpo = await _page.inner_text("body")

                    # Extrai precos do JS do cart via evaluate
                    pares_js = await _page.evaluate("""() => {
                        const result = [];
                        const visited = new Set();
                        const all = document.querySelectorAll('*');
                        for (const el of all) {
                            if (el.childElementCount > 0) continue;
                            const t = (el.innerText || '').trim();
                            if (!t.match(/R\$\s*[\d.,]+/) || t.length > 80) continue;
                            const num = parseFloat(t.replace(/R\$\s*/,'').replace(/\./g,'').replace(',','.'));
                            if (!num || num <= 0) continue;
                            let nome = '';
                            let container = el;
                            for (let i = 0; i < 6; i++) {
                                container = container.parentElement;
                                if (!container) break;
                                const kids = Array.from(container.querySelectorAll('*'));
                                for (const k of kids) {
                                    if (k === el || k.childElementCount > 0) continue;
                                    const kt = (k.innerText || '').trim();
                                    if (kt && kt.length > 5 && kt.length < 100 && !kt.match(/R\$/) && !kt.match(/^[\d\s+:]+$/)) {
                                        nome = kt;
                                        break;
                                    }
                                }
                                if (nome) break;
                            }
                            if (!nome) continue;
                            const key = nome + t;
                            if (!visited.has(key)) {
                                visited.add(key);
                                result.push({setor: nome.substring(0,60), preco: t});
                            }
                        }
                        return result;
                    }""")

                    if pares_js:
                        ingressos = [r for r in pares_js if r and r.get("setor") and r.get("preco")]
                        print(f"  [Arena Kids] {len(ingressos)} ingresso(s) do cart!")
                    else:
                        # Debug: mostra body completo para ver o que tem
                        print(f"  [Arena Kids] JS nao achou pares. Body snippet: {corpo[:500].replace(chr(10),' ')}")
                    
                    if not ingressos:
                        # Fallback linha a linha
                        linhas = [l.strip() for l in corpo.splitlines() if l.strip()]
                        for idx, linha in enumerate(linhas):
                            lps = extrair_precos_texto(linha)
                            if not lps: continue
                            try:
                                val = float(lps[0].replace("R$","").replace(".","").replace(",",".").strip())
                                if val <= 0: continue
                            except:
                                continue
                            nome = re.sub(r'R\$\s*[\d.,]+', '', linha).strip(" -:*+()")
                            nome = re.sub(r'\s+', ' ', nome).strip()
                            nome_l = nome.lower()
                            nome_ruim = not nome or len(nome) < 3 or nome_l.startswith('a partir') or 'taxa' in nome_l
                            if nome_ruim:
                                nome = ""
                                for offset in [1, 2]:
                                    if idx >= offset:
                                        cand = linhas[idx - offset].strip()
                                        if cand and not extrair_precos_texto(cand) and 2 < len(cand) < 80:
                                            nome = cand[:60]
                                            break
                            if nome and len(nome) > 2:
                                ingressos.append({"setor": nome, "preco": lps[0]})
                else:
                    corpo_debug = corpo[:400].replace("\n"," ")
                    print(f"  [Arena Kids] Cart nao carregou. Body: {corpo_debug}")
                await _ctx2.close()
        except Exception as e:
            print(f"  [Arena Kids] Cart login erro: {e}")

    # Fallback: embedstore
    if not ingressos:
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

    return {"ingressos": unicos[:12], "url_evento": ingresse_url}


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
                    eh_galeria = "galeria" in texto.lower() or "galeria" in href.lower()
                    eh_jogo = jogo_corresponde(texto, jogo) or jogo_corresponde(href, jogo)
                    if eh_galeria and eh_jogo:
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

    # Deduplica URLs mantendo Fiel primeiro
    urls_vistas = set()
    urls_unicas = []
    for nome_ev, url_ev in urls_galeria:
        if url_ev not in urls_vistas:
            urls_vistas.add(url_ev)
            urls_unicas.append((nome_ev, url_ev))
    urls_galeria = urls_unicas[:2]  # max 2: Fiel + Padrao

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
                    eh_fiel = "fiel" in texto.lower() or "fiel" in href.lower()
                    eh_jogo = jogo_corresponde(texto, jogo) or jogo_corresponde(href, jogo)
                    if eh_fiel and eh_jogo:
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
        resultado = await frame.evaluate("""() => {
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
# PERSISTENCIA
# ============================================================

def carregar_precos_anteriores():
    return db.carregar_precos()

def salvar_precos(dados):
    db.salvar_precos(dados)

def detectar_mudancas(novo, anterior):
    mudancas = []
    if not anterior:
        return mudancas
    novos = {i["setor"]: i["preco"] for i in novo.get("ingressos", [])}
    ants = {i["setor"]: i["preco"] for i in anterior.get("ingressos", [])}
    for setor, preco in novos.items():
        if setor in ants and ants[setor] != preco:
            mudancas.append({"setor": setor, "preco_anterior": ants[setor], "preco_novo": preco})
    return mudancas


# ============================================================
# MAIN
# ============================================================

def migrar_formato_antigo(dados):
    """Converte prices.json do formato antigo (flat) para o novo (por-jogo)."""
    if "jogo" in dados and "parceiros" in dados:
        nome = dados["jogo"]
        print(f"[Migracao] Formato antigo detectado. Migrando jogo '{nome}'...")
        return {nome: {
            "parceiros": dados.get("parceiros", {}),
            "atualizado_em": dados.get("atualizado_em", ""),
            "historico": dados.get("historico", []),
        }}
    return dados


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="Re-raspar jogos já existentes")
    parser.add_argument("--parceiro", type=str, default=None,
        help="Rodar apenas um parceiro específico (ex: arenakids)")
    args = parser.parse_args()

    jogos = _ler_jogos_config()

    print("=" * 60)
    print(f"  MONITOR DE INGRESSOS - {formatar_hora()}")
    print(f"  Jogos: {jogos}")
    print("=" * 60)

    # Carrega dados existentes e migra formato antigo se necessário
    dados_existentes = carregar_precos_anteriores()
    dados_existentes = migrar_formato_antigo(dados_existentes)

    # Inicia resultados carregando dados de todos os jogos já salvos
    resultados = {jogo: dado for jogo, dado in dados_existentes.items()}

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

        for jogo in jogos:
            global JOGO_BUSCA
            JOGO_BUSCA = jogo

            if not args.force and jogo in dados_existentes:
                print(f"\n[PULANDO] '{jogo}' já tem dados. Use --force para re-raspar.")
                continue

            print(f"\n{'='*60}")
            print(f"  JOGO: {jogo}")
            print(f"{'='*60}")

            # Dados anteriores específicos deste jogo
            dados_jogo_anterior = dados_existentes.get(jogo, {})
            parceiros_anteriores = dados_jogo_anterior.get("parceiros", {})
            historico_jogo = list(dados_jogo_anterior.get("historico", []))

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

                    ant = parceiros_anteriores.get(parceiro["nome"], {})
                    mudancas = detectar_mudancas(dados, ant)
                    dados["mudancas"] = mudancas

                    if mudancas:
                        print(f"  *** {len(mudancas)} mudanca(s) detectada(s)! ***")
                        for m in mudancas:
                            print(f"      {m['setor']}: {m['preco_anterior']} -> {m['preco_novo']}")
                            historico_jogo.append({
                                "data": formatar_hora(),
                                "parceiro": parceiro["nome"],
                                "setor": m["setor"],
                                "preco_anterior": m["preco_anterior"],
                                "preco_novo": m["preco_novo"]
                            })

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
                        "ingressos": [], "mudancas": [], "atualizado_em": formatar_hora()
                    }
                finally:
                    await page.close()

            resultados[jogo] = {
                "parceiros": parceiros_novos,
                "atualizado_em": formatar_hora(),
                "historico": historico_jogo,
            }

        await browser.close()

    salvar_precos(resultados)
    print(f"\nDados salvos no Supabase")
    print("Acesse o dashboard via http://localhost:8000")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
