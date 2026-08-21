"""
Motor Estadístico Vectorial — Métricas Robustas (no paramétricas).

Usa NumPy/SciPy para mediana, IQR, percentiles, asimetría (skewness) y
curtosis (kurtosis), calculados de forma vectorizada sobre arrays de
NumPy. Diseñado para operar eficientemente sobre matrices de hasta
~1.000.000 de filas en memoria (ver "Límites de la Base de Datos y
Procesamiento en Servidor").
"""
import numpy as np
from scipy import stats as scipy_stats

from app.core.exceptions import InsufficientDataError
from app.models.schemas import DistributionStats


def describe(values: list[float], metric_name: str) -> DistributionStats:
    """
    Calcula tendencia central, dispersión y forma para un vector de valores:
    mínimo/máximo/rango, percentiles P5/P10/P25/P75/P90/P95, IQR, desvío
    estándar, coeficiente de variación (std/mean, comparable entre métricas
    de distinta escala), asimetría (skewness) y curtosis.

    Requiere al menos 2 observaciones para que desviación estándar,
    asimetría y curtosis tengan sentido estadístico.
    """
    if len(values) < 2:
        raise InsufficientDataError(
            f"Se necesitan al menos 2 observaciones para describir '{metric_name}' "
            f"(recibidas: {len(values)})"
        )

    arr = np.asarray(values, dtype=float)
    mean = float(np.mean(arr))
    std_dev = float(np.std(arr, ddof=1))
    minimum = float(np.min(arr))
    maximum = float(np.max(arr))

    # Con desvío estándar 0 (todos los valores idénticos — más común de lo
    # que parece con datos reales: p. ej. varios canales con NER exactamente
    # 0.0 porque YouTube no expone likes agregados) skew/kurtosis de SciPy
    # dan NaN (dividen por std_dev al cubo/cuarta potencia). NaN no es JSON
    # válido y tira un 500 al serializar la respuesta — una distribución
    # constante no tiene asimetría/curtosis definida, así que 0.0 es el
    # valor semánticamente correcto, no un parche.
    is_constant = std_dev == 0
    skewness = 0.0 if is_constant else float(scipy_stats.skew(arr, bias=True))
    kurtosis = 0.0 if is_constant else float(scipy_stats.kurtosis(arr, bias=True))

    return DistributionStats(
        metric=metric_name,
        n=int(arr.size),
        mean=mean,
        median=float(np.median(arr)),
        min=minimum,
        max=maximum,
        range=maximum - minimum,
        p5=float(np.percentile(arr, 5)),
        p10=float(np.percentile(arr, 10)),
        p25=float(np.percentile(arr, 25)),
        p75=float(np.percentile(arr, 75)),
        p90=float(np.percentile(arr, 90)),
        p95=float(np.percentile(arr, 95)),
        iqr=float(np.percentile(arr, 75) - np.percentile(arr, 25)),
        std_dev=std_dev,
        coefficient_of_variation=round(std_dev / mean, 4) if mean != 0 else 0.0,
        # Fisher-Pearson (bias=True para consistencia con la fórmula clásica g1)
        skewness=skewness,
        kurtosis=kurtosis,
    )


def percentile(values: list[float], q: float) -> float:
    """Percentil q (0-100) de un vector. Utilidad puntual para endpoints ad-hoc."""
    if not values:
        raise InsufficientDataError("No hay valores para calcular el percentil")
    return float(np.percentile(np.asarray(values, dtype=float), q))