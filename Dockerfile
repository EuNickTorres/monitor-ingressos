FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Instala Chromium + todas as dependências do sistema automaticamente
RUN playwright install --with-deps chromium

COPY . .

EXPOSE 8000

CMD python server.py ${PORT:-8000}
