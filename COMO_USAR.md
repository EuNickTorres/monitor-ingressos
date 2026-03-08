# 🎟️ Monitor de Ingressos — Como Usar

## Instalação (só na primeira vez)

Você precisa ter **Python 3.8+** instalado no PC.

### 1. Instale as dependências
Abra o terminal na pasta do projeto e rode:

```bash
pip install playwright
playwright install chromium
```

---

## Como rodar

### 2. Mude o jogo (quando necessário)
Abra o arquivo `scraper.py` e edite a linha:

```python
JOGO_BUSCA = "Corinthians x Coritiba"   # ← Mude para o próximo jogo
```

### 3. Execute o scraper
```bash
python scraper.py
```

O script vai abrir um navegador invisível, entrar em cada site, procurar o jogo e salvar os preços.

### 4. Veja o dashboard
Abra o arquivo `dashboard.html` no seu navegador (Chrome/Firefox).

> ⚠️ O dashboard.html e o prices.json precisam estar na mesma pasta.

---

## Automatizar para rodar a cada X horas

### No Windows (Agendador de Tarefas):
1. Pesquise "Agendador de Tarefas" no menu iniciar
2. "Criar Tarefa Básica"
3. Configure para rodar `python` com argumento `C:\caminho\para\scraper.py`
4. Defina o intervalo (ex: a cada 2 horas)

### No Mac/Linux (cron):
```bash
crontab -e
# Adicione essa linha para rodar a cada 2 horas:
0 */2 * * * cd /caminho/para/pasta && python scraper.py
```

---

## Arquivos do projeto

| Arquivo | Descrição |
|---|---|
| `scraper.py` | Script principal — busca os preços |
| `dashboard.html` | Painel visual — abra no navegador |
| `prices.json` | Dados gerados automaticamente pelo scraper |
| `requirements.txt` | Dependências Python |

---

## Adicionando novos parceiros

No arquivo `scraper.py`, localize a lista `PARCEIROS` e adicione:

```python
{
    "nome": "Nome do Parceiro",
    "url": "https://site-do-parceiro.com.br/",
    "tipo": "generico",   # use "generico" para sites novos
    "cor": "#ff6b6b",
},
```

Para sites novos, o scraper vai tentar extrair os preços automaticamente.
Se não funcionar, me manda a URL que eu ajusto o scraper para ele.

---

## Problemas comuns

**"Jogo não encontrado"**
→ O nome do jogo no site pode estar diferente. Tente usar só parte do nome, ex: `"Coritiba"`.

**Site do Bar do Zeca retorna vazio**
→ É um site SPA (carregado por JavaScript). O Playwright aguarda o carregamento, mas às vezes demora mais. Tente rodar novamente.

**Dashboard não carrega os preços**
→ O navegador bloqueia leitura de arquivos locais por segurança. Use o VS Code com Live Server, ou abra assim:
```bash
# Python (na pasta do projeto):
python -m http.server 8080
# Depois acesse: http://localhost:8080/dashboard.html
```
