"""
Detección de cuentas potencialmente bot / con métricas infladas.

Regla (ver "Módulo Matemático y Detección de Anomalías"):

    Anomaly Flag  <=>  (Seguidores >= P75)  AND  (NER < Q1 - 1.5 * IQR)

Es decir: canales grandes (top 25% por audiencia) cuyo engagement
normalizado cae muy por debajo de lo esperable para la cohorte
(outlier bajo según la regla clásica de Tukey de 1.5*IQR). Es una señal
de posible compra de seguidores/vistas, no una prueba definitiva.
"""
import numpy as np

from app.core.exceptions import InsufficientDataError
from app.models.schemas import AnomalyFlag, UnifiedChannel


def detect_anomalies(channels: list[UnifiedChannel]) -> list[AnomalyFlag]:
    if len(channels) < 4:
        raise InsufficientDataError(
            "Se necesitan al menos 4 canales para estimar cuartiles de forma confiable"
        )

    followers = np.asarray([c.followers for c in channels], dtype=float)
    ner = np.asarray([c.normalized_er for c in channels], dtype=float)

    p75_followers = float(np.percentile(followers, 75))
    q1_ner = float(np.percentile(ner, 25))
    q3_ner = float(np.percentile(ner, 75))
    iqr_ner = q3_ner - q1_ner
    lower_bound = q1_ner - 1.5 * iqr_ner

    flagged: list[AnomalyFlag] = []
    for channel in channels:
        if channel.followers >= p75_followers and channel.normalized_er < lower_bound:
            flagged.append(AnomalyFlag(
                universal_id=channel.universal_id,
                name=channel.name,
                platform=channel.platform,
                followers=channel.followers,
                normalized_er=channel.normalized_er,
                reason=(
                    f"Seguidores ({channel.followers:,}) >= P75 ({p75_followers:,.0f}) "
                    f"pero NER ({channel.normalized_er:.3f}%) < límite inferior "
                    f"Q1 - 1.5*IQR ({lower_bound:.3f}%)"
                ),
            ))
    return flagged
