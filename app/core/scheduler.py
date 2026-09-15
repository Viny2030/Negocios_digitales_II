"""
Scheduler del worker de seguimiento — APScheduler corriendo dentro del
propio proceso de FastAPI (AsyncIOScheduler, reutiliza el event loop de
uvicorn). Se arranca en el evento `startup` de `main.py` y se apaga en
`shutdown`; no depende de ningún cron externo ni de un segundo proceso.

Corre dos jobs independientes, cada uno con su propia cadencia:

  - `daily_channel_snapshot`: toma una foto de los canales YA trackeados
    (`DAILY_JOB_DAY_OF_WEEK`, default "*" = todos los días).
  - `auto_discovery`: descubre y trackea canales NUEVOS solo, para que el
    dataset crezca sin alta manual (`ENABLE_AUTO_DISCOVERY`, default
    `false` — pensado para un proyecto de investigación con acceso real a
    las APIs; ver `app/services/tracked_channels.py::discover_and_track_channels`).

Para producción real (múltiples réplicas del server) esto tendría que
moverse a un scheduler externo compartido (Celery beat, cron + endpoint
protegido, etc.) para no disparar los jobs N veces — ver `ENABLE_SCHEDULER`
para desactivarlo en réplicas secundarias si hace falta (y dejar
`numReplicas = 1`, ver `railway.toml`).
"""
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import get_settings
from app.db.session import get_session_ctx
from app.models.domain import Platform
from app.services.worker import run_daily_snapshot

logger = logging.getLogger("channel_analytics.scheduler")
settings = get_settings()

_scheduler: AsyncIOScheduler | None = None


def _cadence_label(day_of_week: str) -> str:
    return "todos los días" if day_of_week in ("*", "", None) else f"cada '{day_of_week}'"


async def _job_wrapper() -> None:
    result = await run_daily_snapshot()
    logger.info(
        "Daily snapshot job: %s canales evaluados, %s snapshots creados, %s actualizados, %s errores",
        result.channels_evaluated, result.snapshots_created, result.snapshots_updated, len(result.errors),
    )
    for err in result.errors:
        logger.warning("Daily snapshot job: %s", err)


async def _auto_discovery_job() -> None:
    # Import diferido: evita un ciclo de imports (tracked_channels importa
    # orchestrator, que a su vez toca los collectors — ya se cargan todos
    # antes de que este job corra por primera vez, pero mantenerlo acá
    # deja el import "pesado" fuera del arranque de la app).
    from app.services.tracked_channels import discover_and_track_channels

    try:
        platform = Platform(settings.AUTO_DISCOVERY_PLATFORM)
    except ValueError:
        logger.warning(
            "auto_discovery: AUTO_DISCOVERY_PLATFORM='%s' inválido (usar youtube|tiktok|all), se omite la corrida",
            settings.AUTO_DISCOVERY_PLATFORM,
        )
        return

    async with get_session_ctx() as session:
        result = await discover_and_track_channels(
            session, platform=platform, total_limit=settings.AUTO_DISCOVERY_TOTAL_LIMIT,
            sort_by=settings.AUTO_DISCOVERY_SORT_BY,
        )
    logger.info(
        "Auto-discovery job: %s canales nuevos trackeados de %s (límite %s), %s errores",
        result.total_tracked, result.platforms, result.total_limit, len(result.errors),
    )
    for err in result.errors:
        logger.warning("Auto-discovery job: %s", err)


def start_scheduler() -> AsyncIOScheduler | None:
    global _scheduler
    if not settings.ENABLE_SCHEDULER:
        logger.info("Scheduler deshabilitado (ENABLE_SCHEDULER=false)")
        return None
    if _scheduler is not None:
        return _scheduler

    _scheduler = AsyncIOScheduler(timezone="UTC")

    daily_trigger = CronTrigger(
        day_of_week=settings.DAILY_JOB_DAY_OF_WEEK,
        hour=settings.DAILY_JOB_HOUR_UTC,
        minute=settings.DAILY_JOB_MINUTE_UTC,
    )
    _scheduler.add_job(_job_wrapper, daily_trigger, id="daily_channel_snapshot", replace_existing=True)
    logger.info(
        "Scheduler iniciado: snapshot %s a las %02d:%02d UTC",
        _cadence_label(settings.DAILY_JOB_DAY_OF_WEEK), settings.DAILY_JOB_HOUR_UTC, settings.DAILY_JOB_MINUTE_UTC,
    )

    if settings.ENABLE_AUTO_DISCOVERY:
        discovery_trigger = CronTrigger(
            day_of_week=settings.AUTO_DISCOVERY_DAY_OF_WEEK,
            hour=settings.AUTO_DISCOVERY_HOUR_UTC,
            minute=settings.AUTO_DISCOVERY_MINUTE_UTC,
        )
        _scheduler.add_job(_auto_discovery_job, discovery_trigger, id="auto_discovery", replace_existing=True)
        logger.info(
            "Auto-discovery habilitado: %s canales/corrida (%s, orden=%s) %s a las %02d:%02d UTC",
            settings.AUTO_DISCOVERY_TOTAL_LIMIT, settings.AUTO_DISCOVERY_PLATFORM, settings.AUTO_DISCOVERY_SORT_BY,
            _cadence_label(settings.AUTO_DISCOVERY_DAY_OF_WEEK),
            settings.AUTO_DISCOVERY_HOUR_UTC, settings.AUTO_DISCOVERY_MINUTE_UTC,
        )
    else:
        logger.info("Auto-discovery deshabilitado (ENABLE_AUTO_DISCOVERY=false)")

    _scheduler.start()
    return _scheduler


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
