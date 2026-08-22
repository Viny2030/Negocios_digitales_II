"""
Tests de la capa de usuarios/planes (`services/users.py`): alta de cuenta,
email duplicado, y simulación manual de cada plan de suscripción
(`set_user_plan`) sin pasarela de pago real. Mismo patrón de engine
SQLite en memoria que `test_tracked_channels.py`.
"""
from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.exceptions import UserAlreadyExistsError
from app.core.security import verify_password
from app.db.models import Base
from app.models.domain import Plan
from app.services.users import (
    consume_report_credit,
    create_user,
    get_user_by_email,
    get_user_by_id,
    set_user_plan,
)


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


@pytest.mark.asyncio
async def test_create_user_starts_on_free_plan_with_hashed_password(session):
    user = await create_user(session, email="Ana@Example.com", password="supersecreta123")
    assert user.id is not None
    assert user.email == "ana@example.com"  # normalizado a minúsculas
    assert user.plan == "free"
    assert user.report_credits == 0
    assert user.hashed_password != "supersecreta123"
    assert verify_password("supersecreta123", user.hashed_password) is True
    assert user.has_full_stats_access is False
    assert user.has_premium_access is False


@pytest.mark.asyncio
async def test_create_user_duplicate_email_raises(session):
    await create_user(session, email="dup@example.com", password="password123")
    with pytest.raises(UserAlreadyExistsError):
        await create_user(session, email="DUP@example.com", password="otraClave123")


@pytest.mark.asyncio
async def test_get_user_by_email_and_id(session):
    created = await create_user(session, email="busca@example.com", password="password123")
    by_email = await get_user_by_email(session, "busca@example.com")
    by_id = await get_user_by_id(session, created.id)
    assert by_email.id == created.id
    assert by_id.id == created.id
    assert await get_user_by_email(session, "no-existe@example.com") is None


@pytest.mark.asyncio
async def test_set_user_plan_mensual_grants_full_access_until_expiry(session):
    user = await create_user(session, email="mensual@example.com", password="password123")
    updated = await set_user_plan(session, user, plan=Plan.MENSUAL, active_days=30)
    assert updated.plan == "mensual"
    assert updated.plan_active_until > datetime.utcnow()
    assert updated.has_active_subscription is True
    assert updated.has_full_stats_access is True
    assert updated.has_premium_access is False  # mensual no da premium


@pytest.mark.asyncio
async def test_set_user_plan_premium_grants_premium_access(session):
    user = await create_user(session, email="premium@example.com", password="password123")
    updated = await set_user_plan(session, user, plan=Plan.PREMIUM, active_days=30)
    assert updated.has_full_stats_access is True
    assert updated.has_premium_access is True


@pytest.mark.asyncio
async def test_set_user_plan_unica_grants_access_only_while_credits_remain(session):
    user = await create_user(session, email="unica@example.com", password="password123")
    updated = await set_user_plan(session, user, plan=Plan.UNICA, add_report_credits=2)
    assert updated.plan == "unica"
    assert updated.report_credits == 2
    assert updated.has_active_subscription is False  # única no es continua
    assert updated.has_full_stats_access is True  # pero tiene créditos

    await consume_report_credit(session, updated)
    await consume_report_credit(session, updated)
    assert updated.report_credits == 0
    assert updated.has_full_stats_access is False  # sin créditos, sin acceso


@pytest.mark.asyncio
async def test_set_user_plan_expired_subscription_has_no_access(session):
    user = await create_user(session, email="vencido@example.com", password="password123")
    updated = await set_user_plan(session, user, plan=Plan.MENSUAL, active_days=30)
    # Simula que venció: retrocedemos la fecha de vigencia manualmente.
    updated.plan_active_until = datetime.utcnow() - timedelta(days=1)
    assert updated.has_active_subscription is False
    assert updated.has_full_stats_access is False


@pytest.mark.asyncio
async def test_set_user_plan_free_clears_subscription_but_keeps_credits(session):
    user = await create_user(session, email="downgrade@example.com", password="password123")
    await set_user_plan(session, user, plan=Plan.UNICA, add_report_credits=3)
    updated = await set_user_plan(session, user, plan=Plan.FREE)
    assert updated.plan == "free"
    assert updated.plan_active_until is None
    assert updated.report_credits == 3  # los créditos ya comprados no se pierden
