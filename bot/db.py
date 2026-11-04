"""Persistencia en SQLite — la única fuente de verdad durable del bot.

Todo lo que vive solo en `context.user_data` de python-telegram-bot se pierde cada vez
que el proceso del bot se reinicia (pasa seguido durante desarrollo, y va a pasar cada
vez que se reinicie el notebook). Por eso:
- `postulaciones`: registro de CADA oferta clasificada (se apruebe o no), no solo las
  aprobadas — así una pregunta abierta como "¿por qué WiTi?" se puede responder buscando
  aquí, sin depender de que el proceso nunca se haya reiniciado desde que se procesó.
- `conversacion`: historial de preguntas/respuestas abiertas, para que el chat tenga
  memoria real entre turnos (y sobreviva reinicios)."""

import sqlite3
from contextlib import contextmanager
from datetime import datetime

from bot.config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS postulaciones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    empresa TEXT NOT NULL,
    angulo TEXT,                    -- DE_ES, DS_ES, DE_EN, etc.
    fit_score REAL,
    recomendacion TEXT,             -- postular / descartar
    razones TEXT,
    banda_salarial TEXT,
    oferta_texto TEXT,
    yaml_path TEXT,
    pdf_path TEXT,
    estado TEXT NOT NULL DEFAULT 'pendiente_revision',  -- descartado, pendiente_revision, aprobado, descartado_tras_revision
    creado_en TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversacion (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id TEXT NOT NULL,
    rol TEXT NOT NULL,              -- user / assistant
    contenido TEXT NOT NULL,
    creado_en TEXT NOT NULL
);
"""


@contextmanager
def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def registrar_postulacion(**kwargs) -> int:
    kwargs.setdefault("creado_en", datetime.now().isoformat(timespec="seconds"))
    campos = ", ".join(kwargs.keys())
    placeholders = ", ".join("?" for _ in kwargs)
    with _conn() as conn:
        cur = conn.execute(
            f"INSERT INTO postulaciones ({campos}) VALUES ({placeholders})",
            tuple(kwargs.values()),
        )
        return cur.lastrowid


def actualizar_estado(postulacion_id: int, estado: str) -> None:
    with _conn() as conn:
        conn.execute(
            "UPDATE postulaciones SET estado = ? WHERE id = ?", (estado, postulacion_id)
        )


def actualizar_postulacion(postulacion_id: int, **campos) -> None:
    if not campos:
        return
    asignaciones = ", ".join(f"{c} = ?" for c in campos)
    with _conn() as conn:
        conn.execute(
            f"UPDATE postulaciones SET {asignaciones} WHERE id = ?",
            (*campos.values(), postulacion_id),
        )


def listar_recientes(limit: int = 20):
    with _conn() as conn:
        return conn.execute(
            "SELECT * FROM postulaciones ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()


def buscar_por_empresa(nombre_parcial: str, limit: int = 3):
    """Busca postulaciones cuyo nombre de empresa aparezca en el texto dado (case-insensitive).
    Se usa para responder preguntas abiertas que mencionan una empresa por nombre."""
    with _conn() as conn:
        return conn.execute(
            "SELECT * FROM postulaciones WHERE empresa LIKE ? ORDER BY id DESC LIMIT ?",
            (f"%{nombre_parcial}%", limit),
        ).fetchall()


def empresas_conocidas() -> list[str]:
    with _conn() as conn:
        filas = conn.execute("SELECT DISTINCT empresa FROM postulaciones").fetchall()
        return [f["empresa"] for f in filas]


def guardar_turno(chat_id: str, rol: str, contenido: str) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT INTO conversacion (chat_id, rol, contenido, creado_en) VALUES (?, ?, ?, ?)",
            (chat_id, rol, contenido, datetime.now().isoformat(timespec="seconds")),
        )


def historial_conversacion(chat_id: str, limit: int = 12) -> list[dict]:
    """Últimos `limit` turnos (user/assistant intercalados) en orden cronológico."""
    with _conn() as conn:
        filas = conn.execute(
            "SELECT rol, contenido FROM conversacion WHERE chat_id = ? ORDER BY id DESC LIMIT ?",
            (chat_id, limit),
        ).fetchall()
    return [{"role": f["rol"], "content": f["contenido"]} for f in reversed(filas)]
