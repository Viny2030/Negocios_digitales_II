"""
Autenticación (registro/login armados desde cero: email + contraseña con
hash bcrypt + JWT de sesión) y gestión manual del plan de suscripción de
cada usuario.

No hay pasarela de pago real conectada (Mercado Pago/Stripe): es un
proyecto universitario y la consigna fue dejar lista la ARQUITECTURA de
niveles, no el cobro real. `POST /auth/admin/set-plan` permite simular
cualquiera de los 4 planes a mano, protegido con el mismo `X-Admin-Token`
que ya protegía `/tracking/*` — un futuro webhook de pasarela de pago
podría llamar exactamente al mismo `set_user_plan()` de
`app/services/users.py` sin tocar el resto del sistema.

Planes (ver `app/models/domain.py::Plan`):
  - free    : sin acceso a "toda la estadística" — solo lo público
              (`GET /analytics/benchmarks`, referencia estática).
  - unica   : acceso puntual: consume 1 "crédito de reporte" por cada
              endpoint de estadística consultado (no es acceso continuo).
  - mensual : acceso continuo a TODA la estadística del sitio: métricas
              nacionales e internacionales, incluidas las que no se miden
              en Argentina/Latinoamérica.
  - premium : todo lo de mensual + proyecciones de tendencia y
              recomendaciones de política general por métrica
              (`GET /premium/*`).
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, verify_admin_token
from app.core.exceptions import InvalidCredentialsError, UserNotFoundError
from app.core.security import create_access_token, verify_password
from app.db.models import User
from app.db.session import get_session
from app.models.schemas import (
    AdminSetPlanRequest,
    TokenResponse,
    UserLoginRequest,
    UserOut,
    UserRegisterRequest,
)
from app.services.users import create_user, get_user_by_email, set_user_plan

router = APIRouter(prefix="/auth", tags=["auth"])


def _user_out(user: User) -> UserOut:
    return UserOut.model_validate(user)


@router.post(
    "/register", response_model=TokenResponse, summary="Crear una cuenta nueva (arranca en plan 'free')",
)
async def register(payload: UserRegisterRequest, session: AsyncSession = Depends(get_session)) -> TokenResponse:
    user = await create_user(session, email=payload.email, password=payload.password)
    token = create_access_token(user.id, user.email)
    return TokenResponse(access_token=token, user=_user_out(user))


@router.post("/login", response_model=TokenResponse, summary="Iniciar sesión")
async def login(payload: UserLoginRequest, session: AsyncSession = Depends(get_session)) -> TokenResponse:
    user = await get_user_by_email(session, payload.email)
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise InvalidCredentialsError()
    token = create_access_token(user.id, user.email)
    return TokenResponse(access_token=token, user=_user_out(user))


@router.get("/me", response_model=UserOut, summary="Datos del usuario autenticado (incluye plan y accesos vigentes)")
async def me(user: User = Depends(get_current_user)) -> UserOut:
    return _user_out(user)


@router.post(
    "/admin/set-plan",
    response_model=UserOut,
    dependencies=[Depends(verify_admin_token)],
    summary="(Admin) Simular manualmente un alta/cambio de plan — sin pasarela de pago real",
)
async def admin_set_plan(payload: AdminSetPlanRequest, session: AsyncSession = Depends(get_session)) -> UserOut:
    """
    Único punto de "cobro" del sistema hoy: fija el plan de un usuario a
    mano. Requiere `X-Admin-Token` (si `ADMIN_TOKEN` está configurado en
    el entorno) — mismo mecanismo que las rutas de escritura de
    `/tracking/*`. Pensado para simular la compra de cada nivel durante
    el desarrollo/demo del proyecto.
    """
    user = await get_user_by_email(session, payload.email)
    if user is None:
        raise UserNotFoundError(payload.email)

    updated = await set_user_plan(
        session, user, plan=payload.plan, active_days=payload.active_days, add_report_credits=payload.add_report_credits,
    )
    return _user_out(updated)
