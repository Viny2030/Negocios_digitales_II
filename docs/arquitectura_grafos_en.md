# System technical graphs

> Audience signals point out public statistical anomalies for an advertiser or auditor to review carefully. The system does not detect bots or accuse anyone.

How Channel Analytics works inside: architecture, YouTube ingestion, the audience signal engine, digital inequality, data model and deployment. Every node names the real file or function in the repository.

<!-- Generado por scripts/generar_diagramas.py (Mermaid 12.3.0). No editar a mano. -->

## 1. Software architecture

FastAPI routes, access dependencies, services, collectors and SQLite or PostgreSQL persistence.

```mermaid
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
  MOD --> PG
```

## 2. YouTube Data API ingestion pipeline

Two-step strategy to protect the 10,000-unit daily quota, plus NER sampling.

```mermaid
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
  API-->>U: JSON with meta, benchmark and simulated-data flags
```

## 3. Discovery, tracking and the daily worker

Where channels come from, how one snapshot per day is stored and what can be read without quota.

```mermaid
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
  L2 -.- NOTA
```

## 4. The 7 audience signal engine

Availability condition, formula and points of each signal. A signal without data counts neither way.

```mermaid
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
  SUM --> NEXT["see diagram: score and level"]
```

## 5. Prudence rules, 0 to 100 score and level

Single-signal cap, minimum evidence and final classification.

```mermaid
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
  OUT --> P["System stance: measures how much a channel is worth reviewing.<br/>It does not detect bots, prove fraud or accuse anyone."]
```

## 6. Digital inequality: Gini, Lorenz, Pareto and correlations

How concentrated the audience is within a search and how variables relate.

```mermaid
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
  IN --> CP["CorrelationPair"]
```

## 7. Data model

Tables in app/db/models.py. Identical in SQLite and PostgreSQL; metrics are BIGINT.

```mermaid
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
  }
```

## 8. Integration and deployment flow

From the local Windows environment to Railway, without deploying before secrets are set.

```mermaid
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
  HC --> PGB[("Railway PostgreSQL<br/>external backup with pg_dump")]
```
