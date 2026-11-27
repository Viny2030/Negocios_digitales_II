# Baja a la PC la base que mantienen los workflows de GitHub Actions (levantamiento-canales.yml):
# el último artifact "channel-analytics-db", lo descifra y lo deja como channel_analytics.db,
# para ver en el dashboard local las fotos tomadas en la nube.
#
#   .\scripts\descargar_base.ps1
#
# Requiere `gh` con sesión iniciada y gpg (viene con Git para Windows). La clave sale de
# DB_PASSPHRASE en el entorno o en .env (la misma que el secret del repo).
# Antes de reemplazar, guarda la base local como channel_analytics.local-AAAAMMDD-HHMMSS.db.
# Apagá la API local antes: con uvicorn corriendo, el archivo está en uso.
param(
    [string]$Repo = "Viny2030/Negocios_digitales_II",
    [string]$Artifact = "channel-analytics-db"
)
$ErrorActionPreference = "Stop"
$repoDir = Split-Path $PSScriptRoot -Parent
$db = Join-Path $repoDir "channel_analytics.db"

$pass = $env:DB_PASSPHRASE
if (-not $pass) {
    $envFile = Join-Path $repoDir ".env"
    if (Test-Path $envFile) {
        $line = Get-Content $envFile | Where-Object { $_ -match "^DB_PASSPHRASE=" } | Select-Object -First 1
        if ($line) { $pass = $line.Substring("DB_PASSPHRASE=".Length).Trim() }
    }
}
if (-not $pass) { Write-Error "Falta DB_PASSPHRASE (en el entorno o en .env)." }

$gpg = (Get-Command gpg -ErrorAction SilentlyContinue).Source
if (-not $gpg) { $gpg = "C:\Program Files\Git\usr\bin\gpg.exe" }
if (-not (Test-Path $gpg)) { Write-Error "No se encontró gpg (se instala con Git para Windows)." }

$id = gh api "repos/$Repo/actions/artifacts?name=$Artifact&per_page=100" `
    --jq '[.artifacts[] | select(.expired == false)] | sort_by(.created_at) | last | .id // empty'
if (-not $id) { Write-Error "No hay ningún artifact '$Artifact' vigente en $Repo." }

$tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("base_" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory $tmp | Out-Null
try {
    $zip = Join-Path $tmp "base.zip"
    # Invoke-WebRequest y no `gh api > archivo`: la redirección de PowerShell corrompe binarios.
    $token = gh auth token
    Invoke-WebRequest -Uri "https://api.github.com/repos/$Repo/actions/artifacts/$id/zip" `
        -Headers @{ Authorization = "Bearer $token"; Accept = "application/vnd.github+json" } -OutFile $zip
    Expand-Archive $zip -DestinationPath $tmp
    $enc = Join-Path $tmp "channel_analytics.db.gpg"
    $nueva = Join-Path $tmp "channel_analytics.db"
    $pass | & $gpg --batch --yes --quiet --pinentry-mode loopback --passphrase-fd 0 --decrypt --output $nueva $enc
    if ($LASTEXITCODE -ne 0) { Write-Error "No se pudo descifrar: ¿DB_PASSPHRASE distinta del secret del repo?" }

    $py = Join-Path $repoDir ".venv\Scripts\python.exe"
    if (-not (Test-Path $py)) { $py = "python" }
    $check = & $py -c "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); print(c.execute('PRAGMA integrity_check').fetchone()[0]); print(c.execute('select max(snapshot_date) from channel_metric_snapshots').fetchone()[0])" $nueva
    if ($check[0] -ne "ok") { Write-Error "La base descargada no pasó el chequeo de integridad: $($check[0])" }

    if (Test-Path $db) {
        $respaldo = Join-Path $repoDir ("channel_analytics.local-{0}.db" -f (Get-Date -Format "yyyyMMdd-HHmmss"))
        Move-Item $db $respaldo
        Write-Host "Base local anterior guardada en $respaldo"
    }
    Move-Item $nueva $db
    Write-Host "OK  channel_analytics.db actualizada desde el artifact $id (última foto: $($check[1]))"
} finally {
    Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
}
