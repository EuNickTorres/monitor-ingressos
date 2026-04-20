FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install chromium --with-deps

COPY . .

# run_scheduled.py executa o scraper imediatamente e depois a cada
# SCRAPER_INTERVAL_HOURS horas (padrão: 6), replicando o comportamento
# do cronjob de produção.
CMD ["python", "run_scheduled.py"]
