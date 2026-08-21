"""Tests unitarios del motor estadístico (descriptive / inequality / correlation / anomalies)."""
import pytest

from app.core.exceptions import InsufficientDataError
from app.models.domain import ContentFormat, ContentTier, Platform
from app.models.schemas import UnifiedChannel
from app.services.analytics.anomalies import detect_anomalies
from app.services.analytics.correlation import correlate
from app.services.analytics.descriptive import describe
from app.services.analytics.inequality import gini_coefficient, pareto_alpha, top_decile_share


def test_describe_basic_distribution():
    values = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
    stats = describe(values, "test_metric")

    assert stats.n == 10
    assert stats.median == 55
    assert stats.p25 < stats.median < stats.p75
    assert stats.iqr == pytest.approx(stats.p75 - stats.p25)
    assert stats.min == 10
    assert stats.max == 100
    assert stats.range == 90
    assert stats.p5 <= stats.p10 <= stats.p25
    assert stats.p95 >= stats.p90 >= stats.p75
    assert stats.coefficient_of_variation == pytest.approx(stats.std_dev / stats.mean, abs=1e-3)


def test_describe_coefficient_of_variation_zero_mean():
    # Con mean=0 no debe lanzar ZeroDivisionError.
    stats = describe([-10, 10], "centered_metric")
    assert stats.coefficient_of_variation == 0.0


def test_describe_raises_with_insufficient_data():
    with pytest.raises(InsufficientDataError):
        describe([42], "test_metric")


def test_gini_coefficient_perfect_equality():
    values = [100.0] * 10
    assert gini_coefficient(values) == pytest.approx(0.0, abs=1e-9)


def test_gini_coefficient_high_inequality():
    # Un solo canal concentra casi toda la audiencia -> Gini cercano a 1.
    values = [1.0] * 99 + [1_000_000.0]
    gini = gini_coefficient(values)
    assert gini > 0.9


def test_pareto_alpha_returns_none_with_constant_values():
    # Sin variación por encima de x_min, no se puede estimar alpha.
    assert pareto_alpha([100.0, 100.0, 100.0]) is None


def test_top_decile_share_range():
    values = [1, 2, 3, 4, 5, 6, 7, 8, 9, 1000]
    share = top_decile_share(values)
    assert 0 <= share <= 1
    assert share > 0.9  # el outlier domina el top 10%


def test_correlate_perfect_positive_relationship():
    x = [1, 2, 3, 4, 5]
    y = [2, 4, 6, 8, 10]
    pair = correlate(x, y, "x", "y")
    assert pair.spearman_rho == pytest.approx(1.0)
    assert pair.pearson_r == pytest.approx(1.0)


def _make_channel(uid: str, followers: int, ner: float) -> UnifiedChannel:
    return UnifiedChannel(
        universal_id=uid,
        native_id=uid,
        platform=Platform.YOUTUBE,
        content_format=ContentFormat.VOD,
        name=uid,
        followers=followers,
        total_views=followers * 20,
        total_posts=100,
        raw_interactions=10,
        normalized_er=ner,
        tier=ContentTier.classify(followers),
    )


def test_detect_anomalies_flags_large_channel_with_low_engagement():
    channels = [
        _make_channel("a", 1_000, 5.0),
        _make_channel("b", 2_000, 4.5),
        _make_channel("c", 3_000, 5.5),
        _make_channel("d", 1_000_000, 0.01),  # muchos seguidores, ER casi nulo
    ]
    flagged = detect_anomalies(channels)
    flagged_ids = {f.universal_id for f in flagged}
    assert "d" in flagged_ids
