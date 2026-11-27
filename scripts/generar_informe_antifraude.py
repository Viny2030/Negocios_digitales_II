"""
Genera el informe "Antifraude y métricas nuevas" en español e inglés:

    app/static/antifraude.html     -> /guia/antifraude
    app/static/antifraude_en.html  -> /guia/en/antifraude

Recoge la investigación de noviembre de 2026 sobre qué agregar a las estadísticas de los canales
para detectar me gusta, vistas y suscriptores falsos, qué métricas sumar y qué reglas de la API de
YouTube hay que cumplir. Los dos idiomas tienen las mismas secciones, en el mismo orden y con la
misma forma de bloques, así uno no puede quedar viejo respecto del otro. Después de editar este
archivo:

    python -m scripts.generar_informe_antifraude

tests/test_informe_antifraude.py falla si los HTML no coinciden con lo que genera este script.

Marcado mínimo dentro de los textos: `código`, **negrita** y [texto](https://url).
"""
import re
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = ROOT / "app" / "static"

SECTION_KEYS = (
    "resumen",
    "cumplimiento",
    "estado",
    "limites",
    "senales",
    "metricas",
    "prioridades",
    "fuentes",
)

# --- Fuentes (mismas URLs en los dos idiomas) ---------------------------------------------------

URL_POLICIES = "https://developers.google.com/youtube/terms/developer-policies"
URL_DERIVED = "https://developers.google.com/youtube/terms/derived-metrics-policy"
URL_POLICIES_GUIDE = "https://developers.google.com/youtube/terms/developer-policies-guide"
URL_REVISIONS = "https://developers.google.com/youtube/v3/revision_history"
URL_QUOTA = "https://developers.google.com/youtube/v3/determine_quota_cost"
URL_VIDEOS_LIST = "https://developers.google.com/youtube/data/reference/rest/v3/videos/list"
URL_COMMENT_THREADS = "https://developers.google.com/youtube/data/reference/rest/v3/commentThreads/list"
URL_FAKE_ENGAGEMENT = "https://support.google.com/youtube/answer/3399767?hl=en"
URL_SPAM = "https://support.google.com/youtube/answer/2801973"

URL_FAKE_VIEWS_HOURLY = "https://arxiv.org/html/2210.01096"
URL_LOCKSTEP = "https://arxiv.org/html/1512.05457"
URL_COLLUSIVE = "https://arxiv.org/html/2005.06243"
URL_COMMENT_BOTS = "https://nss.kaist.ac.kr/assets/papers/imc2023-na.pdf"
URL_SCAM_COMMENTS = "https://www.securitee.org/files/likecomment_ndss2024.pdf"
URL_COORDINATED = "https://ceur-ws.org/Vol-3138/paper6_jot.pdf"
URL_VIEW_FRAUD = "https://arxiv.org/pdf/1507.08874"
URL_FAKE_VIEWS_RG = (
    "https://www.researchgate.net/publication/276553787_Analysis_and_Detection_of_Fake_Views_in_Online_Video_Services"
)
URL_BENFORD = "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC4550407/"
URL_BENFORD_ML = "https://link.springer.com/chapter/10.1007/978-3-031-24049-2_3"
URL_SPAM_ML = "https://doaj.org/article/79e77448ebb0404e854fde73e16dbf23"

URL_HYPE_AQS = (
    "https://help.hypeauditor.com/en/articles/2221731-what-is-aqs-audience-quality-score-and-how-is-it-calculated"
)
URL_HYPE_COMMENTS = "https://help.hypeauditor.com/en/articles/2541185-how-do-you-detect-comments-authenticity"
URL_SOCIALBLADE = "https://socialblade.com/blog/dont-freak-drops-subs-views/"
URL_RIVALIQ = "https://help.rivaliq.com/en/articles/9788197-why-youtube-subscriber-counts-are-rounded"
URL_SOCIAVAULT = "https://sociavault.com/blog/good-engagement-rate-youtube"
URL_METRICOOL = "https://metricool.com/youtube-trends/"
URL_DASHSOCIAL = "https://www.dashsocial.com/social-media-benchmarks/youtube"
URL_VIDIQ = "https://vidiq.com/research/youtube-subscriber-benchmarks-2026/"
URL_YTSPAM = "https://www.github.com/darmiel/yt-spam"


# --- Contenido ----------------------------------------------------------------------------------
# Cada sección: (título, [bloques]). Un bloque es ("p" | "h3" | "note", texto) o ("ul" | "ol", [textos]).

ES_SECTIONS = {
    "resumen": ("Resumen", [
        ("p", "Esta página reúne qué conviene agregar a las estadísticas de los canales para detectar "
              "audiencia inflada (me gusta, vistas y suscriptores comprados) y qué métricas nuevas sumar. "
              "Todo se apoya solo en la API oficial de YouTube, la única plataforma con acceso real en este proyecto."),
        ("note", "**Antes de sumar métricas hay que resolver el cumplimiento de las reglas de la API.** "
                 "Hoy el sistema guarda el histórico sin límite y calcula puntajes propios con me gusta y vistas: "
                 "las dos cosas exigen una autorización de YouTube que todavía no se pidió (sección 1)."),
        ("ul", [
            "La señal más fuerte que falta: **vistas que bajan** entre una foto y la siguiente (YouTube borró vistas falsas).",
            "Lo más barato: guardar me gusta, comentarios y vistas por video en cada foto, y pedir `snippet,contentDetails` "
            "en la misma llamada a `videos.list` que ya se hace, sin cuota extra.",
            "Lo más nuevo: calidad de comentarios (duplicados, genéricos, autores repetidos, ráfagas) con `commentThreads.list`.",
        ]),
    ]),
    "cumplimiento": ("1. Primero: cumplir las reglas de la API", [
        ("p", "Fuentes: las [políticas para desarrolladores](" + URL_POLICIES + ") y la "
              "[política de métricas derivadas](" + URL_DERIVED + ") de YouTube."),
        ("ul", [
            "**Límite de 30 días.** La sección III.E.4.b prohíbe guardar el número de suscriptores de un canal más de "
            "30 días sin autorización de su dueño. El resto de los datos obtenidos con API key se borra o se actualiza "
            "a los 30 días. Hoy `channel_metric_snapshots` guarda el histórico sin límite.",
            "**Excepción posible.** Si YouTube acepta el caso de uso de métricas derivadas, se pueden guardar vistas, "
            "me gusta, suscriptores y comentarios hasta 36 meses. Se pide en el formulario de contacto de la API "
            "(\"Section 5: Use Cases…\" y luego \"Analytics & Reporting\"). Títulos, nombres de canal y texto de "
            "comentarios siguen atados a los 30 días.",
            "**Puntajes propios.** La política prohíbe crear métricas con datos de YouTube salvo caso aceptado; su "
            "ejemplo prohibido es justamente \"un puntaje que combine me gusta y vistas\", como el NER y el puntaje de "
            "audiencia. Si se acepta, deben mostrarse separados de los datos de YouTube y nunca como datos oficiales.",
            "**Comparar canales.** La política permite rankear y comparar canales con fines de análisis histórico, pero "
            "la sección III.E.2.a restringe juntar datos de canales de distintos dueños. No encontramos texto que aclare "
            "cuál manda: conviene preguntarlo en el mismo formulario.",
            "**Scraping prohibido** (III.E.6). Todo lo que propone esta página usa solo la API oficial.",
        ]),
        ("p", "**Recomendación:** pedir la aceptación antes del despliegue de marzo de 2027 y agregar en el dashboard un "
              "aviso visible de que los puntajes son del proyecto y no de YouTube."),
    ]),
    "estado": ("2. Qué tiene hoy el sistema", [
        ("p", "`app/services/analytics/audience_integrity.py` combina 7 señales y, si aparece una sola, el resultado "
              "no pasa de \"leve\":"),
        ("ul", [
            "vistas históricas por suscriptor;",
            "interacción baja frente al benchmark de la plataforma;",
            "vistas de los videos recientes frente a los suscriptores;",
            "equilibrio entre vistas, me gusta y comentarios;",
            "un video con muchas más vistas que el resto;",
            "canal atípico dentro de su cohorte;",
            "saltos y caídas de suscriptores en el histórico.",
        ]),
        ("p", "El diseño es prudente: una señal que no se puede calcular no cuenta como normal, una sola no alcanza "
              "para acusar y el texto aclara que son indicios. Tiene tres huecos concretos:"),
        ("ol", [
            "Las fotos diarias guardan solo los totales del canal, sin me gusta, comentarios ni vistas por video. En los "
            "canales seguidos varias señales quedan \"no disponibles\" (`channel_from_snapshot`).",
            "Solo se vigilan las caídas de suscriptores. Que bajen las **vistas** es la marca más directa de que YouTube "
            "detectó vistas falsas y las borró, y no se mira.",
            "Los umbrales son fijos y no están validados contra casos reales (el propio código lo reconoce).",
        ]),
    ]),
    "limites": ("3. Qué no se puede ver con datos públicos", [
        ("ul", [
            "No hay tiempo de visualización, retención, espectadores únicos ni origen del tráfico: eso solo lo ve el "
            "dueño del canal con YouTube Analytics.",
            "Los suscriptores llegan redondeados a 3 cifras significativas cuando el canal supera los 1.000 "
            "([Rival IQ](" + URL_RIVALIQ + ")). Por eso no se evalúan cambios menores al 5%.",
            "**Cambió la forma de contar vistas** ([historial de la API](" + URL_REVISIONS + ")): desde marzo de 2025 "
            "las vistas de Shorts cuentan cada inicio y cada repetición; desde agosto de 2026 una vista cuenta apenas "
            "arranca el video; desde noviembre de 2026 se suman las vistas compartidas en televisores. Hay que marcar "
            "esas fechas en el histórico para no leer un cambio de regla como fraude.",
            "YouTube borra vistas y suscriptores falsos después de un tiempo, a veces semanas "
            "([política de engagement falso](" + URL_FAKE_ENGAGEMENT + ")). Una compra se ve primero como una suba y "
            "más tarde como una caída.",
        ]),
    ]),
    "senales": ("4. Señales nuevas contra el fraude", [
        ("h3", "A. Sin cuota extra: con datos que ya se traen"),
        ("ol", [
            "**Vistas que bajan entre fotos.** El total de vistas de un canal o de un video no debería bajar nunca; "
            "si baja, casi seguro es una corrección de YouTube por vistas falsas "
            "([estudio con conteos por hora](" + URL_FAKE_VIEWS_HOURLY + ")).",
            "**Guardar me gusta, comentarios y vistas de los videos recientes en cada foto**, para que las señales de "
            "equilibrio funcionen también en los canales seguidos y se vean como serie en el tiempo.",
            "**Suscriptores nuevos cada 1.000 vistas nuevas**, con la diferencia entre fotos. Una compra de suscriptores "
            "los sube sin que suban las vistas.",
            "**Dispersión de me gusta por vista entre videos** (coeficiente de variación o desviación mediana) en lugar "
            "de la suma: los me gusta comprados suelen concentrarse en pocos videos.",
            "**Ley de Benford** sobre el primer dígito de las vistas de todos los videos del canal "
            "([Golbeck](" + URL_BENFORD + ")). Solo como filtro débil y con más de 100 videos.",
        ]),
        ("h3", "B. Con cuota baja: 1 unidad por llamada"),
        ("ol", [
            "**Pedir `snippet,contentDetails` en el mismo `videos.list`** ([referencia](" + URL_VIDEOS_LIST + ")); cuesta "
            "1 unidad por llamada sin importar las partes ([costos](" + URL_QUOTA + ")). La duración permite separar "
            "Shorts de videos largos, que tienen otros benchmarks; `publishedAt` permite medir vistas según la edad del "
            "video y calcular el PFI, ya definido en `normalizer.py` pero sin usar.",
            "**Fotos diarias por video**, no solo por canal. Un salto de vistas en un video viejo sin causa aparente es "
            "un patrón típico de compra.",
            "**Calidad de los comentarios** con `commentThreads.list` ([referencia](" + URL_COMMENT_THREADS + ")): "
            "proporción de duplicados o casi duplicados, de comentarios genéricos o de solo emojis, de autores únicos y "
            "ráfagas en pocos minutos. Entre canales, los mismos autores comentando a la vez señalan coordinación "
            "([paper de Google](" + URL_LOCKSTEP + ")). El texto solo puede guardarse 30 días: se guardan los indicadores "
            "y se descarta el texto.",
            "**Probar `videos.batchGetStats`**, método de junio de 2026 que cuesta 1 unidad en una cuota propia y "
            "podría liberar la principal para el job diario. La documentación no detalla sus campos.",
        ]),
        ("h3", "C. Cómo se decide"),
        ("ol", [
            "**Benchmarks propios por nivel y formato**, calculados con la base del proyecto: los de los proveedores se "
            "contradicen y no dicen de dónde salen sus datos.",
            "**Puntajes robustos** (z-score con desviación mediana) dentro de cada cohorte en lugar de umbrales fijos.",
            "**Validación contra casos conocidos:** usar como etiquetas débiles los canales con caídas por depuración "
            "de YouTube y los casos simulados del modo mock, y medir cuánto acierta cada señal antes de darle peso.",
        ]),
    ]),
    "metricas": ("5. Métricas analíticas adicionales", [
        ("ul", [
            "**Vistas típicas por video** (mediana): rendimiento esperable sin la distorsión de los virales.",
            "**Constancia:** coeficiente de variación de las vistas por video.",
            "**Dependencia de virales:** Gini o curva de Lorenz dentro del canal. `lorenz_curve()` ya existe y ningún "
            "endpoint la usa.",
            "**Tasa de éxito:** porcentaje de videos que superan la mediana del canal.",
            "**Velocidad y aceleración del crecimiento** de suscriptores y vistas, por día y por semana.",
            "**Profundidad de conversación:** comentarios por cada me gusta.",
            "**Engagement separado por Shorts y video largo**, con su caída según la edad del video.",
            "**PFI:** frecuencia y regularidad de publicación.",
        ]),
    ]),
    "prioridades": ("6. Orden recomendado", [
        ("ol", [
            "Cumplimiento: pedir la aceptación de métricas derivadas, sumar el aviso en el dashboard y definir qué se "
            "borra a los 30 días mientras no llegue.",
            "Detectar vistas que bajan y guardar me gusta, comentarios y vistas por video en cada foto. Sin cuota extra.",
            "Agregar `snippet,contentDetails` al `videos.list` actual: Shorts frente a video largo, PFI y edad del video.",
            "Calidad de comentarios: unas 700 unidades por día para unos 70 canales con 10 videos (estimado con 100 "
            "comentarios por página, a confirmar en la documentación).",
            "Benchmarks de cohorte, puntajes robustos y validación.",
        ]),
    ]),
    "fuentes": ("7. Fuentes", [
        ("h3", "Oficiales de YouTube"),
        ("ul", [
            "[Políticas para desarrolladores](" + URL_POLICIES + ")",
            "[Política de métricas derivadas](" + URL_DERIVED + ")",
            "[Guía de cumplimiento](" + URL_POLICIES_GUIDE + ")",
            "[Historial de cambios de la API](" + URL_REVISIONS + ")",
            "[Costos de cuota](" + URL_QUOTA + ")",
            "[videos.list](" + URL_VIDEOS_LIST + ")",
            "[commentThreads.list](" + URL_COMMENT_THREADS + ")",
            "[Política de engagement falso](" + URL_FAKE_ENGAGEMENT + ")",
            "[Política de spam](" + URL_SPAM + ")",
        ]),
        ("h3", "Estudios académicos"),
        ("ul", [
            "[Vistas falsas en YouTube a partir de conteos por hora](" + URL_FAKE_VIEWS_HOURLY + ")",
            "[Clusters de engagement falso a escala (Google)](" + URL_LOCKSTEP + ")",
            "[Entidades colusivas en YouTube](" + URL_COLLUSIVE + ")",
            "[Bots de comentarios en YouTube (IMC 2023)](" + URL_COMMENT_BOTS + ")",
            "[Comentarios de estafa (NDSS 2024)](" + URL_SCAM_COMMENTS + ")",
            "[Comportamiento inauténtico coordinado en YouTube](" + URL_COORDINATED + ")",
            "[Detección de fraude de vistas](" + URL_VIEW_FRAUD + ")",
            "[Analysis and Detection of Fake Views](" + URL_FAKE_VIEWS_RG + ")",
            "[La ley de Benford en redes sociales (Golbeck)](" + URL_BENFORD + ")",
            "[Benford y machine learning para bots](" + URL_BENFORD_ML + ")",
            "[Clasificación de spam en comentarios de YouTube](" + URL_SPAM_ML + ")",
        ]),
        ("h3", "Industria (proveedores, no fuentes independientes)"),
        ("ul", [
            "[HypeAuditor: Audience Quality Score](" + URL_HYPE_AQS + ")",
            "[HypeAuditor: autenticidad de comentarios](" + URL_HYPE_COMMENTS + ")",
            "[Social Blade: por qué bajan suscriptores y vistas](" + URL_SOCIALBLADE + ")",
            "[Rival IQ: redondeo de suscriptores](" + URL_RIVALIQ + ")",
            "Benchmarks de engagement, que se contradicen entre sí: [Sociavault](" + URL_SOCIAVAULT + "), "
            "[Metricool](" + URL_METRICOOL + "), [Dash Social](" + URL_DASHSOCIAL + "), [vidIQ 2026](" + URL_VIDIQ + ")",
            "[yt-spam: heurísticas de código abierto](" + URL_YTSPAM + ")",
        ]),
    ]),
}

EN_SECTIONS = {
    "resumen": ("Summary", [
        ("p", "This page gathers what to add to channel statistics to detect inflated audiences (bought likes, views "
              "and subscribers) and which new metrics to add. Everything relies only on the official YouTube API, "
              "the one platform this project has real access to."),
        ("note", "**API compliance has to be solved before adding metrics.** "
                 "The system currently keeps history with no limit and computes its own scores from likes and views: "
                 "both require a YouTube approval that has not been requested yet (section 1)."),
        ("ul", [
            "The strongest missing signal: **views that go down** between one snapshot and the next (YouTube removed fake views).",
            "The cheapest step: store likes, comments and per-video views in each snapshot, and request "
            "`snippet,contentDetails` in the same `videos.list` call already made, at no extra quota.",
            "The newest piece: comment quality (duplicates, generic text, repeated authors, bursts) with `commentThreads.list`.",
        ]),
    ]),
    "cumplimiento": ("1. First: comply with the API rules", [
        ("p", "Sources: YouTube's [developer policies](" + URL_POLICIES + ") and "
              "[derived metrics policy](" + URL_DERIVED + ")."),
        ("ul", [
            "**30-day limit.** Section III.E.4.b forbids storing a channel's subscriber count for more than 30 days "
            "without the owner's authorization. Other data obtained with an API key must be deleted or refreshed after "
            "30 days. Today `channel_metric_snapshots` keeps history with no limit.",
            "**Possible exception.** If YouTube accepts the derived-metrics use case, views, likes, subscribers and "
            "comment counts may be stored for up to 36 months. It is requested through the API contact form "
            "(\"Section 5: Use Cases…\", then \"Analytics & Reporting\"). Titles, channel names and comment text stay "
            "bound to 30 days.",
            "**Own scores.** The policy forbids creating metrics from YouTube data unless the use case is accepted; its "
            "forbidden example is exactly \"a score that factors in likes, total views\", like NER and the audience "
            "score. If accepted, they must be shown apart from YouTube data and never as official data.",
            "**Comparing channels.** The policy allows ranking and comparing channels for historical analysis, but "
            "section III.E.2.a restricts aggregating data from channels with different owners. We found no text saying "
            "which rule prevails: ask in the same form.",
            "**Scraping is forbidden** (III.E.6). Everything on this page uses only the official API.",
        ]),
        ("p", "**Recommendation:** request the approval before the March 2027 deployment and add a visible notice in the "
              "dashboard that scores belong to the project, not to YouTube."),
    ]),
    "estado": ("2. What the system has today", [
        ("p", "`app/services/analytics/audience_integrity.py` combines 7 signals and, if only one shows up, the result "
              "stays at \"mild\" at most:"),
        ("ul", [
            "lifetime views per subscriber;",
            "low engagement against the platform benchmark;",
            "recent video views against subscribers;",
            "balance between views, likes and comments;",
            "one video far above the rest;",
            "outlier channel within its cohort;",
            "subscriber jumps and drops in the history.",
        ]),
        ("p", "The design is cautious: a signal that cannot be computed does not count as normal, a single one is not "
              "enough to accuse, and the text says they are indications. It has three concrete gaps:"),
        ("ol", [
            "Daily snapshots store only channel totals, without likes, comments or per-video views. For tracked "
            "channels several signals end up \"unavailable\" (`channel_from_snapshot`).",
            "Only subscriber drops are watched. Falling **views** are the most direct mark that YouTube detected and "
            "removed fake views, and they are not checked.",
            "Thresholds are fixed and not validated against real cases (the code itself says so).",
        ]),
    ]),
    "limites": ("3. What public data cannot show", [
        ("ul", [
            "There is no watch time, retention, unique viewers or traffic source: only the channel owner sees that, "
            "in YouTube Analytics.",
            "Subscriber counts come rounded to 3 significant figures once a channel passes 1,000 "
            "([Rival IQ](" + URL_RIVALIQ + ")). That is why changes under 5% are not evaluated.",
            "**View counting changed** ([API revision history](" + URL_REVISIONS + ")): since March 2025 Shorts views "
            "count every start and replay; since August 2026 a view counts as soon as playback starts; since November "
            "2026 co-views on TVs are included. Those dates must be marked in the history so a rule change is not read "
            "as fraud.",
            "YouTube removes fake views and subscribers after some time, sometimes weeks "
            "([fake engagement policy](" + URL_FAKE_ENGAGEMENT + ")). A purchase shows up first as a rise and later as "
            "a drop.",
        ]),
    ]),
    "senales": ("4. New anti-fraud signals", [
        ("h3", "A. No extra quota: data already fetched"),
        ("ol", [
            "**Views that go down between snapshots.** A channel's or video's total views should never decrease; if "
            "they do, it is almost certainly a YouTube correction of fake views "
            "([hourly view-count study](" + URL_FAKE_VIEWS_HOURLY + ")).",
            "**Store likes, comments and recent video views in each snapshot**, so balance signals also work for "
            "tracked channels and can be read as a time series.",
            "**New subscribers per 1,000 new views**, from the difference between snapshots. Bought subscribers rise "
            "without views rising.",
            "**Spread of likes per view across videos** (coefficient of variation or median deviation) instead of the "
            "sum: bought likes tend to concentrate on a few videos.",
            "**Benford's law** on the first digit of the views of all the channel's videos "
            "([Golbeck](" + URL_BENFORD + ")). Only as a weak filter, and with more than 100 videos.",
        ]),
        ("h3", "B. Low quota: 1 unit per call"),
        ("ol", [
            "**Request `snippet,contentDetails` in the same `videos.list`** ([reference](" + URL_VIDEOS_LIST + ")); it "
            "costs 1 unit per call regardless of parts ([quota costs](" + URL_QUOTA + ")). Duration separates Shorts from "
            "long videos, which have different benchmarks; `publishedAt` measures views by video age and enables PFI, "
            "already defined in `normalizer.py` but unused.",
            "**Daily per-video snapshots**, not only per channel. A view jump on an old video with no apparent cause "
            "is a typical purchase pattern.",
            "**Comment quality** with `commentThreads.list` ([reference](" + URL_COMMENT_THREADS + ")): share of "
            "duplicates or near-duplicates, of generic or emoji-only comments, of unique authors, and bursts within "
            "minutes. Across channels, the same authors commenting at the same time point to coordination "
            "([Google paper](" + URL_LOCKSTEP + ")). Text may only be kept for 30 days: store the indicators and drop "
            "the text.",
            "**Try `videos.batchGetStats`**, a June 2026 method costing 1 unit in its own quota bucket, which could free "
            "the main quota for the daily job. The documentation does not detail its fields.",
        ]),
        ("h3", "C. How decisions are made"),
        ("ol", [
            "**Own benchmarks by tier and format**, computed from the project's database: vendor benchmarks contradict "
            "each other and do not disclose their data.",
            "**Robust scores** (z-score with median deviation) within each cohort instead of fixed thresholds.",
            "**Validation against known cases:** use channels with YouTube purge drops and the mock mode's simulated "
            "cases as weak labels, and measure how often each signal is right before weighting it.",
        ]),
    ]),
    "metricas": ("5. Additional analytical metrics", [
        ("ul", [
            "**Typical views per video** (median): expected performance without the distortion of viral hits.",
            "**Consistency:** coefficient of variation of views per video.",
            "**Dependence on viral hits:** Gini or Lorenz curve within the channel. `lorenz_curve()` already exists "
            "and no endpoint uses it.",
            "**Hit rate:** share of videos above the channel's median.",
            "**Growth speed and acceleration** of subscribers and views, per day and per week.",
            "**Conversation depth:** comments per like.",
            "**Engagement split by Shorts and long video**, with its decay by video age.",
            "**PFI:** publishing frequency and regularity.",
        ]),
    ]),
    "prioridades": ("6. Recommended order", [
        ("ol", [
            "Compliance: request derived-metrics approval, add the dashboard notice and define what gets deleted after "
            "30 days until it arrives.",
            "Detect falling views and store likes, comments and per-video views in each snapshot. No extra quota.",
            "Add `snippet,contentDetails` to the current `videos.list`: Shorts versus long video, PFI and video age.",
            "Comment quality: about 700 units per day for about 70 channels with 10 videos (estimated at 100 comments "
            "per page, to be confirmed in the documentation).",
            "Cohort benchmarks, robust scores and validation.",
        ]),
    ]),
    "fuentes": ("7. Sources", [
        ("h3", "Official YouTube"),
        ("ul", [
            "[Developer policies](" + URL_POLICIES + ")",
            "[Derived metrics policy](" + URL_DERIVED + ")",
            "[Compliance guide](" + URL_POLICIES_GUIDE + ")",
            "[API revision history](" + URL_REVISIONS + ")",
            "[Quota costs](" + URL_QUOTA + ")",
            "[videos.list](" + URL_VIDEOS_LIST + ")",
            "[commentThreads.list](" + URL_COMMENT_THREADS + ")",
            "[Fake engagement policy](" + URL_FAKE_ENGAGEMENT + ")",
            "[Spam policy](" + URL_SPAM + ")",
        ]),
        ("h3", "Academic studies"),
        ("ul", [
            "[Fake views on YouTube from hourly counts](" + URL_FAKE_VIEWS_HOURLY + ")",
            "[Clustering fake engagement at scale (Google)](" + URL_LOCKSTEP + ")",
            "[Collusive entities on YouTube](" + URL_COLLUSIVE + ")",
            "[Comment bots on YouTube (IMC 2023)](" + URL_COMMENT_BOTS + ")",
            "[Scam comments (NDSS 2024)](" + URL_SCAM_COMMENTS + ")",
            "[Coordinated inauthentic behavior on YouTube](" + URL_COORDINATED + ")",
            "[View fraud detection](" + URL_VIEW_FRAUD + ")",
            "[Analysis and Detection of Fake Views](" + URL_FAKE_VIEWS_RG + ")",
            "[Benford's law in social networks (Golbeck)](" + URL_BENFORD + ")",
            "[Benford and machine learning for bots](" + URL_BENFORD_ML + ")",
            "[YouTube comment spam classification](" + URL_SPAM_ML + ")",
        ]),
        ("h3", "Industry (vendors, not independent sources)"),
        ("ul", [
            "[HypeAuditor: Audience Quality Score](" + URL_HYPE_AQS + ")",
            "[HypeAuditor: comment authenticity](" + URL_HYPE_COMMENTS + ")",
            "[Social Blade: why subscribers and views drop](" + URL_SOCIALBLADE + ")",
            "[Rival IQ: subscriber rounding](" + URL_RIVALIQ + ")",
            "Engagement benchmarks, which contradict each other: [Sociavault](" + URL_SOCIAVAULT + "), "
            "[Metricool](" + URL_METRICOOL + "), [Dash Social](" + URL_DASHSOCIAL + "), [vidIQ 2026](" + URL_VIDIQ + ")",
            "[yt-spam: open-source heuristics](" + URL_YTSPAM + ")",
        ]),
    ]),
}

PAGES = {
    "es": {
        "file": "antifraude.html",
        "html_lang": "es",
        "title": "Channel Analytics · Antifraude y métricas nuevas",
        "heading": "Antifraude y métricas nuevas",
        "lead": "Qué agregar a las estadísticas de los canales para detectar audiencia inflada, qué métricas sumar "
                "y qué reglas de la API de YouTube hay que cumplir. Investigación de noviembre de 2026.",
        "stance": "Las señales de audiencia marcan anomalías estadísticas públicas para que un anunciante o auditor las "
                  "revise con prudencia. El sistema no detecta bots ni acusa a nadie.",
        "toc": "Contenido",
        "nav_back": "Volver a la guía",
        "nav_back_href": "/guia",
        "nav_other": "English",
        "nav_other_href": "/guia/en/antifraude",
        "sections": ES_SECTIONS,
    },
    "en": {
        "file": "antifraude_en.html",
        "html_lang": "en",
        "title": "Channel Analytics · Anti-fraud and new metrics",
        "heading": "Anti-fraud and new metrics",
        "lead": "What to add to channel statistics to detect inflated audiences, which metrics to add and which "
                "YouTube API rules must be followed. Research from November 2026.",
        "stance": "Audience signals flag public statistical anomalies for an advertiser or auditor to review with care. "
                  "The system does not detect bots or accuse anyone.",
        "toc": "Contents",
        "nav_back": "Back to the guide",
        "nav_back_href": "/guia/en",
        "nav_other": "Español",
        "nav_other_href": "/guia/antifraude",
        "sections": EN_SECTIONS,
    },
}

CSS = """
:root { color-scheme: light dark; --bg:#ffffff; --fg:#1f2328; --muted:#59636e; --card:#f6f8fa; --line:#d1d9e0; --accent:#0969da; --warn:#9a6700; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { --bg:#0d1117; --fg:#e6edf3; --muted:#9198a1; --card:#151b23; --line:#3d444d; --accent:#4493f8; --warn:#d29922; } }
:root[data-theme="dark"] { --bg:#0d1117; --fg:#e6edf3; --muted:#9198a1; --card:#151b23; --line:#3d444d; --accent:#4493f8; --warn:#d29922; }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--fg); font:16px/1.6 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
main { max-width:860px; margin:0 auto; padding:32px 16px 64px; }
nav.top { display:flex; gap:16px; justify-content:space-between; font-size:14px; margin-bottom:24px; }
a { color:var(--accent); overflow-wrap:anywhere; }
h1 { font-size:28px; margin:0 0 8px; }
h2 { font-size:21px; margin:40px 0 8px; padding-top:8px; border-top:1px solid var(--line); scroll-margin-top:16px; }
h3 { font-size:17px; margin:24px 0 6px; }
p.lead { color:var(--muted); margin:0 0 12px; }
p.stance { border-left:3px solid var(--accent); padding:8px 12px; background:var(--card); border-radius:4px; }
p.note { border-left:3px solid var(--warn); padding:10px 12px; background:var(--card); border-radius:4px; }
ol.toc { columns:2; font-size:15px; padding-left:0; list-style:none; }
li { margin:4px 0; }
code { font:14px ui-monospace, SFMono-Regular, Consolas, monospace; background:var(--card); border:1px solid var(--line); border-radius:4px; padding:0 4px; }
@media (max-width:600px) { ol.toc { columns:1; } }
"""

_CODE = re.compile(r"`([^`]+)`")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_LINK = re.compile(r"\[([^\]]+)\]\((https://[^)\s]+)\)")


def inline(text: str) -> str:
    """Escapa el texto y aplica el marcado mínimo: `código`, **negrita** y [texto](https://url)."""
    html = escape(text, quote=False)
    html = _CODE.sub(r"<code>\1</code>", html)
    html = _BOLD.sub(r"<strong>\1</strong>", html)
    return _LINK.sub(
        lambda m: f'<a href="{escape(m.group(2))}" target="_blank" rel="noopener">{m.group(1)}</a>', html
    )


def render_block(kind: str, content) -> str:
    if kind == "p":
        return f"<p>{inline(content)}</p>"
    if kind == "note":
        return f'<p class="note">{inline(content)}</p>'
    if kind == "h3":
        return f"<h3>{inline(content)}</h3>"
    if kind in ("ul", "ol"):
        items = "".join(f"<li>{inline(item)}</li>" for item in content)
        return f"<{kind}>{items}</{kind}>"
    raise ValueError(f"Bloque desconocido: {kind}")


def render(lang: str) -> str:
    page = PAGES[lang]
    sections = page["sections"]
    toc = "".join(f'<li><a href="#{key}">{escape(sections[key][0])}</a></li>' for key in SECTION_KEYS)
    body = []
    for key in SECTION_KEYS:
        title, blocks = sections[key]
        body.append(
            f'<section id="{key}">\n<h2>{escape(title)}</h2>\n'
            + "\n".join(render_block(kind, content) for kind, content in blocks)
            + "\n</section>"
        )
    return (
        "<!DOCTYPE html>\n"
        f'<html lang="{page["html_lang"]}">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{escape(page['title'])}</title>\n<style>{CSS}</style>\n</head>\n<body>\n<main>\n"
        f'<nav class="top"><a href="{page["nav_back_href"]}">← {escape(page["nav_back"])}</a>'
        f'<a href="{page["nav_other_href"]}">{escape(page["nav_other"])}</a></nav>\n'
        f'<h1>{escape(page["heading"])}</h1>\n<p class="lead">{escape(page["lead"])}</p>\n'
        f'<p class="stance">{escape(page["stance"])}</p>\n'
        f'<h2 id="contenido">{escape(page["toc"])}</h2>\n<ol class="toc">{toc}</ol>\n'
        + "\n".join(body)
        + "\n</main>\n</body>\n</html>\n"
    )


def outputs() -> dict[Path, str]:
    return {STATIC_DIR / page["file"]: render(lang) for lang, page in PAGES.items()}


def main() -> None:
    for path, content in outputs().items():
        # newline="\n": el mismo archivo byte a byte en Windows y en el CI de Linux.
        path.write_text(content, encoding="utf-8", newline="\n")
        print(f"Generado {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
