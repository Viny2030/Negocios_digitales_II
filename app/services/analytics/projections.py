"""
Proyecciones de tendencia (funcionalidad premium): extrapolación lineal
simple sobre el histórico de snapshots semanales de un canal trackeado.

Deliberadamente NO es un modelo de IA/ML complejo: es un ajuste de
mínimos cuadrados de grado 1 (`numpy.polyfit`) sobre "días desde el
primer snapshot" vs. el valor de la métrica. Es una elección consciente
para este proyecto universitario: simple, explicable, y que mejora sola
a medida que el worker semanal acumula más historial (ver
`docs/manual_metricas_es.md` / `manual_metricas_en.md`).
"""
from datetime import timedelta

import numpy as np

from app.core.exceptions import InsufficientDataError
from app.db.models import ChannelMetricSnapshot

# Métricas numéricas de ChannelMetricSnapshot sobre las que tiene sentido
# proyectar una tendencia.
PROJECTABLE_FIELDS = ("followers", "total_views", "total_posts", "normalized_er")

# Con menos de 3 snapshots un ajuste lineal es solo una línea entre 2
# puntos (o un punto): no hay tendencia real que extrapolar.
MIN_SNAPSHOTS_FOR_PROJECTION = 3

DEFAULT_WEEKS_AHEAD = (1, 4, 12)


def project_metric(
    snapshots: list[ChannelMetricSnapshot], field: str, weeks_ahead: list[int] | tuple[int, ...] = DEFAULT_WEEKS_AHEAD,
) -> dict:
    """
    Ajusta una recta (mínimos cuadrados) a `field` a lo largo del tiempo y
    extrapola su valor a `weeks_ahead` semanas desde el último snapshot.

    Lanza `InsufficientDataError` si `field` no es proyectable o si hay
    menos de `MIN_SNAPSHOTS_FOR_PROJECTION` snapshots disponibles.
    """
    if field not in PROJECTABLE_FIELDS:
        raise InsufficientDataError(
            f"Métrica no proyectable: '{field}'. Disponibles: {', '.join(PROJECTABLE_FIELDS)}"
        )
    if len(snapshots) < MIN_SNAPSHOTS_FOR_PROJECTION:
        raise InsufficientDataError(
            f"Se necesitan al menos {MIN_SNAPSHOTS_FOR_PROJECTION} snapshots semanales para proyectar "
            f"'{field}' (encontrados: {len(snapshots)}). La confiabilidad de la proyección mejora a "
            f"medida que se acumulan más semanas de seguimiento."
        )

    ordered = sorted(snapshots, key=lambda s: s.snapshot_date)
    base_date = ordered[0].snapshot_date
    x = np.array([float((s.snapshot_date - base_date).days) for s in ordered])
    y = np.array([float(getattr(s, field)) for s in ordered])

    # Serie constante (o casi): polyfit devuelve pendiente ~0, lo cual es
    # el resultado correcto (no hay tendencia), no un error.
    slope, intercept = np.polyfit(x, y, 1)

    last_x = x[-1]
    last_date = ordered[-1].snapshot_date
    projections = []
    for weeks in weeks_ahead:
        target_x = last_x + (weeks * 7)
        projected_value = float(slope * target_x + intercept)
        # Ninguna de estas métricas puede ser negativa en la realidad.
        projected_value = max(0.0, projected_value)
        projections.append({
            "weeks_ahead": int(weeks),
            "projected_date": last_date + timedelta(weeks=weeks),
            "projected_value": round(projected_value, 4),
        })

    return {
        "field": field,
        "history_points": len(ordered),
        "weekly_trend": round(float(slope) * 7, 4),
        "projections": projections,
        "confidence_note": (
            "Proyección por extrapolación lineal simple (mínimos cuadrados) sobre el histórico "
            "semanal disponible, sin modelos de IA. Su confiabilidad mejora a medida que el "
            "worker semanal acumula más snapshots — tratarla como una guía direccional, no una "
            "predicción exacta."
        ),
    }


def project_channel(
    snapshots: list[ChannelMetricSnapshot], weeks_ahead: list[int] | tuple[int, ...] = DEFAULT_WEEKS_AHEAD,
) -> list[dict]:
    """
    Proyecta todas las métricas de `PROJECTABLE_FIELDS` para las que haya
    suficiente historial, salteando en silencio las que no alcancen el
    mínimo (no hace fallar la respuesta completa por una sola métrica).
    Lanza `InsufficientDataError` solo si NINGUNA métrica pudo proyectarse.
    """
    results = []
    for field in PROJECTABLE_FIELDS:
        try:
            results.append(project_metric(snapshots, field, weeks_ahead))
        except InsufficientDataError:
            continue

    if not results:
        raise InsufficientDataError(
            f"Se necesitan al menos {MIN_SNAPSHOTS_FOR_PROJECTION} snapshots semanales para "
            f"proyectar cualquier métrica (encontrados: {len(snapshots)})."
        )
    return results
