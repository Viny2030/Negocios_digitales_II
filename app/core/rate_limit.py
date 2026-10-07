"""
Límite de intentos simple, en memoria, para /auth/login y /auth/register
(freno básico a fuerza bruta de contraseñas y a altas masivas de cuentas).

Ventana deslizante de 60 segundos por IP de origen. En memoria del proceso:
alcanza con la única réplica que corre la app (ver `numReplicas = 1` en
railway.toml). Detrás del proxy de Railway, la IP real llega en
X-Forwarded-For -- por eso el Dockerfile arranca uvicorn con
`--proxy-headers`.
"""

import time
from collections import defaultdict, deque

from fastapi import Request

from app.core.config import get_settings
from app.core.exceptions import TooManyRequestsError

settings = get_settings()

WINDOW_SECONDS = 60.0


class SlidingWindowLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def hit(self, key: str, max_calls: int) -> bool:
        """Registra un intento; devuelve False si `key` superó `max_calls` en la ventana."""
        now = time.monotonic()
        hits = self._hits[key]
        while hits and now - hits[0] > WINDOW_SECONDS:
            hits.popleft()
        if len(hits) >= max_calls:
            return False
        hits.append(now)
        return True

    def reset(self) -> None:
        self._hits.clear()


auth_limiter = SlidingWindowLimiter()


async def limit_auth_attempts(request: Request) -> None:
    """Dependencia de FastAPI para las rutas de /auth que reciben credenciales."""
    max_calls = settings.AUTH_RATE_LIMIT_PER_MINUTE
    if max_calls <= 0:
        return
    client_ip = request.client.host if request.client else "desconocida"
    if not auth_limiter.hit(f"{request.url.path}:{client_ip}", max_calls):
        raise TooManyRequestsError()
