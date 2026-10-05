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

INTERVALO_HORAS = float(os.getenv("SCRAPER_INTERVAL_HOURS", "6"))

# SCRAPER_INTERVAL_SECONDS existe para testes e execucoes locais curtas. Em
# producao, respeita SCRAPER_INTERVAL_HOURS (antes este valor era ignorado e o
# scraper acabava rodando a cada 180 segundos).
_intervalo_segundos_override = os.getenv("SCRAPER_INTERVAL_SECONDS")
INTERVALO_SEGUNDOS = (
    int(_intervalo_segundos_override)
    if _intervalo_segundos_override is not None
    else max(60, int(INTERVALO_HORAS * 60 * 60))
)


def _log(msg: str) -> None:
    print(f"[Scheduler {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}] {msg}", flush=True)


if __name__ == "__main__":
    # Import tardio para evitar execução acidental ao importar este módulo
    from scraper import main  # noqa: E402

    _log(f"Iniciado. Intervalo: {INTERVALO_SEGUNDOS}s")

    while True:
        _log("Iniciando execução do scraper...")
        try:
            asyncio.run(main())
        except Exception as exc:
            _log(f"Erro durante scraping: {exc}")

        _log(f"Próxima execução em {INTERVALO_SEGUNDOS}s. Aguardando...")
        time.sleep(INTERVALO_SEGUNDOS)
