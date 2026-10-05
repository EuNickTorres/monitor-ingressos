# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Monitor de Ingressos** is a price monitoring dashboard for Corinthians match tickets. It scrapes 6 vendor websites every 6 hours and exposes the data via a REST API to a vanilla JS frontend.

## Running the Project

### Full Stack (Docker — recommended)
```bash
docker compose up -d
```
Starts MongoDB (port 27017), backend API (port 3000), and the Python scraper. Then open `frontend/index.html` in a browser.

### Backend Only
```bash
cd backend
npm install
npm run dev       # development with --watch
npm start         # production
npm run seed      # populate DB with sample data
```

### Scraper Only
```bash
cd scrapping
pip install -r requirements.txt
python scraper.py --jogo "Corinthians x Vasco"             # jogo obrigatório
python scraper.py --jogo "Corinthians x Vasco" --parceiro "ticket360_fiel"  # parceiro específico
python run_scheduled.py                                    # loop (interval via SCRAPER_INTERVAL_HOURS, default 6h)
```

`--jogo` é obrigatório. `--parceiro` filtra pelo campo `tipo` do parceiro (ex: `fielzone`, `loungebrahma`, `soudaliga`, `arenakids`, `ticket360`, `ticket360_fiel`).

## Architecture

Three services communicate as follows:

```
frontend/index.html + app.js  →  backend (Express/Node)  →  MongoDB
                                                         ↑
                         scrapping/ (Python/Playwright) ─┘
```

- **`backend/`** — Express 5 + Mongoose 8 API. Routes: `/jogos`, `/parceiros`, `/ofertas`. Supports filtering offers by `?jogo_slug=`, `?parceiro_slug=`, `?status=`.
- **`frontend/index.html` + `styles.css` + `app.js`** — Static SPA. Auto-detects localhost vs production, groups duplicate games, separates upcoming/history, and refreshes the API every 60s.
- **`scrapping/`** — Playwright (Chromium headless) scraper with 6 vendor strategies in `scraper.py`. `mongo_upsert.py` normalizes and upserts data. `run_scheduled.py` is the loop driver.

## MongoDB Schema

Three collections:
- **jogos** — `{nome, data, slug}` (unique slug, sorted by date)
- **parceiros** — `{nome, slug}` (unique slug)
- **ofertas** — `{parceiro_id, jogo_id, status, itens[]}` where each item has `{nome, descricao, preco, tipo, publico}`

## Scraper Vendor Strategies

Each vendor in `scraper.py` uses a dedicated async function:

| Vendor | Strategy key | Notes |
|--------|-------------|-------|
| Camarote Fielzone | `fielzone` | Ingresse iframe extraction |
| Lounge Brahma | `loungebrahma` | WooCommerce dropdown variations |
| Bar do Zeca | `soudaliga` | React SPA text-block parsing (fragile) |
| Arena Kids | `arenakids` | Scrapes cart.ingresse.com links from Arena Kids site → opens cart injecting saved session (`ingresse_state.json`) → clicks "Combos" tab → extracts prices from body text. |
| Galeria SCCP | `ticket360` | Modal extraction after "COMPRAR" click |
| Camarote Fiel Torcedor | `ticket360_fiel` | Searches `/eventos/pesquisar?s=Fiel+torcedor` → filters out Galeria SCCP results → closes `#informacaoObrigatoria` modal → clicks COMPRAR → extracts prices |

## Adicionando um Novo Parceiro

### Método: "Explorar e Replicar"

Quando um novo parceiro for adicionado, use o seguinte processo para entender o fluxo de compra antes de implementar o scraper:

### 1. Explorar a página do parceiro
```python
import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()
        await page.goto('https://site-do-parceiro.com.br', wait_until='networkidle', timeout=30000)
        await page.screenshot(path='parceiro_1.png', full_page=False)

        # Ver todos os links de compra
        links = await page.evaluate('''() => {
            return Array.from(document.querySelectorAll('a, button')).map(el => ({
                tag: el.tagName, href: el.href || '',
                text: el.innerText.trim().substring(0, 100)
            })).filter(x => x.text);
        }''')
        for l in links:
            print(l)

        await browser.close()

asyncio.run(main())
```

### 2. Mapear jogos → links
Identificar qual link/botão corresponde a cada jogo. Geralmente é um `<a>` com href apontando para o sistema de venda (Ingresse, Ticket360, site próprio).

### 3. Abrir a página de compra e capturar preços
```python
await page.goto(url_do_jogo, wait_until='networkidle', timeout=30000)
await page.screenshot(path='parceiro_compra.png')
text = await page.inner_text('body')
print(text[:3000])
```

### 4. Identificar padrões
- Se aparecer modal bloqueando → fechar antes de interagir
- Se tiver abas (ex: "Combos", "Individual") → clicar na aba correta
- Se precisar de login → usar perfil persistente (`ingresse_profile/`)
- Os preços geralmente aparecem no formato `R$ X.XXX,00` no body text

### 5. Implementar
Adicionar o parceiro em `PARCEIROS` (scraper.py:42) com `nome`, `url`, `tipo` e `cor`, e criar a função `async def scrape_<tipo>(page, jogo)` seguindo o padrão das existentes.

## Fragile Areas

- **Arena Kids** (`ingresse_state.json`): Requires a saved Ingresse session. The scraper loads `scrapping/ingresse_state.json` (plain JSON cookies — cross-platform) and injects it into a headless Chromium context. When the session expires, the scraper returns gracefully (other vendors keep working). To renew: run `python login_arenakids.py` **locally**, log in on `cart.ingresse.com`, close the browser — the script saves `ingresse_state.json` automatically. Then `docker compose restart scraper`. Session typically lasts weeks/months.
- **Bar do Zeca**: Text proximity parsing on a React SPA — breaks if page layout changes. Em jogos da Libertadores, o scraper pode capturar "Libertadores" como nome do setor em vez do nome real (ex: "Arquibancada"), pois é o primeiro texto curto encontrado no bloco.
- **Slugs in seed.js**: Game slugs contain hard-coded dates and may need manual updates.
- **`prices.json`** in `scrapping/` is a debug artifact — not used by the backend.
- The API has no authentication; it is intended for internal/local use.

## Environment Variables

Backend (see `backend/.env.example`):
```
NODE_ENV=development
PORT=3000
MONGO_URI=mongodb://mongo:27017/ingressos
```

Scraper:
```
MONGO_URI=mongodb://mongo:27017/ingressos
SCRAPER_INTERVAL_HOURS=6
```

## Exportar preços para TXT

Script `scrapping/exportar_precos.py` — gera um arquivo de texto com todos os preços do banco:

```bash
cd scrapping
python exportar_precos.py                    # gera precos.txt
python exportar_precos.py --output meu.txt   # nome customizado
```

Requer MongoDB rodando. Conecta via `MONGO_URI` (padrão: `mongodb://localhost:27017/ingressos`).

---

### Arena Kids — como renovar o login

O scraper usa `ingresse_state.json` (cookies em JSON puro) em vez de perfil Chromium persistente.
Isso resolve o problema de incompatibilidade entre Windows (login local) e Linux (Docker).

**Quando a sessão expirar** (log: `"Sessao expirada"`):
1. `python scrapping/login_arenakids.py`
2. Browser abre no `cart.ingresse.com` — faça o login normalmente
3. Feche a janela do browser — o script salva `ingresse_state.json` automaticamente
4. `docker compose restart scraper`
5. Verificar nos logs: `[Arena Kids] Cart carregou!`

---

## Caso o Arena Kids expire (produção via GitHub Actions)

Quando a sessão do Ingresse expirar, o scraper **não quebra** — os outros 5 parceiros continuam funcionando normalmente. O Arena Kids simplesmente retorna sem dados para aquela execução.

**Como saber que expirou:**
- Acesse o GitHub → repositório → aba **Actions** → última execução do "Scraper de Ingressos"
- Abra o passo **"Rodar scraper"** e procure nos logs por `"Sessao expirada"` ou `[Arena Kids]` sem dados
- Outra forma: no dashboard, o card do Arena Kids vai parar de atualizar os preços

**Como renovar:**
1. Rode localmente: `python scrapping/login_arenakids.py`
2. Browser abre no `cart.ingresse.com` — faça o login normalmente
3. Feche a janela — o script salva `ingresse_state.json` automaticamente
4. ⚠️ **NÃO commite** esse arquivo — ele contém dados pessoais (CPF, email, etc.)
5. Copie o conteúdo do `ingresse_state.json` gerado
6. Vá no GitHub → Settings → Secrets and variables → Actions → edite o secret `INGRESSE_STATE` colando o novo conteúdo
7. Na próxima execução do GitHub Actions (automática ou manual), a sessão já estará renovada

---

## Histórico de implementações relevantes

### Descoberta automática de jogos (multi-fonte)
O scraper não depende mais de uma lista manual de jogos. `_descobrir_jogos()` em `scraper.py` consulta 3 fontes em sequência e mescla com deduplicação:
- **Arena Kids** — links `cart.ingresse.com` na página principal
- **Lounge Brahma** — cards WooCommerce com nome e data no card (`DD/MM HHhMM`)
- **Camarote Fielzone** — cards Ingresse com nome do jogo

A deduplicação usa `_ALIASES_JOGO` + `_ALIASES_TIMES` para reconhecer nomes equivalentes (ex: "Vasco" = "Vasco da Gama", "Atletico MG" = "Atletico Mineiro").

### Datas dos jogos
- Lounge Brahma extrai data diretamente do card (`_extrair_data_raw()`)
- Jogos descobertos por outras fontes usam o `data_hints` do Lounge Brahma como fallback
- `mongo_upsert.py` parseia `dd/mm HHhMM` e `dd/mm` e salva no campo `data` do jogo

### Filtro de jogos no Ticket360 (Galeria SCCP + Fiel Torcedor)
Filtro baseado no **href do link** (não no texto do card), evitando falsos positivos por nomes de cidades. URLs com hífen são normalizadas (`href.replace('-', ' ')`). Combos são excluídos. Ambos os parceiros (ticket360 e ticket360_fiel) usam a mesma lógica.

### Persistência de preços (merge em vez de sobrescrita)
`mongo_upsert.py` faz merge dos itens existentes com os novos: preços são atualizados, itens novos são adicionados, itens que desapareceram da página (esgotados) são **mantidos** — não removidos. Somente se não houver nenhum item é que a oferta vira "fechado".

### Frontend no Cloudflare Workers
`frontend/index.html` (arquivo único) está publicado em:
**https://monitor-ingressos.nicollastorresdamota.workers.dev/**
Deploy via `wrangler deploy` na pasta `frontend/`. O arquivo `_redirects` foi removido pois causava loop infinito. `PROD_API_URL` aponta para `https://monitor-ingressos.onrender.com` (atualizado em 2026-04-23).

### Recuperar preços perdidos do Arena Kids
Script `scrapping/recuperar_vasco_kids.py` — restaura preços do Arena Kids para Corinthians x Vasco a partir de backup. Serve de template caso outros preços sejam perdidos.

---

## Onde parei — 2026-04-22

### O que foi feito hoje (2026-04-22)
- Galeria SCCP: filtro de jogos corrigido para usar href em vez de texto do card (evita falsos positivos como "São Paulo" cidade)
- Preços do Arena Kids para Corinthians x Vasco recuperados manualmente via `recuperar_vasco_kids.py`
- Preços corretos da Galeria SCCP para Corinthians x São Paulo inseridos manualmente (R$ 585 Fiel / R$ 650 Padrão)
- Preços errados do Fiel Torcedor para Corinthians x São Paulo removidos (oferta marcada como fechado)
- Persistência de preços: merge em vez de sobrescrita já implementado em `mongo_upsert.py`

---

## Onde parei — 2026-04-23

### O que foi feito hoje (2026-04-23)

#### Infraestrutura de produção — concluída ✓

**MongoDB Atlas (banco em produção)**
- Cluster free tier criado em https://cloud.mongodb.com (Cluster0, região US)
- Usuário: configurado no MongoDB Atlas; senha armazenada apenas nos secrets de deploy
- Network Access: `0.0.0.0/0` liberado (acesso de qualquer IP — necessário para Render e GitHub Actions)
- Connection string: configurada via secret `MONGO_URI` (não registrar credenciais no repositório)
- Dados migrados do MongoDB local (Docker) via `mongodump` + `mongorestore`: 20 jogos, 6 parceiros, 116 ofertas

**Backend no Render**
- Serviço: `monitor-ingressos` em https://render.com
- URL de produção: **https://monitor-ingressos.onrender.com**
- Plano: Free (512MB RAM) — suficiente para o Express/Mongoose
- Runtime: Docker usando `backend/Dockerfile`
- Variáveis de ambiente configuradas: `MONGO_URI`, `NODE_ENV=production`
- ⚠️ O plano free hiberna após inatividade — primeira requisição pode demorar ~50s para acordar

**Frontend atualizado**
- `PROD_API_URL` em `frontend/index.html` atualizado para `https://monitor-ingressos.onrender.com`
- Dashboard em produção funcionando: https://monitor-ingressos.nicollastorresdamota.workers.dev/

#### Como fazer backup e restaurar o banco
```bash
# Exportar do MongoDB local (Docker)
docker exec -it ingressos-mongo mongodump --db ingressos --out /tmp/dump
docker cp ingressos-mongo:/tmp/dump ./dump

# Importar no Atlas
docker cp ./dump/ingressos ingressos-mongo:/tmp/dump-restore
docker exec -it ingressos-mongo mongorestore --uri "$MONGO_URI" /tmp/dump-restore
```

### Pendente

#### Scraper → GitHub Actions (gratuito)
- Criar workflow `.github/workflows/scraper.yml` com cron `0 */6 * * *` (a cada 6h)
- O runner do GitHub Actions tem 7GB RAM — suficiente para Playwright + Chromium
- O `ingresse_state.json` (sessão Arena Kids) ficará como GitHub Secret e deverá ser atualizado manualmente quando a sessão expirar
- A `MONGO_URI` do Atlas também ficará como GitHub Secret
- Limite: 2000 min/mês grátis para repo privado (~1200 min usados com 4 execuções/dia de 10min)

