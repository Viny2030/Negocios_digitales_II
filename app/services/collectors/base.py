"""
Interfaz abstracta para los colectores de plataformas ("adaptadores" en el
diagrama de arquitectura). Cada plataforma implementa `search()` y devuelve
una lista de diccionarios "crudos" (raw), tal cual los entrega la API de
origen. La homogeneización ocurre después, en `services/analytics/normalizer.py`.

Mantener esta capa desacoplada es lo que permite agregar Instagram, Twitch,
Telegram, etc. en el futuro sin tocar el motor estadístico.
"""
import asyncio
import random
from abc import ABC, abstractmethod
from typing import Any

from app.models.domain import Platform


# Tipo simple: cada colector devuelve una lista de dicts crudos.
RawChannelData = dict[str, Any]

# Semillas de tópicos usadas por el `discover()` genérico (ver más abajo) para
# simular diversidad de nichos ("todos los temas", sin que el usuario elija
# una categoría) cuando la plataforma no tiene un endpoint nativo de
# trending multi-categoría al que engancharse (p. ej. TikTok — ver README).
DEFAULT_DISCOVER_TOPICS: list[str] = [
    "música", "gaming", "entretenimiento", "noticias", "deportes",
    "tecnología", "educación", "humor", "cocina", "viajes",
]


class BaseCollector(ABC):
    """Contrato común que deben cumplir todos los adaptadores de plataforma."""

    platform: Platform

    def __init__(self) -> None:
        if not hasattr(self, "platform"):
            raise NotImplementedError("Cada colector debe declarar su 'platform'")

    @abstractmethod
    async def is_configured(self) -> bool:
        """True si hay credenciales válidas cargadas para esta plataforma."""
        raise NotImplementedError

    @abstractmethod
    async def search(self, query: str, limit: int) -> list[RawChannelData]:
        """
        Busca canales/creadores relacionados con `query` y devuelve hasta
        `limit` registros crudos (sin normalizar).
        """
        raise NotImplementedError

    @abstractmethod
    async def get_channel(self, identifier: str) -> RawChannelData | None:
        """
        Trae el estado ACTUAL de un canal puntual por su ID nativo o @handle
        (a diferencia de `search`, que busca por tema). Es lo que usa el
        worker diario para snapshotear canales trackeados. Devuelve None si
        el canal no existe / no se pudo resolver.
        """
        raise NotImplementedError

    async def get_channels_batch(self, identifiers: list[str]) -> list[RawChannelData]:
        """
        Variante en lote de `get_channel`, para plataformas cuya API lo
        soporte de forma más barata (p. ej. YouTube channels.list con hasta
        50 IDs por llamada). El default hace una llamada por identificador;
        los colectores que puedan batchear deben sobreescribir este método.
        """
        results = []
        for identifier in identifiers:
            raw = await self.get_channel(identifier)
            if raw is not None:
                results.append(raw)
        return results

    async def discover(self, limit: int) -> list[RawChannelData]:
        """
        Devuelve candidatos de "todos los temas" (sin que el llamador tenga
        que elegir una categoría/tema puntual) — usado por
        GET /api/v1/channels/discover para armar la base de canales a
        trackear ordenados por métrica, en vez de buscar tema por tema.

        Implementación genérica: reparte `limit` entre un set fijo de
        tópicos semilla (`DEFAULT_DISCOVER_TOPICS`) y llama a `search()` por
        cada uno en paralelo — funciona igual en modo real o mock porque
        reutiliza `search()` tal cual. Un colector con un endpoint nativo de
        "trending" multi-categoría (p. ej. YouTube `videos?chart=
        mostPopular`) debe sobreescribir este método con esa estrategia más
        precisa y barata en cuota; puede caer a esta implementación llamando
        `await super().discover(limit)` cuando no haya credenciales.
        """
        per_topic = max(2, (limit // len(DEFAULT_DISCOVER_TOPICS)) + 1)
        results_per_topic = await asyncio.gather(
            *(self.search(topic, per_topic) for topic in DEFAULT_DISCOVER_TOPICS)
        )
        combined: list[RawChannelData] = []
        for topic_results in results_per_topic:
            combined.extend(topic_results)
        return combined

    # ------------------------------------------------------------------
    # Utilidad compartida: generación de datos simulados (modo mock).
    # Se usa cuando no hay credenciales configuradas, para poder ejercitar
    # el pipeline completo (ingesta -> normalización -> estadística) sin
    # depender de que el usuario ya tenga aprobadas las API keys.
    # ------------------------------------------------------------------
    def _seeded_rng(self, query: str) -> random.Random:
        """RNG determinístico por query, para que los mocks sean reproducibles."""
        seed = f"{self.platform}:{query}"
        return random.Random(seed)
