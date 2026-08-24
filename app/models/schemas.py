"""
Schemas Pydantic v2: contratos de request/response de la API pública
y la entidad universal `UnifiedChannel` que normaliza YouTube y TikTok
bajo un mismo esquema.
"""
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field, ConfigDict

from app.models.domain import ContentFormat, ContentTier, Plan, Platform


# ─────────────────────────────────────────────────────────────────────────
# Entidad Universal Canal
# ─────────────────────────────────────────────────────────────────────────

class UnifiedChannel(BaseModel):
    """Representación normalizada de un canal, sin importar su plataforma origen."""

    model_config = ConfigDict(use_enum_values=True)

    universal_id: str = Field(..., description="ID único global: '<platform>:<native_id>'")
    native_id: str = Field(..., description="Identificador nativo en la plataforma origen")
    platform: Platform
    content_format: ContentFormat
    name: str
    handle: Optional[str] = Field(None, description="@usuario / nombre corto público")
    url: Optional[str] = None

    # --- Métricas de inventario / audiencia ---
    followers: int = Field(..., ge=0, description="Suscriptores (YouTube) o seguidores (TikTok)")
    total_views: int = Field(0, ge=0, description="Vistas históricas acumuladas")
    total_posts: int = Field(0, ge=0, description="Cantidad de videos publicados")

    # --- Métricas de interacción (última ventana muestreada) ---
    raw_interactions: int = Field(0, ge=0, description="Likes + comments (+ shares/saves si aplica)")
    likes: int = 0
    comments: int = 0
    shares: int = 0
    saves: int = 0

    # --- Métricas normalizadas (ver services/analytics/normalizer.py) ---
    normalized_er: float = Field(0.0, description="Engagement rate normalizado, en % (NER)")
    tier: ContentTier

    fetched_at: datetime = Field(default_factory=datetime.utcnow)


# ─────────────────────────────────────────────────────────────────────────
# Requests
# ─────────────────────────────────────────────────────────────────────────

class ChannelSearchRequest(BaseModel):
    """Payload de POST /api/v1/analyze (Diagrama 1)."""

    query: str = Field(..., min_length=1, max_length=200, description="Tema / palabra clave a buscar")
    platforms: list[Platform] = Field(
        default_factory=lambda: [Platform.YOUTUBE, Platform.TIKTOK],
        description="Plataformas a consultar. 'all' expande a todas las soportadas.",
    )
    limit: int = Field(25, ge=1, le=100, description="Máximo de canales por plataforma")


# ─────────────────────────────────────────────────────────────────────────
# Metadatos de ejecución (compartido por todas las respuestas)
# ─────────────────────────────────────────────────────────────────────────

class ExecutionMeta(BaseModel):
    query: Optional[str] = None
    platforms_requested: list[Platform] = []
    response_time_ms: float
    status: str = "ok"


# ─────────────────────────────────────────────────────────────────────────
# Métricas y benchmarks del medio (referencia de industria por plataforma)
# ─────────────────────────────────────────────────────────────────────────

class PlatformBenchmark(BaseModel):
    """
    Ficha de referencia de industria para una plataforma: la Matriz
    Comparativa de Métricas (ver README) convertida en datos consumibles
    por la API. Son valores estáticos publicados por la industria, no
    calculados sobre la búsqueda actual.
    """

    platform: Platform
    primary_reach_metric: str
    retention_metric: str
    engagement_formula: str
    engagement_benchmark_min_pct: float
    engagement_benchmark_max_pct: float
    typical_posting_frequency: str
    content_lifespan: str
    raw_metric_bias_risk: str


class BenchmarkComparison(BaseModel):
    """Compara el ER promedio observado en una búsqueda contra el rango de industria."""

    platform: Platform
    observed_avg_er: float
    benchmark_min_pct: float
    benchmark_max_pct: float
    status: str = Field(..., description="'below' | 'within' | 'above' del rango de industria")
    delta_from_range_pct: float = Field(
        0.0, description="Qué tan lejos está del borde más cercano del rango, en % relativo (0 si está dentro)"
    )


class BenchmarkResponse(BaseModel):
    meta: ExecutionMeta
    benchmarks: list[PlatformBenchmark]


# ─────────────────────────────────────────────────────────────────────────
# Responses: búsqueda unificada
# ─────────────────────────────────────────────────────────────────────────

class PlatformSummary(BaseModel):
    platform: Platform
    channel_count: int
    total_followers: int
    total_views: int
    avg_normalized_er: float
    benchmark: Optional[BenchmarkComparison] = Field(
        None, description="Comparación del ER promedio observado contra el benchmark de industria"
    )


class SearchResponse(BaseModel):
    """Respuesta de GET /api/v1/channels/search y POST /api/v1/analyze."""

    meta: ExecutionMeta
    summary_by_platform: list[PlatformSummary]
    channels: list[UnifiedChannel]


# ─────────────────────────────────────────────────────────────────────────
# Responses: descubrimiento "por categoría" (sin mezclar temas entre sí)
# ─────────────────────────────────────────────────────────────────────────

class AnomalyFlag(BaseModel):
    """
    Definida acá arriba (antes de usarse en varios lados: `AnomalyResponse`,
    `PlatformOverview` y `CategoryChannels`) porque Pydantic necesita la
    clase ya declarada al momento de armar cada modelo que la referencia.
    """

    universal_id: str
    name: str
    platform: Platform
    followers: int
    normalized_er: float
    reason: str


class CategoryChannels(BaseModel):
    """Ranking de canales de una única categoría/tópico, ya ordenado por métrica."""

    category: str = Field(..., description="Clave interna de la categoría (ver `label` para el nombre legible)")
    label: str = Field(..., description="Nombre legible de la categoría/tópico")
    channel_count: int
    total_followers: int = Field(0, description="Suma de seguidores de todos los canales de esta categoría")
    avg_normalized_er: float = Field(0.0, description="ER promedio (NER %) de esta categoría")
    anomalies: list[AnomalyFlag] = Field(
        default_factory=list,
        description="Canales de esta categoría con métricas potencialmente infladas (necesita >=4 canales en la categoría para calcularse)",
    )
    channels: list[UnifiedChannel]


class PlatformCategoryBreakdown(BaseModel):
    platform: Platform
    categories: list[CategoryChannels]


class DiscoverByCategoryResponse(BaseModel):
    """Respuesta de GET /api/v1/channels/discover/by-category."""

    meta: ExecutionMeta
    sort_by: str
    platforms: list[PlatformCategoryBreakdown]


# ─────────────────────────────────────────────────────────────────────────
# Responses: motor estadístico
# ─────────────────────────────────────────────────────────────────────────

class DistributionStats(BaseModel):
    """Tendencia central, dispersión y forma para una métrica dada."""

    metric: str
    n: int
    mean: float
    median: float
    min: float
    max: float
    range: float = Field(..., description="max - min")
    p5: float
    p10: float
    p25: float
    p75: float
    p90: float
    p95: float
    iqr: float
    std_dev: float
    coefficient_of_variation: float = Field(
        ..., description="std_dev / mean (0 si mean=0). Permite comparar dispersión entre métricas de distinta escala."
    )
    skewness: float
    kurtosis: float


class DistributionResponse(BaseModel):
    meta: ExecutionMeta
    platform: Platform
    followers: DistributionStats
    normalized_er: DistributionStats
    tier_breakdown: dict[str, int]
    benchmark: Optional[BenchmarkComparison] = None


class InequalityStats(BaseModel):
    platform: Platform
    n: int
    gini_followers: float = Field(..., ge=0, le=1)
    pareto_alpha: Optional[float] = None
    top_10_pct_share: float = Field(..., description="Proporción de seguidores en manos del top 10%")


class InequalityResponse(BaseModel):
    meta: ExecutionMeta
    results: list[InequalityStats]


class CorrelationPair(BaseModel):
    variable_x: str
    variable_y: str
    spearman_rho: float
    pearson_r: float
    n: int
    interpretation: str


class CorrelationResponse(BaseModel):
    meta: ExecutionMeta
    platform: Platform
    correlations: list[CorrelationPair]


class AnomalyResponse(BaseModel):
    meta: ExecutionMeta
    platform: Platform
    flagged: list[AnomalyFlag]
    total_evaluated: int


# ─────────────────────────────────────────────────────────────────────────
# Response: overview cross-platform (todo-en-uno)
# ─────────────────────────────────────────────────────────────────────────

class PlatformOverview(BaseModel):
    """
    Consolida, para una plataforma, todo lo que hoy se sirve por separado
    en /distribution, /inequality, /correlation y /anomalies — más el
    benchmark de industria. Los sub-análisis que requieren un mínimo de
    observaciones (correlación >=3, anomalías >=4) se omiten (None / [])
    en vez de hacer fallar la respuesta completa cuando la cohorte es chica.
    """

    platform: Platform
    channel_count: int
    followers: Optional[DistributionStats] = None
    normalized_er: Optional[DistributionStats] = None
    tier_breakdown: dict[str, int] = {}
    inequality: Optional[InequalityStats] = None
    correlations: list[CorrelationPair] = []
    anomalies: list[AnomalyFlag] = []
    benchmark: Optional[BenchmarkComparison] = None


class OverviewResponse(BaseModel):
    meta: ExecutionMeta
    platforms: list[PlatformOverview]


# ─────────────────────────────────────────────────────────────────────────
# Catálogo de canales: tipos/taxonomía (YouTube + propios) y cantidades
# ─────────────────────────────────────────────────────────────────────────

class ChannelTypeCreate(BaseModel):
    """Payload de POST /api/v1/catalog/types — crear un tipo de canal propio."""

    name: str = Field(..., min_length=1, max_length=120, description="Nombre del tipo (ej: 'Finanzas personales')")
    description: Optional[str] = Field(None, max_length=500)


class ChannelTypeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    slug: str
    description: Optional[str] = None
    is_custom: bool = Field(..., description="True = tipo propio creado a mano; False = categoría nativa de YouTube")
    created_at: datetime


class ChannelTypeListResponse(BaseModel):
    meta: ExecutionMeta
    types: list[ChannelTypeOut]


class SetChannelTypeRequest(BaseModel):
    """Payload de PATCH /api/v1/catalog/channels/{tracked_id}/type."""

    channel_type_id: Optional[int] = Field(None, description="null = quitar el tipo asignado")


class ChannelTypeCount(BaseModel):
    """Cuántos canales trackeados hay de un tipo dado (o sin tipo asignado)."""

    channel_type: Optional[ChannelTypeOut] = Field(None, description="None = canales sin tipo asignado todavía")
    channel_count: int


class CatalogSummaryResponse(BaseModel):
    """Respuesta de GET /api/v1/catalog/summary — cantidades por tipo de canal."""

    meta: ExecutionMeta
    total_channels: int
    by_type: list[ChannelTypeCount]


# ─────────────────────────────────────────────────────────────────────────
# Seguimiento diario: canales trackeados + snapshots (worker diario)
# ─────────────────────────────────────────────────────────────────────────

class TrackedChannelCreate(BaseModel):
    """Payload de POST /api/v1/tracking/channels."""

    platform: Platform = Field(..., description="youtube | tiktok")
    identifier: str = Field(
        ..., min_length=1, max_length=200,
        description="ID nativo del canal (p. ej. 'UCxxxx' en YouTube) o @handle",
    )
    label: Optional[str] = Field(None, max_length=200, description="Etiqueta propia, opcional (ej: 'Competidor A')")
    channel_type_id: Optional[int] = Field(
        None, description="Id de un tipo de canal ya existente (ver GET /catalog/types)",
    )
    channel_type_name: Optional[str] = Field(
        None, max_length=120,
        description=(
            "Alternativa a `channel_type_id`: nombre de un tipo de canal. Si ya existe (comparación "
            "case-insensitive) se reusa; si no, se crea uno propio de una. Pensado para el botón "
            "'+ Seguir' de 'Por categoría', que ya conoce el nombre de la categoría de YouTube. "
            "Se ignora si `channel_type_id` viene seteado."
        ),
    )


class ChannelSnapshotOut(BaseModel):
    snapshot_date: date
    followers: int
    total_views: int
    total_posts: int
    normalized_er: float
    tier: str


class TrackedChannelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    platform: Platform
    native_id: str
    handle: Optional[str] = None
    label: Optional[str] = None
    name: Optional[str] = None
    url: Optional[str] = None
    active: bool
    created_at: datetime
    latest_snapshot: Optional[ChannelSnapshotOut] = None
    channel_type: Optional[ChannelTypeOut] = None


class TrackedChannelListResponse(BaseModel):
    meta: ExecutionMeta
    channels: list[TrackedChannelOut]


class ChannelHistoryResponse(BaseModel):
    meta: ExecutionMeta
    channel: TrackedChannelOut
    snapshots: list[ChannelSnapshotOut]


class DailyJobResultOut(BaseModel):
    meta: ExecutionMeta
    channels_evaluated: int
    snapshots_created: int
    snapshots_updated: int
    errors: list[str]


# ─────────────────────────────────────────────────────────────────────────
# Autenticación y planes de suscripción (free / única / mensual / premium)
# ─────────────────────────────────────────────────────────────────────────

# Regex simple de formato de email (evita agregar `email-validator` como
# dependencia solo para esta validación básica de shape).
_EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class UserRegisterRequest(BaseModel):
    """Payload de POST /api/v1/auth/register. Toda cuenta nueva arranca en plan 'free'."""

    email: str = Field(..., min_length=5, max_length=255, pattern=_EMAIL_PATTERN)
    password: str = Field(..., min_length=8, max_length=200, description="Mínimo 8 caracteres")


class UserLoginRequest(BaseModel):
    """Payload de POST /api/v1/auth/login."""

    email: str = Field(..., min_length=5, max_length=255)
    password: str = Field(..., min_length=1, max_length=200)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    plan: str
    plan_active_until: Optional[datetime] = None
    report_credits: int
    is_admin: bool
    has_full_stats_access: bool
    has_premium_access: bool


class TokenResponse(BaseModel):
    """Respuesta de /auth/register y /auth/login: token de sesión + datos del usuario."""

    access_token: str
    token_type: str = "bearer"
    user: UserOut


class AdminSetPlanRequest(BaseModel):
    """
    Payload de POST /api/v1/auth/admin/set-plan — protegido con
    `X-Admin-Token` (igual que `/tracking/*`). Simula manualmente un
    alta/cambio de plan sin pasarela de pago real conectada.
    """

    email: str = Field(..., min_length=5, max_length=255)
    plan: Plan
    active_days: Optional[int] = Field(
        None, ge=1, le=3650, description="Vigencia en días para 'mensual'/'premium' (default 30 si se omite)",
    )
    add_report_credits: Optional[int] = Field(
        None, ge=1, le=1000, description="Créditos de reporte a sumar para 'unica' (default 1 si se omite)",
    )


# ─────────────────────────────────────────────────────────────────────────
# Premium: proyecciones de tendencia y recomendaciones por métrica
# ─────────────────────────────────────────────────────────────────────────

class ProjectionPoint(BaseModel):
    weeks_ahead: int
    projected_date: date
    projected_value: float


class MetricProjection(BaseModel):
    field: str
    history_points: int
    weekly_trend: float
    projections: list[ProjectionPoint]
    confidence_note: str


class ChannelProjectionResponse(BaseModel):
    meta: ExecutionMeta
    tracked_channel_id: int
    projections: list[MetricProjection]


class RecommendationItem(BaseModel):
    metric: str
    priority: str
    finding: str
    recommendation: str


class ChannelRecommendationResponse(BaseModel):
    meta: ExecutionMeta
    tracked_channel_id: int
    recommendations: list[RecommendationItem]
