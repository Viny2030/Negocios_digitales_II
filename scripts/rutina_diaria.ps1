# Rutina diaria de recolección (fase local, hasta el despliegue en Railway de marzo 2027).
#
#   .\scripts\rutina_diaria.ps1
#
# 1. Verifica que la API local responda (uvicorn levantado en otra terminal).
# 2. Toma la foto del día de todos los canales trackeados (POST /tracking/run-daily-job).
#    Es idempotente: si el scheduler de las 15:00 UTC ya la tomó, solo la actualiza.
# 3. Respalda channel_analytics.db con la API de backup de SQLite (copia consistente
#    aunque la app esté corriendo) en una carpeta fuera del repo.
# 4. Muestra el puntaje de las cohortes de La Guía del Streaming (no gasta cuota).
param(
    [string]$Base = "http://127.0.0.1:8000",
    [string]$Backups = "$HOME\OneDrive\backups_channel_analytics",
    [string]$AdminToken = ""
)

$repo = Split-Path $PSScriptRoot -Parent
$headers = @{}
if ($AdminToken) { $headers["X-Admin-Token"] = $AdminToken }

Write-Host "`n== 1. API local" -ForegroundColor Cyan
try {
    $salud = Invoke-RestMethod "$Base/" -TimeoutSec 5
    Write-Host "OK  entorno=$($salud.environment)"
} catch {
    Write-Warning "La API no responde en $Base. Levantala en otra terminal con: uvicorn app.main:app --reload"
    exit 1
}

Write-Host "`n== 2. Foto del día" -ForegroundColor Cyan
try {
    $job = Invoke-RestMethod -Method Post "$Base/api/v1/tracking/run-daily-job" -Headers $headers -TimeoutSec 900
    Write-Host ("Canales evaluados: {0} · fotos nuevas: {1} · actualizadas: {2} · errores: {3}" -f `
        $job.channels_evaluated, $job.snapshots_created, $job.snapshots_updated, $job.errors.Count)
    $job.errors | Select-Object -First 10 | ForEach-Object { Write-Warning $_ }
    if ($job.errors | Where-Object { $_ -match "quota" }) {
        Write-Warning "Se agotó la cuota de YouTube: los canales con error quedan sin foto hoy. Reintentá mañana."
    }
} catch {
    Write-Warning "Falló el job diario: $($_.Exception.Message)"
}

Write-Host "`n== 3. Respaldo de la base" -ForegroundColor Cyan
$db = Join-Path $repo "channel_analytics.db"
New-Item -ItemType Directory -Force $Backups | Out-Null
$destino = Join-Path $Backups ("channel_analytics-{0}.db" -f (Get-Date -Format "yyyyMMdd"))
$py = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }
& $py -c "import sqlite3,sys; s=sqlite3.connect(sys.argv[1]); d=sqlite3.connect(sys.argv[2]); s.backup(d); d.close(); s.close()" $db $destino
if ($LASTEXITCODE -eq 0) {
    $mb = [math]::Round((Get-Item $destino).Length / 1MB, 1)
    Write-Host "OK  $destino ($mb MB)"
    # Conserva los últimos 30 respaldos diarios.
    Get-ChildItem $Backups -Filter "channel_analytics-*.db" | Sort-Object Name -Descending |
        Select-Object -Skip 30 | Remove-Item -ErrorAction SilentlyContinue
} else {
    Write-Warning "No se pudo respaldar $db"
}

Write-Host "`n== 4. Cohortes de La Guía del Streaming" -ForegroundColor Cyan
$lista = (Invoke-RestMethod "$Base/api/v1/tracking/channels" -Headers $headers).channels |
    Where-Object { $_.label -like "laguiadelstreaming:*" }
if (-not $lista) {
    Write-Host "Todavía no hay canales de las cohortes. Completá handles y corré .\scripts\cargar_semilla.ps1"
} else {
    $lista | ForEach-Object {
        $r = Invoke-RestMethod "$Base/api/v1/tracking/channels/$($_.id)/audience-integrity" -Headers $headers
        [pscustomobject]@{
            canal = $_.name; cohorte = ($_.label -replace "^laguiadelstreaming:", "")
            score = $r.assessment.score; nivel = $r.assessment.level
            evaluadas = $r.assessment.signals_evaluated; fotos = $r.snapshots_used
        }
    } | Sort-Object cohorte, score -Descending | Format-Table -AutoSize
}
