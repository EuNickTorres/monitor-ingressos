FROM python:3.11-slim

WORKDIR /app

# Instala curl (para baixar supercronic) e dependências base
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && curl -fsSLo /usr/local/bin/supercronic \
       https://github.com/aptible/supercronic/releases/download/v0.2.29/supercronic-linux-amd64 \
    && chmod +x /usr/local/bin/supercronic \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install chromium --with-deps

COPY . .

# supercronic lê o arquivo crontab e executa os jobs no horário definido
CMD ["supercronic", "crontab"]
