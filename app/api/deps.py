"""
Dependencias de FastAPI compartidas entre routers:

  - `verify_admin_token`: protege rutas de escritura/administración con el
    header `X-Admin-Token` (mismo mecanismo que ya usaba `/tracking/*`,
    ahora también usado por `/auth/admin/set-plan`).
  - `get_current_user` / `get_current_user_optional`: resuelven el usuario
    autenticado a partir de un JWT de sesión (`Authorization: Bearer <token>`).
  - `require_full_access`: exige un plan con acceso a "toda la estadística"
    (única con crédito disponible, o mensual/premium activos) — pensado
    para usarse como `dependencies=[Depends(require_full_access)]` en los
    endpoints de `/channels/*` y `/analytics/*` (excepto `/analytics/benchmarks`,
    que queda público por ser referencia estática).
  - `require_premium`: exige plan 'premium' activo — usado por `/premium/*`
    (proyecciones de tendencia y recomendaciones de política general).

Interruptor `settings.REQUIRE_SUBSCRIPTION` (default `False`): con el
gating desactivado (default), `require_full_access`/`require_premium` NO
llaman siquiera a `get_current_user` — ni piden `Authorization`, para no
romper el uso sin login que tenía el proyecto antes de agregar planes.
Poner `REQUIRE_SUBSCRIPTION=true` en `.env` para exigir de verdad sesión +
plan activo (p. ej. para una demo/entrega formal del sistema de planes).
"""
from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import (
    NotAuthenticatedError,
    PremiumRequiredError,
    SubscriptionRequiredError,
    UnauthorizedError,
)
from app.core.security import decode_access_token
from app.db.models import User
from app.db.session import get_session
from app.services.users import consume_report_credit, get_user_by_id

settings = get_settings()


async def verify_admin_token(x_admin_token: str | None = Header(default=None)) -> None:
    """Exige `X-Admin-Token` solo si `ADMIN_TOKEN` está configurado (default local = sin protección)."""
    if settings.ADMIN_TOKEN and x_admin_token != settings.ADMIN_TOKEN:
        raise UnauthorizedError()


async def get_current_user(
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> User:
    """Resuelve el usuario autenticado a partir de `Authorization: Bearer <token>`."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise NotAuthenticatedError()

    token = authorization.split(" ", 1)[1].strip()
    payload = decode_access_token(token)
    if payload is None:
        raise NotAuthenticatedError()

    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError):
        raise NotAuthenticatedError()

    user = await get_user_by_id(session, user_id)
    if user is None:
        raise NotAuthenticatedError()
    return user


async def get_current_user_optional(
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> User | None:
    """Como `get_current_user`, pero devuelve `None` en vez de fallar si no hay sesión."""
    if not authorization:
        return None
    try:
        return await get_current_user(authorization, session)
    except NotAuthenticatedError:
        return None


async def require_full_access(
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> User | None:
    """
    Exige acceso a "toda la estadística": suscripción 'mensual'/'premium'
    activa (por fecha), o plan 'unica' con al menos 1 crédito de reporte
    disponible (se consume 1 crédito por cada llamada bajo esta regla).

    Si `settings.REQUIRE_SUBSCRIPTION` es `False` (default), no hace nada
    — ni siquiera exige `Authorization` — y el endpoint queda abierto.
    """
    if not settings.REQUIRE_SUBSCRIPTION:
        return None

    user = await get_current_user(authorization, session)
    if user.has_active_subscription:
        return user
    if user.plan == "unica" and user.report_credits > 0:
        await consume_report_credit(session, user)
        return user
    raise SubscriptionRequiredError()


async def require_premium(
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> User | None:
    """
    Exige plan 'premium' activo (proyecciones de tendencia y recomendaciones).
    Igual que `require_full_access`: sin efecto si `REQUIRE_SUBSCRIPTION=False`.
    """
    if not settings.REQUIRE_SUBSCRIPTION:
        return None

    user = await get_current_user(authorization, session)
    if not user.has_premium_access:
        raise PremiumRequiredError()
    return user
