"""
Adaptador TikTok.

Nota importante: la API oficial de TikTok (Research API / Display API)
exige aprobación institucional y no expone una búsqueda libre de creadores
por keyword para la mayoría de los niveles de acceso. Este colector:

  1. Si hay `TIKTOK_CLIENT_KEY` / `TIKTOK_CLIENT_SECRET`, resuelve un
     access token vía OAuth2 client_credentials y deja preparada la
     llamada de búsqueda (`_search_creators`), lista para adaptarse al
     endpoint que tu nivel de acceso tenga habilitado.
  2. Si no hay credenciales (caso más común en desarrollo), cae a modo
     mock — igual que YouTube — para poder probar el pipeline completo.

Esto respeta el principio de "colector desacoplado": el resto del
sistema (normalizer, estadística, endpoints) no necesita saber si el
dato vino de la API real o del modo simulado.
"""
import httpx

from app.core.config import get_settings
from app.core.exceptions import PlatformAPIError
from app.models.domain import Platform
from app.services.collectors.base import BaseCollector, RawChannelData

settings = get_settings()


class TikTokCollector(BaseCollector):
    platform = Platform.TIKTOK

    def __init__(self) -> None:
        super().__init__()
        self.client_key = settings.TIKTOK_CLIENT_KEY
        self.client_secret = settings.TIKTOK_CLIENT_SECRET
        self.base_url = settings.TIKTOK_API_BASE_URL

    async def is_configured(self) -> bool:
        return bool(self.client_key and self.client_secret)

    async def search(self, query: str, limit: int) -> list[RawChannelData]:
        if not await self.is_configured():
            if settings.USE_MOCK_DATA_IF_NO_CREDENTIALS:
                return self._mock_results(query, limit)
            raise PlatformAPIError("tiktok", "TIKTOK_CLIENT_KEY/SECRET no configuradas")

        async with httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT_SECONDS) as client:
            token = await self._get_access_token(client)
            return await self._search_creators(client, token, query, limit)

    async def get_channel(self, identifier: str) -> RawChannelData | None:
        username = identifier.lstrip("@")
        if not await self.is_configured():
            if settings.USE_MOCK_DATA_IF_NO_CREDENTIALS:
                return self._mock_single(username)
            raise PlatformAPIError("tiktok", "TIKTOK_CLIENT_KEY/SECRET no configuradas")

        async with httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT_SECONDS) as client:
            token = await self._get_access_token(client)
            return await self._fetch_user_info(client, token, username)

    async def get_channels_batch(self, identifiers: list[str]) -> list[RawChannelData]:
        """
        La API de Research de TikTok no tiene un endpoint de lote para
        `user/info` — se resuelve un usuario por llamada. Usado por el
        worker diario para snapshotear canales trackeados.
        """
        results: list[RawChannelData] = []
        for identifier in identifiers:
            raw = await self.get_channel(identifier)
            if raw is not None:
                results.append(raw)
        return results

    async def _fetch_user_info(self, client: httpx.AsyncClient, token: str, username: str) -> RawChannelData | None:
        """
        `research/user/info/` — este SÍ es el uso real/documentado del
        endpoint (lookup de un username puntual), a diferencia de
        `_search_creators` que lo fuerza a simular una búsqueda por tema.

        Limitación real de esta API (igual de espíritu que la de YouTube en
        `normalizer.py`): devuelve `likes_count` (total histórico) pero NO
        vistas de video agregadas ni comments/shares/saves — esas métricas
        solo están disponibles consultando video por video. Se remapea al
        mismo shape que `search()`/mock para que `normalize_tiktok_channel`
        no necesite dos caminos distintos; `video_views_sum` en 0 hace que
        el NER de estos snapshots dé 0 en vez de un número engañoso.
        """
        fields = "display_name,follower_count,following_count,likes_count,video_count"
        resp = await client.post(
            f"{self.base_url}/research/user/info/?fields={fields}",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"username": username},
        )
        if resp.status_code == 404:
            return None
        if resp.status_code >= 400:
            raise PlatformAPIError("tiktok", f"HTTP {resp.status_code}: {resp.text[:200]}")
        data = resp.json().get("data", {})
        if not data:
            return None
        return {
            "unique_id": username,
            "user_id": username,
            "nickname": data.get("display_name", username),
            "follower_count": data.get("follower_count", 0),
            "video_count": data.get("video_count", 0),
            "video_views_sum": 0,  # no disponible en este endpoint
            "likes_sum": data.get("likes_count", 0),
            "comments_sum": 0,
            "shares_sum": 0,
            "saves_sum": 0,
        }

    # ------------------------------------------------------------------
    # Llamadas reales a la API (OAuth2 client_credentials)
    # ------------------------------------------------------------------

    async def _get_access_token(self, client: httpx.AsyncClient) -> str:
        resp = await client.post(
            "https://open.tiktokapis.com/v2/oauth/token/",
            data={
                "client_key": self.client_key,
                "client_secret": self.client_secret,
                "grant_type": "client_credentials",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if resp.status_code >= 400:
            raise PlatformAPIError("tiktok", f"No se pudo obtener access_token: HTTP {resp.status_code}")
        data = resp.json()
        token = data.get("access_token")
        if not token:
            raise PlatformAPIError("tiktok", "Respuesta de OAuth sin access_token")
        return token

    async def _search_creators(
        self, client: httpx.AsyncClient, token: str, query: str, limit: int
    ) -> list[RawChannelData]:
        """
        Punto de extensión: ajustar el endpoint/payload al producto TikTok
        habilitado para tu app (Research API / Content Posting / Display).
        Estructura conforme a la convención v2 de TikTok for Developers.
        """
        resp = await client.post(
            f"{self.base_url}/research/user/info/",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"query": query, "max_count": min(limit, 50)},
        )
        if resp.status_code >= 400:
            raise PlatformAPIError("tiktok", f"HTTP {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        return data.get("data", {}).get("users", [])

    # ------------------------------------------------------------------
    # Modo mock (sin credenciales)
    # ------------------------------------------------------------------

    def _mock_key(self, username: str) -> str:
        """
        Normaliza el identificador antes de sembrar el mock: el worker
        diario vuelve a consultar por `native_id` (que en mock es
        `tt_mock_<username>`, ver `_mock_single`), no por el @handle
        original — sin esto, el mismo canal daría datos simulados
        distintos en el alta manual vs. en el primer job diario.
        """
        key = username
        if key.startswith("tt_mock_"):
            key = key[len("tt_mock_"):]
        return key.lower()

    def _mock_single(self, username: str) -> RawChannelData:
        """Mock determinístico para un único canal (usado por el worker diario)."""
        rng = self._seeded_rng(self._mock_key(username))
        followers = int(rng.lognormvariate(10, 2.2))
        video_views = int(followers * rng.uniform(8, 60))
        videos = rng.randint(30, 3000)
        likes = int(video_views * rng.uniform(0.03, 0.09))
        comments = int(video_views * rng.uniform(0.002, 0.01))
        shares = int(video_views * rng.uniform(0.001, 0.006))
        saves = int(video_views * rng.uniform(0.002, 0.012))
        return {
            "unique_id": username,
            "user_id": f"tt_mock_{username}",
            "nickname": f"{username.title()} (tracked)",
            "follower_count": followers,
            "video_count": videos,
            "video_views_sum": video_views,
            "likes_sum": likes,
            "comments_sum": comments,
            "shares_sum": shares,
            "saves_sum": saves,
            "_mock": True,
        }

    def _mock_results(self, query: str, limit: int) -> list[RawChannelData]:
        rng = self._seeded_rng(query)
        mocked: list[RawChannelData] = []
        for i in range(limit):
            followers = int(rng.lognormvariate(9.5, 2.4))
            video_views = int(followers * rng.uniform(8, 60))
            videos = rng.randint(30, 3000)
            likes = int(video_views * rng.uniform(0.03, 0.09))
            comments = int(video_views * rng.uniform(0.002, 0.01))
            shares = int(video_views * rng.uniform(0.001, 0.006))
            saves = int(video_views * rng.uniform(0.002, 0.012))
            mocked.append({
                "unique_id": f"{query.replace(' ', '')}{i+1}",
                "user_id": f"tt_mock_{query.replace(' ', '_')}_{i}",
                "nickname": f"{query.title()} TikTok {i+1}",
                "follower_count": followers,
                "video_count": videos,
                "video_views_sum": video_views,
                "likes_sum": likes,
                "comments_sum": comments,
                "shares_sum": shares,
                "saves_sum": saves,
                "_mock": True,
            })
        return mocked
