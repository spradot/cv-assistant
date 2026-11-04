"""Pipeline de postulación como grafo LangGraph, con pausa humana antes de dar
la postulación por definitiva (interrupt + checkpoint en sqlite, se puede
resumir horas después cuando el usuario responde en Telegram)."""

from __future__ import annotations

import copy
import logging
import re
from typing import Literal, TypedDict

import yaml
from bot import ats_check
from bot.config import CHECKPOINT_DB_PATH, PROJECT_ROOT, README_PATH, YAML_DIR
from bot.classifier import clasificar
from bot.deepseek_client import (
    condensar_a_una_pagina,
    expandir_a_una_pagina,
    pide_proyectos,
    quitar_proyectos,
    generar_contenido,
    reparar_cv_rendercv,
)
from bot.design import ensamblar_yaml
from bot.documentacion import perfil_para_ia
from bot.render import render_cv
from bot.tipos import SECCIONES_EXCLUIDAS_DEFAULT


class Estado(TypedDict, total=False):
    empresa: str
    oferta_texto: str
    perfil_readme: str
    fit_score: float
    angulo: str
    recomendacion: str
    razones: str
    cv: dict
    yaml_content: str
    banda_salarial: str
    experiencia_200: str
    habilidades_200: str
    pretension_renta: str
    disponibilidad: str
    modalidad_preferida: str
    pdf_path: str
    paginas: int
    ats_keywords: list[str]
    ats_parseo_ok: bool
    ats_detalle_parseo: str
    ats_cobertura: float
    ats_keywords_faltantes: list[str]
    feedback_usuario: str | None
    decision_final: str  # "aprobado" | "descartado"


_PREFIJOS_ANGULO = {"DE_ES": "DE_ES_", "DS_ES": "DS_ES_", "DE_EN": "DE_EN_"}

def _cv_de(ruta) -> dict | None:
    """Devuelve el bloque `cv` de un YAML si el archivo tiene la forma esperada (cv + design
    de nivel superior). Nos mordió una vez un archivo con `design` mal anidado dentro de `cv`
    por un bug ya corregido — esta validación evita que un archivo así vuelva a colarse como
    referencia y contamine la estructura que el LLM copia."""
    if not ruta.exists():
        return None
    try:
        data = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return None
    if isinstance(data, dict) and isinstance(data.get("cv"), dict) and "design" in data:
        return data["cv"]
    return None


def _leer_cv_referencia(angulo: str, yaml_dir=YAML_DIR) -> dict:
    """Usa como referencia estructural el `cv` del YAML de empresa MÁS RECIENTE con ese
    ángulo que tenga forma válida (devuelve {} si no hay ninguno: el generador usa un esqueleto neutro). Los archivos en YAML/ solo llegan ahí después de un render
    exitoso (ver render.py), así que el contenido está garantizado renderizable."""
    prefijo = _PREFIJOS_ANGULO.get(angulo, f"{angulo}_")
    candidatos = sorted(yaml_dir.glob(f"{prefijo}*.yaml"), key=lambda p: p.stat().st_mtime, reverse=True)
    for ruta in candidatos:
        cv = _cv_de(ruta)
        if cv is not None:
            return cv
    return {}


def nodo_clasificar(estado: Estado) -> Estado:
    # Mismo filtro que la web: sin registro de CVs, protocolos ni convenciones (~43% menos tokens).
    perfil = estado.get("perfil_readme") or perfil_para_ia(
        README_PATH.read_text(encoding="utf-8"), SECCIONES_EXCLUIDAS_DEFAULT
    )
    resultado = clasificar(estado["oferta_texto"], perfil)
    return {
        "perfil_readme": perfil,
        "fit_score": resultado.fit_score,
        "angulo": resultado.angulo,
        "recomendacion": resultado.recomendacion,
        "razones": resultado.razones,
    }


def _ruta_tras_clasificar(estado: Estado) -> Literal["generar", "descartado"]:
    return "generar" if estado["recomendacion"] == "postular" else "descartado"


def _sin_etiquetas_typst(valor):
    """Typst interpreta `<texto` como el inicio de una etiqueta y falla con "unclosed label"
    (pasa con rangos como "<95%" o "<10 días"). Un espacio tras el `<` basta para evitarlo."""
    if isinstance(valor, str):
        return re.sub(r"<(?=[\w.:-])", "< ", valor)
    if isinstance(valor, list):
        return [_sin_etiquetas_typst(v) for v in valor]
    if isinstance(valor, dict):
        return {k: _sin_etiquetas_typst(v) for k, v in valor.items()}
    return valor


def _sanear_cv(cv: dict) -> dict:
    """Validaciones deterministas antes de renderizar: rendercv rechaza un teléfono o email
    inválido y la IA no puede "repararlos" sin inventar datos — se omiten (son opcionales)
    en vez de gastar llamadas de reparación que igual fallan."""
    cv = _sin_etiquetas_typst(dict(cv))
    telefono = cv.get("phone")
    if telefono:
        try:
            import phonenumbers

            numero = phonenumbers.parse(str(telefono), "CL")
            if phonenumbers.is_valid_number(numero):
                cv["phone"] = phonenumbers.format_number(numero, phonenumbers.PhoneNumberFormat.E164)
            else:
                cv.pop("phone")
        except Exception:
            cv.pop("phone", None)
    secciones = copy.deepcopy(cv.get("sections") or {})
    for nombre, entradas in list(secciones.items()):
        if not isinstance(entradas, list):
            continue
        # {label, details: ""} se renderiza como "Label:" colgando; sin detalle va como texto simple.
        # rendercv no admite mezclar tipos en una sección: si alguna queda sin detalle, todas pasan a texto.
        if entradas and all(isinstance(e, dict) and set(e) <= {"label", "details"} and e.get("label") for e in entradas) and any(
            not str(e.get("details") or "").strip() for e in entradas
        ):
            entradas = [
                f"{str(e['label']).strip()} ({str(e['details']).strip()})" if str(e.get("details") or "").strip() else str(e["label"]).strip()
                for e in entradas
            ]
        # Idiomas con solo la lengua materna no aporta: el propio CV ya está en ese idioma.
        if nombre.lower() in ("idiomas", "languages") and entradas and all(
            isinstance(e, dict) and re.search(r"\b(natal|nativo|nativa|materno|materna|native|mother)", str(e.get("details", "")), re.I)
            for e in entradas
        ):
            del secciones[nombre]
            continue
        secciones[nombre] = entradas
    for entradas in secciones.values():
        for entrada in entradas if isinstance(entradas, list) else []:
            if isinstance(entrada, dict) and "language" in entrada and "label" not in entrada:
                # El modelo a veces escribe Idiomas como {language, level}; rendercv solo lo entiende como {label, details}.
                entrada["label"] = entrada.pop("language")
                entrada["details"] = str(entrada.pop("level", "") or "")
            if isinstance(entrada, dict) and entrada.get("institution") and isinstance(entrada.get("details"), str):
                # Educación no admite `details` (solo las líneas label/details); sus textos van en `highlights`.
                entrada["highlights"] = [*(entrada.get("highlights") or []), entrada.pop("details")]
    if secciones:
        cv["sections"] = secciones
    email = cv.get("email")
    if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", str(email)):
        cv.pop("email")
    return cv


def _resumir_error(error: str) -> str:
    """El error de rendercv trae un banner de ~1.5k caracteres; a la IA solo le sirven las
    filas de la tabla de errores (| cv.campo | valor | mensaje |)."""
    filas = [l.strip() for l in error.splitlines() if l.strip().startswith("| cv.") or "rror" in l and "|" not in l]
    return "\n".join(filas)[:1500] if filas else error[-1500:]


# Un CV de 1 página que ocupa menos de esto deja un hueco visible abajo (el CV de Daniel quedó en
# ~70%). Con `perfil` y `oferta` se rellena con contenido real del perfil; sin ellos (ediciones
# manuales o ajustes puntuales de la web) se respeta lo que el usuario dejó.
LLENADO_MINIMO = 0.88
_INTENTOS_EXPANSION = 2


_SECCIONES_NUCLEO = {"resumen", "habilidades", "experiencia laboral", "educación", "educacion", "idiomas", "certificaciones"}
_LINEAS_POR_HOJA = 60


def _recortar_exceso(cv: dict, exceso: float) -> dict:
    """Quita del `cv` lo de menor prioridad hasta cubrir ~`exceso` (fracción de hoja que
    desborda): primero entradas de secciones opcionales (proyectos, etc., desde el final) y luego
    el último bullet de las experiencias con más de 2. Mecánico: el recorte por LLM convergía
    lento porque el modelo no mide líneas."""
    cv = copy.deepcopy(cv)
    secciones = cv.get("sections") or {}
    quitar = max(1, round(exceso * _LINEAS_POR_HOJA / 2) + 1)  # ~2 líneas por elemento + 1 de holgura
    for _ in range(quitar):
        opcionales = [n for n, e in secciones.items() if n.lower() not in _SECCIONES_NUCLEO and isinstance(e, list) and e]
        if opcionales:
            nombre = opcionales[-1]
            secciones[nombre].pop()
            if not secciones[nombre]:
                del secciones[nombre]
            continue
        experiencia = secciones.get("Experiencia Laboral") or []
        candidatas = [e for e in experiencia if isinstance(e, dict) and len(e.get("highlights") or []) > 2]
        if not candidatas:
            break
        max(reversed(candidatas), key=lambda e: len(e["highlights"]))["highlights"].pop()
    return cv


def _rellenar_pagina(cv, yaml_content, pdf_path, angulo, empresa, perfil, oferta, destino, proyectos=False):
    sobrescrito = False  # render_cv escribe siempre el mismo archivo: un candidato descartado lo pisa
    for _ in range(_INTENTOS_EXPANSION):
        llenado = ats_check.llenado_ultima_pagina(str(pdf_path))
        if llenado >= LLENADO_MINIMO:
            break
        sobrescrito = True
        try:
            cv_candidato = expandir_a_una_pagina(cv, llenado, perfil, oferta)
            if not proyectos:
                cv_candidato = quitar_proyectos(cv_candidato)
            pdf_candidato = render_cv(ensamblar_yaml(_sanear_cv(cv_candidato), angulo), angulo, empresa, **destino)
            recortes = 0
            while ats_check.contar_paginas(str(pdf_candidato)) > 1 and recortes < 4:  # recortar justo lo que desborda
                exceso = ats_check.llenado_ultima_pagina(str(pdf_candidato))
                cv_candidato = _recortar_exceso(cv_candidato, exceso)
                pdf_candidato = render_cv(ensamblar_yaml(_sanear_cv(cv_candidato), angulo), angulo, empresa, **destino)
                recortes += 1
            if ats_check.contar_paginas(str(pdf_candidato)) > 1:
                logging.getLogger(__name__).info("expansión descartada: no cabe en 1 página")
                break
        except RuntimeError as error:
            logging.getLogger(__name__).warning("expansión descartada, rendercv rechazó el cv: %s", str(error)[-1200:])
            break
        nuevo = ats_check.llenado_ultima_pagina(str(pdf_candidato))
        logging.getLogger(__name__).info("relleno de página: %.0f%% -> %.0f%%", llenado * 100, nuevo * 100)
        if nuevo <= llenado:
            break  # no mejoró: no seguir gastando llamadas
        cv = _sanear_cv(cv_candidato)
        yaml_content, pdf_path = ensamblar_yaml(cv, angulo), pdf_candidato
        sobrescrito = False
    if sobrescrito:
        pdf_path = render_cv(yaml_content, angulo, empresa, **destino)
    return cv, yaml_content, pdf_path


def renderizar_cv(
    cv: dict, angulo: str, empresa: str, perfil: str | None = None, oferta: str | None = None,
    proyectos: bool = False, **destino
) -> tuple[dict, str, str, int]:
    """Renderiza el `cv` con reparación automática de errores de esquema, condensado a
    1 página y (si se pasan `perfil` y `oferta`) relleno del espacio en blanco. Devuelve
    (cv final, yaml final, ruta del PDF, páginas). Lo usan el grafo y la web (que re-renderiza
    después de cada ajuste manual o por recomendación ATS)."""
    cv = _sanear_cv(cv)
    yaml_content = ensamblar_yaml(cv, angulo)
    intentos_render = 3
    for intento in range(intentos_render):
        try:
            pdf_path = render_cv(yaml_content, angulo, empresa, **destino)
            break
        except RuntimeError as error:
            if intento == intentos_render - 1:
                raise
            resumen = _resumir_error(str(error))
            logging.getLogger(__name__).warning("rendercv rechazó el cv, se pide reparación:\n%s", resumen)
            cv = _sanear_cv(reparar_cv_rendercv(cv, resumen))
            yaml_content = ensamblar_yaml(cv, angulo)

    # Restricción crítica: el CV debe caber en 1 página. Se verifica contando páginas del PDF
    # real (mecánico, no una opinión del LLM) y si no calza se le pide a DeepSeek que recorte
    # contenido, re-renderizando cada vez para volver a medir.
    intentos_paginas = 6  # 1 recorte por LLM (con criterio de relevancia) y luego recortes mecánicos
    for intento in range(intentos_paginas):
        paginas = ats_check.contar_paginas(str(pdf_path))
        if paginas <= 1 or intento == intentos_paginas - 1:
            break
        if intento == 0:
            cv_candidato = condensar_a_una_pagina(cv, paginas, ats_check.llenado_ultima_pagina(str(pdf_path)))
        else:
            cv_candidato = _recortar_exceso(cv, ats_check.llenado_ultima_pagina(str(pdf_path)))
        yaml_candidato = ensamblar_yaml(cv_candidato, angulo)
        try:
            pdf_candidato = render_cv(yaml_candidato, angulo, empresa, **destino)
        except RuntimeError:
            # El condensado rompió el contenido — nos quedamos con el PDF de más páginas que
            # sí funciona, en vez de arriesgar un render roto por perseguir 1 página.
            break
        cv, yaml_content, pdf_path = cv_candidato, yaml_candidato, pdf_candidato

    if perfil and oferta and paginas <= 1:
        cv, yaml_content, pdf_path = _rellenar_pagina(cv, yaml_content, pdf_path, angulo, empresa, perfil, oferta, destino, proyectos)
        paginas = ats_check.contar_paginas(str(pdf_path))

    return cv, yaml_content, str(pdf_path), paginas


def nodo_generar_y_renderizar(estado: Estado) -> Estado:
    cv_referencia = _leer_cv_referencia(estado["angulo"])
    contenido = generar_contenido(
        oferta_texto=estado["oferta_texto"],
        perfil_readme=estado["perfil_readme"],
        cv_referencia=cv_referencia,
        empresa=estado["empresa"],
        feedback_usuario=estado.get("feedback_usuario"),
    )
    cv, yaml_content, pdf_path, paginas = renderizar_cv(
        contenido.cv, estado["angulo"], estado["empresa"], perfil=estado["perfil_readme"], oferta=estado["oferta_texto"],
        proyectos=pide_proyectos(estado.get("feedback_usuario")),
    )

    ats = ats_check.evaluar(pdf_path, contenido.keywords_ats)
    return {
        "cv": cv,
        "yaml_content": yaml_content,
        "banda_salarial": contenido.banda_salarial,
        "experiencia_200": contenido.experiencia_200,
        "habilidades_200": contenido.habilidades_200,
        "pretension_renta": contenido.pretension_renta,
        "disponibilidad": contenido.disponibilidad,
        "modalidad_preferida": contenido.modalidad_preferida,
        "pdf_path": pdf_path,
        "paginas": paginas,
        "ats_keywords": contenido.keywords_ats,
        "ats_parseo_ok": ats.parseo_ok,
        "ats_detalle_parseo": ats.detalle_parseo,
        "ats_cobertura": ats.cobertura,
        "ats_keywords_faltantes": ats.keywords_faltantes,
        "feedback_usuario": None,
    }


def nodo_revisar(estado: Estado) -> Estado:
    from langgraph.types import interrupt  # import perezoso: la web no instala langgraph

    decision = interrupt(
        {
            "tipo": "revision_humana",
            "empresa": estado["empresa"],
            "angulo": estado["angulo"],
            "oferta_texto": estado["oferta_texto"],
            "fit_score": estado["fit_score"],
            "pdf_path": estado["pdf_path"],
            "paginas": estado["paginas"],
            "banda_salarial": estado["banda_salarial"],
            "experiencia_200": estado["experiencia_200"],
            "habilidades_200": estado["habilidades_200"],
            "ats_parseo_ok": estado["ats_parseo_ok"],
            "ats_detalle_parseo": estado["ats_detalle_parseo"],
            "ats_cobertura": estado["ats_cobertura"],
            "ats_keywords_faltantes": estado["ats_keywords_faltantes"],
        }
    )
    # decision: {"accion": "aprobar" | "ajustar" | "descartar", "feedback": str | None}
    if decision["accion"] == "ajustar":
        return {"feedback_usuario": decision.get("feedback")}
    return {"decision_final": "aprobado" if decision["accion"] == "aprobar" else "descartado"}


def _ruta_tras_revisar(estado: Estado) -> Literal["generar", "fin"]:
    return "generar" if estado.get("feedback_usuario") else "fin"


def construir_grafo():
    import sqlite3

    from langgraph.checkpoint.sqlite import SqliteSaver
    from langgraph.graph import END, START, StateGraph

    grafo = StateGraph(Estado)
    grafo.add_node("clasificar", nodo_clasificar)
    grafo.add_node("generar", nodo_generar_y_renderizar)
    grafo.add_node("revisar", nodo_revisar)

    grafo.add_edge(START, "clasificar")
    grafo.add_conditional_edges(
        "clasificar", _ruta_tras_clasificar, {"generar": "generar", "descartado": END}
    )
    grafo.add_edge("generar", "revisar")
    grafo.add_conditional_edges(
        "revisar", _ruta_tras_revisar, {"generar": "generar", "fin": END}
    )

    # from_conn_string() es un context manager (se cierra la conexión al salir del `with`),
    # así que abrimos la conexión directo para que viva mientras el proceso del bot esté arriba.
    conn = sqlite3.connect(str(CHECKPOINT_DB_PATH), check_same_thread=False)
    checkpointer = SqliteSaver(conn)
    return grafo.compile(checkpointer=checkpointer)
