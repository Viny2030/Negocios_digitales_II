"""
Tests de `services/analytics/projections.py`: extrapolación lineal simple
(sin IA) sobre snapshots semanales de un canal trackeado.
"""
from datetime import date, timedelta

import pytest

from app.core.exceptions import InsufficientDataError
from app.services.analytics.projections import (
    MIN_SNAPSHOTS_FOR_PROJECTION,
    PROJECTABLE_FIELDS,
    project_channel,
    project_metric,
)


class _FakeSnapshot:
    """Doble liviano de ChannelMetricSnapshot: solo necesitamos sus atributos numéricos."""

    def __init__(self, snapshot_date, followers, total_views, total_posts, normalized_er):
        self.snapshot_date = snapshot_date
        self.followers = followers
        self.total_views = total_views
        self.total_posts = total_posts
        self.normalized_er = normalized_er


def _weekly_snapshots(weeks: int, start_followers: int, weekly_growth: int) -> list[_FakeSnapshot]:
    base = date(2026, 1, 5)  # un lunes
    return [
        _FakeSnapshot(
            snapshot_date=base + timedelta(weeks=i),
            followers=start_followers + i * weekly_growth,
            total_views=(start_followers + i * weekly_growth) * 20,
            total_posts=10 + i,
            normalized_er=2.0,
        )
        for i in range(weeks)
    ]


def test_project_metric_rejects_unknown_field():
    snapshots = _weekly_snapshots(4, 1000, 100)
    with pytest.raises(InsufficientDataError):
        project_metric(snapshots, "no_existe")


def test_project_metric_requires_minimum_history():
    snapshots = _weekly_snapshots(MIN_SNAPSHOTS_FOR_PROJECTION - 1, 1000, 100)
    with pytest.raises(InsufficientDataError):
        project_metric(snapshots, "followers")


def test_project_metric_extrapolates_linear_growth():
    snapshots = _weekly_snapshots(5, 1000, 100)  # +100 seguidores/semana
    result = project_metric(snapshots, "followers", weeks_ahead=[1, 4])
    assert result["field"] == "followers"
    assert result["history_points"] == 5
    assert result["weekly_trend"] == pytest.approx(100.0, abs=1.0)

    last_followers = snapshots[-1].followers
    proj_1w = next(p for p in result["projections"] if p["weeks_ahead"] == 1)
    proj_4w = next(p for p in result["projections"] if p["weeks_ahead"] == 4)
    assert proj_1w["projected_value"] == pytest.approx(last_followers + 100, abs=1.0)
    assert proj_4w["projected_value"] == pytest.approx(last_followers + 400, abs=1.0)
    assert proj_4w["projected_date"] == snapshots[-1].snapshot_date + timedelta(weeks=4)


def test_project_metric_never_projects_negative_values():
    # Tendencia fuertemente decreciente: la proyección lejana no debe dar negativo.
    snapshots = _weekly_snapshots(4, 100, -50)
    result = project_metric(snapshots, "followers", weeks_ahead=[52])
    assert result["projections"][0]["projected_value"] >= 0.0


def test_project_channel_skips_fields_without_enough_history_but_keeps_others():
    snapshots = _weekly_snapshots(MIN_SNAPSHOTS_FOR_PROJECTION, 1000, 50)
    results = project_channel(snapshots)
    fields = {r["field"] for r in results}
    assert fields.issubset(set(PROJECTABLE_FIELDS))
    assert "followers" in fields


def test_project_channel_raises_if_no_field_has_enough_history():
    snapshots = _weekly_snapshots(MIN_SNAPSHOTS_FOR_PROJECTION - 1, 1000, 50)
    with pytest.raises(InsufficientDataError):
        project_channel(snapshots)
