# Despliegue: Vercel + Supabase

`main` = producción, `dev` = desarrollo/preview. Una base Supabase por entorno.

## 1. Supabase (dos proyectos: `postulaciones-dev` y `postulaciones-prod`)

Para cada uno:

1. Crear el proyecto (región cercana a la de Vercel; ver paso 3).
2. Aplicar el esquema: SQL Editor → pegar `supabase/migrations/20261104000000_init.sql` → Run
   (o `supabase link --project-ref <ref>` + `supabase db push`). Crea tablas con RLS activado y el bucket privado `cvs`.
3. Copiar:
   - `DATABASE_URL`: Project Settings → Database → Connection string → **Transaction pooler** (puerto 6543).
   - `SUPABASE_URL`: Project Settings → API → Project URL.
   - `SUPABASE_SERVICE_ROLE_KEY`: Project Settings → API (clave secreta; solo servidor, nunca en el frontend).

## 2. GitHub

El remoto actual es `https://github.com/spradot/cv-assistant` (**público**). Confirma que sea el repo correcto y que
`gh auth status` apunte a la cuenta dueña antes de hacer push.

```powershell
git push -u github main
git push -u github dev
```

En GitHub: Settings → Branches → proteger `main` (PR obligatorio).

## 3. Vercel

1. Add New Project → importar el repo. Framework Preset: **Other**. Root Directory: la raíz. `vercel.json` ya define
   el build (`npm ci && npm run build` del frontend), el directorio de salida (`web/static`) y la función Python (`api/index.py`).
2. Settings → Git → **Production Branch = `main`**. Las demás ramas (`dev`) generan Preview.
3. Settings → Environment Variables (marcar el entorno correcto):

   | Variable | Production | Preview (dev) |
   |---|---|---|
   | `DEEPSEEK_API_KEY`, `DEEPSEEK_MODEL`, `DEEPSEEK_BASE_URL` | ✔ | ✔ |
   | `TYPESAFE_API_KEY` / `CLASSIFIER_PROVIDER` (opcional) | ✔ | ✔ |
   | `DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` | proyecto **prod** | proyecto **dev** |
   | `SUPABASE_BUCKET` | `cvs` | `cvs` |
   | `CODIGO_INVITACION` | **obligatorio** (si no, cualquiera crea cuentas y gasta tu IA) | recomendado |
   | `APP_URL` | URL de producción | opcional (usa `VERCEL_URL`) |
   | `SMTP_*` (opcional) | ✔ | ✔ |

4. Región de la función: Settings → Functions → la más cercana a tu proyecto Supabase.
5. Deploy. Crea la primera cuenta (será la administradora) enseguida, con el código de invitación.

## Notas operativas

- **Duración**: generar un CV encadena varias llamadas a IA + render; `vercel.json` pide `maxDuration: 300`
  (máximo con Fluid Compute; Hobby sin Fluid Compute admite 60 s).
- **Disco efímero**: rendercv renderiza en `/tmp` y el PDF se sube a Storage. Nada persiste en la función.
- **Bot de Telegram**: sigue corriendo local con SQLite (`bot/db.py`); no comparte datos con la web.
- **Rollback**: Vercel → Deployments → Promote a una versión anterior. Los cambios de esquema son aditivos: crea
  una migración nueva por cambio en `supabase/migrations/`.
