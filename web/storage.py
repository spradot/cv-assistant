"""Almacenamiento de archivos en Supabase Storage (bucket privado), vía su API REST.

Se usa la clave de servicio desde el servidor: el navegador nunca habla con Storage, todo
pasa por la API (que ya valida la sesión y a quién pertenece cada archivo). Las claves
siguen el patrón `usuarios/<id>/...`."""

import os
from datetime import datetime
from urllib.parse import quote

import httpx

SUPABASE_URL = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or ""
BUCKET = os.environ.get("SUPABASE_BUCKET") or "cvs"
_TIMEOUT = httpx.Timeout(30.0)


class StorageError(RuntimeError):
    pass


def _headers() -> dict:
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        raise StorageError("Faltan SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY (revisa .env / Vercel).")
    headers = {"apikey": SUPABASE_SERVICE_KEY}
    if SUPABASE_SERVICE_KEY.startswith("eyJ"):  # las claves sb_secret_* van solo en `apikey`
        headers["Authorization"] = f"Bearer {SUPABASE_SERVICE_KEY}"
    return headers


def _url(clave: str) -> str:
    return f"{SUPABASE_URL}/storage/v1/object/{BUCKET}/{quote(clave)}"


def subir(clave: str, datos: bytes, content_type: str = "application/octet-stream") -> None:
    r = httpx.post(
        _url(clave), content=datos, timeout=_TIMEOUT,
        headers={**_headers(), "Content-Type": content_type, "x-upsert": "true"},
    )
    if r.status_code >= 300:
        raise StorageError(f"No se pudo guardar {clave}: {r.status_code} {r.text[:200]}")


def descargar(clave: str) -> bytes | None:
    """None si el archivo no existe."""
    r = httpx.get(_url(clave), timeout=_TIMEOUT, headers=_headers())
    if r.status_code in (400, 404):  # Storage responde 400 {"statusCode":"404"} para objetos inexistentes
        return None
    if r.status_code >= 300:
        raise StorageError(f"No se pudo leer {clave}: {r.status_code} {r.text[:200]}")
    return r.content


def listar(carpeta: str, buscar: str | None = None) -> list[dict]:
    """Archivos de una carpeta: [{name, updated_at, ...}], ordenados por nombre descendente."""
    cuerpo = {"prefix": carpeta.strip("/"), "limit": 1000, "sortBy": {"column": "name", "order": "desc"}}
    if buscar:
        cuerpo["search"] = buscar
    r = httpx.post(f"{SUPABASE_URL}/storage/v1/object/list/{BUCKET}", json=cuerpo, timeout=_TIMEOUT, headers=_headers())
    if r.status_code >= 300:
        raise StorageError(f"No se pudo listar {carpeta}: {r.status_code} {r.text[:200]}")
    return [f for f in r.json() if f.get("id")]  # sin `id` son subcarpetas


def modificado(clave: str) -> int | None:
    """Epoch de la última escritura (sirve de versión para cachear PDFs), o None si no existe."""
    carpeta, _, nombre = clave.rpartition("/")
    for f in listar(carpeta, nombre):
        if f["name"] == nombre and f.get("updated_at"):
            return int(datetime.fromisoformat(f["updated_at"].replace("Z", "+00:00")).timestamp())
    return None


def eliminar(claves: list[str]) -> None:
    if not claves:
        return
    r = httpx.request(
        "DELETE", f"{SUPABASE_URL}/storage/v1/object/{BUCKET}", json={"prefixes": claves},
        timeout=_TIMEOUT, headers=_headers(),
    )
    if r.status_code >= 300:
        raise StorageError(f"No se pudo eliminar: {r.status_code} {r.text[:200]}")
