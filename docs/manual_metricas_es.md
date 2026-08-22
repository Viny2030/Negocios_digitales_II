# Manual de métricas — Channel Analytics Core

Este documento explica, en lenguaje llano, cada métrica que calcula el sistema:
qué significa, cómo se calcula y qué endpoint la devuelve. Pensado para
alguien que use el dashboard o la API sin haber leído el código.

> Versión en inglés: [`manual_metricas_en.md`](./manual_metricas_en.md) / English version: [`manual_metricas_en.md`](./manual_metricas_en.md)

## 1. Métricas de canal (inventario y audiencia)

| Campo (API) | Nombre | Qué es |
|---|---|---|
| `followers` | Suscriptores / Seguidores | Cantidad total de suscriptores (YouTube) o seguidores (TikTok) del canal, tal cual lo reporta la plataforma. |
| `total_views` | Vistas totales | Suma histórica de todas las reproducciones de todos los videos del canal (no es "vistas de esta semana", es el acumulado de toda la vida del canal). |
| `total_posts` | Publicaciones | Cantidad de videos publicados por el canal. |
| `raw_interactions` | Interacciones crudas | Suma de señales de interacción disponibles (ver más abajo) en la última muestra tomada. Es la base para calcular el NER (Engagement Rate normalizado). |
| `likes`, `comments`, `shares`, `saves` | Desglose de interacciones | Componentes individuales de `raw_interactions`. **Importante**: la API pública de YouTube no expone "me gusta" agregados a nivel canal, así que en YouTube `likes`, `shares` y `saves` quedan en 0 y `raw_interactions` se aproxima solo con `comments`. En TikTok sí se suman las cuatro señales. |
| `tier` | Tramo de audiencia | Clasificación automática por cantidad de seguidores: **nano** (&lt;10k), **micro** (10k–100k), **mid** (100k–500k), **macro** (500k–1M), **mega** (&gt;1M). |

## 2. Métricas de engagement

| Campo / Sigla | Nombre | Fórmula | Qué mide |
|---|---|---|---|
| `normalized_er` (NER) | Engagement Rate normalizado | `(Interacciones totales / Vistas) × 100` | Qué tan activamente reacciona la audiencia en relación a cuánta gente vio el contenido. Un canal con muchos seguidores pero NER bajo puede tener audiencia poco activa (o inflada). |
| AS (Attention Score) | Puntaje de atención | `Tiempo promedio consumido / Duración total del contenido` | Cuánto de cada video mira en promedio la audiencia. **Todavía no se calcula en vivo**: requiere telemetría de reproducción por video (tiempo visto, duración) que la API de búsqueda/perfil no entrega — queda como utilidad lista para conectar cuando se incorpore esa fuente de datos. |
| PFI (Production Frequency Index) | Índice de frecuencia de producción | `Publicaciones mensuales × (1 / desvío estándar de días entre publicaciones)` | Qué tan seguido Y regular publica un canal (no es lo mismo publicar 12 videos parejos en el mes que 12 videos todos juntos y después silencio). **Todavía no se calcula en vivo** por la misma razón que AS: necesita las fechas de publicación de cada video individual. |

## 3. Estadística descriptiva (percentiles, dispersión y forma)

Se aplica sobre un conjunto de canales (por ejemplo, todos los resultados de
una búsqueda) para una métrica dada (seguidores, NER, etc.). Endpoint:
`GET /analytics/distribution`.

| Campo | Qué es |
|---|---|
| `mean` / `median` | Promedio y mediana (valor central). La mediana es más resistente a un solo canal gigante que distorsione el promedio. |
| `min` / `max` / `range` | Mínimo, máximo y la diferencia entre ambos. |
| `p5`, `p10`, `p25`, `p75`, `p90`, `p95` | Percentiles: por ejemplo, `p90` es el valor por debajo del cual está el 90% de los canales — el 10% restante está por encima. |
| `iqr` | Rango intercuartílico (`p75 − p25`): dónde se concentra el "canal típico", ignorando extremos. |
| `std_dev` | Desvío estándar: cuánto se dispersan los valores respecto al promedio. |
| `coefficient_of_variation` | `std_dev / mean`. Permite comparar la dispersión de métricas con escalas muy distintas (p. ej. seguidores vs. NER) en una misma unidad relativa. |
| `skewness` (asimetría) | Si la distribución tiene una "cola" hacia valores altos (positiva, lo más común: pocos canales gigantes) o hacia valores bajos (negativa). |
| `kurtosis` (curtosis) | Qué tan "puntiaguda" es la distribución comparada con una normal — valores altos indican más outliers de lo esperable. |

## 4. Desigualdad y concentración de audiencia

Responden a la pregunta "¿qué tan repartida está la audiencia entre los
canales de este grupo?". Endpoint: `GET /analytics/inequality`.

| Campo | Nombre | Rango | Qué mide |
|---|---|---|---|
| `gini_followers` | Coeficiente de Gini | 0 a 1 | 0 = todos los canales tienen la misma cantidad de seguidores (igualdad perfecta). 1 = un solo canal concentra toda la audiencia del grupo. |
| `pareto_alpha` | Exponente de Pareto (ley de potencia) | típicamente 1–3 | Qué tan pronunciada es la desigualdad tipo "80/20": valores más bajos (cerca de 1) indican una cola más pesada (pocos canales enormes dominan mucho más). `null` si no hay suficiente variación en los datos para estimarlo. |
| `top_10_pct_share` | Participación del top 10% | 0 a 1 | Qué proporción de los seguidores totales del grupo está en manos del 10% de canales más grandes. |

## 5. Correlación entre variables

Responden a preguntas como "¿publicar más seguido se relaciona con más
engagement?". Endpoint: `GET /analytics/correlation`. Se calculan dos
coeficientes en paralelo, ambos entre −1 (relación inversa perfecta) y +1
(relación directa perfecta), 0 = sin relación:

- **Spearman (`spearman_rho`)**: correlación de **rangos** — no asume que la
  relación sea una línea recta, y es más resistente a un outlier viral que
  distorsione todo. Es el coeficiente principal que usa el sistema para
  interpretar resultados.
- **Pearson (`pearson_r`)**: correlación **lineal** clásica, se muestra como
  referencia complementaria.

El campo `interpretation` traduce el número a una frase (ej. "Correlación
moderada positiva").

## 6. Detección de anomalías (posible inflado de métricas)

Endpoint: `GET /analytics/anomalies`. Regla aplicada sobre el grupo de
canales de una búsqueda:

> Se marca un canal cuando **Seguidores ≥ P75** (está en el 25% con más
> audiencia del grupo) **Y** **NER < Q1 − 1,5 × IQR** (su engagement cae muy
> por debajo de lo esperable, según el criterio clásico de outlier de
> Tukey).

En criollo: canales grandes cuya audiencia parece anormalmente poco activa
en comparación con canales de tamaño similar — una señal de posible compra
de seguidores/vistas, **no una prueba definitiva** (también puede pasar con
canales legítimos de nicho muy pasivo, o por la limitación de YouTube de no
exponer likes agregados).

## 7. Benchmarks de industria (referencia por plataforma)

Endpoint: `GET /analytics/benchmarks`. Son valores de referencia
publicados por la industria (no se recalculan por búsqueda), usados para
contextualizar si el ER promedio observado está **"below"** (por debajo),
**"within"** (dentro) o **"above"** (por encima) del rango típico.

| | YouTube | TikTok |
|---|---|---|
| Rango de Engagement Rate esperado | 1,5% – 3,5% | 4,0% – 9,0% |
| Métrica de retención | Retención relativa de audiencia (AVD) | Ratio de finalización (Completion Rate) |
| Frecuencia de publicación típica | 1–3 publicaciones/semana | 1–3 publicaciones/día |
| Vida útil del contenido | Larga (meses a años, por SEO/búsqueda) | Muy corta a media (24h a 7 días) |
| Riesgo de sesgo conocido | El clickbait infla vistas iniciales sin retención real | El algoritmo favorece viralidad efímera por sobre la base de seguidores |

> **Nota sobre YouTube y el ER**: como la API pública no expone "me gusta"
> agregados a nivel canal, el NER de YouTube en este sistema se aproxima
> solo con comentarios — por eso suele aparecer "below" del benchmark. Es
> una limitación de la métrica cruda documentada, no un error del sistema.

## 8. Descubrimiento "todos los temas" (sin categoría)

`GET /channels/discover` y `GET /channels/discover/by-category` no
requieren un tema/palabra clave: arman una foto de canales combinando el
contenido "trending" de YouTube en 15 categorías (música, gaming,
entretenimiento, noticias y política, deportes, ciencia y tecnología,
educación, comedia, estilo de vida, cine y animación, autos y vehículos,
mascotas y animales, viajes y eventos, blogs, ONGs y activismo) y varias
regiones a la vez (por default: Argentina, México, España, Estados
Unidos), para no depender de que el usuario adivine un tema puntual. El
resultado se puede ordenar de mayor a menor por cualquiera de las métricas
de la sección 1 (`followers`, `total_views`, `total_posts`,
`normalized_er`).

## 9. Glosario rápido de campos

| Campo | Significado en una línea |
|---|---|
| `universal_id` | Identificador único global del canal: `<plataforma>:<id_nativo>` (p. ej. `youtube:UCxxxx`). |
| `native_id` | ID propio de la plataforma de origen. |
| `platform` | `youtube` o `tiktok`. |
| `handle` | @usuario público del canal. |
| `content_format` | `vod` (video bajo demanda, YouTube) o `micro_video` (formato corto, TikTok). |
| `fetched_at` | Momento exacto en que se tomó ese dato. |

## 10. Planes de suscripción y qué desbloquea cada uno

El acceso a las métricas de este manual está organizado en 4 planes
(`app/models/domain.py::Plan`). **Todavía no hay pasarela de pago real
conectada** (Mercado Pago/Stripe quedan pendientes — proyecto
universitario): el cambio de plan se simula a mano vía `POST
/api/v1/auth/admin/set-plan`, o desde la pestaña "Cuenta" del dashboard.

| Plan | Qué desbloquea |
|---|---|
| `free` | Nada de lo listado en las secciones 1 a 6 — solo la sección 7 (`/analytics/benchmarks`), que es referencia estática y queda siempre pública. |
| `unica` | Acceso puntual (consume 1 "crédito de reporte" por consulta) a TODAS las métricas de este manual: estadística descriptiva, desigualdad, correlación, anomalías y descubrimiento "todos los temas" — nacionales e internacionales, incluidas las que no se miden en Argentina/Latinoamérica. |
| `mensual` | Lo mismo que `unica`, pero de forma continua (mientras la suscripción no venza), sin consumir créditos por consulta. |
| `premium` | Todo lo de `mensual` **+ las dos secciones siguientes** (proyecciones de tendencia y recomendaciones), exclusivas de este plan. |

### 10.1 Proyecciones de tendencia (premium)

Endpoint: `GET /premium/channels/{tracked_id}/projections`. Extrapola
cada métrica numérica de un canal trackeado (`followers`, `total_views`,
`total_posts`, `normalized_er`) hacia adelante en el tiempo, a partir de
su historial de snapshots **semanales** (ver sección 8 y el worker de
seguimiento diario/semanal en el `README.md`).

Cómo se calcula: un ajuste de mínimos cuadrados de grado 1 (una recta,
`numpy.polyfit`) sobre "días desde el primer snapshot" vs. el valor de la
métrica — **no es un modelo de inteligencia artificial**. Es una elección
deliberada: simple, explicable, y que mejora sola a medida que se
acumulan más semanas de historial. Requiere al menos 3 snapshots por
métrica; con menos, esa métrica se omite (no hace fallar el resto).

| Campo de la respuesta | Qué es |
|---|---|
| `weekly_trend` | Pendiente de la recta ajustada, expresada por semana (ej: `+1200` seguidores/semana). |
| `history_points` | Cantidad de snapshots usados para el ajuste — más puntos, proyección más confiable. |
| `projections[].weeks_ahead` / `projected_date` / `projected_value` | El valor extrapolado a 1, 4 y 12 semanas desde el último snapshot (configurable vía `?weeks_ahead=`). |
| `confidence_note` | Recordatorio de que es una guía direccional, no una predicción exacta — sobre todo con pocos snapshots todavía. |

### 10.2 Recomendaciones de política general (premium)

Endpoint: `GET /premium/channels/{tracked_id}/recommendations`. Motor de
**reglas fijas** (no IA generativa) que traduce el benchmark de industria
de la sección 7 y, cuando hay suficiente historial, la tendencia semanal
de seguidores calculada en 10.1, en sugerencias accionables por métrica.

Ejemplos de reglas aplicadas:

- Si el ER observado está **por debajo** del benchmark de la plataforma →
  prioridad "alta": sugiere formatos que inviten a comentar y revisar si
  el crecimiento de seguidores viene con audiencia realmente activa.
- Si el ER está **por encima** del benchmark → prioridad "informativa":
  sugiere escalar frecuencia de publicación manteniendo el formato actual.
- Si la tendencia semanal de seguidores es **negativa** → prioridad
  "alta": revisar consistencia de publicación reciente.
- Si la tendencia es **cero** (audiencia estancada) → prioridad "media":
  probar un formato o subtema nuevo.
- Si no se detecta ningún desvío → una nota informativa de que la
  estrategia actual está en línea con lo esperable.

Cada recomendación trae `metric` (a qué métrica corresponde), `priority`
(`alta` / `media` / `informativa`), `finding` (qué se detectó) y
`recommendation` (la sugerencia en sí).
