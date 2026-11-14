"""La curva de Lorenz es coherente con el coeficiente de Gini que ya calcula el sistema."""

import pytest

from app.core.exceptions import InsufficientDataError
from app.services.analytics.inequality import gini_coefficient, lorenz_curve


def _area(p: list[float], lz: list[float]) -> float:
    # trapecios a mano: np.trapz/np.trapezoid cambian de nombre entre versiones de numpy
    return sum((p[i] - p[i - 1]) * (lz[i] + lz[i - 1]) / 2 for i in range(1, len(p)))


@pytest.mark.parametrize(
    "values",
    [
        [10, 10, 10, 10],
        [0, 0, 0, 100],
        [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
        [1_200, 35_000, 90, 4_500_000, 12_000, 780_000, 3],
    ],
)
def test_gini_es_uno_menos_dos_veces_el_area_bajo_lorenz(values):
    p, lz = lorenz_curve(values)
    assert gini_coefficient(values) == pytest.approx(1 - 2 * _area(p, lz), abs=1e-12)


def test_la_curva_va_de_cero_a_uno_y_no_decrece():
    p, lz = lorenz_curve([5, 1, 3])
    assert (p[0], lz[0]) == (0.0, 0.0)
    assert p[-1] == pytest.approx(1.0) and lz[-1] == pytest.approx(1.0)
    assert all(b >= a for a, b in zip(lz, lz[1:], strict=False))
    assert all(
        lz[i] <= p[i] + 1e-12 for i in range(len(p))
    )  # nunca por encima de la igualdad


def test_sin_valores_positivos_no_hay_curva():
    with pytest.raises(InsufficientDataError):
        lorenz_curve([0, 0, 0])
