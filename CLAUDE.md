# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Monitor de Ingressos** is a price monitoring dashboard for Corinthians match tickets. It scrapes 6 vendor websites every 6 hours and exposes the data via a REST API to a vanilla JS frontend.

## Running the Project

### Full Stack (Docker — recommended)
```bash
docker compose up -d
```
Starts MongoDB (port 27017), backend API (port 3000), and the Python scraper. Then open `frontend/dashboard.html` in a browser.

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
frontend/dashboard.html  →  backend (Express/Node)  →  MongoDB
                                                         ↑
                         scrapping/ (Python/Playwright) ─┘
```

- **`backend/`** — Express 5 + Mongoose 8 API. Routes: `/jogos`, `/parceiros`, `/ofertas`. Supports filtering offers by `?jogo_slug=`, `?parceiro_slug=`, `?status=`.
- **`frontend/dashboard.html`** — Single self-contained HTML file. Auto-detects localhost vs production for API URL. Polls backend every 60s.
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

## Onde parei — 2026-04-16

### Arena Kids — como renovar o login

O scraper usa `ingresse_state.json` (cookies em JSON puro) em vez de perfil Chromium persistente.
Isso resolve o problema de incompatibilidade entre Windows (login local) e Linux (Docker).

**Quando a sessão expirar** (log: `"Sessao expirada"`):
1. `python scrapping/login_arenakids.py`
2. Browser abre no `cart.ingresse.com` — faça o login normalmente
3. Feche a janela do browser — o script salva `ingresse_state.json` automaticamente
4. `docker compose restart scraper`
5. Verificar nos logs: `[Arena Kids] Cart carregou!`
