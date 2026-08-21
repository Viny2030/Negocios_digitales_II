"""
Métricas de Desigualdad y Concentración (monopolio de audiencia).

Implementa:
  - Coeficiente de Gini (0 = igualdad perfecta, 1 = concentración total)
  - Exponente de la Ley de Potencia / Pareto (alpha), vía estimador de
    máxima verosimilitud (Hill estimator / MLE de Clauset et al.)
  - Participación del top 10% (complemento intuitivo al Gini)
"""
import numpy as np

from app.core.exceptions import InsufficientDataError


def gini_coefficient(values: list[float]) -> float:
    """
    G = (2 * Σ(i * y_i) - (n+1) * Σy_i) / (n * Σy_i)

    con y_i ordenado de forma ascendente e i = 1..n (índice 1-based).
    Robusto a ceros; requiere al menos un valor positivo.
    """
    if not values:
        raise InsufficientDataError("No hay valores para calcular el coeficiente de Gini")

    arr = np.sort(np.asarray(values, dtype=float))
    arr = np.clip(arr, a_min=0, a_max=None)  # el Gini clásico asume no-negatividad
    n = arr.size
    total = arr.sum()

    if total == 0:
        return 0.0

    index = np.arange(1, n + 1)  # i = 1..n
    numerator = 2 * np.sum(index * arr) - (n + 1) * total
    denominator = n * total
    return float(numerator / denominator)


def pareto_alpha(values: list[float], x_min: float | None = None) -> float | None:
    """
    Estimador de máxima verosimilitud del exponente de la ley de potencia:

        alpha = 1 + n / Σ ln(x_i / x_min)

    Solo tiene sentido para valores estrictamente positivos por encima de
    un umbral `x_min` (por defecto, el mínimo del propio vector). Devuelve
    None si no hay suficiente variación para estimarlo.
    """
    arr = np.asarray([v for v in values if v > 0], dtype=float)
    if arr.size < 2:
        return None

    threshold = x_min if x_min is not None else float(np.min(arr))
    tail = arr[arr >= threshold]
    if tail.size < 2:
        return None

    log_ratios = np.log(tail / threshold)
    denom = np.sum(log_ratios)
    if denom == 0:
        return None

    alpha = 1 + tail.size / denom
    return float(alpha)


def top_decile_share(values: list[float]) -> float:
    """Proporción del total que concentra el 10% de observaciones más grandes."""
    if not values:
        raise InsufficientDataError("No hay valores para calcular la participación del top 10%")

    arr = np.sort(np.asarray(values, dtype=float))[::-1]  # descendente
    total = arr.sum()
    if total == 0:
        return 0.0

    top_n = max(1, int(np.ceil(arr.size * 0.10)))
    return float(arr[:top_n].sum() / total)
