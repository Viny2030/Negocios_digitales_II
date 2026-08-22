"""
Seguridad de autenticación: hashing de contraseñas (bcrypt) y JWT de
sesión (pyjwt) para el login "armado desde cero" (sin Auth0/Firebase/etc.
ni ningún proveedor externo de identidad) — es la arquitectura de acceso
para los planes de suscripción (ver `app/models/domain.py::Plan` y
`app/db/models.py::User`).

Nota de seguridad: bcrypt trunca/ignora silenciosamente lo que exceda 72
bytes de contraseña — irrelevante en la práctica para contraseñas
normales, documentado acá por transparencia.
"""
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import get_settings

settings = get_settings()


def hash_password(password: str) -> str:
    """Hashea una contraseña en texto plano con bcrypt (salt aleatorio por usuario)."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed_password: str) -> bool:
    """Compara una contraseña en texto plano contra su hash bcrypt almacenado."""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed_password.encode("utf-8"))
    except (ValueError, TypeError):
        # Hash corrupto/formato inesperado: tratamos como credencial inválida,
        # no como error 500.
        return False


def create_access_token(user_id: int, email: str) -> str:
    """Emite un JWT de sesión (`sub`=id de usuario) válido por `JWT_EXPIRE_MINUTES`."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "email": email,
        "iat": now,
        "exp": now + timedelta(minutes=settings.JWT_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict | None:
    """Decodifica y valida un JWT de sesión. Devuelve `None` si es inválido/expiró."""
    try:
        return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None
