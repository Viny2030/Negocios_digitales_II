"""
Excepciones de dominio y manejadores de error para FastAPI.

Centralizar los errores de los colectores externos (YouTube, TikTok)
permite que la capa de API responda siempre con un JSON consistente,
sin filtrar trazas internas ni detalles de proveedor.
"""
from fastapi import Request, status
from fastapi.responses import JSONResponse


class ChannelAnalyticsError(Exception):
    """Excepción base de la aplicación."""

    def __init__(self, message: str, status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class PlatformAPIError(ChannelAnalyticsError):
    """Error al comunicarse con la API externa de una plataforma."""

    def __init__(self, platform: str, detail: str, status_code: int = status.HTTP_502_BAD_GATEWAY):
        self.platform = platform
        super().__init__(f"Error consultando {platform}: {detail}", status_code)


class QuotaExceededError(ChannelAnalyticsError):
    """Se agotó la cuota diaria de una API externa (p. ej. YouTube)."""

    def __init__(self, platform: str):
        self.platform = platform
        super().__init__(
            f"Cuota diaria excedida para {platform}",
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        )


class InsufficientDataError(ChannelAnalyticsError):
    """No hay suficientes registros para calcular una métrica estadística."""

    def __init__(self, detail: str):
        super().__init__(detail, status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)


class UnsupportedPlatformError(ChannelAnalyticsError):
    """Se solicitó una plataforma no soportada en esta fase (solo YouTube/TikTok)."""

    def __init__(self, platform: str):
        super().__init__(
            f"Plataforma no soportada: '{platform}'. Disponibles: youtube, tiktok, all.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )


class ChannelNotFoundError(ChannelAnalyticsError):
    """El identificador (ID nativo o @handle) no resolvió a ningún canal real."""

    def __init__(self, platform: str, identifier: str):
        super().__init__(
            f"No se encontró ningún canal de {platform} para '{identifier}'",
            status_code=status.HTTP_404_NOT_FOUND,
        )


class TrackedChannelNotFoundError(ChannelAnalyticsError):
    """No existe (o ya fue dado de baja) el canal trackeado solicitado."""

    def __init__(self, tracked_id: int):
        super().__init__(
            f"No existe un canal trackeado con id={tracked_id}",
            status_code=status.HTTP_404_NOT_FOUND,
        )


class UnauthorizedError(ChannelAnalyticsError):
    """Falta o es inválido el header X-Admin-Token (solo si ADMIN_TOKEN está configurado)."""

    def __init__(self):
        super().__init__("Token de administración inválido o ausente", status_code=status.HTTP_401_UNAUTHORIZED)


async def channel_analytics_exception_handler(request: Request, exc: ChannelAnalyticsError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.__class__.__name__,
            "message": exc.message,
            "path": str(request.url.path),
        },
    )


def register_exception_handlers(app) -> None:
    """Registra todos los manejadores de excepciones en la app FastAPI."""
    app.add_exception_handler(ChannelAnalyticsError, channel_analytics_exception_handler)
