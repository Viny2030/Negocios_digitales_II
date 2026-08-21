"""
Engine y sesiones async de SQLAlchemy.

Con SQLite (default) esto es un único archivo `channel_analytics.db` en la
raíz del proyecto — no requiere ningún servicio externo corriendo. Cambiar
`DATABASE_URL` a `postgresql+asyncpg://...` (ver docker-compose.yml) escala
sin tocar el resto del código: todo el acceso a datos pasa por `get_session()`.
"""
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.db.models import Base

settings = get_settings()

_connect_args = {"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {}

engine = create_async_engine(settings.DATABASE_URL, echo=False, connect_args=_connect_args)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db() -> None:
    """Crea las tablas si no existen. Llamado en el startup de FastAPI."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@asynccontextmanager
async def get_session_ctx() -> AsyncIterator[AsyncSession]:
    """Uso fuera de una request FastAPI (p. ej. desde el worker/scheduler)."""
    async with async_session_factory() as session:
        yield session


async def get_session() -> AsyncIterator[AsyncSession]:
    """Dependency de FastAPI: `session: AsyncSession = Depends(get_session)`."""
    async with async_session_factory() as session:
        yield session
