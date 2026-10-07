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
import secrets

from fastapi import Depends, Header, Request
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
from app.services.users import get_user_by_id, open_report_window

settings = get_settings()


async def verify_admin_token(x_admin_token: str | None = Header(default=None)) -> None:
    """Exige `X-Admin-Token` solo si `ADMIN_TOKEN` está configurado (default local = sin protección)."""
    if not settings.ADMIN_TOKEN:
        return
    # compare_digest: comparación en tiempo constante (un `!=` común deja
    # inferir el token carácter por carácter midiendo tiempos de respuesta).
    if x_admin_token is None or not secrets.compare_digest(x_admin_token, settings.ADMIN_TOKEN):
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
        # `from None`: un JWT con `sub` ausente/no numérico es simplemente un
        # token inválido (401 de cara al cliente) — no un error interno, así
        # que no tiene sentido encadenarle el traceback de la conversión.
        raise NotAuthenticatedError() from None

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
    request: Request,
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> User | None:
    """
    Exige acceso a "toda la estadística": suscripción 'mensual'/'premium'
    activa (por fecha), o plan 'unica' con una ventana de reporte abierta o
    al menos 1 crédito disponible.

    Plan 'unica': un crédito = un reporte = una ventana de
    `UNICA_REPORT_WINDOW_HOURS` horas de consultas libres (el dashboard hace
    varias llamadas por pantalla; antes cada una gastaba un crédito). El
    crédito NO se descuenta acá: se marca como pendiente en `request.state`
    y lo descuenta `consume_report_credit_on_success` (middleware, ver
    `app/main.py`) solo si la respuesta terminó bien (< 400). Así una
    request que falla (422 por un parámetro inválido, 400, 502 de la API
    externa...) no gasta el crédito. No alcanza con una dependencia con
    `yield`: FastAPI corre su código de salida normalmente aunque la
    request termine en 422 por validación.

    Si `settings.REQUIRE_SUBSCRIPTION` es `False` (default), no hace nada
    — ni siquiera exige `Authorization` — y el endpoint queda abierto.
    """
    if not settings.REQUIRE_SUBSCRIPTION:
        return None

    user = await get_current_user(authorization, session)
    if user.has_active_subscription or (user.plan == "unica" and user.has_open_report_window):
        return user
    if user.plan == "unica" and user.report_credits > 0:
        request.state.pending_report_credit = (session.bind, user.id)
        return user
    raise SubscriptionRequiredError()


async def consume_report_credit_on_success(request: Request, call_next):
    """
    Middleware HTTP: si la request usó un crédito 'unica' (ver
    `require_full_access`) y la respuesta salió bien, abre la ventana de
    reporte descontando el crédito. Usa una sesión nueva sobre el MISMO
    engine que usó la request (la de la dependencia ya se cerró a esta
    altura), así funciona igual con la base real y con la de los tests.
    """
    response = await call_next(request)
    pending = getattr(request.state, "pending_report_credit", None)
    if pending is not None and response.status_code < 400:
        bind, user_id = pending
        async with AsyncSession(bind, expire_on_commit=False) as session:
            user = await get_user_by_id(session, user_id)
            if user is not None:
                await open_report_window(session, user)
    return response


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
