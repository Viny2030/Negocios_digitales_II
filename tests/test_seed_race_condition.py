"""
Regresión de la protección contra condición de carrera agregada a
`app/db/session.py::_seed_default_channel_types`.

Esa función hace "leer conteo, insertar si es 0" sin ningún lock: si dos
procesos (o dos `uvicorn --reload` locales) arrancan al mismo tiempo, los
dos pueden pasar el chequeo "¿hay filas?" antes de que cualquiera de los
dos commitee, y el segundo `commit()` choca contra el `UNIQUE` de
`name`/`slug` ya insertado por el primero. Antes de este fix, ese
`IntegrityError` no se atajaba y tiraba abajo el startup entero.

Se fuerza el `IntegrityError` justo en `commit()` (en vez de simular la
carrera con dos tareas async reales) porque el timing exacto de esa
condición de carrera depende del modo de locking de SQLite y no es
reproducible de forma determinística en un test — lo que sí es
determinístico, y lo que importa probar, es que la función ataja la
excepción en el lugar correcto y no la deja propagarse.
"""
import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.db.session as db_session
from app.db.models import Base


@pytest.mark.asyncio
async def test_seed_does_not_raise_when_commit_hits_a_unique_violation(monkeypatch):
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    real_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    rollback_called = {"value": False}

    def factory_with_failing_commit():
        """
        Devuelve una sesión real (mismas tablas, mismo engine) pero con
        `commit()` reemplazado para simular justo el `IntegrityError` que
        dispara una carrera perdida contra otro proceso sembrando el mismo
        catálogo al mismo tiempo.
        """
        session = real_factory()

        async def failing_commit():
            raise IntegrityError(
                "INSERT INTO channel_types (...)", {}, Exception("UNIQUE constraint failed: channel_types.slug")
            )

        real_rollback = session.rollback

        async def tracking_rollback():
            rollback_called["value"] = True
            await real_rollback()

        monkeypatch.setattr(session, "commit", failing_commit)
        monkeypatch.setattr(session, "rollback", tracking_rollback)
        return session

    monkeypatch.setattr(db_session, "async_session_factory", factory_with_failing_commit)

    # Antes del fix, esto propagaba `IntegrityError` y tiraba abajo el
    # startup de FastAPI (`init_db()` la llama sin try/except alrededor).
    await db_session._seed_default_channel_types()

    assert rollback_called["value"] is True
    await engine.dispose()
