# Configuración inicial (una sola vez) del levantamiento en GitHub Actions:
#   1. genera la clave de cifrado de la base y la agrega a .env como DB_PASSPHRASE (si no estaba);
#   2. carga en el repo los secrets DB_PASSPHRASE y YOUTUBE_API_KEY (la clave sale de .env);
#   3. cifra una copia consistente de channel_analytics.db en bootstrap/channel_analytics.db.gpg,
#      la base de la que arranca la primera corrida del workflow.
# No muestra ningún valor secreto en pantalla.
#
#   .\scripts\configurar_actions.ps1
#
# Requiere `gh` con sesión iniciada y gpg (viene con Git para Windows).
param([string]$Repo = "Viny2030/Negocios_digitales_II")
$ErrorActionPreference = "Stop"
$repoDir = Split-Path $PSScriptRoot -Parent
$envFile = Join-Path $repoDir ".env"
$db = Join-Path $repoDir "channel_analytics.db"

function Get-EnvValue([string]$name) {
    $line = Get-Content $envFile | Where-Object { $_ -match "^$name=" } | Select-Object -First 1
    if ($line) { return $line.Substring($name.Length + 1).Trim() }
    return $null
}

$py = Join-Path $repoDir ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }
$gpg = (Get-Command gpg -ErrorAction SilentlyContinue).Source
if (-not $gpg) { $gpg = "C:\Program Files\Git\usr\bin\gpg.exe" }

# 1. Clave de cifrado
$pass = Get-EnvValue "DB_PASSPHRASE"
if (-not $pass) {
    $pass = & $py -c "import secrets; print(secrets.token_urlsafe(32))"
    Add-Content $envFile "`n# Clave de cifrado de la base de los workflows de GitHub Actions (igual al secret DB_PASSPHRASE).`n# La usa scripts/descargar_base.ps1. No compartir.`nDB_PASSPHRASE=$pass"
    Write-Host "1. DB_PASSPHRASE generada y agregada a .env"
} else {
    Write-Host "1. DB_PASSPHRASE ya estaba en .env: se reutiliza"
}

# 2. Secrets del repo
$pass | gh secret set DB_PASSPHRASE --repo $Repo
$key = Get-EnvValue "YOUTUBE_API_KEY"
if (-not $key) { Write-Error "No hay YOUTUBE_API_KEY en .env" }
$key | gh secret set YOUTUBE_API_KEY --repo $Repo
Write-Host "2. Secrets DB_PASSPHRASE y YOUTUBE_API_KEY cargados en $Repo"

# 3. Base inicial cifrada (copia consistente con la API de backup de SQLite)
$tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("boot_" + [guid]::NewGuid().ToString("N") + ".db")
try {
    & $py -c "import sqlite3,sys; s=sqlite3.connect(sys.argv[1]); d=sqlite3.connect(sys.argv[2]); s.backup(d); d.close(); s.close()" $db $tmp
    New-Item -ItemType Directory -Force (Join-Path $repoDir "bootstrap") | Out-Null
    $out = Join-Path $repoDir "bootstrap\channel_analytics.db.gpg"
    $pass | & $gpg --batch --yes --quiet --pinentry-mode loopback --passphrase-fd 0 --symmetric --cipher-algo AES256 --output $out $tmp
    if ($LASTEXITCODE -ne 0) { Write-Error "gpg no pudo cifrar la base" }
    Write-Host "3. Base inicial cifrada en bootstrap\channel_analytics.db.gpg ($([math]::Round((Get-Item $out).Length / 1KB)) KB)"
} finally {
    Remove-Item $tmp -ErrorAction SilentlyContinue
}

Write-Host "`nListo. Para el mail, cargá también (Gmail con contraseña de aplicación):"
Write-Host "  gh secret set SMTP_USERNAME   # la cuenta de Gmail que envía"
Write-Host "  gh secret set SMTP_PASSWORD   # contraseña de aplicación de 16 letras"
Write-Host "  gh secret set MAIL_TO         # a quién le llega"
