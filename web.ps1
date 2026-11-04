# web.ps1 — Levanta la web en http://127.0.0.1:8000 (requiere DATABASE_URL y SUPABASE_* en .env)
# Uso: .\web.ps1          → compila el frontend si falta y levanta el servidor
#      .\web.ps1 -Build   → fuerza recompilar el frontend (tras cambios en web/frontend)
param([switch]$Build)

$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $dir

if ($Build -or -not (Test-Path "web\static\index.html")) {
    Push-Location web\frontend
    if (-not (Test-Path "node_modules")) { npm install }
    npm run build
    Pop-Location
}

Start-Process "http://127.0.0.1:8000"
& .\.venv\Scripts\python.exe -m web
