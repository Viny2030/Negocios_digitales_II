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
import asyncio

import httpx

from app.core.config import get_settings
from app.core.exceptions import PlatformAPIError, QuotaExceededError
from app.models.domain import Platform
from app.services.collectors.base import BaseCollector, RawChannelData

settings = get_settings()

# IDs de categoría de YouTube (`videoCategoryId`) usados por `discover()` /
# `discover_by_category()` para armar una foto de "todos los temas" sin que
# el usuario tenga que elegir una categoría puntual. Se dejan afuera las
# categorías de género de películas (30-44: Action/Adventure, Classics,
# Horror, etc.) porque YouTube no publica un "mostPopular" real para ellas
# en la inmensa mayoría de las regiones (devuelven vacío o 404) — el resto
# cubre los géneros de canal más disímiles a propósito, para maximizar la
# diversidad de nichos en una sola pasada.
DISCOVER_CATEGORY_LABELS: dict[str, str] = {
    "1": "Cine y animación",
    "2": "Autos y vehículos",
    "10": "Música",
    "15": "Mascotas y animales",
    "17": "Deportes",
    "19": "Viajes y eventos",
    "20": "Gaming",
    "22": "Blogs (People & Blogs)",
    "23": "Comedia",
    "24": "Entretenimiento",
    "25": "Noticias y política",
    "26": "Estilo de vida (Howto & Style)",
    "27": "Educación",
    "28": "Ciencia y tecnología",
    "29": "ONGs y activismo",
}
DISCOVER_CATEGORY_IDS: list[str] = list(DISCOVER_CATEGORY_LABELS)


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

    async def discover(self, limit: int, region_codes: list[str] | None = None) -> list[RawChannelData]:
        """
        Arma una foto de "todos los temas" para GET /api/v1/channels/discover,
        sin pedirle al usuario que elija una categoría: recorre los videos
        "mostPopular" (trending) de YouTube combinando cada categoría de
        `DISCOVER_CATEGORY_IDS` con cada región de `region_codes` (default:
        `settings.DISCOVER_REGION_CODES`), pagina varias veces por
        combinación (`DISCOVER_PAGES_PER_REGION_CATEGORY`) para juntar más
        candidatos de los que entran en una sola página de 50, junta los
        canales dueños de esos videos (deduplicados entre TODAS las
        categorías/regiones) y trae sus estadísticas en lote.

        Mucho más barato en cuota que buscar tema por tema con `search.list`
        (100 unidades/llamada): `videos.list` cuesta 1 unidad/llamada. El
        caller (orchestrator) es quien ordena de mayor a menor por la
        métrica elegida y recorta a `limit`; acá se junta la mayor variedad
        posible de candidatos (no hay un tope artificial propio).
        """
        if not await self.is_configured():
            if settings.USE_MOCK_DATA_IF_NO_CREDENTIALS:
                # Sin credenciales no hay "trending" real: cae al fallback
                # genérico de BaseCollector (múltiples búsquedas mock por tema).
                return await super().discover(limit)
            raise PlatformAPIError("youtube", "YOUTUBE_API_KEY no configurada")

        regions = region_codes or settings.DISCOVER_REGION_CODES
        async with httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT_SECONDS) as client:
            by_category = await self._discover_trending_channel_ids_by_category(client, regions)
            all_ids: list[str] = []
            seen: set[str] = set()
            for ids in by_category.values():
                for channel_id in ids:
                    if channel_id not in seen:
                        seen.add(channel_id)
                        all_ids.append(channel_id)
            if not all_ids:
                return []
            return await self._fetch_channels_batch(client, all_ids)

    async def discover_by_category(
        self, limit_per_category: int, region_codes: list[str] | None = None
    ) -> dict[str, list[RawChannelData]]:
        """
        Variante de `discover()` que NO mezcla las categorías entre sí:
        devuelve un ranking independiente por cada una (ver
        GET /api/v1/channels/discover/by-category), para poder "abarcar
        todos los temas" viendo cada nicho por separado en vez de una
        sola lista global donde los géneros más grandes (música, gaming)
        tapan a los más chicos.
        """
        if not await self.is_configured():
            if settings.USE_MOCK_DATA_IF_NO_CREDENTIALS:
                return await super().discover_by_category(limit_per_category)
            raise PlatformAPIError("youtube", "YOUTUBE_API_KEY no configurada")

        regions = region_codes or settings.DISCOVER_REGION_CODES
        async with httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT_SECONDS) as client:
            by_category_ids = await self._discover_trending_channel_ids_by_category(client, regions)
            results: dict[str, list[RawChannelData]] = {}
            for category_id, channel_ids in by_category_ids.items():
                results[category_id] = await self._fetch_channels_batch(client, channel_ids)
            return results

    async def _discover_trending_channel_ids_by_category(
        self, client: httpx.AsyncClient, region_codes: list[str]
    ) -> dict[str, list[str]]:
        """
        Para cada categoría en `DISCOVER_CATEGORY_IDS`, combina el trending
        de todas las `region_codes` (paginando `DISCOVER_PAGES_PER_REGION_
        CATEGORY` veces cada una) en una única lista de channelIds
        deduplicados. Las combinaciones región+categoría se resuelven en
        paralelo, acotadas por un semáforo (`HTTP_MAX_CONCURRENT_REQUESTS`)
        para no disparar cientos de requests simultáneos.
        """
        semaphore = asyncio.Semaphore(settings.HTTP_MAX_CONCURRENT_REQUESTS)
        by_category: dict[str, list[str]] = {cat: [] for cat in DISCOVER_CATEGORY_IDS}
        seen_by_category: dict[str, set[str]] = {cat: set() for cat in DISCOVER_CATEGORY_IDS}
        quota_exceeded = False

        async def fetch_page(category_id: str, region_code: str, page_token: str | None):
            nonlocal quota_exceeded
            if quota_exceeded:
                return None
            params = {
                "part": "snippet",
                "chart": "mostPopular",
                "regionCode": region_code,
                "videoCategoryId": category_id,
                "maxResults": 50,
                "key": self.api_key,
            }
            if page_token:
                params["pageToken"] = page_token
            async with semaphore:
                resp = await client.get(f"{self.base_url}/videos", params=params)
            if resp.status_code == 403 and "quota" in resp.text.lower():
                # Sin cuota para seguir: se corta acá, se devuelve lo ya juntado.
                quota_exceeded = True
                return None
            if resp.status_code >= 400:
                # Una combinación región+categoría puede no tener "mostPopular"
                # ahí (o el parámetro no ser válido) — se sigue con el resto.
                return None
            return resp.json()

        async def fetch_category_region(category_id: str, region_code: str) -> None:
            page_token: str | None = None
            for _ in range(settings.DISCOVER_PAGES_PER_REGION_CATEGORY):
                data = await fetch_page(category_id, region_code, page_token)
                if not data:
                    break
                for item in data.get("items", []):
                    channel_id = item.get("snippet", {}).get("channelId")
                    if channel_id and channel_id not in seen_by_category[category_id]:
                        seen_by_category[category_id].add(channel_id)
                        by_category[category_id].append(channel_id)
                page_token = data.get("nextPageToken")
                if not page_token:
                    break

        await asyncio.gather(*(
            fetch_category_region(category_id, region_code)
            for category_id in DISCOVER_CATEGORY_IDS
            for region_code in region_codes
        ))
        return by_category

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
