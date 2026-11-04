"""Punto único de llamadas a DeepSeek: arma los mensajes de forma amigable con la caché de
contexto y registra el consumo de tokens de cada llamada (tabla llm_uso).

Caché de DeepSeek: es por PREFIJO exacto de los mensajes y cobra los tokens que aciertan
(prompt_cache_hit_tokens) a una fracción del precio normal. Por eso todas las tareas que usan
el perfil arrancan con el MISMO mensaje de sistema (SISTEMA_BASE + perfil) y ponen lo variable
al final: oferta → datos de la tarea → instrucciones. Así el perfil (lo más largo) se cobra
completo solo la primera vez, y dentro de una misma postulación también la oferta queda
cacheada entre generar / recomendar / ajustar / sugerir."""

import contextvars
import json
import logging
import os
import sqlite3
import time
from datetime import datetime

from openai import OpenAI

from bot.config import DATABASE_URL, DB_PATH, DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL

_client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)

# deepseek-flash "razona" antes de responder y esos tokens se cobran como salida: en tareas
# mecánicas (ajustar, condensar, editar secciones, sugerir) era 70-85% de la salida sin mejorar
# el resultado. Solo las tareas que requieren juicio lo mantienen; configurable en .env con
# DEEPSEEK_RAZONAMIENTO=clasificar,generar_cv  (o "todas" / "ninguna"). Medido al generar un CV:
# sin razonamiento -62% de salida y 3x más rápido, con calidad equivalente.
_RAZONAMIENTO = os.environ.get("DEEPSEEK_RAZONAMIENTO", "clasificar").strip().lower()


def _con_razonamiento(operacion: str) -> bool:
    if _RAZONAMIENTO in ("todas", "all"):
        return True
    if _RAZONAMIENTO in ("ninguna", "none", ""):
        return False
    return operacion.split("_faltantes")[0] in {o.strip() for o in _RAZONAMIENTO.split(",")}


# La web lo setea por request (middleware) para atribuir el consumo a cada usuario.
usuario_actual: contextvars.ContextVar[int | None] = contextvars.ContextVar("usuario_actual", default=None)

SISTEMA_BASE = (
    "Eres el asistente de postulaciones laborales de un candidato. Su documento de perfil, abajo, "
    "es la fuente de verdad: nunca inventes experiencia, stack, certificaciones, cifras ni fechas que "
    "no estén ahí. Responde exactamente en el formato que pida cada tarea."
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS llm_uso (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    operacion TEXT NOT NULL,
    proveedor TEXT NOT NULL,
    modelo TEXT,
    prompt_tokens INTEGER DEFAULT 0,
    cache_hit_tokens INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    reasoning_tokens INTEGER DEFAULT 0,
    ms INTEGER DEFAULT 0,
    creado_en TEXT NOT NULL
);
"""


def compacto(obj) -> str:
    """JSON sin indentación ni espacios: ~20-30% menos tokens que indent=2, mismo contenido."""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def con_perfil(perfil: str, contenido_usuario: str) -> list[dict]:
    return [
        {"role": "system", "content": f"{SISTEMA_BASE}\n\nPERFIL DEL CANDIDATO:\n{perfil}"},
        {"role": "user", "content": contenido_usuario},
    ]


def chat(operacion: str, mensajes: list[dict], json_mode: bool = False, temperature: float = 0) -> str | dict:
    inicio = time.perf_counter()
    kwargs = {"response_format": {"type": "json_object"}} if json_mode else {}
    if not _con_razonamiento(operacion):
        kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
    completion = _client.chat.completions.create(
        model=DEEPSEEK_MODEL, messages=mensajes, temperature=temperature, **kwargs
    )
    uso = completion.usage
    detalles = getattr(uso, "completion_tokens_details", None)
    registrar(
        operacion,
        "deepseek",
        prompt_tokens=getattr(uso, "prompt_tokens", 0) or 0,
        cache_hit_tokens=getattr(uso, "prompt_cache_hit_tokens", 0) or 0,
        completion_tokens=getattr(uso, "completion_tokens", 0) or 0,
        reasoning_tokens=getattr(detalles, "reasoning_tokens", 0) or 0,
        ms=int((time.perf_counter() - inicio) * 1000),
    )
    texto = completion.choices[0].message.content or ""
    return json.loads(texto) if json_mode else texto.strip()


def _asegurar_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)
    columnas = {c[1] for c in conn.execute("PRAGMA table_info(llm_uso)")}
    if "reasoning_tokens" not in columnas:
        conn.execute("ALTER TABLE llm_uso ADD COLUMN reasoning_tokens INTEGER DEFAULT 0")


def registrar(operacion: str, proveedor: str, **campos) -> None:
    valores = (
        usuario_actual.get(),
        operacion,
        proveedor,
        DEEPSEEK_MODEL if proveedor == "deepseek" else proveedor,
        campos.get("prompt_tokens", 0),
        campos.get("cache_hit_tokens", 0),
        campos.get("completion_tokens", 0),
        campos.get("reasoning_tokens", 0),
        campos.get("ms", 0),
    )
    columnas = (
        "user_id, operacion, proveedor, modelo, prompt_tokens, cache_hit_tokens, completion_tokens, reasoning_tokens, ms"
    )
    try:
        if DATABASE_URL:  # web (Supabase)
            from bot import pg

            with pg.conn() as c:
                c.execute(f"INSERT INTO llm_uso ({columnas}) VALUES ({', '.join(['%s'] * 9)})", valores)
            return
        conn = sqlite3.connect(DB_PATH)  # bot de Telegram (local)
        try:
            _asegurar_schema(conn)
            conn.execute(
                f"INSERT INTO llm_uso ({columnas}, creado_en) VALUES ({', '.join(['?'] * 10)})",
                (*valores, datetime.now().isoformat(timespec="seconds")),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:  # sqlite3.Error / psycopg.Error / falta de config
        logging.getLogger(__name__).warning("no se pudo registrar el consumo de IA", exc_info=True)
        # el registro de consumo nunca debe romper una postulación


def resumen_uso(user_id: int | None, dias: int = 30) -> dict:
    if DATABASE_URL:
        return _resumen_uso_pg(user_id, dias)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        _asegurar_schema(conn)
        filtro = "creado_en >= datetime('now', ?)" + (" AND user_id = ?" if user_id is not None else "")
        params = [f"-{dias} days"] + ([user_id] if user_id is not None else [])
        por_op = conn.execute(
            f"SELECT operacion, proveedor, COUNT(*) llamadas, SUM(prompt_tokens) prompt, SUM(cache_hit_tokens) cache, "
            f"SUM(completion_tokens) salida, SUM(reasoning_tokens) razonamiento, AVG(ms) ms FROM llm_uso WHERE {filtro} "
            f"GROUP BY operacion, proveedor ORDER BY prompt + salida DESC",
            params,
        ).fetchall()
        recientes = conn.execute(
            f"SELECT operacion, proveedor, prompt_tokens, cache_hit_tokens, completion_tokens, reasoning_tokens, ms, creado_en "
            f"FROM llm_uso WHERE {filtro} ORDER BY id DESC LIMIT 40",
            params,
        ).fetchall()
    finally:
        conn.close()
    return {"por_operacion": [dict(f) for f in por_op], "recientes": [dict(f) for f in recientes]}


def _resumen_uso_pg(user_id: int | None, dias: int) -> dict:
    from bot import pg

    filtro = "creado_en >= now() - make_interval(days => %s)" + (" AND user_id = %s" if user_id is not None else "")
    params = [max(1, min(int(dias), 365))] + ([user_id] if user_id is not None else [])
    with pg.conn() as c:
        por_op = c.execute(
            f"SELECT operacion, proveedor, COUNT(*)::int llamadas, COALESCE(SUM(prompt_tokens), 0)::int prompt, "
            f"COALESCE(SUM(cache_hit_tokens), 0)::int cache, COALESCE(SUM(completion_tokens), 0)::int salida, "
            f"COALESCE(SUM(reasoning_tokens), 0)::int razonamiento, COALESCE(AVG(ms), 0)::float ms FROM llm_uso WHERE {filtro} "
            f"GROUP BY operacion, proveedor ORDER BY SUM(prompt_tokens) + SUM(completion_tokens) DESC",
            params,
        ).fetchall()
        recientes = c.execute(
            f"SELECT operacion, proveedor, prompt_tokens, cache_hit_tokens, completion_tokens, reasoning_tokens, ms, "
            f"to_char(creado_en, 'YYYY-MM-DD\"T\"HH24:MI:SS') creado_en FROM llm_uso WHERE {filtro} ORDER BY id DESC LIMIT 40",
            params,
        ).fetchall()
    return {"por_operacion": por_op, "recientes": recientes}
