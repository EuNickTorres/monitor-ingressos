"""
Camada de persistência: usa Supabase se SUPABASE_URL estiver configurado,
caso contrário usa arquivos locais (prices.json / config.json).
"""
import json
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PRICES_PATH = os.path.join(BASE_DIR, "prices.json")
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

_SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
_SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
_USE_SUPABASE = bool(_SUPABASE_URL and _SUPABASE_KEY)

_client = None


def _get_client():
    global _client
    if _client is None:
        from supabase import create_client
        _client = create_client(_SUPABASE_URL, _SUPABASE_KEY)
    return _client


def _db_get(key):
    try:
        res = _get_client().table("store").select("value").eq("key", key).maybe_single().execute()
        return res.data["value"] if res.data else None
    except Exception as e:
        print(f"[DB] Erro ao ler '{key}': {e}")
        return None


def _db_set(key, value):
    try:
        _get_client().table("store").upsert({"key": key, "value": value}).execute()
    except Exception as e:
        print(f"[DB] Erro ao salvar '{key}': {e}")


# ── PRICES ───────────────────────────────────────────────────────────────────

def carregar_precos():
    if _USE_SUPABASE:
        return _db_get("prices") or {}
    if os.path.exists(PRICES_PATH):
        try:
            with open(PRICES_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def salvar_precos(dados):
    if _USE_SUPABASE:
        _db_set("prices", dados)
    else:
        with open(PRICES_PATH, "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False, indent=2)


# ── CONFIG ────────────────────────────────────────────────────────────────────

def carregar_config():
    if _USE_SUPABASE:
        return _db_get("config") or {"jogos": []}
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"jogos": []}


def salvar_config(dados):
    if _USE_SUPABASE:
        _db_set("config", dados)
    else:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False, indent=2)
