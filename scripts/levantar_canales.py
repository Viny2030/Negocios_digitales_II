"""
Levantamiento diario de canales sin la API levantada: toma la foto del día de todos los canales
en seguimiento (el mismo `run_daily_snapshot` que usan el scheduler y POST /tracking/run-daily-job)
y termina. Lo corren los workflows `levantamiento-canales.yml` (principal) y
`levantamiento-canales-respaldo.yml` (respaldo, con `--solo-si-falta`).

    python -m scripts.levantar_canales [--solo-si-falta]

Se niega a correr si la foto saldría inventada o si la base no es la real:
  - sin `YOUTUBE_API_KEY`, o con el modo mock habilitado, sale con código 2 (los colectores
    devolverían datos simulados y se guardarían como si fueran reales);
  - si la base no tiene canales activos, sale con código 3 (lo más probable es que no se haya
    recuperado la base del día anterior; seguir subiría una base vacía como la "última").
Si ningún canal quedó con foto (cuota agotada, clave inválida) sale con código 1, así el
workflow no reemplaza la base anterior por una que no suma nada.

`--solo-si-falta`: si hoy ya tienen foto al menos el 98% de los canales activos, no consulta la
API (no gasta cuota) y lo informa. Es lo que hace el workflow de respaldo.

Deja el resumen en Markdown en `RESUMEN_PATH` (si está definido, lo usa el mail) y en
`GITHUB_STEP_SUMMARY`, y escribe `resultado=tomada|ya_estaba` en `GITHUB_OUTPUT`.

Lee la base de `DATABASE_URL` como el resto de la app: el SQLite local por default, o el
Postgres de Railway cuando esa variable apunta ahí.
"""
import argparse
import asyncio
import os
import sys
from datetime import date

from app.core.config import Settings, get_settings

EXIT_OK = 0
EXIT_NO_SNAPSHOTS = 1
EXIT_UNSAFE_CONFIG = 2
EXIT_EMPTY_DATABASE = 3

# Con `--solo-si-falta`, cobertura de hoy a partir de la cual no se vuelve a consultar la API.
# No se exige el 100%: un canal borrado de YouTube no vuelve nunca y haría correr el respaldo
# todos los días gastando cuota por nada.
ALREADY_DONE_SHARE = 0.98


def config_problems(settings: Settings) -> list[str]:
    """Motivos por los que la foto no saldría de la API real de YouTube."""
    problems = []
    if not settings.YOUTUBE_API_KEY:
        problems.append("Falta YOUTUBE_API_KEY.")
    if settings.USE_MOCK_DATA_IF_NO_CREDENTIALS:
        problems.append("El modo mock está habilitado: definir USE_MOCK_DATA_IF_NO_CREDENTIALS=false.")
    return problems


def already_done(snapshots_today: int, active_channels: int) -> bool:
    return active_channels > 0 and snapshots_today >= active_channels * ALREADY_DONE_SHARE


def summary_markdown(result, active_channels: int) -> str:
    lines = [
        "## Levantamiento diario de canales",
        "",
        "| Canales activos | Fotos nuevas | Fotos actualizadas | Errores |",
        "| ---: | ---: | ---: | ---: |",
        f"| {active_channels} | {result.snapshots_created} | {result.snapshots_updated} | {len(result.errors)} |",
    ]
    if result.errors:
        lines += ["", "### Errores", ""] + [f"- {error}" for error in result.errors[:50]]
        if len(result.errors) > 50:
            lines.append(f"- … y {len(result.errors) - 50} más")
    return "\n".join(lines) + "\n"


def already_done_markdown(snapshots_today: int, active_channels: int, today: date) -> str:
    return (
        "## Levantamiento diario de canales\n\n"
        f"La foto del {today:%d/%m/%Y} ya estaba tomada: {snapshots_today} de {active_channels} canales activos. "
        "No se consultó la API.\n"
    )


def _write_outputs(summary: str, resultado: str | None) -> None:
    print(summary)
    for env_name in ("RESUMEN_PATH", "GITHUB_STEP_SUMMARY"):
        path = os.environ.get(env_name)
        if path:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(summary)
    output = os.environ.get("GITHUB_OUTPUT")
    if output and resultado:
        with open(output, "a", encoding="utf-8") as fh:
            fh.write(f"resultado={resultado}\n")


async def run(only_if_missing: bool = False) -> int:
    settings = get_settings()
    problems = config_problems(settings)
    if problems:
        for problem in problems:
            print(f"ERROR: {problem}", file=sys.stderr)
        return EXIT_UNSAFE_CONFIG

    # Imports diferidos: crean el engine de la base, que no hace falta si la configuración no sirve.
    from sqlalchemy import func, select

    from app.db.models import ChannelMetricSnapshot, TrackedChannel
    from app.db.session import get_session_ctx, init_db
    from app.services.tracked_channels import list_tracked
    from app.services.worker import run_daily_snapshot

    await init_db()
    today = date.today()  # la misma fecha que pone el worker a las fotos
    async with get_session_ctx() as session:
        active_channels = len(await list_tracked(session, active_only=True))
        snapshots_today = (await session.execute(
            select(func.count())
            .select_from(ChannelMetricSnapshot)
            .join(TrackedChannel, ChannelMetricSnapshot.tracked_channel_id == TrackedChannel.id)
            .where(TrackedChannel.active.is_(True), ChannelMetricSnapshot.snapshot_date == today)
        )).scalar_one()
    if active_channels == 0:
        print("ERROR: la base no tiene canales activos; no se toma la foto.", file=sys.stderr)
        return EXIT_EMPTY_DATABASE

    if only_if_missing and already_done(snapshots_today, active_channels):
        _write_outputs(already_done_markdown(snapshots_today, active_channels, today), "ya_estaba")
        return EXIT_OK

    result = await run_daily_snapshot()
    if result.snapshots_created + result.snapshots_updated == 0:
        _write_outputs(summary_markdown(result, active_channels), None)
        print("ERROR: ningún canal quedó con foto (¿cuota agotada o clave inválida?).", file=sys.stderr)
        return EXIT_NO_SNAPSHOTS
    _write_outputs(summary_markdown(result, active_channels), "tomada")
    return EXIT_OK


def main() -> None:
    parser = argparse.ArgumentParser(description="Foto diaria de los canales en seguimiento.")
    parser.add_argument(
        "--solo-si-falta", action="store_true",
        help="No consultar la API si la foto de hoy ya está tomada (workflow de respaldo).",
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(run(only_if_missing=args.solo_si_falta)))


if __name__ == "__main__":
    main()
