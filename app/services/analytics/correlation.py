"""
Matriz de Correlación e Interacciones entre variables de canal
(p. ej. Publicaciones vs. Engagement, Seguidores vs. Engagement Rate).

Se reportan dos coeficientes en paralelo:
  - Spearman (rho): correlación de rangos, no asume linealidad ni
    distribución normal — más robusta ante outliers virales.
  - Pearson (r): correlación lineal clásica, útil como referencia.
"""
from scipy import stats as scipy_stats

from app.core.exceptions import InsufficientDataError
from app.models.schemas import CorrelationPair


def _interpret(rho: float) -> str:
    magnitude = abs(rho)
    direction = "positiva" if rho > 0 else "negativa" if rho < 0 else "nula"
    if magnitude < 0.1:
        strength = "insignificante"
    elif magnitude < 0.3:
        strength = "débil"
    elif magnitude < 0.5:
        strength = "moderada"
    elif magnitude < 0.7:
        strength = "fuerte"
    else:
        strength = "muy fuerte"
    return f"Correlación {strength} {direction} (rho={rho:.3f})"


def correlate(x: list[float], y: list[float], label_x: str, label_y: str) -> CorrelationPair:
    """Calcula Spearman rho y Pearson r entre dos vectores alineados por índice."""
    if len(x) != len(y):
        raise InsufficientDataError("Los vectores x e y deben tener la misma longitud")
    if len(x) < 3:
        raise InsufficientDataError(
            f"Se necesitan al menos 3 observaciones para correlacionar "
            f"'{label_x}' vs '{label_y}' (recibidas: {len(x)})"
        )

    spearman_result = scipy_stats.spearmanr(x, y)
    pearson_result = scipy_stats.pearsonr(x, y)

    rho = float(spearman_result.correlation) if not _is_nan(spearman_result.correlation) else 0.0

    return CorrelationPair(
        variable_x=label_x,
        variable_y=label_y,
        spearman_rho=round(rho, 4),
        pearson_r=round(float(pearson_result[0]), 4) if not _is_nan(pearson_result[0]) else 0.0,
        n=len(x),
        interpretation=_interpret(rho),
    )


def _is_nan(value: float) -> bool:
    return value != value  # NaN != NaN
