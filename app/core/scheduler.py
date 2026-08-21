"""
Scheduler del worker diario — APScheduler corriendo dentro del propio
proceso de FastAPI (AsyncIOScheduler, reutiliza el event loop de uvicorn).
Se arranca en el evento `startup` de `main.py` y se apaga en `shutdown`;
no depende de ningún cron externo ni de un segundo proceso.

Para producción real (múltiples réplicas del server) esto tendría que
moverse a un scheduler externo compartido (Celery beat, cron + endpoint
protegido, etc.) para no disparar el job N veces — ver `ENABLE_SCHEDULER`
para desactivarlo en réplicas secundarias si hace falta.
"""
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import get_settings
from app.services.worker import run_daily_snapshot

logger = logging.getLogger("channel_analytics.scheduler")
settings = get_settings()

_scheduler: AsyncIOScheduler | None = None


async def _job_wrapper() -> None:
    result = await run_daily_snapshot()
    logger.info(
        "Daily snapshot job: %s canales evaluados, %s snapshots creados, %s actualizados, %s errores",
        result.channels_evaluated, result.snapshots_created, result.snapshots_updated, len(result.errors),
    )
    for err in result.errors:
        logger.warning("Daily snapshot job: %s", err)


def start_scheduler() -> AsyncIOScheduler | None:
    global _scheduler
    if not settings.ENABLE_SCHEDULER:
        logger.info("Scheduler deshabilitado (ENABLE_SCHEDULER=false)")
        return None
    if _scheduler is not None:
        return _scheduler

    _scheduler = AsyncIOScheduler(timezone="UTC")
    trigger = CronTrigger(hour=settings.DAILY_JOB_HOUR_UTC, minute=settings.DAILY_JOB_MINUTE_UTC)
    _scheduler.add_job(_job_wrapper, trigger, id="daily_channel_snapshot", replace_existing=True)
    _scheduler.start()
    logger.info(
        "Scheduler iniciado: snapshot diario a las %02d:%02d UTC",
        settings.DAILY_JOB_HOUR_UTC, settings.DAILY_JOB_MINUTE_UTC,
    )
    return _scheduler


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
