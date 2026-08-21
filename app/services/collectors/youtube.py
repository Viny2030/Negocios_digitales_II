"""
Adaptador YouTube — YouTube Data API v3.

Estrategia de dos llamadas para minimizar el consumo de cuota:
  1. `search.list` (type=channel)  -> 100 unidades, resuelve IDs de canal
     que matchean la query.
  2. `channels.list` (hasta 50 IDs por llamada) -> 1 unidad, trae
     snippet + statistics de esos IDs en batch.

Esto es deliberado: pedir `channels.list` en lote es ~100x más barato en
cuota que iterar `search.list` por canal (ver "Límites de Ingesta" en el
diseño). Con 10.000 unidades/día se pueden resolver hasta 100 búsquedas
y cientos de miles de lecturas de canal.
"""
import httpx

from app.core.config import get_settings
from app.core.exceptions import PlatformAPIError, QuotaExceededError
from app.models.domain import Platform
from app.services.collectors.base import BaseCollector, RawChannelData

settings = get_settings()


class YouTubeCollector(BaseCollector):
    platform = Platform.YOUTUBE

    def __init__(self) -> None:
        super().__init__()
        self.api_key = settings.YOUTUBE_API_KEY
        self.base_url = settings.YOUTUBE_API_BASE_URL

    async def is_configured(self) -> bool:
        return bool(self.api_key)

    async def search(self, query: str, limit: int) -> list[RawChannelData]:
        if not await self.is_configured():
            if settings.USE_MOCK_DATA_IF_NO_CREDENTIALS:
                return self._mock_results(query, limit)
            raise PlatformAPIError("youtube", "YOUTUBE_API_KEY no configurada")

        async with httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT_SECONDS) as client:
            channel_ids = await self._search_channel_ids(client, query, limit)
            if not channel_ids:
                return []
            return await self._fetch_channels_batch(client, channel_ids)

    async def get_channel(self, identifier: str) -> RawChannelData | None:
        results = await self.get_channels_batch([identifier])
        return results[0] if results else None

    async def get_channels_batch(self, identifiers: list[str]) -> list[RawChannelData]:
        """
        Usado por el worker diario para snapshotear canales trackeados.
        `identifiers` puede mezclar IDs nativos (empiezan con 'UC') y
        @handles. Los IDs se piden en un único `channels.list` en lote
        (hasta 50, 1 unidad de cuota); `forHandle` solo acepta un valor por
        llamada, así que los handles se resuelven uno por uno.
        """
        if not await self.is_configured():
            if settings.USE_MOCK_DATA_IF_NO_CREDENTIALS:
                return [self._mock_single(ident) for ident in identifiers]
            raise PlatformAPIError("youtube", "YOUTUBE_API_KEY no configurada")

        raw_ids = [i for i in identifiers if not i.startswith("@")]
        handles = [i for i in identifiers if i.startswith("@")]

        async with httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT_SECONDS) as client:
            results: list[RawChannelData] = []
            if raw_ids:
                results.extend(await self._fetch_channels_batch(client, raw_ids))
            for handle in handles:
                params = {"part": "snippet,statistics", "forHandle": handle.lstrip("@"), "key": self.api_key}
                resp = await client.get(f"{self.base_url}/channels", params=params)
                self._raise_for_status(resp)
                items = resp.json().get("items", [])
                if items:
                    results.append(items[0])
            return results

    # ------------------------------------------------------------------
    # Llamadas reales a la API
    # ------------------------------------------------------------------

    async def _search_channel_ids(self, client: httpx.AsyncClient, query: str, limit: int) -> list[str]:
        params = {
            "part": "snippet",
            "type": "channel",
            "q": query,
            "maxResults": min(limit, 50),
            "key": self.api_key,
        }
        resp = await client.get(f"{self.base_url}/search", params=params)
        self._raise_for_status(resp)
        data = resp.json()
        return [item["snippet"]["channelId"] if "channelId" in item.get("snippet", {})
                else item["id"]["channelId"] for item in data.get("items", [])]

    async def _fetch_channels_batch(self, client: httpx.AsyncClient, channel_ids: list[str]) -> list[RawChannelData]:
        results: list[RawChannelData] = []
        # channels.list acepta hasta 50 IDs separados por coma en una sola llamada.
        for i in range(0, len(channel_ids), 50):
            batch = channel_ids[i:i + 50]
            params = {
                "part": "snippet,statistics",
                "id": ",".join(batch),
                "key": self.api_key,
            }
            resp = await client.get(f"{self.base_url}/channels", params=params)
            self._raise_for_status(resp)
            data = resp.json()
            results.extend(data.get("items", []))
        return results

    def _raise_for_status(self, resp: httpx.Response) -> None:
        if resp.status_code == 403:
            body = resp.text.lower()
            if "quota" in body:
                raise QuotaExceededError("youtube")
            raise PlatformAPIError("youtube", f"Acceso denegado (403): {resp.text[:200]}")
        if resp.status_code >= 400:
            raise PlatformAPIError("youtube", f"HTTP {resp.status_code}: {resp.text[:200]}")

    # ------------------------------------------------------------------
    # Modo mock (sin credenciales)
    # ------------------------------------------------------------------

    def _mock_key(self, identifier: str) -> str:
        """
        Normaliza el identificador antes de generar/sembrar el mock, para que
        el mismo canal dé siempre los mismos datos simulados sin importar si
        se lo consulta por @handle (alta manual) o por su ID nativo mock ya
        resuelto (worker diario, que siempre re-consulta por `native_id`).
        Sin esto, un canal trackeado por @handle mostraría un salto brusco
        e irreal entre el primer snapshot y el del primer job diario.
        """
        key = identifier.lstrip("@")
        if key.startswith("UC_mock_"):
            key = key[len("UC_mock_"):]
        return key.lower()

    def _mock_single(self, identifier: str) -> RawChannelData:
        """Mock determinístico para un único canal (usado por el worker diario)."""
        label = self._mock_key(identifier)
        rng = self._seeded_rng(label)
        subs = int(rng.lognormvariate(10, 2.0))
        views = int(subs * rng.uniform(15, 120))
        videos = rng.randint(20, 1500)
        return {
            "id": identifier if not identifier.startswith("@") else f"UC_mock_{label}",
            "snippet": {"title": f"{label.title()} (tracked)", "customUrl": f"@{label}"},
            "statistics": {
                "subscriberCount": str(subs),
                "viewCount": str(views),
                "videoCount": str(videos),
                "commentCount": str(int(views * rng.uniform(0.0005, 0.004))),
            },
            "_mock": True,
        }

    def _mock_results(self, query: str, limit: int) -> list[RawChannelData]:
        rng = self._seeded_rng(query)
        mocked: list[RawChannelData] = []
        for i in range(limit):
            subs = int(rng.lognormvariate(9, 2.2))  # distribución sesgada, realista
            views = int(subs * rng.uniform(15, 120))
            videos = rng.randint(20, 1500)
            mocked.append({
                "id": f"UC_mock_{query.replace(' ', '_')}_{i}",
                "snippet": {
                    "title": f"{query.title()} Channel {i+1}",
                    "customUrl": f"@{query.replace(' ', '')}{i+1}",
                    "description": f"Canal mock generado para la búsqueda '{query}'.",
                },
                "statistics": {
                    "subscriberCount": str(subs),
                    "viewCount": str(views),
                    "videoCount": str(videos),
                    "commentCount": str(int(views * rng.uniform(0.0005, 0.004))),
                },
                "_mock": True,
            })
        return mocked
