"""
Métricas y benchmarks del medio (referencia de industria por plataforma).

Convierte la "Matriz Comparativa de Métricas por Plataforma" en datos
estáticos consumibles por la API, y expone una función para comparar el
Engagement Rate observado en una búsqueda contra el rango típico
publicado por la industria para esa plataforma.

Estos valores son de referencia general (no se recalculan por búsqueda);
sirven para contextualizar si un canal o cohorte está dentro, por encima
o por debajo de lo esperable para su plataforma.
"""
from app.models.domain import Platform
from app.models.schemas import BenchmarkComparison, PlatformBenchmark

INDUSTRY_BENCHMARKS: dict[Platform, PlatformBenchmark] = {
    Platform.YOUTUBE: PlatformBenchmark(
        platform=Platform.YOUTUBE,
        primary_reach_metric="Suscriptores y Vistas",
        retention_metric="Retención Relativa de Audiencia (AVD / Retención %)",
        engagement_formula="(Likes + Comentarios + Shares) / Vistas",
        engagement_benchmark_min_pct=1.5,
        engagement_benchmark_max_pct=3.5,
        typical_posting_frequency="1 – 3 publicaciones/semana",
        content_lifespan="Larga (meses a años, por SEO/búsqueda)",
        raw_metric_bias_risk="Clickbait distorsiona vistas iniciales sin retención",
    ),
    Platform.TIKTOK: PlatformBenchmark(
        platform=Platform.TIKTOK,
        primary_reach_metric="Seguidores y Video Views",
        retention_metric="Ratio de Finalización (Completion Rate)",
        engagement_formula="(Likes + Comentarios + Shares + Bookmarks) / Vistas",
        engagement_benchmark_min_pct=4.0,
        engagement_benchmark_max_pct=9.0,
        typical_posting_frequency="1 – 3 publicaciones/día",
        content_lifespan="Muy corta a media (24h a 7 días)",
        raw_metric_bias_risk="El algoritmo favorece la viralidad efímera frente a la masa de seguidores",
    ),
}


def get_benchmarks(platforms: list[Platform]) -> list[PlatformBenchmark]:
    """Devuelve las fichas de benchmark para las plataformas pedidas (youtube/tiktok)."""
    return [INDUSTRY_BENCHMARKS[p] for p in platforms if p in INDUSTRY_BENCHMARKS]


def compare_to_benchmark(platform: Platform, avg_normalized_er: float) -> BenchmarkComparison | None:
    """
    Ubica `avg_normalized_er` (en %) respecto al rango de industria de
    `platform`. Devuelve None si la plataforma no tiene benchmark
    definido (p. ej. no aplica fuera de youtube/tiktok en esta fase).

    `delta_from_range_pct` expresa qué tan lejos está del borde más
    cercano del rango, como porcentaje relativo a ese borde (0 si está
    dentro del rango).
    """
    bench = INDUSTRY_BENCHMARKS.get(platform)
    if bench is None:
        return None

    if avg_normalized_er < bench.engagement_benchmark_min_pct:
        status = "below"
        edge = bench.engagement_benchmark_min_pct
        delta = ((edge - avg_normalized_er) / edge) * 100 if edge > 0 else 0.0
    elif avg_normalized_er > bench.engagement_benchmark_max_pct:
        status = "above"
        edge = bench.engagement_benchmark_max_pct
        delta = ((avg_normalized_er - edge) / edge) * 100 if edge > 0 else 0.0
    else:
        status = "within"
        delta = 0.0

    return BenchmarkComparison(
        platform=platform,
        observed_avg_er=round(avg_normalized_er, 4),
        benchmark_min_pct=bench.engagement_benchmark_min_pct,
        benchmark_max_pct=bench.engagement_benchmark_max_pct,
        status=status,
        delta_from_range_pct=round(delta, 2),
    )
