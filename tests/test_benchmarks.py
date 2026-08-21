"""Tests unitarios de los benchmarks de industria (métricas del medio)."""
import pytest

from app.models.domain import Platform
from app.services.analytics.benchmarks import compare_to_benchmark, get_benchmarks


def test_get_benchmarks_returns_youtube_and_tiktok():
    result = get_benchmarks([Platform.YOUTUBE, Platform.TIKTOK])
    platforms = {b.platform for b in result}
    assert platforms == {Platform.YOUTUBE, Platform.TIKTOK}


def test_get_benchmarks_filters_unsupported_platform():
    # Platform.ALL no tiene ficha propia de benchmark.
    result = get_benchmarks([Platform.YOUTUBE, Platform.ALL])
    assert len(result) == 1
    assert result[0].platform == Platform.YOUTUBE


def test_compare_to_benchmark_within_range():
    # YouTube: 1.5% - 3.5%
    comparison = compare_to_benchmark(Platform.YOUTUBE, 2.4)
    assert comparison.status == "within"
    assert comparison.delta_from_range_pct == 0.0


def test_compare_to_benchmark_below_range():
    comparison = compare_to_benchmark(Platform.YOUTUBE, 0.5)
    assert comparison.status == "below"
    assert comparison.delta_from_range_pct > 0


def test_compare_to_benchmark_above_range():
    # TikTok: 4.0% - 9.0%
    comparison = compare_to_benchmark(Platform.TIKTOK, 15.0)
    assert comparison.status == "above"
    assert comparison.delta_from_range_pct == pytest.approx(66.67, rel=1e-2)
