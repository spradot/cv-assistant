# render.ps1 — Renderiza todos los YAMLs de postulación o uno específico
# Uso: .\render.ps1             → renderiza todos los DS_ES_*.yaml y DE_ES_*.yaml
# Uso: .\render.ps1 SMS         → renderiza solo DS_ES_SMS.yaml o DE_ES_SMS.yaml

param([string]$empresa = "")

$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $dir

$procesadosDir = Join-Path $dir "procesados"
$yamlDir = Join-Path $dir "YAML"
New-Item -ItemType Directory -Force -Path $procesadosDir | Out-Null
New-Item -ItemType Directory -Force -Path $yamlDir | Out-Null

if ($empresa -ne "") {
    $archivos = Get-ChildItem -Path $dir -Filter "*_$empresa.yaml"
} else {
    $archivos = Get-ChildItem -Path $dir -Filter "DS_ES_*.yaml"
    $archivos += Get-ChildItem -Path $dir -Filter "DE_ES_*.yaml"
}

if ($archivos.Count -eq 0) {
    Write-Host "No se encontraron archivos para renderizar." -ForegroundColor Yellow
    exit
}

foreach ($archivo in $archivos) {
    Write-Host "Renderizando: $($archivo.Name)" -ForegroundColor Cyan
    $empresaNombre = $archivo.BaseName -replace "^(DE|DS)_ES_", ""
    $pdfPath = Join-Path $dir "Samuel_Prado_${empresaNombre}_CV.pdf"
    $output = python -m rendercv render $archivo.FullName --pdf-path $pdfPath 2>&1
    $output | Write-Host
    if (Test-Path $pdfPath) {
        Write-Host "OK: Samuel_Prado_${empresaNombre}_CV.pdf generado." -ForegroundColor Green
        Move-Item -Path $pdfPath -Destination $procesadosDir -Force
        Move-Item -Path $archivo.FullName -Destination $yamlDir -Force
    } else {
        Write-Host "ERROR: no se genero el PDF para $($archivo.Name)" -ForegroundColor Red
    }
}
