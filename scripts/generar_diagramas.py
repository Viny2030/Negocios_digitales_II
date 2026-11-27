"""
Genera los grafos técnicos detallados (Mermaid.js) del funcionamiento del sitio:

    app/static/diagramas.html        -> /guia/diagramas
    app/static/diagramas_en.html     -> /guia/en/diagramas
    docs/arquitectura_grafos.md      -> mismo contenido, se ve renderizado en GitHub
    docs/arquitectura_grafos_en.md

Igual que `scripts/generar_guia.py`: los dos idiomas tienen los mismos diagramas, en el
mismo orden y con la misma cantidad de líneas (se traducen línea por línea), así un grafo
no puede cambiar en un idioma y quedar viejo en el otro. Después de editar este archivo:

    python -m scripts.generar_diagramas

tests/test_diagramas.py falla si los archivos guardados no coinciden con lo que genera
este script, o si un idioma tiene un diagrama que el otro no.

Mermaid se carga desde jsDelivr con versión fija y hash SRI: si el archivo del CDN
cambiara, el navegador se niega a ejecutarlo. Sin conexión, cada diagrama queda visible
como texto (su código fuente), que igual se puede leer.
"""

from __future__ import annotations

from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = ROOT / "app" / "static"
DOCS_DIR = ROOT / "docs"

MERMAID_VERSION = "12.3.0"
MERMAID_URL = (
    f"https://cdn.jsdelivr.net/npm/mermaid@{MERMAID_VERSION}/dist/mermaid.min.js"
)
MERMAID_SRI = "sha384-HHW54r639fK42Ip0coGF3mz8oSiGn0eEoWNTLs75X7H63pLSDBa0Tqs0RwGmLlXE"

# Orden de aparición. Cada idioma define (título, introducción, fuente Mermaid) por clave.
DIAGRAM_KEYS = (
    "arquitectura",
    "ingesta",
    "descubrimiento_worker",
    "senales",
    "puntaje",
    "desigualdad",
    "datos",
    "despliegue",
)

# ─────────────────────────────────────────────────────────────────────────────
# Español
# ─────────────────────────────────────────────────────────────────────────────

ES_ARQUITECTURA = """\
flowchart TB
  subgraph CLI["Clientes"]
    DASH["GET /dashboard<br/>app/static/dashboard.html"]
    GUIA["GET /guia · /guia/en<br/>/guia/diagramas"]
    SWAG["GET /docs · /redoc<br/>Swagger y ReDoc"]
    GHA["GitHub Actions<br/>ci.yml · daily-job.yml"]
  end
  subgraph APP["app/main.py · FastAPI con lifespan"]
    LIFE["lifespan: production_safety_warnings<br/>init_db · start_scheduler"]
    MW["CORSMiddleware<br/>consume_report_credit_on_success"]
    DEPS["app/api/deps.py<br/>verify_admin_token · get_current_user<br/>require_full_access · require_premium"]
    RL["app/core/rate_limit.py<br/>limit_auth_attempts · 60 s por IP"]
    subgraph RUT["app/api/v1/router.py · prefijo /api/v1"]
      AUTH["auth.py<br/>/auth/register · login · me · admin/set-plan"]
      SEARCH["search.py<br/>/analyze · /channels/search · discover"]
      STATS["statistics.py<br/>/analytics/benchmarks · distribution<br/>inequality · correlation · anomalies<br/>audience-integrity · overview"]
      TRACK["tracking.py<br/>/tracking/channels · history<br/>audience-integrity · run-daily-job"]
      CAT["catalog.py<br/>/catalog/types · summary"]
      PREM["premium.py<br/>/premium/channels/id/projections<br/>recommendations"]
    end
  end
  subgraph SRV["app/services"]
    ORCH["orchestrator.py · Ingestion Hub<br/>fetch_unified_channels · discover_unified_channels<br/>enrich_engagement"]
    COLL["collectors/base.py · youtube.py · tiktok.py<br/>BaseCollector · modo mock determinístico"]
    NORM["analytics/normalizer.py<br/>RawChannelData a UnifiedChannel · NER"]
    ANA["analytics/descriptive · inequality<br/>correlation · anomalies · benchmarks"]
    AUD["analytics/audience_integrity.py<br/>assess_channel · 7 familias de señales"]
    PRS["analytics/projections · recommendations"]
    TCS["tracked_channels.py<br/>CRUD · upsert de snapshots · catálogo"]
    USR["users.py<br/>create_user · set_user_plan"]
    WRK["worker.py · run_daily_snapshot"]
  end
  SCHED["app/core/scheduler.py · AsyncIOScheduler UTC<br/>daily_channel_snapshot · auto_discovery"]
  SEC["app/core/security.py<br/>bcrypt · PyJWT HS256"]
  subgraph PER["app/db · SQLAlchemy 2 async"]
    SESS["session.py · engine · init_db<br/>get_session · migraciones livianas"]
    MOD["models.py · ChannelType · TrackedChannel<br/>ChannelMetricSnapshot · User"]
    SQLITE[("SQLite · channel_analytics.db<br/>desarrollo local")]
    PG[("PostgreSQL · producción Railway")]
  end
  YT(["YouTube Data API v3 · 10.000 u/día"])
  TT(["TikTok Research API"])
  CLI --> MW --> RUT
  LIFE --> SESS
  LIFE --> SCHED
  RUT -.-> DEPS
  AUTH -.-> RL
  AUTH --> USR
  AUTH --> SEC
  DEPS --> SEC
  SEARCH --> ORCH
  STATS --> ORCH
  STATS --> ANA
  STATS --> AUD
  TRACK --> TCS
  TRACK --> WRK
  TRACK --> AUD
  CAT --> TCS
  PREM --> PRS
  PREM --> TCS
  ORCH --> COLL
  ORCH --> NORM
  COLL --> YT
  COLL --> TT
  SCHED --> WRK
  SCHED --> TCS
  WRK --> COLL
  WRK --> TCS
  TCS --> SESS
  USR --> SESS
  SESS --> MOD
  MOD --> SQLITE
  MOD --> PG"""

ES_INGESTA = """\
sequenceDiagram
  autonumber
  actor U as Dashboard o cliente
  participant API as search.py o statistics.py
  participant O as orchestrator.py
  participant Y as YouTubeCollector
  participant G as YouTube Data API v3
  participant N as normalizer.py
  U->>API: GET /channels/search o /analytics/... con query, platform y limit
  API->>O: fetch_unified_channels(query, platforms, limit)
  O->>O: resolve_platforms() y platform_available()
  alt Sin YOUTUBE_API_KEY y con modo mock
    O->>Y: search() devuelve _mock_results(), semilla por query
  else Con credenciales reales
    O->>Y: search(query, limit)
    Y->>G: search.list type=channel · 100 unidades
    G-->>Y: IDs de canal
    Y->>G: channels.list snippet,statistics · lotes de 50 · 1 u por lote
    Y->>G: playlistItems.list de UU... · 1 u por canal
    Y->>G: videos.list statistics · lotes de 50 · 1 u por lote
    Note over Y,G: _recent_engagement con N = YOUTUBE_ENGAGEMENT_RECENT_VIDEOS = 10<br/>cuesta cerca de 1,2 u por canal
    opt Cuota agotada o error a mitad de camino
      G-->>Y: 403 quotaExceeded
      Y-->>O: búsqueda: QuotaExceededError · muestreo: canal sin _recent_engagement
    end
  end
  Y-->>O: lista de RawChannelData
  O->>N: normalize_channels(raw, platform)
  N-->>O: UnifiedChannel con NER, tier, recent_video_views e is_mock
  O-->>API: channels_by_platform
  API-->>U: JSON con meta, benchmark y avisos de datos simulados"""

ES_DESCUBRIMIENTO = """\
flowchart TB
  subgraph DESC["Descubrimiento sin palabra clave · GET /channels/discover y /discover/by-category"]
    D1["YouTubeCollector.discover()<br/>videos.list chart=mostPopular · 1 u por página"]
    D2["15 categorías × 4 regiones AR, MX, ES, US<br/>× DISCOVER_PAGES_PER_REGION_CATEGORY = 2<br/>como máximo 120 u por corrida"]
    D3["asyncio.Semaphore(HTTP_MAX_CONCURRENT_REQUESTS = 10)<br/>se corta al primer quotaExceeded y devuelve lo juntado"]
    D4["Deduplicar channelId · channels.list en lotes de 50"]
    D5["Ordenar por sort_by y recortar a limit"]
    D6["enrich_engagement() solo sobre el resultado final<br/>la cuota extra es proporcional a lo devuelto"]
    D1 --> D2 --> D3 --> D4 --> D5 --> D6
  end
  subgraph ALTA["Alta al seguimiento"]
    A1["POST /tracking/channels<br/>get_channel(identifier) y primer snapshot"]
    A2["POST /tracking/discover-and-track<br/>round-robin entre categorías · tipo de canal automático"]
  end
  subgraph JOB["Worker diario · app/services/worker.py"]
    W0["scheduler.py · CronTrigger UTC<br/>DAILY_JOB_HOUR_UTC = 9 · todos los días"]
    W1["list_tracked(active_only=True)<br/>agrupar por plataforma"]
    W2["get_channels_batch(): IDs UC en lote de 50 · 1 u<br/>handles con forHandle, uno por llamada"]
    W3["normalize_channels() y _match_tracked()<br/>por native_id y, si no, por handle"]
    W4["upsert del snapshot del día<br/>UNIQUE tracked_channel_id + snapshot_date"]
    W5["DailyJobResult: evaluados, creados,<br/>actualizados y errores por canal"]
    W0 --> W1 --> W2 --> W3 --> W4 --> W5
  end
  subgraph LECT["Lectura sin gastar cuota"]
    L1["GET /tracking/channels/id/history"]
    L2["GET /tracking/channels/id/audience-integrity<br/>channel_from_snapshot() y assess_channel(snapshots)"]
  end
  NOTA["No hay caché HTTP de respuestas: /analytics/* recalcula en cada llamada.<br/>La memoria persistente del sistema es channel_metric_snapshots."]
  D6 --> A2
  A1 --> W1
  A2 --> W1
  W4 --> L1
  W4 --> L2
  L2 -.- NOTA"""

ES_SENALES = """\
flowchart TD
  IN["assess_channel(channel, cohort_flagged, snapshots)<br/>app/services/analytics/audience_integrity.py"] --> CHK["check(disponible, nombre, cálculo)<br/>si la condición no se cumple: signals_unavailable<br/>no suma puntos y nunca cuenta como normal"]
  CHK --> C1{"S1 · ¿followers ≥ 1.000<br/>y total_posts ≥ 10?"}
  CHK --> C2{"S2 · ¿ner_available()?<br/>NER 0.0 sin muestreo = no medido"}
  CHK --> C3{"S3 · ¿followers ≥ 10.000, 3 o más videos<br/>y vistas por seguidor menos de 50?"}
  CHK --> C4{"S4 · ¿hay vistas recientes<br/>y me gusta o comentarios mayores a 0?"}
  CHK --> C5{"S5 · ¿5 o más videos recientes?"}
  CHK --> C6{"S6 · ¿hay cohorte de 4 o más canales?"}
  CHK --> C7{"S7 · ¿4 o más snapshots?"}
  C1 -- sí --> F1["r = total_views / followers<br/>r menor que 1: 35 pts · r menor que 3: 20 pts<br/>few_views_for_followers"]
  C2 -- sí --> F2["NER = interacciones / vistas × 100<br/>menos de 10 % del piso: 30 pts · menos de 25 %: 15 pts<br/>YouTube piso 1,5 %: umbrales 0,15 % y 0,375 %<br/>low_engagement"]
  C3 -- sí --> F3["s = mediana(vistas recientes) / followers × 100<br/>s menor que 0,5 %: 25 pts · s menor que 1,5 %: 12 pts<br/>few_recent_views"]
  C4 -- sí --> F4["likes / vistas recientes menor que 0,1 %: 20 pts · views_without_likes<br/>comments / likes menor que 0,2 %: 15 pts · likes_without_comments<br/>un 0 no cuenta: YouTube permite ocultar y desactivar"]
  C5 -- sí --> F5["máx ≥ 20 × mediana del resto: 10 pts<br/>isolated_view_spike · pesa poco a propósito"]
  C6 -- sí --> F6["detect_anomalies(): followers ≥ P75<br/>y NER menor que Q1 − 1,5 × IQR · 15 pts<br/>cohort_outlier · solo canales con NER medido"]
  C7 -- sí --> F7["cambio % entre fotos, normalizado por día<br/>cambios menores a 5 % se ignoran por redondeo de YouTube<br/>salto muy por encima del ritmo habitual: 30 pts<br/>40 pts si las vistas no acompañan<br/>caída de 5 % o más: 25 pts"]
  F1 --> SUM["signals · evaluated"]
  F2 --> SUM
  F3 --> SUM
  F4 --> SUM
  F5 --> SUM
  F6 --> SUM
  F7 --> SUM
  SUM --> NEXT["ver diagrama: puntaje y nivel"]"""

ES_PUNTAJE = """\
flowchart TD
  A["signals: lista de AudienceSignal<br/>evaluated: señales calculables"] --> B["score = min(Σ points, 100)"]
  B --> C{"¿se disparó una sola señal?"}
  C -- sí --> D["score = min(score, SINGLE_SIGNAL_CAP = 49)<br/>un único número nunca supera leve"]
  C -- no --> E["score sin cambios"]
  D --> L{"_level(score, evaluated, followers)"}
  E --> L
  L -- "evaluated menor que 2 o followers menor que 1.000" --> DI["datos_insuficientes"]
  L -- "score menor que 25" --> SS["sin_senales"]
  L -- "25 a 49" --> LV["leve"]
  L -- "50 a 74" --> RV["revisar"]
  L -- "75 o más" --> AL["alta"]
  DI --> OUT["AudienceAssessment<br/>score · level · signals con su detalle<br/>signals_unavailable · is_mock · DISCLAIMER"]
  SS --> OUT
  LV --> OUT
  RV --> OUT
  AL --> OUT
  OUT --> P["Postura del sistema: mide cuánto conviene revisar un canal.<br/>No detecta bots, no prueba fraude y no acusa a nadie."]"""

ES_DESIGUALDAD = """\
flowchart LR
  Q["GET /analytics/inequality<br/>GET /analytics/overview"] --> F["fetch_unified_channels()<br/>platform=all solo usa plataformas disponibles"]
  F --> V["x = followers de cada canal"]
  V --> S["ordenar de menor a mayor · clip en 0<br/>n canales · total T = Σ x"]
  S --> G["gini_coefficient()<br/>G = (2 × Σ i·xᵢ − (n + 1) × T) / (n × T)<br/>0 igualdad · 1 concentración total"]
  S --> L["Curva de Lorenz<br/>pᵢ = i / n · Lᵢ = suma acumulada de xᵢ / T"]
  L --> GL["G = 1 − 2 × área bajo Lorenz por trapecios<br/>misma cifra que gini_coefficient()"]
  V --> PA["pareto_alpha()<br/>α = 1 + n / Σ ln(xᵢ / x_min)<br/>None sin variación suficiente"]
  V --> TD["top_decile_share()<br/>suma del top ⌈0,1 × n⌉ / T"]
  G --> IS["InequalityStats por plataforma"]
  PA --> IS
  TD --> IS
  QC["GET /analytics/correlation<br/>una sola plataforma"] --> PR["pares: total_posts con NER<br/>followers con NER"]
  PR --> CO["correlate(): scipy spearmanr y pearsonr<br/>NaN pasa a 0.0"]
  CO --> IN["_interpret(rho): fuerza y dirección<br/>Spearman es el coeficiente principal"]
  IN --> CP["CorrelationPair"]"""

ES_DATOS = """\
erDiagram
  CHANNEL_TYPES ||--o{ TRACKED_CHANNELS : clasifica
  TRACKED_CHANNELS ||--o{ CHANNEL_METRIC_SNAPSHOTS : "una foto por día"
  CHANNEL_TYPES {
    int id PK
    string name UK "120"
    string slug UK "140"
    string description "500, opcional"
    bool is_custom "false si es categoría de YouTube"
    datetime created_at
  }
  TRACKED_CHANNELS {
    int id PK
    string platform "20 · youtube o tiktok"
    string native_id "200 · UNIQUE con platform"
    string handle "200"
    string label "200"
    string name "300"
    string url "500"
    bool active "baja lógica"
    int channel_type_id FK "nullable"
  }
  CHANNEL_METRIC_SNAPSHOTS {
    int id PK
    int tracked_channel_id FK
    date snapshot_date "UNIQUE con tracked_channel_id"
    bigint followers
    bigint total_views
    bigint total_posts
    bigint raw_interactions
    float normalized_er
    string tier "20"
    datetime fetched_at
  }
  USERS {
    int id PK
    string email UK "255"
    string hashed_password "bcrypt"
    string plan "free, unica, mensual, premium"
    datetime plan_active_until
    int report_credits
    datetime unica_access_until
    bool is_admin
  }"""

ES_DESPLIEGUE = """\
flowchart LR
  DEV["PyCharm en Windows<br/>.venv · SQLite · modo mock"] --> PUSH["push a feature/audiencia-inflada"]
  PUSH --> CI["ci.yml: ruff check y pytest -q<br/>Python 3.11 · sin credenciales"]
  CI -- verde --> PR["PR número 1 hacia main"]
  PR --> MRG["merge a main"]
  MRG --> RW{"Railway: ¿Wait for CI activo<br/>y variables cargadas?"}
  RW -- no --> STOP["no desplegar todavía<br/>ADMIN_TOKEN · JWT_SECRET_KEY · YOUTUBE_API_KEY<br/>DATABASE_URL · CORS_ALLOWED_ORIGINS"]
  RW -- sí --> BLD["build con Dockerfile<br/>uvicorn --proxy-headers en $PORT"]
  BLD --> LS["lifespan: si APP_ENV=production y falta un secreto<br/>la app no arranca"]
  LS --> HC["healthcheck GET /<br/>1 réplica: el scheduler vive en el proceso"]
  HC --> PGB[("PostgreSQL de Railway<br/>respaldo externo con pg_dump")]"""

# ─────────────────────────────────────────────────────────────────────────────
# English (line-by-line translation of the Spanish sources)
# ─────────────────────────────────────────────────────────────────────────────

EN_ARQUITECTURA = """\
flowchart TB
  subgraph CLI["Clients"]
    DASH["GET /dashboard<br/>app/static/dashboard.html"]
    GUIA["GET /guia · /guia/en<br/>/guia/en/diagramas"]
    SWAG["GET /docs · /redoc<br/>Swagger and ReDoc"]
    GHA["GitHub Actions<br/>ci.yml · daily-job.yml"]
  end
  subgraph APP["app/main.py · FastAPI with lifespan"]
    LIFE["lifespan: production_safety_warnings<br/>init_db · start_scheduler"]
    MW["CORSMiddleware<br/>consume_report_credit_on_success"]
    DEPS["app/api/deps.py<br/>verify_admin_token · get_current_user<br/>require_full_access · require_premium"]
    RL["app/core/rate_limit.py<br/>limit_auth_attempts · 60 s per IP"]
    subgraph RUT["app/api/v1/router.py · prefix /api/v1"]
      AUTH["auth.py<br/>/auth/register · login · me · admin/set-plan"]
      SEARCH["search.py<br/>/analyze · /channels/search · discover"]
      STATS["statistics.py<br/>/analytics/benchmarks · distribution<br/>inequality · correlation · anomalies<br/>audience-integrity · overview"]
      TRACK["tracking.py<br/>/tracking/channels · history<br/>audience-integrity · run-daily-job"]
      CAT["catalog.py<br/>/catalog/types · summary"]
      PREM["premium.py<br/>/premium/channels/id/projections<br/>recommendations"]
    end
  end
  subgraph SRV["app/services"]
    ORCH["orchestrator.py · Ingestion Hub<br/>fetch_unified_channels · discover_unified_channels<br/>enrich_engagement"]
    COLL["collectors/base.py · youtube.py · tiktok.py<br/>BaseCollector · deterministic mock mode"]
    NORM["analytics/normalizer.py<br/>RawChannelData to UnifiedChannel · NER"]
    ANA["analytics/descriptive · inequality<br/>correlation · anomalies · benchmarks"]
    AUD["analytics/audience_integrity.py<br/>assess_channel · 7 signal families"]
    PRS["analytics/projections · recommendations"]
    TCS["tracked_channels.py<br/>CRUD · snapshot upsert · catalog"]
    USR["users.py<br/>create_user · set_user_plan"]
    WRK["worker.py · run_daily_snapshot"]
  end
  SCHED["app/core/scheduler.py · AsyncIOScheduler UTC<br/>daily_channel_snapshot · auto_discovery"]
  SEC["app/core/security.py<br/>bcrypt · PyJWT HS256"]
  subgraph PER["app/db · SQLAlchemy 2 async"]
    SESS["session.py · engine · init_db<br/>get_session · lightweight migrations"]
    MOD["models.py · ChannelType · TrackedChannel<br/>ChannelMetricSnapshot · User"]
    SQLITE[("SQLite · channel_analytics.db<br/>local development")]
    PG[("PostgreSQL · Railway production")]
  end
  YT(["YouTube Data API v3 · 10,000 u/day"])
  TT(["TikTok Research API"])
  CLI --> MW --> RUT
  LIFE --> SESS
  LIFE --> SCHED
  RUT -.-> DEPS
  AUTH -.-> RL
  AUTH --> USR
  AUTH --> SEC
  DEPS --> SEC
  SEARCH --> ORCH
  STATS --> ORCH
  STATS --> ANA
  STATS --> AUD
  TRACK --> TCS
  TRACK --> WRK
  TRACK --> AUD
  CAT --> TCS
  PREM --> PRS
  PREM --> TCS
  ORCH --> COLL
  ORCH --> NORM
  COLL --> YT
  COLL --> TT
  SCHED --> WRK
  SCHED --> TCS
  WRK --> COLL
  WRK --> TCS
  TCS --> SESS
  USR --> SESS
  SESS --> MOD
  MOD --> SQLITE
  MOD --> PG"""

EN_INGESTA = """\
sequenceDiagram
  autonumber
  actor U as Dashboard or client
  participant API as search.py or statistics.py
  participant O as orchestrator.py
  participant Y as YouTubeCollector
  participant G as YouTube Data API v3
  participant N as normalizer.py
  U->>API: GET /channels/search or /analytics/... with query, platform and limit
  API->>O: fetch_unified_channels(query, platforms, limit)
  O->>O: resolve_platforms() and platform_available()
  alt No YOUTUBE_API_KEY and mock mode on
    O->>Y: search() returns _mock_results(), seeded by query
  else Real credentials
    O->>Y: search(query, limit)
    Y->>G: search.list type=channel · 100 units
    G-->>Y: channel IDs
    Y->>G: channels.list snippet,statistics · batches of 50 · 1 u per batch
    Y->>G: playlistItems.list of UU... · 1 u per channel
    Y->>G: videos.list statistics · batches of 50 · 1 u per batch
    Note over Y,G: _recent_engagement with N = YOUTUBE_ENGAGEMENT_RECENT_VIDEOS = 10<br/>costs about 1.2 u per channel
    opt Quota exhausted or error halfway
      G-->>Y: 403 quotaExceeded
      Y-->>O: search: QuotaExceededError · sampling: channel without _recent_engagement
    end
  end
  Y-->>O: list of RawChannelData
  O->>N: normalize_channels(raw, platform)
  N-->>O: UnifiedChannel with NER, tier, recent_video_views and is_mock
  O-->>API: channels_by_platform
  API-->>U: JSON with meta, benchmark and simulated-data flags"""

EN_DESCUBRIMIENTO = """\
flowchart TB
  subgraph DESC["Keyword-free discovery · GET /channels/discover and /discover/by-category"]
    D1["YouTubeCollector.discover()<br/>videos.list chart=mostPopular · 1 u per page"]
    D2["15 categories × 4 regions AR, MX, ES, US<br/>× DISCOVER_PAGES_PER_REGION_CATEGORY = 2<br/>at most 120 u per run"]
    D3["asyncio.Semaphore(HTTP_MAX_CONCURRENT_REQUESTS = 10)<br/>stops at the first quotaExceeded and returns what it has"]
    D4["Deduplicate channelId · channels.list in batches of 50"]
    D5["Sort by sort_by and cut to limit"]
    D6["enrich_engagement() only on the final result<br/>extra quota is proportional to what is returned"]
    D1 --> D2 --> D3 --> D4 --> D5 --> D6
  end
  subgraph ALTA["Adding to tracking"]
    A1["POST /tracking/channels<br/>get_channel(identifier) and first snapshot"]
    A2["POST /tracking/discover-and-track<br/>round-robin across categories · automatic channel type"]
  end
  subgraph JOB["Daily worker · app/services/worker.py"]
    W0["scheduler.py · CronTrigger UTC<br/>DAILY_JOB_HOUR_UTC = 9 · every day"]
    W1["list_tracked(active_only=True)<br/>group by platform"]
    W2["get_channels_batch(): UC IDs in batches of 50 · 1 u<br/>handles via forHandle, one per call"]
    W3["normalize_channels() and _match_tracked()<br/>by native_id, falling back to handle"]
    W4["upsert today's snapshot<br/>UNIQUE tracked_channel_id + snapshot_date"]
    W5["DailyJobResult: evaluated, created,<br/>updated and per-channel errors"]
    W0 --> W1 --> W2 --> W3 --> W4 --> W5
  end
  subgraph LECT["Reads that spend no quota"]
    L1["GET /tracking/channels/id/history"]
    L2["GET /tracking/channels/id/audience-integrity<br/>channel_from_snapshot() and assess_channel(snapshots)"]
  end
  NOTA["There is no HTTP response cache: /analytics/* recomputes on every call.<br/>The system's persistent memory is channel_metric_snapshots."]
  D6 --> A2
  A1 --> W1
  A2 --> W1
  W4 --> L1
  W4 --> L2
  L2 -.- NOTA"""

EN_SENALES = """\
flowchart TD
  IN["assess_channel(channel, cohort_flagged, snapshots)<br/>app/services/analytics/audience_integrity.py"] --> CHK["check(available, name, compute)<br/>if the condition fails: signals_unavailable<br/>adds no points and never counts as normal"]
  CHK --> C1{"S1 · followers ≥ 1,000<br/>and total_posts ≥ 10?"}
  CHK --> C2{"S2 · ner_available()?<br/>NER 0.0 without sampling = not measured"}
  CHK --> C3{"S3 · followers ≥ 10,000, 3 or more videos<br/>and fewer than 50 views per follower?"}
  CHK --> C4{"S4 · recent views present<br/>and likes or comments above 0?"}
  CHK --> C5{"S5 · 5 or more recent videos?"}
  CHK --> C6{"S6 · cohort of 4 or more channels?"}
  CHK --> C7{"S7 · 4 or more snapshots?"}
  C1 -- yes --> F1["r = total_views / followers<br/>r below 1: 35 pts · r below 3: 20 pts<br/>few_views_for_followers"]
  C2 -- yes --> F2["NER = interactions / views × 100<br/>below 10 % of the floor: 30 pts · below 25 %: 15 pts<br/>YouTube floor 1.5 %: thresholds 0.15 % and 0.375 %<br/>low_engagement"]
  C3 -- yes --> F3["s = median(recent views) / followers × 100<br/>s below 0.5 %: 25 pts · s below 1.5 %: 12 pts<br/>few_recent_views"]
  C4 -- yes --> F4["likes / recent views below 0.1 %: 20 pts · views_without_likes<br/>comments / likes below 0.2 %: 15 pts · likes_without_comments<br/>a 0 does not count: YouTube lets creators hide and disable"]
  C5 -- yes --> F5["max ≥ 20 × median of the rest: 10 pts<br/>isolated_view_spike · deliberately low weight"]
  C6 -- yes --> F6["detect_anomalies(): followers ≥ P75<br/>and NER below Q1 − 1.5 × IQR · 15 pts<br/>cohort_outlier · only channels with measured NER"]
  C7 -- yes --> F7["% change between snapshots, normalised per day<br/>changes under 5 % ignored because YouTube rounds counts<br/>jump far above the usual pace: 30 pts<br/>40 pts if views do not follow<br/>drop of 5 % or more: 25 pts"]
  F1 --> SUM["signals · evaluated"]
  F2 --> SUM
  F3 --> SUM
  F4 --> SUM
  F5 --> SUM
  F6 --> SUM
  F7 --> SUM
  SUM --> NEXT["see diagram: score and level"]"""

EN_PUNTAJE = """\
flowchart TD
  A["signals: list of AudienceSignal<br/>evaluated: computable signals"] --> B["score = min(Σ points, 100)"]
  B --> C{"did only one signal fire?"}
  C -- yes --> D["score = min(score, SINGLE_SIGNAL_CAP = 49)<br/>a single number never goes beyond mild"]
  C -- no --> E["score unchanged"]
  D --> L{"_level(score, evaluated, followers)"}
  E --> L
  L -- "evaluated below 2 or followers below 1,000" --> DI["datos_insuficientes"]
  L -- "score below 25" --> SS["sin_senales"]
  L -- "25 to 49" --> LV["leve"]
  L -- "50 to 74" --> RV["revisar"]
  L -- "75 or more" --> AL["alta"]
  DI --> OUT["AudienceAssessment<br/>score · level · signals with their detail<br/>signals_unavailable · is_mock · DISCLAIMER"]
  SS --> OUT
  LV --> OUT
  RV --> OUT
  AL --> OUT
  OUT --> P["System stance: measures how much a channel is worth reviewing.<br/>It does not detect bots, prove fraud or accuse anyone."]"""

EN_DESIGUALDAD = """\
flowchart LR
  Q["GET /analytics/inequality<br/>GET /analytics/overview"] --> F["fetch_unified_channels()<br/>platform=all only uses available platforms"]
  F --> V["x = followers of each channel"]
  V --> S["sort ascending · clip at 0<br/>n channels · total T = Σ x"]
  S --> G["gini_coefficient()<br/>G = (2 × Σ i·xᵢ − (n + 1) × T) / (n × T)<br/>0 equality · 1 total concentration"]
  S --> L["Lorenz curve<br/>pᵢ = i / n · Lᵢ = cumulative sum of xᵢ / T"]
  L --> GL["G = 1 − 2 × area under Lorenz by trapezoids<br/>same figure as gini_coefficient()"]
  V --> PA["pareto_alpha()<br/>α = 1 + n / Σ ln(xᵢ / x_min)<br/>None without enough variation"]
  V --> TD["top_decile_share()<br/>sum of the top ⌈0.1 × n⌉ / T"]
  G --> IS["InequalityStats per platform"]
  PA --> IS
  TD --> IS
  QC["GET /analytics/correlation<br/>single platform"] --> PR["pairs: total_posts with NER<br/>followers with NER"]
  PR --> CO["correlate(): scipy spearmanr and pearsonr<br/>NaN becomes 0.0"]
  CO --> IN["_interpret(rho): strength and direction<br/>Spearman is the primary coefficient"]
  IN --> CP["CorrelationPair"]"""

EN_DATOS = """\
erDiagram
  CHANNEL_TYPES ||--o{ TRACKED_CHANNELS : classifies
  TRACKED_CHANNELS ||--o{ CHANNEL_METRIC_SNAPSHOTS : "one snapshot per day"
  CHANNEL_TYPES {
    int id PK
    string name UK "120"
    string slug UK "140"
    string description "500, optional"
    bool is_custom "false for YouTube categories"
    datetime created_at
  }
  TRACKED_CHANNELS {
    int id PK
    string platform "20 · youtube or tiktok"
    string native_id "200 · UNIQUE with platform"
    string handle "200"
    string label "200"
    string name "300"
    string url "500"
    bool active "soft delete"
    int channel_type_id FK "nullable"
  }
  CHANNEL_METRIC_SNAPSHOTS {
    int id PK
    int tracked_channel_id FK
    date snapshot_date "UNIQUE with tracked_channel_id"
    bigint followers
    bigint total_views
    bigint total_posts
    bigint raw_interactions
    float normalized_er
    string tier "20"
    datetime fetched_at
  }
  USERS {
    int id PK
    string email UK "255"
    string hashed_password "bcrypt"
    string plan "free, unica, mensual, premium"
    datetime plan_active_until
    int report_credits
    datetime unica_access_until
    bool is_admin
  }"""

EN_DESPLIEGUE = """\
flowchart LR
  DEV["PyCharm on Windows<br/>.venv · SQLite · mock mode"] --> PUSH["push to feature/audiencia-inflada"]
  PUSH --> CI["ci.yml: ruff check and pytest -q<br/>Python 3.11 · no credentials"]
  CI -- green --> PR["PR number 1 into main"]
  PR --> MRG["merge into main"]
  MRG --> RW{"Railway: Wait for CI on<br/>and variables set?"}
  RW -- no --> STOP["do not deploy yet<br/>ADMIN_TOKEN · JWT_SECRET_KEY · YOUTUBE_API_KEY<br/>DATABASE_URL · CORS_ALLOWED_ORIGINS"]
  RW -- yes --> BLD["Dockerfile build<br/>uvicorn --proxy-headers on $PORT"]
  BLD --> LS["lifespan: with APP_ENV=production and a missing secret<br/>the app refuses to start"]
  LS --> HC["healthcheck GET /<br/>1 replica: the scheduler lives in the process"]
  HC --> PGB[("Railway PostgreSQL<br/>external backup with pg_dump")]"""

PAGES = {
    "es": {
        "file": "diagramas.html",
        "doc": "arquitectura_grafos.md",
        "html_lang": "es",
        "title": "Channel Analytics · Grafos técnicos del sistema",
        "heading": "Grafos técnicos del sistema",
        "lead": (
            "Cómo funciona Channel Analytics por dentro: arquitectura, ingesta desde YouTube, "
            "motor de señales de audiencia, desigualdad digital, modelo de datos y despliegue. "
            "Cada nodo cita el archivo o la función real del repositorio."
        ),
        "stance": (
            "Las señales de audiencia marcan anomalías estadísticas públicas para que un anunciante "
            "o auditor las revise con prudencia. El sistema no detecta bots ni acusa a nadie."
        ),
        "nav_back": "Volver a la guía",
        "nav_back_href": "/guia",
        "nav_other": "English",
        "nav_other_href": "/guia/en/diagramas",
        "toc": "Contenido",
        "offline": "Si no ves los diagramas, el navegador no pudo cargar Mermaid: abajo queda su código fuente.",
        "diagrams": {
            "arquitectura": (
                "1. Arquitectura de software",
                "Rutas FastAPI, dependencias de acceso, servicios, colectores y persistencia SQLite o PostgreSQL.",
                ES_ARQUITECTURA,
            ),
            "ingesta": (
                "2. Pipeline de ingesta desde YouTube Data API",
                "Estrategia de dos pasos para cuidar la cuota diaria de 10.000 unidades y muestreo del NER.",
                ES_INGESTA,
            ),
            "descubrimiento_worker": (
                "3. Descubrimiento, seguimiento y worker diario",
                "De dónde salen los canales, cómo se guarda un snapshot por día y qué se puede leer sin gastar cuota.",
                ES_DESCUBRIMIENTO,
            ),
            "senales": (
                "4. Motor de las 7 señales de audiencia",
                "Condición de disponibilidad, fórmula y puntos de cada señal. Una señal sin datos no cuenta a favor ni en contra.",
                ES_SENALES,
            ),
            "puntaje": (
                "5. Reglas de prudencia, puntaje 0 a 100 y nivel",
                "Tope por señal única, evidencia mínima y clasificación final.",
                ES_PUNTAJE,
            ),
            "desigualdad": (
                "6. Desigualdad digital: Gini, Lorenz, Pareto y correlaciones",
                "Qué tan concentrada está la audiencia dentro de una búsqueda y cómo se relacionan las variables.",
                ES_DESIGUALDAD,
            ),
            "datos": (
                "7. Modelo de datos",
                "Tablas de app/db/models.py. Idénticas en SQLite y PostgreSQL; las métricas son BIGINT.",
                ES_DATOS,
            ),
            "despliegue": (
                "8. Flujo de integración y despliegue",
                "Del entorno local en Windows a Railway, sin desplegar antes de tener los secretos cargados.",
                ES_DESPLIEGUE,
            ),
        },
    },
    "en": {
        "file": "diagramas_en.html",
        "doc": "arquitectura_grafos_en.md",
        "html_lang": "en",
        "title": "Channel Analytics · System technical graphs",
        "heading": "System technical graphs",
        "lead": (
            "How Channel Analytics works inside: architecture, YouTube ingestion, the audience "
            "signal engine, digital inequality, data model and deployment. "
            "Every node names the real file or function in the repository."
        ),
        "stance": (
            "Audience signals point out public statistical anomalies for an advertiser or auditor "
            "to review carefully. The system does not detect bots or accuse anyone."
        ),
        "nav_back": "Back to the guide",
        "nav_back_href": "/guia/en",
        "nav_other": "Español",
        "nav_other_href": "/guia/diagramas",
        "toc": "Contents",
        "offline": "If the diagrams do not show, the browser could not load Mermaid: their source is below.",
        "diagrams": {
            "arquitectura": (
                "1. Software architecture",
                "FastAPI routes, access dependencies, services, collectors and SQLite or PostgreSQL persistence.",
                EN_ARQUITECTURA,
            ),
            "ingesta": (
                "2. YouTube Data API ingestion pipeline",
                "Two-step strategy to protect the 10,000-unit daily quota, plus NER sampling.",
                EN_INGESTA,
            ),
            "descubrimiento_worker": (
                "3. Discovery, tracking and the daily worker",
                "Where channels come from, how one snapshot per day is stored and what can be read without quota.",
                EN_DESCUBRIMIENTO,
            ),
            "senales": (
                "4. The 7 audience signal engine",
                "Availability condition, formula and points of each signal. A signal without data counts neither way.",
                EN_SENALES,
            ),
            "puntaje": (
                "5. Prudence rules, 0 to 100 score and level",
                "Single-signal cap, minimum evidence and final classification.",
                EN_PUNTAJE,
            ),
            "desigualdad": (
                "6. Digital inequality: Gini, Lorenz, Pareto and correlations",
                "How concentrated the audience is within a search and how variables relate.",
                EN_DESIGUALDAD,
            ),
            "datos": (
                "7. Data model",
                "Tables in app/db/models.py. Identical in SQLite and PostgreSQL; metrics are BIGINT.",
                EN_DATOS,
            ),
            "despliegue": (
                "8. Integration and deployment flow",
                "From the local Windows environment to Railway, without deploying before secrets are set.",
                EN_DESPLIEGUE,
            ),
        },
    },
}

CSS = """
:root { color-scheme: light dark; --bg:#ffffff; --fg:#1f2328; --muted:#59636e; --card:#f6f8fa; --line:#d1d9e0; --accent:#0969da; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { --bg:#0d1117; --fg:#e6edf3; --muted:#9198a1; --card:#151b23; --line:#3d444d; --accent:#4493f8; } }
:root[data-theme="dark"] { --bg:#0d1117; --fg:#e6edf3; --muted:#9198a1; --card:#151b23; --line:#3d444d; --accent:#4493f8; }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--fg); font:16px/1.55 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
main { max-width:1180px; margin:0 auto; padding:32px 20px 64px; }
nav.top { display:flex; gap:16px; justify-content:space-between; font-size:14px; margin-bottom:24px; }
a { color:var(--accent); }
h1 { font-size:28px; margin:0 0 8px; }
h2 { font-size:20px; margin:40px 0 6px; scroll-margin-top:16px; }
p.lead, p.intro { color:var(--muted); margin:0 0 12px; }
p.stance { border-left:3px solid var(--accent); padding:8px 12px; background:var(--card); border-radius:4px; }
ol.toc { columns:2; font-size:15px; padding-left:20px; }
figure { margin:12px 0 0; padding:16px; background:var(--card); border:1px solid var(--line); border-radius:8px; overflow-x:auto; }
pre.mermaid { margin:0; font:13px/1.4 ui-monospace, SFMono-Regular, Consolas, monospace; white-space:pre; }
pre.mermaid[data-processed="true"] { display:flex; justify-content:center; white-space:normal; }
p.offline { font-size:13px; color:var(--muted); }
"""

SCRIPT = """
<script src="{url}" integrity="{sri}" crossorigin="anonymous"></script>
<script>
  (function () {{
    var params = new URLSearchParams(window.location.search);
    var forced = params.get("theme");
    if (forced === "dark" || forced === "light") {{ document.documentElement.setAttribute("data-theme", forced); }}
    var attr = document.documentElement.getAttribute("data-theme");
    var dark = attr ? attr === "dark" : window.matchMedia("(prefers-color-scheme: dark)").matches;
    if (window.mermaid) {{
      window.mermaid.initialize({{ startOnLoad: true, securityLevel: "strict", theme: dark ? "dark" : "default",
        flowchart: {{ htmlLabels: true, useMaxWidth: true }}, sequence: {{ useMaxWidth: true }} }});
    }}
  }})();
</script>
"""


def render(lang: str) -> str:
    page = PAGES[lang]
    toc = "".join(
        f'<li><a href="#{key}">{escape(page["diagrams"][key][0])}</a></li>'
        for key in DIAGRAM_KEYS
    )
    sections = []
    for key in DIAGRAM_KEYS:
        title, intro, source = page["diagrams"][key]
        sections.append(
            f'<section id="{key}">\n<h2>{escape(title)}</h2>\n<p class="intro">{escape(intro)}</p>\n'
            f'<figure><pre class="mermaid">\n{escape(source, quote=False)}\n</pre></figure>\n</section>'
        )
    return (
        "<!DOCTYPE html>\n"
        f'<html lang="{page["html_lang"]}">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{escape(page['title'])}</title>\n<style>{CSS}</style>\n</head>\n<body>\n<main>\n"
        f'<nav class="top"><a href="{page["nav_back_href"]}">← {escape(page["nav_back"])}</a>'
        f'<a href="{page["nav_other_href"]}">{escape(page["nav_other"])}</a></nav>\n'
        f'<h1>{escape(page["heading"])}</h1>\n<p class="lead">{escape(page["lead"])}</p>\n'
        f'<p class="stance">{escape(page["stance"])}</p>\n'
        f'<h2 id="contenido">{escape(page["toc"])}</h2>\n<ol class="toc">{toc}</ol>\n'
        f'<p class="offline">{escape(page["offline"])}</p>\n'
        + "\n".join(sections)
        + "\n</main>\n"
        + SCRIPT.format(url=MERMAID_URL, sri=MERMAID_SRI)
        + "</body>\n</html>\n"
    )


def render_markdown(lang: str) -> str:
    page = PAGES[lang]
    parts = [
        f"# {page['heading']}",
        "",
        f"> {page['stance']}",
        "",
        page["lead"],
        "",
        f"<!-- Generado por scripts/generar_diagramas.py (Mermaid {MERMAID_VERSION}). No editar a mano. -->",
    ]
    for key in DIAGRAM_KEYS:
        title, intro, source = page["diagrams"][key]
        parts += ["", f"## {title}", "", intro, "", "```mermaid", source, "```"]
    return "\n".join(parts) + "\n"


def outputs() -> dict[Path, str]:
    files: dict[Path, str] = {}
    for lang, page in PAGES.items():
        files[STATIC_DIR / page["file"]] = render(lang)
        files[DOCS_DIR / page["doc"]] = render_markdown(lang)
    return files


def main() -> None:
    for path, content in outputs().items():
        path.parent.mkdir(parents=True, exist_ok=True)
        # newline="\n": el mismo archivo byte a byte en Windows y en el CI de Linux.
        path.write_text(content, encoding="utf-8", newline="\n")
        print(f"Generado {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
