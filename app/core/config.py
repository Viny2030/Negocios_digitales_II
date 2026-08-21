"""
Configuración central de la aplicación.

Usa Pydantic v2 Settings para cargar variables de entorno (.env) con
validación de tipos. Solo se incluyen las credenciales necesarias para
las plataformas activas en esta fase: YouTube y TikTok.
"""
from functools import lru_cache
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # --- Metadatos de la app ---
    APP_NAME: str = "Channel Analytics Core"
    APP_VERSION: str = "0.1.0"
    API_V1_PREFIX: str = "/api/v1"
    DEBUG: bool = False

    # --- YouTube Data API v3 ---
    YOUTUBE_API_KEY: Optional[str] = None
    YOUTUBE_API_BASE_URL: str = "https://www.googleapis.com/youtube/v3"
    # Cuota diaria estándar del proyecto (10.000 unidades/día)
    YOUTUBE_DAILY_QUOTA_UNITS: int = 10_000

    # --- TikTok (Research/Display API oficial) ---
    TIKTOK_CLIENT_KEY: Optional[str] = None
    TIKTOK_CLIENT_SECRET: Optional[str] = None
    TIKTOK_API_BASE_URL: str = "https://open.tiktokapis.com/v2"

    # Si no hay credenciales configuradas, los colectores devuelven datos
    # simulados (modo mock) en lugar de fallar, para poder desarrollar y
    # probar el pipeline end-to-end sin depender de aprobaciones externas.
    USE_MOCK_DATA_IF_NO_CREDENTIALS: bool = True

    # --- HTTP client ---
    HTTP_TIMEOUT_SECONDS: float = 15.0
    HTTP_MAX_CONCURRENT_REQUESTS: int = 10

    # --- Límites de negocio (ver matriz de límites) ---
    DEFAULT_SEARCH_LIMIT: int = 25
    MAX_SEARCH_LIMIT: int = 100

    # --- Persistencia (seguimiento diario de canales) ---
    # SQLite por defecto: cero configuración, un archivo en el propio proyecto.
    # Cambiar a postgresql+asyncpg://... para usar el servicio de docker-compose.
    DATABASE_URL: str = "sqlite+aiosqlite:///./channel_analytics.db"

    # --- Worker diario (dim_channels / fact_channel_metrics_daily) ---
    ENABLE_SCHEDULER: bool = True
    DAILY_JOB_HOUR_UTC: int = 3
    DAILY_JOB_MINUTE_UTC: int = 0
    # Si se define, los endpoints /api/v1/tracking/* exigen este valor en el
    # header 'X-Admin-Token'. Vacío/None = sin protección (uso local).
    ADMIN_TOKEN: Optional[str] = None


@lru_cache
def get_settings() -> Settings:
    """Devuelve una instancia cacheada de Settings (singleton)."""
    return Settings()
