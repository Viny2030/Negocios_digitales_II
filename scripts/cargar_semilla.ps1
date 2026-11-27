# Carga al seguimiento los canales de semilla_laguiadelstreaming.csv que tengan handle_youtube.
# Usa la propia API local (POST /api/v1/tracking/channels): resuelve por @handle con
# channels.list forHandle (1 unidad) en vez de search.list (100 unidades).
#
#   .\cargar_semilla.ps1                       # contra http://127.0.0.1:8000
#   .\cargar_semilla.ps1 -Base http://127.0.0.1:8000 -AdminToken xxx
param(
    [string]$Base = "http://127.0.0.1:8000",
    [string]$Csv = "$PSScriptRoot\semilla_laguiadelstreaming.csv",
    [string]$AdminToken = ""
)

try { Invoke-RestMethod "$Base/" -TimeoutSec 5 | Out-Null }
catch {
    Write-Warning "La API no responde en $Base. Levantala en otra terminal con: uvicorn app.main:app --reload"
    exit 1
}

$headers = @{}
if ($AdminToken) { $headers["X-Admin-Token"] = $AdminToken }

# Sin YOUTUBE_API_KEY la app inventa datos (modo mock): no sirven para calibrar.
$filas = Import-Csv -Path $Csv -Encoding UTF8 | Where-Object { $_.handle_youtube -and $_.handle_youtube.Trim() }
if (-not $filas) { Write-Warning "Completá la columna handle_youtube (ej. @canal) antes de correr."; exit 1 }

foreach ($f in $filas) {
    $handle = $f.handle_youtube.Trim()
    if (-not $handle.StartsWith("@")) { $handle = "@$handle" }
    $body = @{
        platform          = "youtube"
        identifier        = $handle
        label             = "laguiadelstreaming:$($f.cohorte)"
        channel_type_name = "Cohorte $($f.cohorte)"
    } | ConvertTo-Json
    try {
        $r = Invoke-RestMethod -Method Post -Uri "$Base/api/v1/tracking/channels" -Headers $headers `
            -ContentType "application/json; charset=utf-8" -Body ([Text.Encoding]::UTF8.GetBytes($body))
        $snap = $r.latest_snapshot
        Write-Host ("OK   {0,-22} id={1,-4} seguidores={2}" -f $f.nombre, $r.id, $snap.followers)
    } catch {
        Write-Warning ("FALLA {0} ({1}): {2}" -f $f.nombre, $handle, $_.Exception.Message)
    }
}

# Auditoría de cada canal trackeado de estas cohortes (no gasta cuota: lee snapshots).
$lista = (Invoke-RestMethod "$Base/api/v1/tracking/channels" -Headers $headers).channels |
    Where-Object { $_.label -like "laguiadelstreaming:*" }
$lista | ForEach-Object {
    $a = (Invoke-RestMethod "$Base/api/v1/tracking/channels/$($_.id)/audience-integrity" -Headers $headers).assessment
    [pscustomobject]@{ canal = $_.name; cohorte = $_.label; score = $a.score; nivel = $a.level
                       evaluadas = $a.signals_evaluated; mock = $a.is_mock }
} | Sort-Object cohorte, score -Descending | Format-Table -AutoSize
