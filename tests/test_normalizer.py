"""Tests unitarios de la capa de normalización."""
import pytest

from app.models.domain import ContentTier, Platform
from app.services.analytics.normalizer import (
    normalize_tiktok_channel,
    normalize_youtube_channel,
    normalized_engagement_rate,
)


def test_normalized_engagement_rate_basic():
    assert normalized_engagement_rate(interactions=50, direct_consumption=1000) == 5.0


def test_normalized_engagement_rate_zero_consumption():
    # No debe lanzar ZeroDivisionError: canal sin vistas registradas.
    assert normalized_engagement_rate(interactions=10, direct_consumption=0) == 0.0


def test_normalize_youtube_channel_maps_fields_correctly():
    raw = {
        "id": "UC12345",
        "snippet": {"title": "Canal de Prueba", "customUrl": "@prueba"},
        "statistics": {
            "subscriberCount": "150000",
            "viewCount": "5000000",
            "videoCount": "200",
            "commentCount": "12000",
        },
    }
    channel = normalize_youtube_channel(raw)

    assert channel.universal_id == "youtube:UC12345"
    assert channel.platform == Platform.YOUTUBE
    assert channel.followers == 150_000
    assert channel.total_views == 5_000_000
    assert channel.tier == ContentTier.MID  # 100k-500k
    assert channel.normalized_er == pytest.approx(0.24, rel=1e-2)


def test_normalize_tiktok_channel_maps_fields_correctly():
    raw = {
        "user_id": "tt789",
        "unique_id": "pruebatiktok",
        "nickname": "Prueba TikTok",
        "follower_count": 2_000_000,
        "video_count": 300,
        "video_views_sum": 40_000_000,
        "likes_sum": 3_000_000,
        "comments_sum": 100_000,
        "shares_sum": 50_000,
        "saves_sum": 80_000,
    }
    channel = normalize_tiktok_channel(raw)

    assert channel.universal_id == "tiktok:tt789"
    assert channel.platform == Platform.TIKTOK
    assert channel.followers == 2_000_000
    assert channel.tier == ContentTier.MEGA  # > 1M
    assert channel.raw_interactions == 3_230_000
    assert channel.normalized_er > 0


def test_content_tier_classification_boundaries():
    assert ContentTier.classify(9_999) == ContentTier.NANO
    assert ContentTier.classify(10_000) == ContentTier.MICRO
    assert ContentTier.classify(100_000) == ContentTier.MID
    assert ContentTier.classify(500_000) == ContentTier.MACRO
    assert ContentTier.classify(1_000_000) == ContentTier.MEGA
