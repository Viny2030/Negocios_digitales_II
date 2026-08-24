"""
Engine y sesiones async de SQLAlchemy.

Con SQLite (default) esto es un único archivo `channel_analytics.db` en la
raíz del proyecto — no requiere ningún servicio externo corriendo. Cambiar
`DATABASE_URL` a `postgresql+asyncpg://...` (ver docker-compose.yml) escala
sin tocar el resto del código: todo el acceso a datos pasa por `get_session()`.
"""
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.db.models import Base

settings = get_settings()

_connect_args = {"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {}

engine = create_async_engine(settings.DATABASE_URL, echo=False, connect_args=_connect_args)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def _migrate_add_channel_type_column(conn: AsyncConnection) -> None:
    """
    Migración liviana in-place para instalaciones SQLite que ya tenían
    `tracked_channels` creada por una versión anterior del código (sin
    `channel_type_id`) — `create_all` solo crea tablas que faltan, nunca
    altera columnas de una tabla existente. No-op en instalaciones nuevas
    (donde `create_all` ya crea la columna de una) y en Postgres (que
    necesitaría una migración real tipo Alembic, fuera del alcance de
    este proyecto universitario).
    """
    if conn.engine.dialect.name != "sqlite":
        return
    result = await conn.execute(text("PRAGMA table_info(tracked_channels)"))
    columns = {row[1] for row in result.fetchall()}
    if "channel_type_id" not in columns:
        await conn.execute(text(
            "ALTER TABLE tracked_channels ADD COLUMN channel_type_id INTEGER REFERENCES channel_types(id)"
        ))


async def _seed_default_channel_types() -> None:
    """
    Siembra el catálogo (`channel_types`) con las 15 categorías nativas de
    YouTube (`is_custom=False`) la primera vez que arranca la app, para
    que "tipo de canal" tenga opciones útiles de una sin que el usuario
    tenga que crearlas a mano. No-op si la tabla ya tiene filas (no
    pisa tipos que el usuario haya editado/agregado).
    """
    # Import diferido: evita un ciclo de imports (collectors -> config, y
    # este módulo ya es importado por config indirectamente en algunos tests).
    from app.db.models import ChannelType
    from app.services.collectors.youtube import DISCOVER_CATEGORY_LABELS
    from app.services.tracked_channels import slugify

    async with async_session_factory() as session:
        existing = await session.execute(text("SELECT COUNT(*) FROM channel_types"))
        if existing.scalar_one() > 0:
            return
        for label in DISCOVER_CATEGORY_LABELS.values():
            session.add(ChannelType(name=label, slug=slugify(label), is_custom=False))
        await session.commit()


async def init_db() -> None:
    """
    Crea las tablas si no existen, corre la migración liviana de
    `channel_type_id` y siembra el catálogo de tipos por default.
    Llamado en el startup de FastAPI.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _migrate_add_channel_type_column(conn)
    await _seed_default_channel_types()


@asynccontextmanager
async def get_session_ctx() -> AsyncIterator[AsyncSession]:
    """Uso fuera de una request FastAPI (p. ej. desde el worker/scheduler)."""
    async with async_session_factory() as session:
        yield session


async def get_session() -> AsyncIterator[AsyncSession]:
    """Dependency de FastAPI: `session: AsyncSession = Depends(get_session)`."""
    async with async_session_factory() as session:
        yield session
