"""
Entidades y enumeraciones del dominio.

Estas clases representan conceptos de negocio compartidos entre todas
las plataformas soportadas, independientemente de cómo cada API externa
llame a sus propios campos.
"""
from enum import Enum


class Platform(str, Enum):
    """Plataformas soportadas en esta fase del proyecto."""

    YOUTUBE = "youtube"
    TIKTOK = "tiktok"
    ALL = "all"


class ContentTier(str, Enum):
    """
    Clasificación de canales por tamaño de audiencia (seguidores/suscriptores).

    Rangos definidos en el modelo conceptual:
        Nano   : < 10k
        Micro  : 10k - 100k
        Mid    : 100k - 500k
        Macro  : 500k - 1M
        Mega   : > 1M
    """

    NANO = "nano"
    MICRO = "micro"
    MID = "mid"
    MACRO = "macro"
    MEGA = "mega"

    @staticmethod
    def classify(followers: int) -> "ContentTier":
        if followers < 10_000:
            return ContentTier.NANO
        if followers < 100_000:
            return ContentTier.MICRO
        if followers < 500_000:
            return ContentTier.MID
        if followers < 1_000_000:
            return ContentTier.MACRO
        return ContentTier.MEGA


class ContentFormat(str, Enum):
    """Naturaleza operativa del contenido publicado por el canal."""

    VOD = "vod"                # Video bajo demanda (YouTube)
    MICRO_VIDEO = "micro_video"  # Micro-video / short form (TikTok)


class Plan(str, Enum):
    """
    Niveles de suscripción del sitio (arquitectura lista, sin pasarela de
    pago real conectada todavía — proyecto universitario, ver
    `app/services/users.py` y `POST /api/v1/auth/admin/set-plan` para
    simular manualmente un cambio de plan).

        FREE    : sin acceso a "toda la estadística" (solo lo público:
                  `/analytics/benchmarks`).
        UNICA   : compra puntual de UN reporte — consume 1
                  `report_credits` por cada endpoint de estadística
                  consultado, no es acceso continuo.
        MENSUAL : acceso continuo (mientras `plan_active_until` no venza)
                  a TODA la estadística del sitio: métricas nacionales e
                  internacionales, incluidas las que no se miden en
                  Argentina/Latinoamérica.
        PREMIUM : todo lo de MENSUAL + proyecciones de tendencia y
                  recomendaciones de política general para mejorar cada
                  métrica.
    """

    FREE = "free"
    UNICA = "unica"
    MENSUAL = "mensual"
    PREMIUM = "premium"
