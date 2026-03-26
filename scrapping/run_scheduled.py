"""
Executa o scraper periodicamente, replicando o comportamento de um cronjob.

Configuração via variáveis de ambiente:
  SCRAPER_INTERVAL_HOURS  — intervalo em horas entre execuções (padrão: 6)

Na primeira inicialização o scraper roda imediatamente; depois aguarda o
intervalo configurado antes de cada próxima execução.
"""
import asyncio
import os
import time
from datetime import datetime

INTERVALO_HORAS = int(os.getenv("SCRAPER_INTERVAL_HOURS", "6"))
INTERVALO_SEGUNDOS = INTERVALO_HORAS * 3600


def _log(msg: str) -> None:
    print(f"[Scheduler {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}] {msg}", flush=True)


if __name__ == "__main__":
    # Import tardio para evitar execução acidental ao importar este módulo
    from scraper import main  # noqa: E402

    _log(f"Iniciado. Intervalo: {INTERVALO_HORAS}h ({INTERVALO_SEGUNDOS}s)")

    while True:
        _log("Iniciando execução do scraper...")
        try:
            asyncio.run(main())
        except Exception as exc:
            _log(f"Erro durante scraping: {exc}")

        _log(f"Próxima execução em {INTERVALO_HORAS}h. Aguardando...")
        time.sleep(INTERVALO_SEGUNDOS)
