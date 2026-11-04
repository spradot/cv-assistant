"""Estado de cada postulación hecha desde la web (oferta, clasificación, CV, ATS, versiones),
en la tabla `web_postulaciones` de Postgres (Supabase). `datos` es un JSONB con todo el estado."""

from datetime import datetime

from psycopg.types.json import Jsonb

from bot import pg


def _iso(valor: datetime) -> str:
    return valor.isoformat(timespec="seconds")


def crear(user_id: int, empresa: str, estado: str, datos: dict) -> int:
    with pg.conn() as c:
        fila = c.execute(
            "INSERT INTO web_postulaciones (user_id, empresa, estado, datos) VALUES (%s, %s, %s, %s) RETURNING id",
            (user_id, empresa, estado, Jsonb(datos)),
        ).fetchone()
    return fila["id"]


def obtener(user_id: int, pid: int) -> dict | None:
    with pg.conn() as c:
        fila = c.execute("SELECT * FROM web_postulaciones WHERE id = %s AND user_id = %s", (pid, user_id)).fetchone()
    if fila is None:
        return None
    return {
        "id": fila["id"],
        "empresa": fila["empresa"],
        "estado": fila["estado"],
        "creado_en": _iso(fila["creado_en"]),
        "actualizado_en": _iso(fila["actualizado_en"]),
        **fila["datos"],
    }


def guardar(user_id: int, pid: int, estado: str, datos: dict) -> None:
    with pg.conn() as c:
        c.execute(
            "UPDATE web_postulaciones SET estado = %s, datos = %s, actualizado_en = now() WHERE id = %s AND user_id = %s",
            (estado, Jsonb(datos), pid, user_id),
        )


def listar(user_id: int, limit: int = 100) -> list[dict]:
    with pg.conn() as c:
        filas = c.execute(
            "SELECT id, empresa, estado, creado_en, actualizado_en, datos->'fit_score' AS fit_score, "
            "datos->>'recomendacion' AS recomendacion, datos->>'angulo' AS angulo, datos->'ats_cobertura' AS ats_cobertura "
            "FROM web_postulaciones WHERE user_id = %s ORDER BY id DESC LIMIT %s",
            (user_id, limit),
        ).fetchall()
    return [{**f, "creado_en": _iso(f["creado_en"]), "actualizado_en": _iso(f["actualizado_en"])} for f in filas]


def eliminar(user_id: int, pid: int) -> None:
    with pg.conn() as c:
        c.execute("DELETE FROM web_postulaciones WHERE id = %s AND user_id = %s", (pid, user_id))


def referencia_cv(user_id: int, angulo: str) -> dict:
    """El `cv` de la postulación MÁS RECIENTE del usuario con ese ángulo (referencia estructural
    para el generador). {} si no hay ninguna: el generador usa un esqueleto neutro. Solo hay
    `cv` en postulaciones que ya renderizaron bien."""
    with pg.conn() as c:
        fila = c.execute(
            "SELECT datos->'cv' AS cv FROM web_postulaciones WHERE user_id = %s AND datos->>'angulo' = %s "
            "AND jsonb_typeof(datos->'cv') = 'object' ORDER BY id DESC LIMIT 1",
            (user_id, angulo),
        ).fetchone()
    return fila["cv"] if fila else {}
