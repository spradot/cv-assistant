"""Punto de entrada de Vercel: expone la app FastAPI como función serverless.
vercel.json reescribe /api/* hacia aquí; el frontend (web/static) lo sirve la CDN."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from web.app import app  # noqa: E402,F401
