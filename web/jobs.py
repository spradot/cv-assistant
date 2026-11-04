"""Cola de trabajos en segundo plano sobre Postgres (tabla `jobs`).

Por qué así: en serverless no hay un proceso que siga vivo tras responder, y `waitUntil` no
da reintentos ni registro. Entonces:
1. POST /generar solo ENCOLA (fila `pendiente`) y dispara al worker con una llamada HTTP a
   /api/internal/jobs/<id>/ejecutar (otra invocación de la función, con su propio límite de duración).
2. El worker reclama el job de forma atómica, lo ejecuta y deja `listo` / `error`.
3. El frontend consulta GET /api/jobs; esa consulta también RECUPERA jobs atascados: uno
   `pendiente` que nadie tomó, o `ejecutando` cuyo latido se apagó (worker muerto), se re-despacha
   hasta _MAX_INTENTOS veces."""

import hashlib
import hmac
import logging
import os
import threading

import httpx
import psycopg
from psycopg.types.json import Jsonb

from bot import pg
from web import storage

log = logging.getLogger(__name__)

_MAX_INTENTOS = 2
_PENDIENTE_HUERFANO_S = 15  # un job pendiente más viejo que esto nadie lo tomó: re-despachar
_PENDIENTE_ABANDONADO_S = 120  # si en este tiempo nadie lo toma, se da por fallido
_LATIDO_MUERTO_S = 90  # sin latido por más de esto el worker murió
_LATIDO_CADA_S = 15

# Para firmar la llamada interna worker←API. JOBS_SECRET es opcional: sin él se deriva de la clave de servicio.
_SECRETO = (os.environ.get("JOBS_SECRET") or storage.SUPABASE_SERVICE_KEY or "").encode()
# Vercel Deployment Protection (Preview) bloquea llamadas servidor→servidor sin este bypass.
_BYPASS = os.environ.get("VERCEL_AUTOMATION_BYPASS_SECRET")


def token(job_id: int) -> str:
    return hmac.new(_SECRETO, f"job:{job_id}".encode(), hashlib.sha256).hexdigest()


def token_valido(job_id: int, recibido: str | None) -> bool:
    return bool(_SECRETO) and hmac.compare_digest(token(job_id), recibido or "")


_COLUMNAS = "id, user_id, postulacion_id, tipo, estado, etapa, error, intentos, visto, creado_en, terminado_en"


def _publico(f: dict) -> dict:
    return {**f, "creado_en": f["creado_en"].isoformat(timespec="seconds"),
            "terminado_en": f["terminado_en"].isoformat(timespec="seconds") if f["terminado_en"] else None}


def encolar(user_id: int, postulacion_id: int, params: dict) -> tuple[dict, bool]:
    """(job, nuevo). Si la postulación ya tiene uno activo se devuelve ese (no se duplica el costo)."""
    with pg.conn() as c:
        try:
            f = c.execute(
                f"INSERT INTO jobs (user_id, postulacion_id, params) VALUES (%s, %s, %s) RETURNING {_COLUMNAS}",
                (user_id, postulacion_id, Jsonb(params)),
            ).fetchone()
            return _publico(f), True
        except psycopg.errors.UniqueViolation:
            c.rollback()
            f = c.execute(
                f"SELECT {_COLUMNAS} FROM jobs WHERE postulacion_id = %s AND estado IN ('pendiente', 'ejecutando')",
                (postulacion_id,),
            ).fetchone()
            return _publico(f), False


def reclamar(job_id: int) -> dict | None:
    """Toma el job si está pendiente (atómico: dos workers no lo ejecutan a la vez)."""
    with pg.conn() as c:
        return c.execute(
            "UPDATE jobs SET estado = 'ejecutando', intentos = intentos + 1, iniciado_en = now(), latido_en = now(), "
            "etapa = 'Iniciando', error = NULL WHERE id = %s AND estado = 'pendiente' RETURNING *",
            (job_id,),
        ).fetchone()


def etapa(job_id: int, texto: str) -> None:
    with pg.conn() as c:
        c.execute("UPDATE jobs SET etapa = %s, latido_en = now() WHERE id = %s AND estado = 'ejecutando'", (texto, job_id))


def terminar(job_id: int, error: str | None = None) -> None:
    with pg.conn() as c:
        c.execute(
            "UPDATE jobs SET estado = %s, error = %s, etapa = NULL, terminado_en = now(), visto = false WHERE id = %s",
            ("error" if error else "listo", error, job_id),
        )


class Latido:
    """Hilo que renueva `latido_en` mientras el worker trabaja (los pasos de IA/render son largos)."""

    def __init__(self, job_id: int):
        self._job_id, self._fin = job_id, threading.Event()
        self._hilo = threading.Thread(target=self._correr, daemon=True)

    def _correr(self):
        while not self._fin.wait(_LATIDO_CADA_S):
            try:
                with pg.conn() as c:
                    c.execute("UPDATE jobs SET latido_en = now() WHERE id = %s AND estado = 'ejecutando'", (self._job_id,))
            except Exception:  # un latido perdido no debe matar el trabajo
                log.warning("latido del job %s falló", self._job_id, exc_info=True)

    def __enter__(self):
        self._hilo.start()
        return self

    def __exit__(self, *exc):
        self._fin.set()


def visibles(user_id: int) -> tuple[list[dict], list[int]]:
    """(jobs activos + terminados sin ver, ids a re-despachar). Recupera los atascados:
    - pendiente que nadie tomó en _PENDIENTE_HUERFANO_S: se re-despacha (máx. una vez por ese intervalo);
      si lleva más de _PENDIENTE_ABANDONADO_S sin tomarse, falla;
    - ejecutando sin latido: el worker murió; se reencola hasta _MAX_INTENTOS, luego falla."""
    with pg.conn() as c:
        atascados = c.execute(
            "SELECT id, intentos, estado, creado_en < now() - make_interval(secs => %s) AS abandonado FROM jobs "
            "WHERE user_id = %s AND ("
            " (estado = 'pendiente' AND coalesce(latido_en, creado_en) < now() - make_interval(secs => %s))"
            " OR (estado = 'ejecutando' AND latido_en < now() - make_interval(secs => %s)))",
            (_PENDIENTE_ABANDONADO_S, user_id, _PENDIENTE_HUERFANO_S, _LATIDO_MUERTO_S),
        ).fetchall()
        reintentar = []
        for j in atascados:
            sin_intentos = j["estado"] == "ejecutando" and j["intentos"] >= _MAX_INTENTOS
            if sin_intentos or (j["estado"] == "pendiente" and j["abandonado"]):
                c.execute(
                    "UPDATE jobs SET estado = 'error', error = %s, etapa = NULL, terminado_en = now(), visto = false WHERE id = %s",
                    ("La generación se interrumpió y no pudo reintentarse. Vuelve a intentarlo.", j["id"]),
                )
            else:  # pendiente huérfano, o ejecutando muerto con intentos disponibles
                c.execute("UPDATE jobs SET estado = 'pendiente', latido_en = now() WHERE id = %s", (j["id"],))
                reintentar.append(j["id"])
        filas = c.execute(
            f"SELECT j.{_COLUMNAS.replace(', ', ', j.')}, p.empresa FROM jobs j JOIN web_postulaciones p ON p.id = j.postulacion_id "
            "WHERE j.user_id = %s AND (j.estado IN ('pendiente', 'ejecutando') OR NOT j.visto) ORDER BY j.id DESC LIMIT 20",
            (user_id,),
        ).fetchall()
    return [_publico(f) for f in filas], reintentar


def marcar_visto(user_id: int, job_id: int) -> None:
    with pg.conn() as c:
        c.execute("UPDATE jobs SET visto = true WHERE id = %s AND user_id = %s AND estado IN ('listo', 'error')", (job_id, user_id))


def despachar(base_url: str, job_id: int) -> None:
    """Dispara al worker (otra invocación) y NO espera el resultado: el read-timeout corto es lo esperado.
    Si la llamada se pierde, el job queda `pendiente` y `visibles()` lo recupera."""
    headers = {"x-job-token": token(job_id)}
    if _BYPASS:
        headers["x-vercel-protection-bypass"] = _BYPASS
    try:
        httpx.post(
            f"{base_url.rstrip('/')}/api/internal/jobs/{job_id}/ejecutar", headers=headers,
            timeout=httpx.Timeout(connect=5.0, read=2.0, write=5.0, pool=5.0),
        )
    except httpx.ReadTimeout:
        pass
    except httpx.HTTPError:
        log.warning("no se pudo despachar el job %s", job_id, exc_info=True)
