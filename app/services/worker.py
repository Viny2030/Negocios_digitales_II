"""
Worker diario — Pilar 2 del diseño original ("Persistencia y Worker Diario").

Recorre los canales trackeados activos, agrupados por plataforma, pide su
estado actual a los collectors (en lote cuando la plataforma lo soporta —
ver `get_channels_batch` en cada colector) y guarda un snapshot por canal
para el día de hoy. Pensado para dispararse:

  - Automáticamente, una vez por día, vía el scheduler de `core/scheduler.py`.
  - A mano, para probar sin esperar 24hs, vía POST /api/v1/tracking/run-daily-job.

Es tolerante a fallos por canal individual: si uno falla (borrado, rate
limit puntual, no encontrado) el resto del lote sigue procesándose y el
error queda reportado en `DailyJobResult.errors` en vez de tirar abajo
todo el job.
"""
from dataclasses import dataclass, field

from app.db.models import TrackedChannel
from app.db.session import get_session_ctx
from app.models.domain import Platform
from app.services.analytics.normalizer import normalize_channels
from app.services.collectors.tiktok import TikTokCollector
from app.services.collectors.youtube import YouTubeCollector
from app.services.tracked_channels import list_tracked, upsert_snapshot_from_channel

_COLLECTORS = {Platform.YOUTUBE: YouTubeCollector, Platform.TIKTOK: TikTokCollector}


@dataclass
class DailyJobResult:
    channels_evaluated: int = 0
    snapshots_created: int = 0
    snapshots_updated: int = 0
    errors: list[str] = field(default_factory=list)


def _match_tracked(tracked_list: list[TrackedChannel], native_id: str, handle: str | None) -> TrackedChannel | None:
    """
    Empareja un canal normalizado (devuelto por la API) con el registro de
    `TrackedChannel` que lo originó. No se puede asumir que el orden de la
    respuesta en lote coincide con el orden pedido, así que se matchea por
    ID nativo primero y por handle como respaldo (p. ej. si trackeaste un
    canal de YouTube por @handle, la API devuelve su UC-id real y hay que
    reconciliarlo igual).
    """
    for tc in tracked_list:
        if tc.native_id == native_id:
            return tc
    handle_norm = (handle or "").lstrip("@").lower()
    if handle_norm:
        for tc in tracked_list:
            if (tc.handle or "").lstrip("@").lower() == handle_norm or tc.native_id.lstrip("@").lower() == handle_norm:
                return tc
    return None


async def run_daily_snapshot() -> DailyJobResult:
    result = DailyJobResult()

    async with get_session_ctx() as session:
        tracked = await list_tracked(session, active_only=True)
        result.channels_evaluated = len(tracked)
        if not tracked:
            return result

        by_platform: dict[Platform, list[TrackedChannel]] = {}
        for tc in tracked:
            platform = Platform(tc.platform)
            by_platform.setdefault(platform, []).append(tc)

        for platform, group in by_platform.items():
            collector_cls = _COLLECTORS.get(platform)
            if collector_cls is None:
                result.errors.append(f"Plataforma sin colector: {platform}")
                continue
            collector = collector_cls()
            identifiers = [tc.native_id for tc in group]

            try:
                raw_results = await collector.get_channels_batch(identifiers)
            except Exception as exc:  # noqa: BLE001 - reportar y seguir con otras plataformas
                result.errors.append(f"{platform.value}: fallo al consultar canales en lote: {exc}")
                continue

            try:
                unified = normalize_channels(raw_results, platform)
            except Exception as exc:  # noqa: BLE001
                result.errors.append(f"{platform.value}: fallo al normalizar resultados: {exc}")
                continue

            matched_ids: set[int] = set()
            for channel in unified:
                tracked_channel = _match_tracked(group, channel.native_id, channel.handle)
                if tracked_channel is None:
                    result.errors.append(
                        f"{platform.value}: no se pudo emparejar '{channel.native_id}' con un canal trackeado"
                    )
                    continue
                matched_ids.add(tracked_channel.id)
                try:
                    _, created = await upsert_snapshot_from_channel(session, tracked_channel.id, channel)
                    if created:
                        result.snapshots_created += 1
                    else:
                        result.snapshots_updated += 1
                except Exception as exc:  # noqa: BLE001
                    result.errors.append(
                        f"{platform.value}:{tracked_channel.native_id}: error guardando snapshot: {exc}"
                    )

            for tc in group:
                if tc.id not in matched_ids:
                    result.errors.append(f"{platform.value}:{tc.native_id}: no devuelto por la API (¿borrado o renombrado?)")

    return result
