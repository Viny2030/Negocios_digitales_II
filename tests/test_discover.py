"""
Tests de "todos los temas" (GET /channels/discover, sin categoría/tema
puntual): el `discover()` genérico de `BaseCollector`, el override de
`YouTubeCollector` cuando no hay credenciales, y el orquestador que ordena
de mayor a menor y deduplica.

El modo mock queda forzado por el fixture autouse `force_mock_mode` de
`tests/conftest.py`, así que estos tests no dependen de si `.env` tiene o
no una API key real cargada.
"""
import pytest

from app.core.exceptions import InsufficientDataError
from app.models.domain import Platform
from app.services.collectors.tiktok import TikTokCollector
from app.services.collectors.youtube import YouTubeCollector
from app.services.orchestrator import discover_unified_channels


@pytest.mark.asyncio
async def test_base_discover_combines_multiple_seed_topics():
    """TikTok no sobreescribe discover(): usa el fallback genérico de
    BaseCollector, que reparte el límite entre varios tópicos semilla."""
    collector = TikTokCollector()
    raw = await collector.discover(limit=20)
    assert len(raw) > 0


@pytest.mark.asyncio
async def test_youtube_discover_falls_back_to_mock_without_credentials():
    collector = YouTubeCollector()
    raw = await collector.discover(limit=20)
    assert len(raw) > 0
    assert all(item.get("_mock") for item in raw)


@pytest.mark.asyncio
async def test_discover_unified_channels_sorts_descending_by_metric():
    channels_by_platform = await discover_unified_channels(
        platforms=[Platform.YOUTUBE], limit=15, sort_by="followers",
    )
    channels = channels_by_platform[Platform.YOUTUBE]
    assert 0 < len(channels) <= 15
    followers = [c.followers for c in channels]
    assert followers == sorted(followers, reverse=True)


@pytest.mark.asyncio
async def test_discover_unified_channels_supports_other_metrics():
    channels_by_platform = await discover_unified_channels(
        platforms=[Platform.YOUTUBE], limit=15, sort_by="normalized_er",
    )
    channels = channels_by_platform[Platform.YOUTUBE]
    ner_values = [c.normalized_er for c in channels]
    assert ner_values == sorted(ner_values, reverse=True)


@pytest.mark.asyncio
async def test_discover_unified_channels_dedupes_by_universal_id():
    channels_by_platform = await discover_unified_channels(
        platforms=[Platform.YOUTUBE], limit=50, sort_by="followers",
    )
    ids = [c.universal_id for c in channels_by_platform[Platform.YOUTUBE]]
    assert len(ids) == len(set(ids))


@pytest.mark.asyncio
async def test_discover_unified_channels_rejects_invalid_sort_by():
    with pytest.raises(InsufficientDataError):
        await discover_unified_channels(platforms=[Platform.YOUTUBE], limit=10, sort_by="not_a_real_field")
