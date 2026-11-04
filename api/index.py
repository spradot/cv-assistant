"""Punto de entrada de Vercel: expone la app FastAPI como función serverless.
servicio "backend" de vercel.json: las rutas /api/* llegan aquí con el prefijo intacto; el servicio "frontend" sirve el resto."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from web.app import app  # noqa: E402,F401
