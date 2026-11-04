"""Punto único de entrada para clasificación de fit. Elige Jev o el fallback de
DeepSeek según CLASSIFIER_PROVIDER (bot/config.py decide automáticamente: usa Jev
si hay TYPESAFE_API_KEY, si no cae a DeepSeek). El resto del código (graph.py) no
necesita saber cuál está activo."""

from bot.config import CLASSIFIER_PROVIDER
from bot.tipos import Clasificacion, Preferencias


def clasificar(oferta_texto: str, perfil_resumen: str, preferencias: Preferencias | None = None) -> Clasificacion:
    if CLASSIFIER_PROVIDER == "jev":
        from bot.jev_client import clasificar as _clasificar
    else:
        from bot.deepseek_classifier import clasificar as _clasificar
    return _clasificar(oferta_texto, perfil_resumen, preferencias or Preferencias())
