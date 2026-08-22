"""
Scheduler del worker de seguimiento — APScheduler corriendo dentro del
propio proceso de FastAPI (AsyncIOScheduler, reutiliza el event loop de
uvicorn). Se arranca en el evento `startup` de `main.py` y se apaga en
`shutdown`; no depende de ningún cron externo ni de un segundo proceso.

Por default corre 1 vez por semana (`DAILY_JOB_DAY_OF_WEEK`, default
"mon") a la hora configurada — para volver a una corrida diaria, poner
`DAILY_JOB_DAY_OF_WEEK=*` en el .env.

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
    trigger = CronTrigger(
        day_of_week=settings.DAILY_JOB_DAY_OF_WEEK,
        hour=settings.DAILY_JOB_HOUR_UTC,
        minute=settings.DAILY_JOB_MINUTE_UTC,
    )
    _scheduler.add_job(_job_wrapper, trigger, id="daily_channel_snapshot", replace_existing=True)
    _scheduler.start()
    cadence = (
        "todos los días" if settings.DAILY_JOB_DAY_OF_WEEK in ("*", "", None)
        else f"cada '{settings.DAILY_JOB_DAY_OF_WEEK}'"
    )
    logger.info(
        "Scheduler iniciado: snapshot %s a las %02d:%02d UTC",
        cadence, settings.DAILY_JOB_HOUR_UTC, settings.DAILY_JOB_MINUTE_UTC,
    )
    return _scheduler


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
