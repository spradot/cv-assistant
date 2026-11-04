# Postulaciones — asistente de CVs con IA

Pega una oferta laboral y obtén: clasificación de ajuste (postular / descartar), un CV en PDF a medida
generado desde tu perfil (rendercv), chequeo ATS, ajustes con vista previa y respaldo de cada cambio.

- **Web** (`web/`): API FastAPI + SPA React (Vite/Tailwind). Multiusuario. Se despliega en **Vercel**.
- **Bot de Telegram** (`bot/`, `main.py`): el mismo pipeline por chat. Solo local (no va a Vercel).
- **Datos**: Postgres de **Supabase**. **Archivos** (perfil, respaldos, YAML, PDFs): Supabase **Storage** (bucket privado `cvs`).

## Ramas y entornos

| Rama | Vercel | Supabase |
|---|---|---|
| `main` | Production | proyecto **prod** |
| `dev` | Preview (cada push) | proyecto **dev** |

Flujo: se trabaja en `dev` → PR a `main` → merge = deploy a producción.

## Desarrollo local

```powershell
python -m venv .venv; .\.venv\Scripts\pip install -r requirements-dev.txt
copy .env.example .env      # completa DEEPSEEK_*, DATABASE_URL, SUPABASE_*  (usa el proyecto *dev*)
.\web.ps1 -Build            # compila el frontend y levanta http://127.0.0.1:8000
```

Frontend con recarga en caliente: `cd web/frontend; npm install; npm run dev` (proxy a `/api` en :8000).

## Base de datos y almacenamiento

El esquema vive en [`supabase/migrations/`](supabase/migrations). Se aplica una vez por proyecto Supabase
(`supabase db push` o pegando el SQL en el SQL Editor). La migración también crea el bucket privado `cvs`.

## Despliegue

Ver [`docs/DESPLIEGUE.md`](docs/DESPLIEGUE.md).

## Estructura

```
api/index.py        entrada serverless de Vercel (expone web.app)
web/                API (app.py, cuentas.py, store.py, storage.py) y frontend (web/frontend)
bot/                pipeline de IA, render de CVs, bot de Telegram
supabase/migrations esquema SQL
vercel.json         build, rewrites /api/* y límites de la función
```

## Datos personales

Nada personal se versiona: `.env`, `mi_perfil.md` (perfil del bot de Telegram), CVs generados (`YAML/`, `procesados/`,
`*.pdf`), bases SQLite y logs están en `.gitignore`. El repositorio es público: no subas CVs ni perfiles.
