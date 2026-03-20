"""
Servidor HTTP para o Monitor de Ingressos.
Sem dependencias externas alem da stdlib.

Uso: python server.py [porta]   (padrao: 8000)
"""
import http.server
import json
import os
import subprocess
import sys
from urllib.parse import urlparse
import db

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css":  "text/css; charset=utf-8",
    ".js":   "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
}


class Handler(http.server.BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        print(f"[{self.command}] {self.path}")

    def send_json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path, content_type):
        try:
            with open(path, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(data)
        except FileNotFoundError:
            self.send_response(404)
            self.end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        if path in ("/", "/dashboard.html"):
            self.send_file(os.path.join(BASE_DIR, "dashboard.html"),
                           "text/html; charset=utf-8")

        elif path == "/config":
            try:
                cfg = db.carregar_config()
                # Normaliza formato antigo para novo
                if "jogo" in cfg and "jogos" not in cfg:
                    cfg = {"jogos": [cfg["jogo"]]}
                self.send_json(200, cfg)
            except Exception as e:
                self.send_json(500, {"erro": str(e)})

        elif path == "/prices.json":
            try:
                prices = db.carregar_precos()
                self.send_json(200, prices)
            except Exception as e:
                self.send_json(500, {"erro": str(e)})

        else:
            # Serve qualquer arquivo estático do diretório base
            filename = os.path.basename(parsed.path)
            filepath = os.path.join(BASE_DIR, filename)
            if os.path.isfile(filepath) and not filename.startswith("."):
                ext = os.path.splitext(filename)[1].lower()
                ct = CONTENT_TYPES.get(ext, "application/octet-stream")
                self.send_file(filepath, ct)
            else:
                self.send_response(404)
                self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path == "/config":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                action = body.get("action")  # "add" ou "remove"
                jogo = (body.get("jogo") or "").strip()
                data = (body.get("data") or "").strip()

                if not jogo:
                    self.send_json(400, {"erro": "Campo 'jogo' obrigatorio"})
                    return

                # Lê config atual
                try:
                    cfg = db.carregar_config()
                    if "jogo" in cfg and "jogos" not in cfg:
                        cfg = {"jogos": [{"nome": cfg["jogo"], "data": ""}]}
                except Exception:
                    cfg = {"jogos": []}

                # Normaliza entradas antigas (strings) para dicts
                jogos = [
                    j if isinstance(j, dict) else {"nome": j, "data": ""}
                    for j in cfg.get("jogos", [])
                ]

                def get_nome(j):
                    return j.get("nome", "") if isinstance(j, dict) else j

                if action == "add":
                    if not any(get_nome(j) == jogo for j in jogos):
                        jogos.append({"nome": jogo, "data": data})
                elif action == "remove":
                    jogos = [j for j in jogos if get_nome(j) != jogo]
                    # Remove também dos prices
                    try:
                        prices = db.carregar_precos()
                        if jogo in prices:
                            del prices[jogo]
                            db.salvar_precos(prices)
                    except Exception:
                        pass
                else:
                    self.send_json(400, {"erro": "action deve ser 'add' ou 'remove'"})
                    return

                cfg["jogos"] = jogos
                db.salvar_config(cfg)

                self.send_json(200, {"ok": True, "jogos": jogos})

            except json.JSONDecodeError:
                self.send_json(400, {"erro": "JSON invalido"})
            except Exception as e:
                self.send_json(500, {"erro": str(e)})
        elif path == "/run-scraper":
            try:
                scraper_path = os.path.join(BASE_DIR, "scraper.py")
                result = subprocess.run(
                    [sys.executable, scraper_path],
                    capture_output=True, text=True, cwd=BASE_DIR, timeout=120
                )
                if result.returncode == 0:
                    self.send_json(200, {"ok": True})
                else:
                    self.send_json(500, {"erro": result.stderr[-500:] or "Scraper falhou"})
            except subprocess.TimeoutExpired:
                self.send_json(500, {"erro": "Timeout ao executar scraper"})
            except Exception as e:
                self.send_json(500, {"erro": str(e)})
        else:
            self.send_response(404)
            self.end_headers()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get("PORT", 8000))
    server = http.server.ThreadingHTTPServer(("", port), Handler)
    print(f"Servidor rodando em http://localhost:{port}")
    print("Ctrl+C para parar.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor encerrado.")
