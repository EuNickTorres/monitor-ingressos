# Monitor de Ingressos

## 1. Visão Geral

**Monitor de Ingressos** é uma aplicação web que monitora e exibe preços de ingressos para jogos do Corinthians em múltiplos parceiros/vendedores. O sistema raspa automaticamente os sites dos parceiros a cada 6 horas, persiste os dados no MongoDB e os expõe via API REST para um dashboard web.

**Problema resolvido:** Comparar preços de camarotes e ingressos VIP espalhados em 6 sites diferentes, de forma automática e centralizada.

---

## 2. Arquitetura

```
┌──────────────────┐        HTTP REST         ┌──────────────────────┐
│  dashboard.html  │ ◄─────────────────────── │  backend (Node.js)   │
│  (Vanilla JS)    │   /jogos, /ofertas        │  Express + Mongoose  │
└──────────────────┘                           └──────────┬───────────┘
                                                          │ ODM
                                                ┌─────────▼───────────┐
                                                │   MongoDB            │
                                                │   ingressos DB       │
                                                │   jogos, parceiros,  │
                                                │   ofertas            │
                                                └─────────▲───────────┘
                                                          │ upsert
                                               ┌──────────┴───────────┐
                                               │  scraper (Python)    │
                                               │  Playwright headless │
                                               │  6 parceiros         │
                                               │  roda a cada 6h      │
                                               └──────────────────────┘
```

**Stack:**
- **Backend:** Node.js 20, Express 5, Mongoose 8
- **Frontend:** HTML/CSS/JS puro (sem framework)
- **Banco:** MongoDB 7
- **Scraper:** Python 3.11, Playwright (Chromium headless)
- **Infra:** Docker + Docker Compose

---

## 3. Estrutura de Pastas

```
monitor-ingressos/
├── docker-compose.yml          # Orquestra 3 serviços: mongo, backend, scraper
├── backend/
│   ├── Dockerfile              # node:20-alpine, porta 3000
│   ├── .env / .env.example     # NODE_ENV, PORT, MONGO_URI
│   ├── package.json            # deps: express, mongoose, cors, dotenv
│   └── src/
│       ├── server.js           # Entry point, CORS, monta rotas
│       ├── db.js               # Conexão Mongoose
│       ├── routes.js           # Router raiz + health check GET /
│       ├── routes/
│       │   ├── jogos.js        # GET /jogos, GET /jogos/:slug
│       │   ├── ofertas.js      # GET /ofertas (com filtros), GET /ofertas/:id
│       │   └── parceiros.js    # GET /parceiros, GET /parceiros/:slug
│       ├── models/
│       │   ├── Jogo.js         # Schema: nome, data, slug (unique)
│       │   ├── Parceiro.js     # Schema: nome, slug (unique)
│       │   └── Oferta.js       # Schema: parceiro_id, jogo_id, status, itens[]
│       └── seed.js             # Popula DB com dados de exemplo
├── frontend/
│   └── dashboard.html          # SPA completa (CSS e JS embutidos)
└── scrapping/
    ├── Dockerfile              # python:3.11-slim + Playwright Chromium
    ├── requirements.txt        # playwright, pymongo
    ├── scraper.py              # Lógica de scraping por parceiro (~1200 linhas)
    ├── mongo_upsert.py         # Transforma e persiste resultados no MongoDB
    ├── run_scheduled.py        # Loop infinito com intervalo configurável
    ├── prices.json             # Cache local dos últimos preços raspados
    └── ingresse_profile/       # Perfil Chromium persistente (sessão do Ingresse)
```

---

## 4. Lógica Principal

### Fluxo de Scraping (a cada 6h)

```
run_scheduled.py
  └─ loop infinito com sleep(SCRAPER_INTERVAL_HOURS * 3600)
       └─ scraper.py::main()
            ├─ Inicia Playwright Chromium (headless, anti-detecção)
            ├─ Para cada jogo configurado:
            │   └─ Para cada parceiro (6 no total):
            │        ├─ Cria nova página
            │        ├─ Chama scrape_<tipo>(page, jogo)
            │        └─ Retorna [{setor, preco}] ou {erro: msg}
            └─ Passa resultados para mongo_upsert.upsert_resultados()
                  ├─ Upsert Jogo por slug
                  ├─ Upsert Parceiro por slug
                  └─ Upsert Oferta com itens transformados
```

### Estratégias de Scraping por Parceiro

| Parceiro | Tipo | Estratégia |
|---|---|---|
| Camarote Fielzone | `fielzone` | Navega à home, localiza link do jogo, extrai preços de iframe Ingresse |
| Lounge Brahma | `loungebrahma` | WooCommerce, itera dropdown de variações |
| Bar do Zeca | `soudaliga` | React SPA, extrai texto do DOM via JS, parseia por bloco/linha |
| Arena Kids | `arenakids` | Perfil Chromium persistente com sessão salva no Ingresse (suporta 2FA manual) |
| Galeria SCCP | `ticket360` | Busca evento, clica "COMPRAR", extrai modal de setores |
| Fiel Torcedor | `ticket360_fiel` | Mesmo que ticket360, rota de busca diferente |

### Fluxo do Dashboard

```
Carrega página
  └─ fetch /jogos → renderiza cards horizontais
       └─ Seleciona primeiro jogo (ou último selecionado)
            └─ fetch /ofertas?jogo_slug=X → renderiza grid de parceiros
                 └─ Polling a cada 60s para /jogos (atualização automática)
```

### API Endpoints

```
GET /                          → {status: "ok"}
GET /jogos                     → Jogo[] ordenado por data ASC
GET /jogos/:slug               → Jogo (404 se não existe)
GET /parceiros                 → Parceiro[] ordenado por nome
GET /parceiros/:slug           → Parceiro
GET /ofertas                   → Oferta[] com refs populadas
  ?status=ativo|fechado
  ?jogo_slug=<slug>
  ?parceiro_slug=<slug>
GET /ofertas/:id               → Oferta por _id
```

### Modelo de Dados (Oferta)

```js
{
  parceiro_id: ObjectId,   // ref → Parceiro
  jogo_id: ObjectId,       // ref → Jogo
  status: "ativo"|"fechado",
  itens: [{
    nome: String,          // ex: "Cadeira Coberta"
    descricao: String,
    preco: Number,         // em reais (float)
    tipo: "individual"|"combo",
    publico: "adulto"|"infantil"|"misto",
    adultos: Number,       // apenas para combo
    criancas: Number       // apenas para combo
  }]
}
```

---

## 5. Configuração e Execução

### Pré-requisitos

- Docker e Docker Compose instalados

### Subir tudo

```bash
docker compose up -d
```

Isso sobe:
1. **MongoDB** na porta 27017
2. **Backend** na porta 3000 (com hot-reload via `--watch`)
3. **Scraper** que roda imediatamente e depois a cada 6h

### Acessar o dashboard

Abra `frontend/dashboard.html` diretamente no navegador.
> O JS detecta `localhost` e aponta para `http://localhost:3000`

### Rodar seed (dados de exemplo)

```bash
cd backend
npm run seed
```

### Rodar o scraper manualmente

```bash
cd scrapping
python scraper.py                              # Raspa todos parceiros, todos jogos
python scraper.py --parceiro "Bar do Zeca"    # Parceiro específico
python scraper.py --jogo "Corinthians x Vasco" # Jogo específico
```

### Variáveis de Ambiente

**backend/.env:**
```env
NODE_ENV=development
PORT=3000
MONGO_URI=mongodb://mongo:27017/ingressos
```

**scraper (via docker-compose):**
```env
MONGO_URI=mongodb://mongo:27017/ingressos
SCRAPER_INTERVAL_HOURS=6
```

---

## 6. Dependências

### Backend
| Pacote | Versão | Uso |
|---|---|---|
| express | ^5.2.1 | Framework HTTP |
| mongoose | ^8.12.1 | ODM para MongoDB |
| cors | ^2.8.6 | Permite requisições cross-origin do frontend |
| dotenv | ^16.4.7 | Carrega variáveis de ambiente |

### Scraper
| Pacote | Uso |
|---|---|
| playwright | Automação Chromium headless para scraping |
| pymongo | Driver MongoDB para upserts |

---

## 7. Pontos Importantes para Contexto Futuro

### Suposições

- O foco atual é **exclusivamente Corinthians**. Os parceiros são camarotes e lounges da Neo Química Arena.
- O dashboard é um arquivo HTML estático — não há build process. Servir diretamente.
- O scraper assume que os sites dos parceiros não mudaram sua estrutura HTML. Mudanças de layout quebram o scraping.

### Partes Frágeis

1. **`scraper.py` (Arena Kids/Ingresse):** Usa perfil de browser persistente em `ingresse_profile/` para manter sessão. Se a sessão expirar, requer login manual com OTP. Isso pode pausar o scraper se não houver intervenção humana.

2. **`scrape_soudaliga()`:** Depende de extração de texto puro do DOM de uma SPA React. O algoritmo de matching de nomes de setor/preço é frágil (baseado em proximidade de linhas).

3. **`extrair_setores_precos_frame()`:** Lógica complexa de pairing de setores com preços via avaliação JS + parsing por linha. Dois modos de fallback embutidos.

4. **Sem autenticação na API:** Qualquer cliente pode ler todos os dados. Adequado para uso interno/local.

5. **`dashboard.css` está desatualizado:** O CSS real está embutido em `dashboard.html`. O arquivo `.css` separado é backup/rascunho.

6. **`prices.json`:** Cache local criado pelo scraper. Não é usado pelo backend — é apenas um artefato de debug/backup.

### Limitações Conhecidas

- Não há suporte a múltiplos times/campeonatos. Hardcoded para Corinthians.
- Nenhum sistema de alertas (email/WhatsApp) quando preços mudam.
- O scraper não tem retry automático por parceiro — se um falha, o erro é registrado e o restante continua.
- Sem paginação na API (retorna todos os documentos).

---

## 8. Resumo para Recuperação de Contexto (IA)

> **Se você esquecer tudo, aqui está o que mais importa:**

- **O que é:** Dashboard de monitoramento de preços de ingressos do Corinthians, com scraping automático de 6 sites parceiros.
- **Como funciona:** Scraper Python/Playwright roda a cada 6h → grava no MongoDB → API Node.js/Express expõe os dados → frontend HTML puro consome a API.
- **Arquivos críticos:**
  - `scrapping/scraper.py` — toda lógica de scraping (1200+ linhas, 6 estratégias distintas)
  - `scrapping/mongo_upsert.py` — normalização de dados e persistência
  - `backend/src/routes/ofertas.js` — endpoint principal com filtros
  - `backend/src/models/Oferta.js` — modelo de dados central
  - `frontend/dashboard.html` — toda a UI (CSS e JS embutidos)
- **Para subir:** `docker compose up -d` na raiz
- **Ponto de atenção:** A sessão do Ingresse (Arena Kids) pode expirar e exigir login manual. O perfil do browser fica em `scrapping/ingresse_profile/`.
- **Não há framework no frontend** — JS vanilla puro com polling a cada 60s.
