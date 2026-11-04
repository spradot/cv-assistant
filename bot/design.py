"""Fuente única del diseño del CV — el LLM nunca la ve ni la toca. Separar diseño de
contenido (en vez de pedirle al LLM el archivo completo y luego intentar corregirlo)
elimina de raíz tres clases de bug que ya nos mordieron: el modelo cambiando márgenes/
fuentes al "ayudar" a que quepa en 1 página, YAML roto por valores sin comillas, y el
riesgo de que una referencia rotativa (el YAML de empresa más reciente) propague una
corrupción hacia adelante. También ahorra tokens: ya no hay que regenerar ~150 líneas
de boilerplate de diseño en cada llamada."""

import copy
from datetime import date

import yaml

from bot.config import PROJECT_ROOT

_CANONICAL_PATH = PROJECT_ROOT / "bot" / "design_canonico.yaml"


def _cargar_canonico() -> dict:
    return yaml.safe_load(_CANONICAL_PATH.read_text(encoding="utf-8"))


def _es_ingles(angulo: str) -> bool:
    return angulo.upper().endswith("_EN") or angulo.upper() == "EN"


def _titulo_educacion(cv: dict, conector: str) -> dict:
    """La plantilla de rendercv "DEGREE in AREA" repite el título cuando grado y área coinciden
    ("Ingeniero Civil Industrial in Ingeniería Civil Industrial") y no se traduce el "in". Se arma
    el texto en `degree` (la plantilla solo muestra DEGREE), con el conector del idioma del CV."""
    cv = copy.deepcopy(cv)
    for entradas in (cv.get("sections") or {}).values():
        for e in entradas if isinstance(entradas, list) else []:
            if not (isinstance(e, dict) and e.get("institution") and e.get("area")):
                continue
            grado, area = str(e.get("degree") or "").strip(), str(e["area"]).strip()
            g, a = grado.lower(), area.lower()
            if not grado:
                e["degree"] = area
            elif g in a:
                e["degree"] = area
            elif a in g or len(set(a.split()) & set(g.split())) >= 2:
                e["degree"] = grado  # el grado ya nombra el área
            else:
                e["degree"] = f"{grado} {conector} {area}"
    return cv


def ensamblar_yaml(cv: dict, angulo: str = "") -> str:
    """Combina el diseño fijo con el contenido (`cv`) que generó el LLM. El LLM solo
    produce `cv`; todo lo demás sale de design_canonico.yaml. `angulo` define el idioma de los
    textos fijos de la plantilla (un ángulo `*_EN` queda en inglés; el resto en español)."""
    canonico = _cargar_canonico()
    ingles = _es_ingles(angulo)
    cv = _titulo_educacion(cv, "in" if ingles else "en")
    design, locale = canonico["design"], dict(canonico["locale"])
    design["entry_types"]["education_entry"]["main_column_first_row_template"] = "**INSTITUTION**\n*DEGREE*"
    if not ingles:
        locale["present"] = "actualidad"
        locale["last_updated_date_template"] = "Actualizado en TODAY"
    documento = {
        "cv": cv,
        "design": design,
        "locale": locale,
        "rendercv_settings": {**canonico["rendercv_settings"], "date": date.today().isoformat()},
    }
    return yaml.dump(documento, allow_unicode=True, sort_keys=False, width=1000)
