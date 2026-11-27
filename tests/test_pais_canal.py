"""País declarado del canal: normalización desde YouTube y actualización en cada foto."""
from datetime import date

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.models import Base, TrackedChannel
from app.models.domain import Platform
from app.services.analytics.normalizer import normalize_youtube_channel
from app.services.collectors.youtube import YouTubeCollector
from app.services.tracked_channels import upsert_snapshot_from_channel


def _raw(country=None):
    snippet = {"title": "Canal", "customUrl": "@canal"}
    if country is not None:
        snippet["country"] = country
    return {"id": "UC1", "snippet": snippet, "statistics": {"subscriberCount": "1000", "viewCount": "5000"}}


@pytest.mark.parametrize(
    ("value", "expected"),
    [("AR", "AR"), ("ar", "AR"), (" mx ", "MX"), (None, None), ("", None), ("ARG", None), ("1A", None)],
)
def test_normaliza_el_pais(value, expected):
    assert normalize_youtube_channel(_raw(value)).country == expected


def test_mock_declara_pais_sin_alterar_los_datos():
    collector = YouTubeCollector()
    first = collector._mock_single("@canaldeprueba")
    again = collector._mock_single("@canaldeprueba")
    assert first == again
    assert first["snippet"].get("country") in {None, *filter(None, YouTubeCollector._MOCK_COUNTRIES)}


@pytest.fixture
async def session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        yield s
    await engine.dispose()


async def test_la_foto_actualiza_el_pais(session):
    tracked = TrackedChannel(platform=Platform.YOUTUBE.value, native_id="UC1")
    session.add(tracked)
    await session.commit()

    await upsert_snapshot_from_channel(session, tracked.id, normalize_youtube_channel(_raw("AR")), date(2026, 11, 26))
    await session.refresh(tracked)
    assert tracked.country == "AR"

    # Si deja de declararlo, se conserva el último conocido.
    await upsert_snapshot_from_channel(session, tracked.id, normalize_youtube_channel(_raw()), date(2026, 11, 27))
    await session.refresh(tracked)
    assert tracked.country == "AR"
