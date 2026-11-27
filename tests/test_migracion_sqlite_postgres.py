"""
scripts/migrar_sqlite_a_postgres.py, probado de SQLite a SQLite (sin servidor Postgres en el
CI). El paso de secuencias (`setval`) solo corre contra Postgres; el resto es el mismo código.
"""

from datetime import date, datetime

import pytest
from sqlalchemy import func, inspect, select
from sqlalchemy.ext.asyncio import create_async_engine

from app.db.models import Base, ChannelMetricSnapshot, ChannelType, TrackedChannel, User
from scripts.migrar_sqlite_a_postgres import migrar


async def _origen(path, tier="mega"):
    url = f"sqlite+aiosqlite:///{path}"
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(
            ChannelType.__table__.insert(),
            [
                {
                    "id": 7,
                    "name": "Noticias",
                    "slug": "noticias",
                    "is_custom": False,
                    "created_at": datetime(2026, 1, 1),
                }
            ],
        )
        await conn.execute(
            TrackedChannel.__table__.insert(),
            [
                {
                    "id": 3,
                    "platform": "youtube",
                    "native_id": "UC_a",
                    "active": True,
                    "channel_type_id": 7,
                    "created_at": datetime(2026, 1, 1),
                },
                {
                    "id": 9,
                    "platform": "youtube",
                    "native_id": "UC_b",
                    "active": False,
                    "channel_type_id": None,
                    "created_at": datetime(2026, 1, 2),
                },
            ],
        )
        await conn.execute(
            ChannelMetricSnapshot.__table__.insert(),
            [
                {
                    "tracked_channel_id": 3,
                    "snapshot_date": date(2026, 1, d),
                    "followers": 10_000_000_000 + d,
                    "total_views": 35_000_000_000,
                    "total_posts": 900,
                    "raw_interactions": 1_000,
                    "normalized_er": 2.5,
                    "tier": tier,
                    "fetched_at": datetime(2026, 1, d, 9),
                }
                for d in range(1, 6)
            ],
        )
        await conn.execute(
            User.__table__.insert(),
            [
                {
                    "email": "a@b.c",
                    "hashed_password": "x",
                    "plan": "free",
                    "report_credits": 0,
                    "is_admin": False,
                }
            ],
        )
    await engine.dispose()
    return url


async def _contar(url):
    engine = create_async_engine(url)
    async with engine.connect() as conn:
        out = {
            t.name: (
                await conn.execute(select(func.count()).select_from(t))
            ).scalar_one()
            for t in Base.metadata.sorted_tables
        }
        out["sum_followers"] = (
            await conn.execute(select(func.sum(ChannelMetricSnapshot.followers)))
        ).scalar()
    await engine.dispose()
    return out


async def test_ensayo_no_escribe_y_aplicar_copia_todo(tmp_path):
    origen = await _origen(tmp_path / "origen.db")
    destino = f"sqlite+aiosqlite:///{tmp_path / 'destino.db'}"

    assert await migrar(origen, destino, aplicar=False) == 0
    engine = create_async_engine(destino)
    async with engine.connect() as conn:
        tablas = await conn.run_sync(lambda c: inspect(c).get_table_names())
    await engine.dispose()
    assert tablas == []  # el ensayo no crea ni escribe nada

    assert await migrar(origen, destino, aplicar=True) == 0
    assert await _contar(destino) == await _contar(origen)


async def test_conserva_ids_y_claves_foraneas(tmp_path):
    origen = await _origen(tmp_path / "origen.db")
    destino = f"sqlite+aiosqlite:///{tmp_path / 'destino.db'}"
    assert await migrar(origen, destino, aplicar=True) == 0

    engine = create_async_engine(destino)
    async with engine.connect() as conn:
        ids = sorted((await conn.execute(select(TrackedChannel.id))).scalars())
        refs = set(
            (
                await conn.execute(select(ChannelMetricSnapshot.tracked_channel_id))
            ).scalars()
        )
        tipo = (
            await conn.execute(
                select(TrackedChannel.channel_type_id).where(TrackedChannel.id == 3)
            )
        ).scalar()
    await engine.dispose()
    assert ids == [3, 9] and refs == {3} and tipo == 7


async def test_texto_mas_largo_que_la_columna_frena_la_migracion(tmp_path, capsys):
    origen = await _origen(tmp_path / "origen.db", tier="x" * 25)  # tier es String(20)
    destino = f"sqlite+aiosqlite:///{tmp_path / 'destino.db'}"
    assert await migrar(origen, destino, aplicar=True) == 1
    assert "channel_metric_snapshots.tier" in capsys.readouterr().out


async def test_destino_con_datos_no_se_pisa(tmp_path, capsys):
    origen = await _origen(tmp_path / "origen.db")
    destino = await _origen(tmp_path / "destino.db")
    assert await migrar(origen, destino, aplicar=True) == 1
    assert "ya tiene datos" in capsys.readouterr().out


@pytest.mark.parametrize(
    "url", ["postgres://u:p@h:5432/db", "postgresql://u:p@h:5432/db"]
)
def test_acepta_la_url_tal_cual_la_da_railway(url, monkeypatch):
    import scripts.migrar_sqlite_a_postgres as m

    capturado = {}

    async def falso(origen, destino, aplicar):
        capturado["destino"] = destino
        return 0

    monkeypatch.setattr(m, "migrar", falso)
    assert m.main(["--destino", url]) == 0
    assert capturado["destino"] == "postgresql+asyncpg://u:p@h:5432/db"
