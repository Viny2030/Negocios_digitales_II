"""
Tests de `services/analytics/recommendations.py`: motor de reglas (no IA)
que traduce benchmarks de industria + tendencia semanal en
recomendaciones de política general por métrica.
"""
from app.models.domain import Platform
from app.services.analytics.recommendations import recommend_for_channel


def test_recommend_flags_below_benchmark_engagement():
    # YouTube: rango esperado 1.5%-3.5% — 0.5% queda "below".
    items = recommend_for_channel(
        platform=Platform.YOUTUBE, followers=100_000, total_posts=50, normalized_er=0.5,
    )
    metrics = {i["metric"] for i in items}
    assert "normalized_er" in metrics
    below_item = next(i for i in items if i["metric"] == "normalized_er")
    assert below_item["priority"] == "alta"


def test_recommend_flags_above_benchmark_engagement_as_informational():
    items = recommend_for_channel(
        platform=Platform.YOUTUBE, followers=100_000, total_posts=50, normalized_er=5.0,
    )
    above_item = next(i for i in items if i["metric"] == "normalized_er")
    assert above_item["priority"] == "informativa"


def test_recommend_flags_negative_follower_trend():
    items = recommend_for_channel(
        platform=Platform.YOUTUBE, followers=100_000, total_posts=50, normalized_er=2.5,
        weekly_follower_trend=-25.0,
    )
    followers_item = next(i for i in items if i["metric"] == "followers")
    assert followers_item["priority"] == "alta"


def test_recommend_flags_stagnant_follower_trend():
    items = recommend_for_channel(
        platform=Platform.YOUTUBE, followers=100_000, total_posts=50, normalized_er=2.5,
        weekly_follower_trend=0.0,
    )
    followers_item = next(i for i in items if i["metric"] == "followers")
    assert followers_item["priority"] == "media"


def test_recommend_falls_back_to_general_note_when_nothing_is_flagged():
    items = recommend_for_channel(
        platform=Platform.YOUTUBE, followers=100_000, total_posts=50, normalized_er=2.5,
        weekly_follower_trend=10.0,
    )
    assert len(items) == 1
    assert items[0]["metric"] == "general"
