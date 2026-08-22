# Channel Analytics Core

Sistema unificado de analítica de canales de contenido. **Fase actual: YouTube + TikTok.**

Normaliza canales de distintas plataformas bajo una Entidad Universal Canal
(`UnifiedChannel`) y calcula estadística robusta (mediana, IQR, percentiles),
desigualdad (Gini, Pareto), correlación (Spearman/Pearson) y detección de
anomalías, todo servido vía FastAPI.

El acceso a "toda la estadística" del sitio funciona por planes de
suscripción (**free / única / mensual / premium** — ver [Planes de
suscripción y autenticación](#planes-de-suscripción-y-autenticación)
más abajo); premium además desbloquea proyecciones de tendencia y
recomendaciones de política general por métrica.

## Quickstart

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# (opcional) completar YOUTUBE_API_KEY / TIKTOK_CLIENT_KEY / TIKTOK_CLIENT_SECRET

uvicorn app.main:app --reload
```

Abrir http://localhost:8000/docs para la documentación interactiva (Swagger UI)
o **http://localhost:8000/dashboard para el dashboard visual**.

**No hace falta tener credenciales para probar el sistema**: si faltan,
cada colector cae automáticamente a datos simulados (modo mock), con una
distribución log-normal realista (pocos canales grandes, muchos chicos),
para poder ejercitar el pipeline completo de ingesta → normalización →
estadística.

## Dashboard visual

`GET /dashboard` sirve un dashboard de una sola página (`app/static/dashboard.html`
— HTML/CSS/JS plano, sin frameworks ni librerías externas) que consume la propia
API por `fetch` (mismo origen, sin configurar nada de CORS). Seis pestañas:

- **Resumen** — KPIs por plataforma (canales, seguidores, vistas, ER promedio con
  badge de benchmark), canales por tier, Gini de desigualdad, distribución de
  seguidores y de ER (percentiles P10–P90 / IQR / mediana), y correlaciones
  (Spearman) con su interpretación.
- **Por canal** — tabla completa, ordenable por cualquier columna, filtrable por
  nombre/@handle, con chip de tier y aviso ⚠ en los canales que el detector de
  anomalías marcó como posiblemente inflados.
- **Por categoría** — un ranking independiente por cada categoría de YouTube
  (música, gaming, noticias, ciencia y tecnología, etc.), sin mezclarlas entre
  sí — para que un género grande (música, gaming) no tape a uno más chico.
- **Por temática** — cada búsqueda queda guardada en la sesión del navegador
  (no se persiste en el backend) para comparar seguidores y ER promedio entre
  distintos temas buscados.
- **Métricas del medio** — las fichas de benchmark de industria (`/analytics/benchmarks`).
- **Seguimiento diario** — alta/baja de canales trackeados (por ID nativo o
  @handle, plataforma abierta a YouTube o TikTok), tabla con su último snapshot
  (seguidores, NER, tier, fecha), botón "Correr job ahora" para disparar el
  worker sin esperar al scheduler (semanal por default), y un mini gráfico de
  línea con el historial de seguidores del canal seleccionado. Ver la sección
  [Seguimiento (persistencia + worker)](#seguimiento-persistencia--worker)
  más abajo.

Debajo del buscador por tema hay una segunda fila ("— o todos los temas, sin
categoría —") con dos modos que no piden palabra clave:

- **🌐 Lista única** (`GET /channels/discover`) — junta candidatos de todos
  los temas en una sola lista, ordenada de mayor a menor por la métrica
  elegida (suscriptores, vistas, publicaciones o NER). El campo numérico al
  lado controla cuántos canales en total (hasta 2000; no hay un tope duro,
  el real es cuántos canales distintos aparecen en el trending combinado).
- **📊 Por categoría** (`GET /channels/discover/by-category`) — el mismo
  descubrimiento, pero sin mezclar las categorías: un ranking independiente
  por cada una (pestaña "Por categoría"). El campo numérico controla cuántos
  canales **por categoría**, no un total global.

En ambos casos, cómo se arma la lista de candidatos: en YouTube, recorriendo
el trending (`videos.list chart=mostPopular`) combinando cada categoría de
`YouTubeCollector.DISCOVER_CATEGORY_LABELS` (15 en total — música, gaming,
entretenimiento, noticias y política, deportes, ciencia y tecnología,
educación, comedia, estilo de vida, cine y animación, autos y vehículos,
mascotas y animales, viajes y eventos, blogs, ONGs y activismo) con cada
región de `DISCOVER_REGION_CODES` (default: Argentina, México, España,
Estados Unidos), paginando un par de veces cada combinación para juntar más
candidatos de los que entran en una sola página de 50. Desde cualquiera de
las dos tablas, "+ Seguir" agrega ese canal al seguimiento semanal sin tener
que darlo de alta a mano.

Soporta modo claro/oscuro (automático según el sistema, con toggle manual que
se recuerda en `localStorage`). Los gráficos son SVG dibujados a mano siguiendo
las convenciones de la skill de dataviz de Claude (paleta categórica fija YouTube=azul/TikTok=naranja,
barras con extremo redondeado, tooltips al pasar el mouse, tabla como vista accesible).

### Con Docker

```bash
docker compose up --build
```

## Tests

```bash
pytest -v
```

## Endpoints principales

| Método | Ruta | Descripción |
|---|---|---|
| POST | `/api/v1/analyze` | Pipeline completo: busca en YouTube + TikTok, normaliza y devuelve canales + resumen (con benchmark de industria por plataforma) |
| GET | `/api/v1/channels/search?query=&platform=youtube\|tiktok\|all&limit=` | Búsqueda unificada |
| GET | `/api/v1/channels/discover?platform=&limit=&sort_by=followers\|total_views\|total_posts\|normalized_er` | **Todos los temas**, lista única: candidatos de temas bien distintos, ordenados de mayor a menor por la métrica elegida. `limit` hasta `DISCOVER_MAX_LIMIT` (2000 por default) |
| GET | `/api/v1/channels/discover/by-category?platform=&limit_per_category=&sort_by=` | **Todos los temas**, por categoría: igual que el anterior pero sin mezclar — un ranking independiente por cada categoría/tópico |
| GET | `/api/v1/analytics/benchmarks?platform=youtube\|tiktok\|all` | **Métricas del medio**: ficha de referencia de industria por plataforma (fórmula y rango de ER, retención, frecuencia de publicación típica, vida útil del contenido, riesgo de sesgo). No requiere `query`, no consulta APIs externas. |
| GET | `/api/v1/analytics/distribution?query=&platform=youtube\|tiktok&limit=` | Mín/máx/rango, percentiles (P5/P10/P25/P75/P90/P95), IQR, desvío estándar, **coeficiente de variación**, skewness, kurtosis — más comparación contra el benchmark de industria |
| GET | `/api/v1/analytics/inequality?query=&limit=` | Coeficiente de Gini, exponente de Pareto y participación del top 10%, comparando YouTube vs TikTok |
| GET | `/api/v1/analytics/correlation?query=&platform=youtube\|tiktok&limit=` | Spearman/Pearson: publicaciones vs. engagement, seguidores vs. engagement |
| GET | `/api/v1/analytics/anomalies?query=&platform=youtube\|tiktok&limit=` | Detección de cuentas con métricas potencialmente infladas |
| GET | `/api/v1/analytics/overview?query=&limit=` | **Todo-en-uno**: distribución + desigualdad + correlación + anomalías + benchmark, para YouTube y TikTok, en una sola respuesta |
| POST | `/api/v1/tracking/channels` | Alta de un canal al seguimiento diario (`{platform, identifier, label?}`) — resuelve el canal contra la API/mock y toma su primer snapshot de una |
| GET | `/api/v1/tracking/channels?include_inactive=` | Lista los canales trackeados con su último snapshot |
| DELETE | `/api/v1/tracking/channels/{tracked_id}` | Baja lógica de un canal trackeado (conserva el historial ya tomado) |
| GET | `/api/v1/tracking/channels/{tracked_id}/history?days=` | Historial de snapshots diarios de un canal trackeado |
| POST | `/api/v1/tracking/run-daily-job` | Dispara el worker diario ahora mismo, sin esperar al scheduler |
| POST | `/api/v1/auth/register` | Crear una cuenta (email + contraseña, arranca en plan 'free') → devuelve JWT de sesión |
| POST | `/api/v1/auth/login` | Iniciar sesión → devuelve JWT de sesión |
| GET | `/api/v1/auth/me` | Datos del usuario autenticado: plan, vigencia, créditos, accesos vigentes |
| POST | `/api/v1/auth/admin/set-plan` | (Admin) Simular manualmente un alta/cambio de plan — sin pasarela de pago real |
| GET | `/api/v1/premium/channels/{tracked_id}/projections` | **[Premium]** Proyección de tendencia por métrica (extrapolación lineal sobre el histórico semanal) |
| GET | `/api/v1/premium/channels/{tracked_id}/recommendations` | **[Premium]** Recomendaciones de política general para mejorar cada métrica |

> Nota: `POST /analyze`, `/channels/search`, `/channels/discover*` y todo
> `/analytics/*` **excepto** `/analytics/benchmarks` requieren "toda la
> estadística" (plan única con crédito disponible, mensual o premium
> activos — ver la sección de planes más abajo).

### Métricas y benchmarks del medio

Cada plataforma trae una ficha de referencia de industria (`/analytics/benchmarks`) con el rango típico de Engagement Rate publicado (YouTube 1.5%–3.5%, TikTok 4.0%–9.0%), su fórmula, métrica de retención, frecuencia de publicación esperable, vida útil del contenido y el riesgo de sesgo conocido en sus métricas crudas. Los endpoints que calculan un ER promedio (`/analyze`, `/channels/search`, `/analytics/distribution`, `/analytics/overview`) adjuntan automáticamente un objeto `benchmark` que indica si ese promedio cae **"below"**, **"within"** o **"above"** del rango de industria, y qué tan lejos (`delta_from_range_pct`).

> Nota sobre el modo mock: la API pública de YouTube no expone "likes" agregados a nivel canal, así que el colector mock (y el real) aproximan `raw_interactions` solo con comentarios — por eso el ER de YouTube en modo mock suele salir "below" del benchmark. Es una limitación de la métrica cruda documentada en `normalizer.py`, no un bug.

📖 **Manual completo de métricas** (qué es cada campo, cómo se calcula, qué endpoint la devuelve): [`docs/manual_metricas_es.md`](./docs/manual_metricas_es.md) · **Full metrics manual** (English): [`docs/manual_metricas_en.md`](./docs/manual_metricas_en.md)

### Ejemplo

```bash
curl -X POST http://localhost:8000/api/v1/analyze \
  -H "Content-Type: application/json" \
  -d '{"query": "fitness", "platforms": ["youtube", "tiktok"], "limit": 20}'

curl "http://localhost:8000/api/v1/analytics/inequality?query=fitness&limit=30"
```

## Credenciales

| Plataforma | Variables | Dónde obtenerlas | Costo |
|---|---|---|---|
| YouTube | `YOUTUBE_API_KEY` | Google Cloud Console → Habilitar YouTube Data API v3 → Crear API Key | Gratis, 10.000 unidades/día |
| TikTok | `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET` | https://developers.tiktok.com → Registrar app | Gratis, sujeto a aprobación |

Ver `.env.example` para el detalle completo. Ninguna de las dos es obligatoria:
sin `YOUTUBE_API_KEY` ni `TIKTOK_CLIENT_KEY`/`TIKTOK_CLIENT_SECRET` el sistema
(búsqueda, estadística **y** seguimiento diario) funciona igual en modo mock.

## Arquitectura

```
app/
├── main.py                    # App FastAPI + rutas /dashboard, /favicon.ico + lifespan (init_db, scheduler)
├── static/
│   └── dashboard.html         # Dashboard de una sola página (HTML/CSS/JS plano)
├── api/
│   ├── deps.py                # Dependencias compartidas: X-Admin-Token, JWT (get_current_user), gating por plan
│   └── v1/
│       ├── endpoints/
│       │   ├── auth.py       # /auth/{register,login,me,admin/set-plan} — autenticación + planes
│       │   ├── search.py     # POST /analyze, GET /channels/search, /channels/discover* (requieren plan)
│       │   ├── statistics.py # /analytics/{benchmarks,distribution,inequality,correlation,anomalies,overview}
│       │   ├── tracking.py   # /tracking/{channels,run-daily-job} — alta/baja + historial + disparo manual del worker
│       │   └── premium.py    # /premium/channels/{id}/{projections,recommendations} — solo plan premium
│       └── router.py
├── core/
│   ├── config.py             # Settings (Pydantic BaseSettings) — incluye JWT_SECRET_KEY/JWT_EXPIRE_MINUTES
│   ├── exceptions.py         # Excepciones de dominio + handlers
│   ├── security.py           # Hashing de contraseñas (bcrypt) + JWT de sesión (pyjwt)
│   └── scheduler.py           # APScheduler: corre el worker diario 1 vez/día (hora configurable, UTC)
├── db/
│   ├── models.py               # SQLAlchemy: TrackedChannel, ChannelMetricSnapshot, User (email/plan/report_credits)
│   └── session.py              # Engine async + sesiones (SQLite por default, Postgres opcional vía DATABASE_URL)
├── models/
│   ├── domain.py              # Platform, ContentTier, ContentFormat, Plan (enums)
│   └── schemas.py             # UnifiedChannel + Request/Response schemas (Pydantic v2)
└── services/
    ├── orchestrator.py        # Ingestion Hub: despacho concurrente + resumen
    ├── tracked_channels.py     # CRUD de canales trackeados + upsert idempotente de snapshots
    ├── users.py                # CRUD de usuarios + simulación manual de cambio de plan (set_user_plan)
    ├── worker.py               # Worker diario: recorre canales activos, snapshotea, tolera errores por canal
    ├── collectors/
    │   ├── base.py             # Interfaz abstracta + generador de datos mock
    │   ├── youtube.py          # YouTube Data API v3 (search.list + channels.list batch, get_channel(s) para el worker)
    │   └── tiktok.py           # TikTok API (OAuth2 client_credentials) + modo mock
    └── analytics/
        ├── normalizer.py       # raw -> UnifiedChannel, NER/AS/PFI
        ├── descriptive.py      # mediana, IQR, percentiles, skewness, kurtosis, CV
        ├── inequality.py       # Gini, Pareto alpha, top-10% share
        ├── correlation.py      # Spearman/Pearson
        ├── anomalies.py        # Regla: seguidores>=P75 AND NER < Q1-1.5*IQR
        ├── benchmarks.py       # Métricas del medio: referencia de industria por plataforma
        ├── projections.py      # [Premium] Extrapolación lineal simple sobre snapshots semanales
        └── recommendations.py  # [Premium] Reglas: benchmark + tendencia -> recomendaciones por métrica
```

### Seguimiento (persistencia + worker)

Además del pipeline en tiempo real (`/analyze`, `/analytics/*`), el sistema
persiste una lista abierta de canales trackeados y les toma un snapshot
periódico (semanal por default):

1. **Alta manual** (dashboard, botón "+ Seguir" en la pestaña "Por canal", o
   `POST /tracking/channels`): se resuelve el canal contra la API/mock, se
   guarda en `dim_channels` (tabla `tracked_channels`) y se toma un primer
   snapshot al instante — no hace falta esperar a la corrida del scheduler
   para ver el primer dato.
2. **Worker** (`app/services/worker.py`, `run_daily_snapshot`): agrupa los
   canales activos por plataforma, los re-consulta (en lote cuando la API lo
   soporta) y guarda un snapshot por canal en `fact_channel_metrics_daily`
   (tabla `channel_metric_snapshots`, una fila por canal/día). Es idempotente
   — correrlo dos veces el mismo día actualiza en vez de duplicar — y
   tolerante a fallos por canal individual (uno que falla no tira abajo el
   resto del lote).
3. **Scheduler** (`app/core/scheduler.py`, APScheduler): por default corre el
   worker **una vez por semana** (`DAILY_JOB_DAY_OF_WEEK=mon`,
   `DAILY_JOB_HOUR_UTC=9`, `DAILY_JOB_MINUTE_UTC=0` → lunes 09:00 UTC / 06:00
   hora Argentina, que no tiene horario de verano). Para volver a una corrida
   diaria, poner `DAILY_JOB_DAY_OF_WEEK=*`; `DAILY_JOB_DAY_OF_WEEK` acepta la
   sintaxis de `APScheduler` `CronTrigger` (`mon`, `mon-fri`, `mon,wed,fri`,
   etc.). Se puede desactivar con `ENABLE_SCHEDULER=false` y disparar el job
   vos mismo (cron externo, GitHub Actions, etc.) contra
   `POST /tracking/run-daily-job`.

Por default usa SQLite (`DATABASE_URL`, un único archivo `channel_analytics.db`
en la raíz del proyecto, cero infraestructura extra). Para escalar a
producción, cambiar `DATABASE_URL` a `postgresql+asyncpg://...` (ver el stub
comentado en `docker-compose.yml`) — el resto del código no cambia, porque
toda la persistencia pasa por `get_session()`/`get_session_ctx()`.

Los endpoints de escritura de `/tracking/*` (alta, baja, disparo manual)
quedan abiertos por default (uso local/desarrollo); si configurás
`ADMIN_TOKEN`, hay que mandar el header `X-Admin-Token: <valor>` en cada uno.

## Planes de suscripción y autenticación

El sitio funciona por planes de suscripción — arquitectura completa y
funcional, **sin pasarela de pago real conectada todavía** (Mercado
Pago/Stripe quedan pendientes; este es un proyecto universitario y la
consigna fue dejar lista la arquitectura de niveles, no el cobro real).

> **Importante — `REQUIRE_SUBSCRIPTION` (default `False`)**: por default
> la exigencia de plan está **desactivada**: podés registrarte, loguearte
> y simular planes desde la pestaña "Cuenta" del dashboard, pero
> `/analyze`, `/channels/*` y `/analytics/*` (excepto `/benchmarks`)
> funcionan igual **sin login**, como antes de agregar suscripciones — no
> hace falta crear una cuenta para usar el dashboard en el día a día.
> Poner `REQUIRE_SUBSCRIPTION=true` en `.env` (y reiniciar el server) para
> que esos endpoints exijan de verdad sesión + plan activo (p. ej. para
> una demo o entrega formal de este sistema de planes).

| Plan | Acceso | Cómo funciona |
|---|---|---|
| `free` | Sin acceso a "toda la estadística" (solo `/analytics/benchmarks`, referencia estática, público) | Plan por defecto al registrarse |
| `unica` | Acceso puntual: consume 1 "crédito de reporte" por cada endpoint de estadística consultado | No es continuo — cada `report_credits` habilita una sola consulta |
| `mensual` | Acceso continuo a **toda la estadística** del sitio: métricas nacionales e internacionales, incluidas las que no se miden en Argentina/Latinoamérica | Continuo mientras `plan_active_until` no venza |
| `premium` | Todo lo de `mensual` **+ proyecciones de tendencia + recomendaciones de política general** por métrica (`/premium/*`) | Continuo mientras `plan_active_until` no venza |

**Autenticación** (armada desde cero, sin proveedor externo): `POST
/auth/register` / `POST /auth/login` devuelven un JWT de sesión
(`app/core/security.py`, firmado con `JWT_SECRET_KEY` — **cambiar este
valor en `.env` para cualquier uso más allá de desarrollo local**);
mandarlo como `Authorization: Bearer <token>` en los endpoints que lo
requieran. `GET /auth/me` devuelve el plan vigente y los accesos
calculados (`has_full_stats_access`, `has_premium_access`).

**Simular un cambio de plan** (sin cobro real): `POST
/auth/admin/set-plan` (protegido con `X-Admin-Token`, igual que
`/tracking/*`) fija a mano el plan de cualquier usuario ya registrado —
`{"email": "...", "plan": "premium", "active_days": 30}` para
`mensual`/`premium`, o `{"email": "...", "plan": "unica",
"add_report_credits": 3}` para sumar créditos de reporte. Es también la
pestaña **"Cuenta"** del dashboard (login/registro + este mismo
formulario). El día que se conecte un procesador de pagos real, alcanza
con que su webhook llame a `set_user_plan()` en
`app/services/users.py` — el resto del sistema (gating de endpoints, JWT,
dashboard) no necesita cambios.

**Proyecciones** (`GET /premium/channels/{id}/projections`): extrapolación
lineal simple (mínimos cuadrados, `numpy.polyfit`, sin IA) sobre el
histórico de snapshots semanales de un canal trackeado — mejora sola a
medida que el worker semanal acumula más datos (necesita al menos 3
snapshots). **Recomendaciones** (`GET
/premium/channels/{id}/recommendations`): motor de reglas fijas (no IA
generativa) que traduce el benchmark de industria (`/analytics/benchmarks`)
y la tendencia de seguidores en sugerencias accionables por métrica. Ver
`docs/manual_metricas_es.md` / `manual_metricas_en.md` para el detalle
completo de ambas.

## Límites a tener en cuenta

- **YouTube**: `search.list` cuesta 100 unidades/llamada (máx. ~100
  búsquedas/día con la cuota gratuita); `channels.list` en lote de 50 IDs
  cuesta 1 unidad. El colector ya usa esta estrategia de dos pasos para
  minimizar consumo.
- **TikTok**: la API oficial no siempre expone búsqueda libre por keyword
  según el nivel de acceso aprobado; por eso el colector prioriza el modo
  mock salvo que configures credenciales con el producto correcto
  habilitado.
- **`/channels/discover*`**: cada combinación categoría+región+página de
  `videos.list` cuesta 1 unidad — con los defaults (15 categorías × 4
  regiones × hasta 2 páginas) una corrida completa consume unos pocos
  cientos de unidades, lejos de las 10.000/día. `DISCOVER_REGION_CODES` y
  `DISCOVER_PAGES_PER_REGION_CATEGORY` (en `.env`) controlan cuánta
  variedad se junta a costa de más llamadas y más tiempo de respuesta.
- Ambos colectores son extensibles: agregar una plataforma nueva implica
  crear un `Collector` + un `normalize_*` y sumarlo a `orchestrator.py`.

## Extender a otras plataformas

Para agregar Instagram, Twitch, Telegram, etc.:

1. Crear `app/services/collectors/<plataforma>.py` heredando de `BaseCollector`.
2. Agregar el enum en `app/models/domain.py::Platform`.
3. Escribir `normalize_<plataforma>_channel()` en `normalizer.py`.
4. Registrar el collector en `SUPPORTED_PLATFORMS` y `_COLLECTORS` de `orchestrator.py`.

El motor estadístico (`descriptive.py`, `inequality.py`, `correlation.py`,
`anomalies.py`) no necesita ningún cambio: opera sobre `UnifiedChannel`,
no sobre estructuras específicas de plataforma.
