# Grafos técnicos del sistema

> Las señales de audiencia marcan anomalías estadísticas públicas para que un anunciante o auditor las revise con prudencia. El sistema no detecta bots ni acusa a nadie.

Cómo funciona Channel Analytics por dentro: arquitectura, ingesta desde YouTube, motor de señales de audiencia, desigualdad digital, modelo de datos y despliegue. Cada nodo cita el archivo o la función real del repositorio.

<!-- Generado por scripts/generar_diagramas.py (Mermaid 12.3.0). No editar a mano. -->

## 1. Arquitectura de software

Rutas FastAPI, dependencias de acceso, servicios, colectores y persistencia SQLite o PostgreSQL.

```mermaid
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
  MOD --> PG
```

## 2. Pipeline de ingesta desde YouTube Data API

Estrategia de dos pasos para cuidar la cuota diaria de 10.000 unidades y muestreo del NER.

```mermaid
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
  API-->>U: JSON con meta, benchmark y avisos de datos simulados
```

## 3. Descubrimiento, seguimiento y worker diario

De dónde salen los canales, cómo se guarda un snapshot por día y qué se puede leer sin gastar cuota.

```mermaid
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
  L2 -.- NOTA
```

## 4. Motor de las 7 señales de audiencia

Condición de disponibilidad, fórmula y puntos de cada señal. Una señal sin datos no cuenta a favor ni en contra.

```mermaid
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
  SUM --> NEXT["ver diagrama: puntaje y nivel"]
```

## 5. Reglas de prudencia, puntaje 0 a 100 y nivel

Tope por señal única, evidencia mínima y clasificación final.

```mermaid
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
  OUT --> P["Postura del sistema: mide cuánto conviene revisar un canal.<br/>No detecta bots, no prueba fraude y no acusa a nadie."]
```

## 6. Desigualdad digital: Gini, Lorenz, Pareto y correlaciones

Qué tan concentrada está la audiencia dentro de una búsqueda y cómo se relacionan las variables.

```mermaid
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
  IN --> CP["CorrelationPair"]
```

## 7. Modelo de datos

Tablas de app/db/models.py. Idénticas en SQLite y PostgreSQL; las métricas son BIGINT.

```mermaid
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
  }
```

## 8. Flujo de integración y despliegue

Del entorno local en Windows a Railway, sin desplegar antes de tener los secretos cargados.

```mermaid
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
  HC --> PGB[("PostgreSQL de Railway<br/>respaldo externo con pg_dump")]
```
