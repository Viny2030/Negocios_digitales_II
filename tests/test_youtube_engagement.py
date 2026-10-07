"""
Engagement de YouTube a partir de los videos recientes de cada canal.

La API de YouTube ya no devuelve `statistics.commentCount` a nivel canal (y
nunca devolvió likes agregados): antes de este cambio el NER de TODOS los
canales reales daba 0. Estos tests simulan la API real con
`httpx.MockTransport` (sin red ni cuota) para verificar que el NER sale de
(likes + comentarios) / vistas de los últimos videos subidos.
"""

import httpx
import pytest

import app.services.collectors.youtube as youtube_module
from app.models.domain import Platform
from app.services.analytics.normalizer import normalize_channels, normalize_youtube_channel
from app.services.collectors.youtube import YouTubeCollector

CHANNEL_ID = "UCabcdefghijklmnopqrstuv"
BIG_VIEWS = 75_565_565_453  # > 2^31: el caso que rompía el INSERT en Postgres


def _handler(quota_on_playlist: bool = False):
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path.rsplit("/", 1)[-1]
        calls.append(path)
        if path == "channels":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": CHANNEL_ID,
                            "snippet": {"title": "Canal real", "customUrl": "@canalreal"},
                            # Como responde la API hoy: SIN commentCount.
                            "statistics": {
                                "subscriberCount": "29500000",
                                "viewCount": str(BIG_VIEWS),
                                "videoCount": "900",
                            },
                        }
                    ]
                },
            )
        if path == "playlistItems":
            if quota_on_playlist:
                return httpx.Response(403, text='{"error": {"errors": [{"reason": "quotaExceeded"}]}}')
            assert request.url.params["playlistId"] == "UU" + CHANNEL_ID[2:]
            return httpx.Response(
                200,
                json={
                    "items": [
                        {"contentDetails": {"videoId": "v1"}},
                        {"contentDetails": {"videoId": "v2"}},
                    ]
                },
            )
        if path == "videos":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {"id": "v1", "statistics": {"viewCount": "1000", "likeCount": "40", "commentCount": "10"}},
                        {"id": "v2", "statistics": {"viewCount": "3000", "likeCount": "90", "commentCount": "20"}},
                    ]
                },
            )
        return httpx.Response(404)

    return handler, calls


@pytest.fixture
def fake_youtube(monkeypatch):
    monkeypatch.setattr(youtube_module.settings, "YOUTUBE_API_KEY", "fake-key")
    real_client = httpx.AsyncClient

    def install(handler):
        transport = httpx.MockTransport(handler)
        monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real_client(transport=transport, **kw))

    return install


async def test_ner_sale_de_los_videos_recientes(fake_youtube):
    handler, calls = _handler()
    fake_youtube(handler)

    raw = await YouTubeCollector().get_channels_batch([CHANNEL_ID])
    channel = normalize_channels(raw, Platform.YOUTUBE)[0]

    # (40 + 90 likes + 10 + 20 comentarios) / (1000 + 3000 vistas) = 4%
    assert channel.normalized_er == pytest.approx(4.0)
    assert channel.likes == 130
    assert channel.comments == 30
    assert channel.raw_interactions == 160
    assert channel.engagement_videos_sampled == 2
    assert channel.total_views == BIG_VIEWS  # vistas del canal intactas
    assert channel.is_mock is False
    assert calls == ["channels", "playlistItems", "videos"]


async def test_sin_cuota_para_videos_el_canal_se_guarda_igual(fake_youtube):
    """Si se agota la cuota al muestrear videos, el canal NO se pierde: queda
    con NER "no disponible" (engagement_videos_sampled=None)."""
    handler, _ = _handler(quota_on_playlist=True)
    fake_youtube(handler)

    raw = await YouTubeCollector().get_channels_batch([CHANNEL_ID])
    channel = normalize_channels(raw, Platform.YOUTUBE)[0]

    assert channel.followers == 29_500_000
    assert channel.engagement_videos_sampled is None
    assert channel.normalized_er == 0.0


async def test_muestreo_desactivado_no_gasta_cuota_extra(fake_youtube, monkeypatch):
    monkeypatch.setattr(youtube_module.settings, "YOUTUBE_ENGAGEMENT_RECENT_VIDEOS", 0)
    handler, calls = _handler()
    fake_youtube(handler)

    await YouTubeCollector().get_channels_batch([CHANNEL_ID])
    assert calls == ["channels"]


def test_mock_se_marca_como_simulado():
    raw = YouTubeCollector()._mock_single("@algo")
    channel = normalize_youtube_channel(raw)
    assert channel.is_mock is True


async def test_discover_muestrea_engagement_solo_de_los_canales_finales(fake_youtube, monkeypatch):
    """El trending junta muchos candidatos: el muestreo de videos (1 unidad de
    cuota por canal) se hace solo para los que quedan en el resultado."""
    from app.services.orchestrator import discover_unified_channels

    monkeypatch.setattr(youtube_module.settings, "DISCOVER_REGION_CODES", ["AR"])
    monkeypatch.setattr(youtube_module.settings, "DISCOVER_PAGES_PER_REGION_CATEGORY", 1)
    candidates = [f"UC{i:022d}" for i in range(6)]
    playlist_calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path.rsplit("/", 1)[-1]
        params = request.url.params
        if path == "videos" and params.get("chart") == "mostPopular":
            return httpx.Response(200, json={"items": [{"snippet": {"channelId": c}} for c in candidates]})
        if path == "channels":
            ids = params["id"].split(",")
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": c,
                            "snippet": {"title": c},
                            "statistics": {
                                "subscriberCount": str(1000 * (i + 1)),
                                "viewCount": "5000",
                                "videoCount": "10",
                            },
                        }
                        for i, c in enumerate(candidates)
                        if c in ids
                    ]
                },
            )
        if path == "playlistItems":
            playlist_calls.append(params["playlistId"])
            return httpx.Response(200, json={"items": [{"contentDetails": {"videoId": "v-" + params["playlistId"]}}]})
        if path == "videos":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {"id": vid, "statistics": {"viewCount": "100", "likeCount": "5", "commentCount": "1"}}
                        for vid in params["id"].split(",")
                    ]
                },
            )
        return httpx.Response(404)

    fake_youtube(handler)
    result = await discover_unified_channels([Platform.YOUTUBE], limit=2, sort_by="followers")
    channels = result[Platform.YOUTUBE]

    assert [c.native_id for c in channels] == [candidates[5], candidates[4]]
    assert len(playlist_calls) == 2  # no 6
    assert all(c.normalized_er == pytest.approx(6.0) for c in channels)
