"""
Punto de entrada de la aplicación FastAPI.

Ejecutar en desarrollo:
    uvicorn app.main:app --reload

Documentación interactiva autogenerada:
    /docs        (Swagger UI)
    /redoc       (ReDoc)

Dashboard visual (canales, temáticas, seguimiento diario y métricas del medio):
    /dashboard
"""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.scheduler import shutdown_scheduler, start_scheduler
from app.db.session import init_db

logging.basicConfig(level=logging.INFO)

settings = get_settings()

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DOCS_DIR = BASE_DIR.parent / "docs"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: crea las tablas (dim_channels / fact_channel_metrics_daily)
    # si todavía no existen, y arranca el scheduler del worker diario.
    await init_db()
    start_scheduler()
    yield
    # Shutdown: apaga el scheduler prolijamente.
    shutdown_scheduler()


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=(
        "Sistema unificado de analítica de canales de contenido. "
        "Fase actual: YouTube + TikTok."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_exception_handlers(app)
app.include_router(api_router, prefix=settings.API_V1_PREFIX)

# El dashboard es un único HTML+JS+CSS estático que consume la propia API
# (mismo origen, sin problemas de CORS) — ver app/static/dashboard.html.
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/dashboard", tags=["dashboard"], summary="Dashboard visual: canales, temáticas, seguimiento diario y métricas del medio", include_in_schema=False)
async def dashboard() -> FileResponse:
    return FileResponse(STATIC_DIR / "dashboard.html")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> FileResponse:
    return FileResponse(STATIC_DIR / "favicon.ico")


@app.get(
    "/manual/es", tags=["docs"], summary="Manual de métricas explicadas (Español)", include_in_schema=False,
)
async def manual_es() -> FileResponse:
    """
    Sirve `docs/manual_metricas_es.md` — el manual, en texto plano
    Markdown, no vive dentro del dashboard (que es solo HTML/JS/CSS
    contra la API): esta ruta es un atajo para abrirlo con un clic desde
    ahí en vez de tener que ir a buscarlo en el explorador de archivos.
    """
    return FileResponse(DOCS_DIR / "manual_metricas_es.md", media_type="text/markdown; charset=utf-8")


@app.get(
    "/manual/en", tags=["docs"], summary="Metrics manual (English)", include_in_schema=False,
)
async def manual_en() -> FileResponse:
    """Sirve `docs/manual_metricas_en.md` — ver `manual_es()` arriba."""
    return FileResponse(DOCS_DIR / "manual_metricas_en.md", media_type="text/markdown; charset=utf-8")


@app.get("/", tags=["health"], summary="Health check")
async def health_check() -> dict:
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "platforms_supported": ["youtube", "tiktok"],
        "mock_mode_available": settings.USE_MOCK_DATA_IF_NO_CREDENTIALS,
        "daily_scheduler_enabled": settings.ENABLE_SCHEDULER,
        "dashboard": "/dashboard",
    }
