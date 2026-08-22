"""
CRUD de usuarios y gestión manual (sin pasarela de pago real) de su plan
de suscripción. Capa fina sobre SQLAlchemy, calcada del estilo de
`services/tracked_channels.py`.

Por qué "manual": este es un proyecto universitario y la consigna fue
dejar lista la arquitectura de niveles (free/única/mensual/premium) sin
conectar un cobro real todavía (Mercado Pago/Stripe quedan para más
adelante). `set_user_plan` es el único punto que un futuro webhook de
pago tendría que llamar para que todo el resto del sistema (gating de
`/channels/*`, `/analytics/*`, `/premium/*`) funcione sin cambios.
"""
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import UserAlreadyExistsError
from app.core.security import hash_password
from app.db.models import User
from app.models.domain import Plan

settings = get_settings()


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    stmt = select(User).where(User.email == email.strip().lower())
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_user_by_id(session: AsyncSession, user_id: int) -> User | None:
    return await session.get(User, user_id)


async def create_user(session: AsyncSession, email: str, password: str) -> User:
    """Registra una cuenta nueva en plan 'free'. Falla si el email ya existe."""
    email_norm = email.strip().lower()
    existing = await get_user_by_email(session, email_norm)
    if existing is not None:
        raise UserAlreadyExistsError(email_norm)

    user = User(
        email=email_norm, hashed_password=hash_password(password),
        plan=Plan.FREE.value, report_credits=0, is_admin=False,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def set_user_plan(
    session: AsyncSession,
    user: User,
    plan: Plan,
    active_days: int | None = None,
    add_report_credits: int | None = None,
) -> User:
    """
    Simula manualmente un alta/cambio de plan (sin pasarela de pago real):

      - 'mensual' / 'premium': fija `plan_active_until` = ahora + `active_days`
        (default `settings.DEFAULT_PLAN_ACTIVE_DAYS`, 30 días).
      - 'unica': suma `add_report_credits` (default 1) al saldo existente de
        `report_credits`, sin tocar `plan_active_until`.
      - 'free': limpia la vigencia de suscripción (los créditos de 'única'
        ya acumulados NO se borran, para no perder un reporte ya pagado).
    """
    user.plan = plan.value
    if plan in (Plan.MENSUAL, Plan.PREMIUM):
        days = active_days if active_days is not None else settings.DEFAULT_PLAN_ACTIVE_DAYS
        user.plan_active_until = datetime.utcnow() + timedelta(days=days)
    elif plan == Plan.UNICA:
        user.report_credits += add_report_credits if add_report_credits is not None else 1
    elif plan == Plan.FREE:
        user.plan_active_until = None

    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def consume_report_credit(session: AsyncSession, user: User) -> User:
    """Descuenta 1 crédito de reporte ('única'). El llamador debe validar `report_credits > 0` antes."""
    user.report_credits -= 1
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user
