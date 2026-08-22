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


def _default_discover_regions() -> list[str]:
    return ["AR", "MX", "ES", "US"]


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

    # --- Worker de seguimiento (dim_channels / fact_channel_metrics_daily) ---
    ENABLE_SCHEDULER: bool = True
    # Por default corre 1 vez por semana: lunes 09:00 UTC (06:00 hora Argentina,
    # UTC-3 todo el año, sin horario de verano). `DAILY_JOB_DAY_OF_WEEK` acepta
    # la sintaxis de APScheduler CronTrigger ("mon".."sun", "mon-fri", "*" para
    # correr todos los días, etc.) — poner "*" para volver a una corrida diaria.
    DAILY_JOB_DAY_OF_WEEK: str = "mon"
    DAILY_JOB_HOUR_UTC: int = 9
    DAILY_JOB_MINUTE_UTC: int = 0
    # Si se define, los endpoints /api/v1/tracking/* exigen este valor en el
    # header 'X-Admin-Token'. Vacío/None = sin protección (uso local).
    ADMIN_TOKEN: Optional[str] = None

    # --- Descubrimiento multi-tema (GET /channels/discover, /discover/by-category) ---
    # Región usada como default cuando se pide una sola (p. ej. vía query
    # param `region_code`). Para la pasada "todos los temas" se combinan
    # varias regiones a la vez — ver DISCOVER_REGION_CODES.
    DISCOVER_REGION_CODE: str = "AR"
    # Regiones combinadas por default al descubrir (más regiones = más
    # variedad de canales, ver README). Cada región agrega, como mucho,
    # `len(DISCOVER_CATEGORY_IDS) * DISCOVER_PAGES_PER_REGION_CATEGORY`
    # llamadas a `videos.list` (1 unidad de cuota c/u) — barato incluso con
    # varias regiones.
    DISCOVER_REGION_CODES: list[str] = Field(default_factory=_default_discover_regions)
    # Páginas de `videos.list chart=mostPopular` a recorrer por combinación
    # región+categoría (maxResults=50/página, tope real de YouTube ronda los
    # ~200 videos por trending). Subir esto junta más canales por corrida a
    # costa de más llamadas (todas de 1 unidad) y más tiempo de respuesta.
    DISCOVER_PAGES_PER_REGION_CATEGORY: int = 2
    # Tope "práctico" de `limit`/`limit_per_category` en /channels/discover*:
    # no hay un límite duro de la API (channels.list no tiene tope de lote,
    # solo pagina de a 50), esto es solo una salvaguarda para no pedir un
    # número absurdo por accidente.
    DISCOVER_MAX_LIMIT: int = 2000
    DISCOVER_DEFAULT_LIMIT_PER_CATEGORY: int = 30

    # --- Autenticación y suscripciones (planes: free/unica/mensual/premium) ---
    # Firma los JWT de sesión emitidos por /api/v1/auth/{register,login}.
    # IMPORTANTE: este default es solo para desarrollo/proyecto universitario
    # — en un despliegue real hay que sobreescribirlo en `.env` con un valor
    # secreto propio (nunca commitear ese valor real).
    JWT_SECRET_KEY: str = "dev-only-secret-cambiar-en-produccion-negocios-digitales-ii"
    JWT_ALGORITHM: str = "HS256"
    # Duración del token de sesión: 7 días por default.
    JWT_EXPIRE_MINUTES: int = 60 * 24 * 7
    # Días de vigencia por defecto al simular una alta de 'mensual'/'premium'
    # vía POST /auth/admin/set-plan cuando no se especifica `active_days`.
    DEFAULT_PLAN_ACTIVE_DAYS: int = 30


@lru_cache
def get_settings() -> Settings:
    """Devuelve una instancia cacheada de Settings (singleton)."""
    return Settings()
