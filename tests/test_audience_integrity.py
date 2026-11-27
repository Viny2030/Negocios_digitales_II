"""Señales de audiencia inusual: casos inflados, casos genuinos y datos que faltan."""
from datetime import date, timedelta
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.main import app
from app.models.domain import ContentFormat, ContentTier, Platform
from app.models.schemas import UnifiedChannel
from app.services.analytics.anomalies import detect_anomalies
from app.services.analytics.audience_integrity import SINGLE_SIGNAL_CAP, assess_channel
from app.services.collectors.youtube import YouTubeCollector

client = TestClient(app)


def _channel(followers=100_000, total_views=5_000_000, posts=200, likes=3_000, comments=150,
             ner=3.15, views=(10_000,) * 10, sampled=10, platform=Platform.YOUTUBE, is_mock=False):
    return UnifiedChannel(
        universal_id=f"{platform.value}:x", native_id="x", platform=platform,
        content_format=ContentFormat.VOD, name="Canal", followers=followers, total_views=total_views,
        total_posts=posts, raw_interactions=likes + comments, likes=likes, comments=comments,
        normalized_er=ner, engagement_videos_sampled=sampled, recent_video_views=list(views) if views else None,
        tier=ContentTier.classify(followers), is_mock=is_mock,
    )


def _codes(assessment) -> set[str]:
    return {s.code for s in assessment.signals}


def _history(*followers_views, days=7):
    start = date(2026, 1, 1)
    return [
        SimpleNamespace(snapshot_date=start + timedelta(days=i * days), followers=f, total_views=v)
        for i, (f, v) in enumerate(followers_views)
    ]


def test_canal_genuino_no_tiene_senales():
    result = assess_channel(_channel())
    assert result.signals == []
    assert result.score == 0
    assert result.level == "sin_senales"


def test_canal_con_seguidores_comprados_pide_revision():
    result = assess_channel(_channel(
        followers=2_000_000, total_views=1_500_000, likes=20, comments=5, ner=0.02, views=(1_000,) * 10,
    ))
    assert {"few_views_for_followers", "low_engagement", "few_recent_views"} <= _codes(result)
    assert result.level == "alta"
    assert all(signal.detail for signal in result.signals)


def test_una_sola_senal_no_alcanza_para_revisar():
    result = assess_channel(_channel(total_views=50_000))
    assert _codes(result) == {"few_views_for_followers"}
    assert result.score <= SINGLE_SIGNAL_CAP
    assert result.level == "leve"


def test_engagement_no_medido_no_es_engagement_nulo():
    result = assess_channel(_channel(ner=0.0, likes=0, comments=0, sampled=None, views=None))
    assert "low_engagement" not in _codes(result)
    assert "Interacción" in result.signals_unavailable


def test_con_una_sola_senal_calculable_dice_datos_insuficientes():
    result = assess_channel(_channel(followers=500, total_views=0, posts=2, sampled=None, views=None))
    assert result.level == "datos_insuficientes"
    assert result.signals_evaluated < 2


def test_me_gusta_ocultos_no_cuentan_como_ausencia_de_me_gusta():
    result = assess_channel(_channel(likes=0, comments=0, ner=3.0))
    assert "views_without_likes" not in _codes(result)
    assert "likes_without_comments" not in _codes(result)


def test_comentarios_desactivados_no_son_senal():
    assert "likes_without_comments" not in _codes(assess_channel(_channel(likes=5_000, comments=0)))


def test_muchos_me_gusta_sin_comentarios_es_senal():
    assert "likes_without_comments" in _codes(assess_channel(_channel(likes=50_000, comments=10)))


def test_medio_con_historia_no_se_marca_por_pocas_vistas_recientes():
    """Caso real: medios con años de historia y decenas de miles de videos, cuyas vistas
    se reparten. Tienen cientos de vistas históricas por seguidor."""
    result = assess_channel(_channel(
        followers=20_000_000, total_views=7_500_000_000, posts=34_000, likes=2_000, comments=500,
        ner=0.82, views=(10_000,) * 10,
    ))
    assert "few_recent_views" not in _codes(result)


def test_pocas_vistas_recientes_cuentan_si_tampoco_hay_vistas_historicas():
    result = assess_channel(_channel(followers=1_000_000, total_views=20_000_000, views=(2_000,) * 10))
    assert "few_recent_views" in _codes(result)


def test_canal_de_un_suscriptor_no_dice_sin_senales():
    result = assess_channel(_channel(followers=1, total_views=6, posts=5, views=(1,) * 5), cohort_flagged=set())
    assert result.level == "datos_insuficientes"


def test_un_video_viral_pesa_poco():
    result = assess_channel(_channel(views=(10_000,) * 9 + (500_000,)))
    assert _codes(result) == {"isolated_view_spike"}
    assert result.level == "sin_senales"


def test_canal_chico_no_se_evalua_por_proporciones():
    result = assess_channel(_channel(followers=800, total_views=500, views=(5,) * 10))
    assert "few_views_for_followers" not in _codes(result)
    assert "few_recent_views" not in _codes(result)


def test_salto_de_seguidores_sin_vistas_es_senal_fuerte():
    snapshots = _history(
        (100_000, 5_000_000), (100_500, 5_050_000), (101_000, 5_100_000), (160_000, 5_110_000), (160_500, 5_150_000),
    )
    jump = next(s for s in assess_channel(_channel(), snapshots=snapshots).signals if s.code == "follower_jump")
    assert jump.points == 40


def test_salto_acompanado_de_vistas_pesa_menos():
    snapshots = _history(
        (100_000, 5_000_000), (100_500, 5_050_000), (101_000, 5_100_000), (160_000, 9_000_000), (160_500, 9_050_000),
    )
    jump = next(s for s in assess_channel(_channel(), snapshots=snapshots).signals if s.code == "follower_jump")
    assert jump.points == 30


def test_caida_de_seguidores_es_senal():
    snapshots = _history((200_000, 5_000_000), (200_500, 5_050_000), (150_000, 5_100_000), (150_500, 5_150_000))
    assert "follower_drop" in _codes(assess_channel(_channel(), snapshots=snapshots))


def test_crecimiento_parejo_no_es_senal():
    snapshots = _history(*[(100_000 + i * 1_000, 5_000_000 + i * 50_000) for i in range(8)])
    result = assess_channel(_channel(), snapshots=snapshots)
    assert not {"follower_jump", "follower_drop"} & _codes(result)


def test_el_salto_se_mide_por_dia_y_no_por_foto():
    """Un 6% en 60 días es crecimiento normal, aunque entre dos fotos parezca mucho."""
    snapshots = _history((100_000, 5_000_000), (106_000, 5_500_000), (112_000, 6_000_000), (118_000, 6_500_000), days=60)
    assert "follower_jump" not in _codes(assess_channel(_channel(), snapshots=snapshots))


def test_pocas_fotos_no_alcanzan_para_el_historial():
    result = assess_channel(_channel(), snapshots=_history((100_000, 1), (160_000, 2)))
    assert "Evolución de seguidores" in result.signals_unavailable


def test_el_detector_viejo_no_marca_canales_sin_engagement_medido():
    channels = [_channel(followers=f, ner=n) for f, n in [(1_000, 5.0), (2_000, 4.5), (3_000, 5.5), (4_000, 5.0)]]
    unmeasured = _channel(followers=1_000_000, ner=0.0, sampled=None, likes=0, comments=0, views=None)
    unmeasured.universal_id = "youtube:sin-medir"
    assert "youtube:sin-medir" not in {f.universal_id for f in detect_anomalies([*channels, unmeasured])}


def test_el_mock_trae_canales_inflados_y_es_reproducible():
    collector = YouTubeCollector()
    first = collector._mock_audience("clave", 10_000)
    assert first == collector._mock_audience("clave", 10_000)
    outcomes = [collector._mock_audience(f"canal{i}", 10_000)[0] for i in range(300)]
    assert 0.05 < sum(subs > 10_000 for subs in outcomes) / 300 < 0.30


def test_endpoint_ordena_por_puntaje_y_avisa_que_es_simulado():
    r = client.get("/api/v1/analytics/audience-integrity", params={"query": "fitness", "platform": "youtube", "limit": 30})
    assert r.status_code == 200, r.text
    body = r.json()
    scores = [c["score"] for c in body["channels"]]
    assert scores == sorted(scores, reverse=True)
    assert body["mock_data"] is True
    assert "no una prueba" in body["disclaimer"]
    assert any(c["level"] in ("revisar", "alta") for c in body["channels"])
    assert any(c["level"] == "sin_senales" for c in body["channels"])


def test_endpoint_rechaza_platform_all():
    r = client.get("/api/v1/analytics/audience-integrity", params={"query": "fitness", "platform": "all"})
    assert r.status_code == 400
