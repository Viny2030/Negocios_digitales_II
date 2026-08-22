"""
Recomendaciones de política general por métrica (funcionalidad premium).

Motor basado en reglas fijas, NO en IA generativa: traduce el mismo
benchmark de industria que ya expone `services/analytics/benchmarks.py`
(y, cuando está disponible, la tendencia semanal calculada por
`services/analytics/projections.py`) en sugerencias accionables y
explicables por métrica. Documentado en `docs/manual_metricas_*.md`.
"""
from app.models.domain import Platform
from app.services.analytics.benchmarks import compare_to_benchmark

# Umbral por debajo del cual, además de estar "below" del benchmark, se
# considera que el volumen de interacción es prácticamente nulo (no solo
# bajo respecto al rango esperado).
_LOW_ER_ABSOLUTE_THRESHOLD_PCT = 1.0


def recommend_for_channel(
    platform: Platform,
    followers: int,
    total_posts: int,
    normalized_er: float,
    weekly_follower_trend: float | None = None,
) -> list[dict]:
    """
    Genera recomendaciones de política general para un canal, a partir de
    su última foto de métricas y (si está disponible) su tendencia
    semanal de seguidores calculada vía `project_metric`.
    """
    recommendations: list[dict] = []

    bench = compare_to_benchmark(platform, normalized_er)
    if bench is not None:
        if bench.status == "below":
            recommendations.append({
                "metric": "normalized_er",
                "priority": "alta",
                "finding": (
                    f"El engagement rate observado ({normalized_er:.2f}%) está por debajo del rango "
                    f"típico de {platform.value} ({bench.benchmark_min_pct}%–{bench.benchmark_max_pct}%)."
                ),
                "recommendation": (
                    "Priorizar formatos que inviten a comentar (preguntas directas a la audiencia, "
                    "encuestas, llamados a la acción explícitos en los primeros segundos) y revisar si "
                    "el crecimiento de seguidores viene acompañado de una audiencia realmente activa "
                    "o si conviene ajustar la frecuencia de publicación antes de seguir escalando alcance."
                ),
            })
        elif bench.status == "above":
            recommendations.append({
                "metric": "normalized_er",
                "priority": "informativa",
                "finding": (
                    f"El engagement rate observado ({normalized_er:.2f}%) está por encima del rango "
                    f"típico de {platform.value}."
                ),
                "recommendation": (
                    "Buen momento para escalar la frecuencia de publicación manteniendo el formato "
                    "actual, y para documentar qué elementos del contenido reciente explican el "
                    "engagement por encima del benchmark (para repetirlos)."
                ),
            })

    if normalized_er < _LOW_ER_ABSOLUTE_THRESHOLD_PCT and total_posts > 0:
        recommendations.append({
            "metric": "raw_interactions",
            "priority": "media",
            "finding": "Volumen de interacción (comentarios y, si aplica, likes/shares) muy bajo en términos absolutos.",
            "recommendation": (
                "Fijar (pin) un comentario propio con una pregunta abierta al público en cada "
                "publicación nueva, y responder activamente los primeros comentarios para incentivar "
                "más respuestas (el algoritmo de la mayoría de las plataformas prioriza la actividad "
                "temprana)."
            ),
        })

    if weekly_follower_trend is not None:
        if weekly_follower_trend < 0:
            recommendations.append({
                "metric": "followers",
                "priority": "alta",
                "finding": f"La tendencia semanal de seguidores es negativa (≈ {weekly_follower_trend:.1f}/semana).",
                "recommendation": (
                    "Revisar la frecuencia y consistencia de publicación de las últimas semanas, y "
                    "comparar el contenido reciente contra las publicaciones históricas de mejor "
                    "desempeño del propio canal para identificar qué cambió."
                ),
            })
        elif weekly_follower_trend == 0:
            recommendations.append({
                "metric": "followers",
                "priority": "media",
                "finding": "La audiencia está estancada: sin crecimiento neto reciente.",
                "recommendation": (
                    "Probar un formato o subtema nuevo dentro del mismo nicho, y evaluar su impacto "
                    "en las próximas 2 a 3 semanas de seguimiento antes de descartarlo."
                ),
            })

    if not recommendations:
        recommendations.append({
            "metric": "general",
            "priority": "informativa",
            "finding": "No se detectaron desvíos relevantes respecto a los benchmarks de industria disponibles.",
            "recommendation": (
                "Mantener la estrategia de contenido actual y seguir acumulando snapshots semanales: "
                "más historial habilita proyecciones de tendencia más confiables."
            ),
        })

    return recommendations
