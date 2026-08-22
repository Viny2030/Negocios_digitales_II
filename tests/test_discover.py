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
from app.services.collectors.base import DEFAULT_DISCOVER_TOPICS
from app.services.collectors.tiktok import TikTokCollector
from app.services.collectors.youtube import DISCOVER_CATEGORY_IDS, YouTubeCollector
from app.services.orchestrator import category_label, discover_by_category_unified, discover_unified_channels


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


# ---------------------------------------------------------------------
# discover_by_category() / GET /channels/discover/by-category — un ranking
# independiente por cada categoría/tópico, en vez de una sola lista mezclada.
# ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_base_discover_by_category_returns_one_key_per_seed_topic():
    """TikTok cae al fallback genérico: un ranking por cada tópico semilla."""
    collector = TikTokCollector()
    by_topic = await collector.discover_by_category(limit_per_category=10)
    assert set(by_topic.keys()) == set(DEFAULT_DISCOVER_TOPICS)
    assert all(len(raw) > 0 for raw in by_topic.values())


@pytest.mark.asyncio
async def test_youtube_discover_by_category_falls_back_to_mock_without_credentials():
    collector = YouTubeCollector()
    by_topic = await collector.discover_by_category(limit_per_category=10)
    assert set(by_topic.keys()) == set(DEFAULT_DISCOVER_TOPICS)


@pytest.mark.asyncio
async def test_discover_by_category_unified_keeps_categories_independent():
    by_platform = await discover_by_category_unified(
        platforms=[Platform.YOUTUBE], limit_per_category=10, sort_by="followers",
    )
    by_category = by_platform[Platform.YOUTUBE]
    assert len(by_category) > 1
    for channels in by_category.values():
        assert len(channels) <= 10
        followers = [c.followers for c in channels]
        assert followers == sorted(followers, reverse=True)


@pytest.mark.asyncio
async def test_discover_by_category_unified_rejects_invalid_sort_by():
    with pytest.raises(InsufficientDataError):
        await discover_by_category_unified(
            platforms=[Platform.YOUTUBE], limit_per_category=10, sort_by="not_a_real_field",
        )


def test_category_label_maps_youtube_ids_and_passes_through_generic_topics():
    # Un ID real de categoría de YouTube tiene nombre legible propio.
    assert category_label(Platform.YOUTUBE, "10") == "Música"
    # Un tópico del fallback genérico (TikTok, o YouTube sin credenciales)
    # ya es legible tal cual — se devuelve con formato título.
    assert category_label(Platform.TIKTOK, "música") == "Música"
    # Todas las categorías reales de YouTube tienen que tener nombre propio
    # (si no, el dashboard mostraría el ID numérico crudo).
    for category_id in DISCOVER_CATEGORY_IDS:
        label = category_label(Platform.YOUTUBE, category_id)
        assert label != category_id
