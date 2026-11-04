"""Conexión a Postgres (Supabase) para la web. El esquema lo gestionan las migraciones de
`supabase/migrations/` (no se crea al vuelo).

Pensado para serverless (Vercel): una conexión corta por operación, contra el pooler de
Supabase en modo transacción (puerto 6543), que no admite prepared statements."""

from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

from bot.config import DATABASE_URL


@contextmanager
def conn():
    if not DATABASE_URL:
        raise RuntimeError("Falta DATABASE_URL (cadena de conexión Postgres de Supabase). Revisa .env / Vercel.")
    c = psycopg.connect(DATABASE_URL, row_factory=dict_row, prepare_threshold=None, connect_timeout=10)
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()
