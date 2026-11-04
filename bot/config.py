from pathlib import Path

from dotenv import load_dotenv
import os

load_dotenv()


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Falta la variable de entorno {name} (revisa .env)")
    return value


# Solo el bot de Telegram las necesita (la web corre sin ellas) — telegram_bot.py las
# valida con require_telegram() al arrancar.
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN") or None
TELEGRAM_ALLOWED_USER_ID = int(os.environ["TELEGRAM_ALLOWED_USER_ID"]) if os.environ.get("TELEGRAM_ALLOWED_USER_ID") else None


def require_telegram() -> None:
    _require("TELEGRAM_BOT_TOKEN")
    _require("TELEGRAM_ALLOWED_USER_ID")

DEEPSEEK_API_KEY = _require("DEEPSEEK_API_KEY")

# Postgres de Supabase (cadena de conexión). La web la exige; el bot de Telegram sigue en SQLite local.
DATABASE_URL = os.environ.get("DATABASE_URL") or None
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-flash")

TYPESAFE_API_KEY = os.environ.get("TYPESAFE_API_KEY") or None  # opcional: sin ella, se usa DeepSeek como clasificador
CLASSIFIER_PROVIDER = os.environ.get("CLASSIFIER_PROVIDER") or (
    "jev" if TYPESAFE_API_KEY else "deepseek"
)

# Preferencias por defecto del bot de Telegram (la web las guarda por usuario). Van en .env, no en el código.
PISO_SALARIAL = os.environ.get("PISO_SALARIAL") or "no especificado (no descartes por sueldo)"
MODALIDAD = os.environ.get("MODALIDAD") or "cualquier modalidad"

PROJECT_ROOT = Path(os.environ.get("PROJECT_ROOT", Path(__file__).resolve().parent.parent))
YAML_DIR = PROJECT_ROOT / "YAML"
PROCESADOS_DIR = PROJECT_ROOT / "procesados"
# Perfil personal del bot de Telegram (local, ignorado por git; la web guarda el perfil en Supabase).
README_PATH = PROJECT_ROOT / "mi_perfil.md"
RENDER_SCRIPT = PROJECT_ROOT / "render.ps1"
DB_PATH = PROJECT_ROOT / "postulaciones.db"
CHECKPOINT_DB_PATH = PROJECT_ROOT / "graph_checkpoints.db"
