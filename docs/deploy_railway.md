# Despliegue en Railway sin `railway.toml`

Railway deja de leer `railway.toml` y `railway.json` (Config as Code) el **1 de diciembre de 2026**.
Desde ese día manda la configuración del servicio en el dashboard. Este repositorio ya no trae
`railway.toml`: los mismos valores quedan registrados acá y se cargan una sola vez en el dashboard.

## 1. Valores del servicio API (Settings del servicio)

| Ajuste en Railway | Valor | Venía de `railway.toml` |
|---|---|---|
| Build → Builder | Dockerfile | `builder = "DOCKERFILE"` |
| Build → Dockerfile path | `Dockerfile` | `dockerfilePath` |
| Deploy → Healthcheck path | `/` | `healthcheckPath` |
| Deploy → Healthcheck timeout | `100` s | `healthcheckTimeout` |
| Deploy → Restart policy | On failure, 3 reintentos | `restartPolicyType`, `restartPolicyMaxRetries` |
| Deploy → Replicas | **1** | `numReplicas = 1` |
| Settings → Config as code → Config file path | **vacío** | — |

**Una sola réplica, siempre.** El worker diario y el descubrimiento automático corren con
APScheduler dentro del proceso de FastAPI (`app/core/scheduler.py`), y el límite de intentos de
`/auth/*` vive en memoria (`app/core/rate_limit.py`). Con dos réplicas, cada job correría dos veces
y el límite de intentos se dividiría entre procesos.

Orden seguro: primero cargar estos valores en el dashboard (mientras el archivo exista, el archivo
gana), después mergear el PR que borra `railway.toml`, y por último vaciar el campo *Config file path*.

## 2. Que el merge a `main` no despliegue antes de tiempo

1. **Settings → Source → Wait for CI**: activado. Railway espera a que `.github/workflows/ci.yml`
   (ruff + pytest) termine en verde antes de construir.
2. Antes del primer merge, cargar las variables. Sin ellas, en producción la app **no arranca**
   (`production_safety_warnings` en `app/core/config.py`, llamado desde `lifespan` en `app/main.py`):
   - `ADMIN_TOKEN` y `JWT_SECRET_KEY`: `python -c "import secrets; print(secrets.token_hex(32))"`, uno por variable.
   - `YOUTUBE_API_KEY`: rotada si alguna vez se compartió fuera del repo.
   - `DATABASE_URL` = `${{Postgres.DATABASE_URL}}`.
   - `CORS_ALLOWED_ORIGINS` = el dominio público real.
3. Si querés control total, dejá el servicio sin rama de despliegue automático hasta revisar las
   variables, y desplegá a mano la primera vez.

## 3. Alternativa: Infraestructura como Código (`.railway/railway.ts`)

Railway ofrece `railway config migrate` (CLI 5.49.1 o superior) para traducir el archivo viejo a
`.railway/railway.ts`. Primero en modo ensayo, sin escribir nada:

```powershell
railway config migrate --service api
```

Si el resultado convence: `railway config migrate --apply --delete-files` y después `railway config plan`.
Requiere Node y el paquete `railway` en el repo, y la documentación de IaC no garantiza que traslade
la política de reinicio: hay que verificarla a mano con `plan`. Para un servicio único en Python,
la opción del punto 1 es más simple.

## 4. Respaldo externo de PostgreSQL (`pg_dump`)

La versión de `pg_dump` tiene que ser igual o mayor que la del servidor
(`SELECT version();` en la consola de Railway). Con Docker, sin instalar nada en Windows:

```powershell
$env:PG_URL = "postgresql://usuario:clave@host.proxy.rlwy.net:PUERTO/railway"   # URL pública de la base
$fecha = Get-Date -Format "yyyyMMdd-HHmm"
docker run --rm -v "${PWD}\backups:/backups" postgres:17-alpine `
  pg_dump "$env:PG_URL" --format=custom --no-owner --file "/backups/channel_analytics-$fecha.dump"
```

Restaurar en una base vacía: `pg_restore --no-owner --dbname "<url>" backups\channel_analytics-<fecha>.dump`.
Para automatizarlo, el mismo comando puede ir en un workflow de GitHub Actions con `schedule`,
con `PG_URL` como secret y el `.dump` subido como artifact o a un bucket externo.

## 5. Migrar el histórico local (SQLite) a PostgreSQL

Ver `scripts/migrar_sqlite_a_postgres.py`: ensayo por defecto, `--aplicar` copia en una sola
transacción, conserva los `id`, reubica las secuencias y verifica filas y sumas de métricas.
La base de destino tiene que estar vacía (no arrancar la app contra ella antes de migrar).
