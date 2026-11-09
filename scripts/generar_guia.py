"""
Genera la guía de uso en español e inglés, con sus dos grafos:

    app/static/guia.html      -> /guia
    app/static/guia_en.html   -> /guia/en

Los dos idiomas comparten la posición de los nodos y las conexiones, así un grafo no
puede cambiar en un idioma y quedar viejo en el otro. Después de editar este archivo:

    python -m scripts.generar_guia

tests/test_guia.py falla si los HTML no coinciden con lo que genera este script.
"""
from html import escape
from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parents[1] / "app" / "static"

_W, _H = 170, 58

# (id, x, y, ancho, alto, tipo)
FLOW_NODES = [
    ("youtube", 30, 30, _W, _H, "input"),
    ("tiktok", 30, 110, _W, _H, "input"),
    ("mock", 30, 190, _W, _H, "input"),
    ("collectors", 230, 110, _W, _H, "process"),
    ("normalizer", 430, 110, _W, _H, "process"),
    ("statistics", 630, 30, _W, _H, "process"),
    ("audience", 630, 110, _W, _H, "signal"),
    ("api", 830, 110, _W, _H, "endpoint"),
    ("dashboard", 830, 30, _W, _H, "output"),
    ("plans", 830, 210, _W, _H, "control"),
    ("users", 830, 310, _W, _H, "input"),
    ("scheduler", 230, 310, _W, _H, "control"),
    ("worker", 430, 310, _W, _H, "process"),
    ("database", 630, 310, _W, _H, "store"),
]
FLOW_EDGES = [
    "M200 59 L215 59 L215 125 L230 125",
    "M200 139 L230 139",
    "M200 219 L215 219 L215 153 L230 153",
    "M400 139 L430 139",
    "M600 125 L615 125 L615 59 L630 59",
    "M600 139 L630 139",
    "M800 59 L815 59 L815 125 L830 125",
    "M800 139 L830 139",
    "M915 110 L915 88",
    "M915 210 L915 168",
    "M915 310 L915 268",
    "M400 339 L430 339",
    "M515 310 L515 240 L315 240 L315 168",
    "M600 339 L630 339",
    "M715 310 L715 168",
]
FLOW_LABELS = [("reads", 415, 232), ("history", 765, 245)]
FLOW_VIEWBOX = (1030, 390)

INFO_NODES = [
    ("types", 30, 30, 270, 104, "store"),
    ("channel", 385, 30, 270, 104, "store"),
    ("snapshot", 740, 30, 270, 120, "store"),
    ("user", 30, 190, 270, 120, "store"),
    ("search", 385, 215, 270, 72, "input"),
    ("videos", 740, 215, 270, 72, "input"),
    ("signals", 385, 325, 270, 72, "signal"),
]
INFO_EDGES = [
    "M300 82 L385 82",
    "M655 82 L740 82",
    "M520 287 L520 325",
    "M875 287 L875 361 L655 361",
    "M875 150 L875 182 L700 182 L700 345 L655 345",
]
INFO_LABELS = [("one_to_many", 342, 72), ("one_to_many", 697, 72), ("evaluates", 560, 310), ("history", 760, 176)]
INFO_BAND = ("band", 385, 208)
INFO_VIEWBOX = (1040, 415)

GRAPH_TEXT = {
    "es": {
        "flow": {
            "youtube": ("API de YouTube", ["canales y videos recientes"]),
            "tiktok": ("API de TikTok", ["perfil y videos"]),
            "mock": ("Datos simulados", ["si no hay credenciales"]),
            "collectors": ("Colectores", ["uno por plataforma"]),
            "normalizer": ("Normalización", ["canal universal y NER"]),
            "statistics": ("Motor estadístico", ["distribución, Gini, correlación"]),
            "audience": ("Señales de audiencia", ["puntaje e indicios"]),
            "api": ("API", ["/api/v1"]),
            "dashboard": ("Dashboard", ["/dashboard"]),
            "plans": ("Sesión y planes", ["JWT, gating opcional"]),
            "users": ("Usuarios", ["registro e inicio de sesión"]),
            "scheduler": ("Programador", ["APScheduler"]),
            "worker": ("Worker de seguimiento", ["foto de cada canal"]),
            "database": ("Base de datos", ["canales y fotos"]),
        },
        "labels": {"reads": "consulta", "history": "historial", "one_to_many": "1 a N", "evaluates": "se evalúan"},
        "info": {
            "types": ("Tipo de canal", ["tabla channel_types", "name, slug, description", "is_custom"]),
            "channel": ("Canal seguido", ["tabla tracked_channels", "platform, native_id, handle, name", "active, channel_type_id"]),
            "snapshot": ("Foto del canal", ["tabla channel_metric_snapshots", "snapshot_date, followers, total_views", "total_posts, raw_interactions", "normalized_er, tier"]),
            "user": ("Usuario", ["tabla users", "email, hashed_password", "plan, plan_active_until", "report_credits, unica_access_until"]),
            "search": ("Canales de una búsqueda", ["seguidores, vistas, interacción"]),
            "videos": ("Videos recientes", ["vistas, me gusta, comentarios"]),
            "signals": ("Señales de audiencia", ["se recalculan en cada consulta"]),
        },
        "band": "No se guardan",
        "legend": {
            "input": "Entrada", "control": "Control", "process": "Proceso", "signal": "Señales",
            "endpoint": "API", "store": "Dato guardado", "output": "Pantalla",
        },
        "aria_flow": "Grafo de funcionamiento: de las fuentes de datos al dashboard, con el seguimiento periódico",
        "aria_info": "Grafo de información: qué datos guarda el sistema y cuáles no",
    },
    "en": {
        "flow": {
            "youtube": ("YouTube API", ["channels and recent videos"]),
            "tiktok": ("TikTok API", ["profile and videos"]),
            "mock": ("Simulated data", ["when there are no credentials"]),
            "collectors": ("Collectors", ["one per platform"]),
            "normalizer": ("Normalization", ["universal channel and NER"]),
            "statistics": ("Statistics engine", ["distribution, Gini, correlation"]),
            "audience": ("Audience signals", ["score and indications"]),
            "api": ("API", ["/api/v1"]),
            "dashboard": ("Dashboard", ["/dashboard"]),
            "plans": ("Session and plans", ["JWT, optional gating"]),
            "users": ("Users", ["sign-up and login"]),
            "scheduler": ("Scheduler", ["APScheduler"]),
            "worker": ("Tracking worker", ["snapshot of each channel"]),
            "database": ("Database", ["channels and snapshots"]),
        },
        "labels": {"reads": "queries", "history": "history", "one_to_many": "1 to N", "evaluates": "evaluated"},
        "info": {
            "types": ("Channel type", ["channel_types table", "name, slug, description", "is_custom"]),
            "channel": ("Tracked channel", ["tracked_channels table", "platform, native_id, handle, name", "active, channel_type_id"]),
            "snapshot": ("Channel snapshot", ["channel_metric_snapshots table", "snapshot_date, followers, total_views", "total_posts, raw_interactions", "normalized_er, tier"]),
            "user": ("User", ["users table", "email, hashed_password", "plan, plan_active_until", "report_credits, unica_access_until"]),
            "search": ("Channels from a search", ["followers, views, engagement"]),
            "videos": ("Recent videos", ["views, likes, comments"]),
            "signals": ("Audience signals", ["recalculated on every query"]),
        },
        "band": "Not stored",
        "legend": {
            "input": "Input", "control": "Control", "process": "Process", "signal": "Signals",
            "endpoint": "API", "store": "Stored data", "output": "Screen",
        },
        "aria_flow": "Operation graph: from data sources to the dashboard, with periodic tracking",
        "aria_info": "Information graph: which data the system stores and which it does not",
    },
}


def _node_svg(node: tuple, text: tuple[str, list[str]]) -> str:
    node_id, x, y, width, height, kind = node
    title, lines = text
    center = x + width / 2
    total = 18 + 15 * len(lines)
    baseline = y + (height - total) / 2 + 14
    parts = [
        f'<g class="node {kind}" data-node="{node_id}">',
        f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="8"/>',
        f'<text class="title" x="{center:g}" y="{baseline:g}">{escape(title)}</text>',
    ]
    parts.extend(
        f'<text class="sub" x="{center:g}" y="{baseline + 18 + 15 * i:g}">{escape(line)}</text>'
        for i, line in enumerate(lines)
    )
    parts.append("</g>")
    return "".join(parts)


def _graph(viewbox, nodes, edges, labels, texts, label_texts, aria, marker, extra="") -> str:
    width, height = viewbox
    parts = [
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{escape(aria)}">',
        f'<defs><marker id="{marker}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
        'orient="auto-start-reverse"><path class="arrow" d="M0 0 L10 5 L0 10 z"/></marker></defs>',
    ]
    parts.extend(f'<path class="edge" d="{d}" marker-end="url(#{marker})"/>' for d in edges)
    parts.extend(_node_svg(node, texts[node[0]]) for node in nodes)
    parts.extend(f'<text class="edge-label" x="{x}" y="{y}">{escape(label_texts[key])}</text>' for key, x, y in labels)
    parts.append(extra)
    parts.append("</svg>")
    return "".join(parts)


def flow_graph(lang: str) -> str:
    text = GRAPH_TEXT[lang]
    return _graph(FLOW_VIEWBOX, FLOW_NODES, FLOW_EDGES, FLOW_LABELS, text["flow"], text["labels"], text["aria_flow"], "af")


def info_graph(lang: str) -> str:
    text = GRAPH_TEXT[lang]
    _, x, y = INFO_BAND
    band = f'<text class="band-title" x="{x}" y="{y}">{escape(text["band"])}</text>'
    return _graph(INFO_VIEWBOX, INFO_NODES, INFO_EDGES, INFO_LABELS, text["info"], text["labels"], text["aria_info"], "ai", band)


def legend(lang: str) -> str:
    items = "".join(
        f'<li><span class="swatch {kind}"></span>{escape(label)}</li>'
        for kind, label in GRAPH_TEXT[lang]["legend"].items()
    )
    return f'<ul class="legend">{items}</ul>'


CSS = """
:root {
  --bg: #f6f7f9; --panel: #ffffff; --text: #1c2430; --muted: #5b6675; --line: #d9dee5;
  --accent: #1d4ed8; --code-bg: #eef1f5; --warn-bg: #fff6e5; --warn-line: #b7791f;
  --input: #e8eefc; --input-line: #3b5fc4; --control: #fdeee3; --control-line: #bf6a24;
  --endpoint: #e9e8fb; --endpoint-line: #5a50c2; --process: #eef1f5; --process-line: #66717f;
  --store: #e3f4ea; --store-line: #2c8050; --output: #fbf3d6; --output-line: #94790f;
  --signal: #fde8ec; --signal-line: #b83a55;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) { {{DARK}} }
}
:root[data-theme="dark"] { {{DARK}} }
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body { margin: 0; background: var(--bg); color: var(--text); line-height: 1.6; font-size: 16px;
  font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
header { background: var(--panel); border-bottom: 1px solid var(--line); padding: 28px 16px; }
.wrap { max-width: 960px; margin: 0 auto; padding: 0 16px; }
header .wrap { padding: 0; display: flex; gap: 16px; justify-content: space-between; align-items: flex-start; }
h1 { margin: 0 0 6px; font-size: 28px; line-height: 1.2; }
header p { margin: 0; color: var(--muted); }
.lang { flex-shrink: 0; font-weight: 600; }
nav { margin: 24px 0; padding: 16px 20px; background: var(--panel); border: 1px solid var(--line); border-radius: 8px; }
nav ol { margin: 0; padding-left: 20px; columns: 2; column-gap: 32px; }
section { margin: 36px 0; }
h2 { font-size: 22px; margin: 0 0 12px; padding-bottom: 6px; border-bottom: 1px solid var(--line); }
h3 { font-size: 17px; margin: 22px 0 8px; }
a { color: var(--accent); }
code { font-family: ui-monospace, Consolas, Menlo, monospace; font-size: .9em; background: var(--code-bg);
  padding: 1px 5px; border-radius: 4px; overflow-wrap: anywhere; }
pre { background: var(--code-bg); padding: 14px; border-radius: 8px; overflow-x: auto; }
pre code { background: none; padding: 0; overflow-wrap: normal; }
.table { overflow-x: auto; margin: 12px 0; }
table { border-collapse: collapse; width: 100%; background: var(--panel); font-size: 15px; }
th, td { border: 1px solid var(--line); padding: 8px 10px; text-align: left; vertical-align: top; }
th { background: var(--code-bg); }
.note { background: var(--warn-bg); border-left: 4px solid var(--warn-line); padding: 12px 16px;
  border-radius: 4px; margin: 14px 0; }
.graph { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 12px; overflow-x: auto; }
.graph svg { display: block; width: 100%; min-width: 820px; height: auto; }
.node rect { stroke-width: 1.4; }
.node .title { font-size: 14px; font-weight: 650; fill: var(--text); text-anchor: middle; }
.node .sub { font-size: 12px; fill: var(--muted); text-anchor: middle; }
.input rect { fill: var(--input); stroke: var(--input-line); }
.control rect { fill: var(--control); stroke: var(--control-line); }
.endpoint rect { fill: var(--endpoint); stroke: var(--endpoint-line); }
.process rect { fill: var(--process); stroke: var(--process-line); }
.store rect { fill: var(--store); stroke: var(--store-line); }
.output rect { fill: var(--output); stroke: var(--output-line); }
.signal rect { fill: var(--signal); stroke: var(--signal-line); }
.edge { fill: none; stroke: var(--muted); stroke-width: 1.3; }
.arrow { fill: var(--muted); }
.edge-label { font-size: 12px; fill: var(--muted); text-anchor: middle; }
.band-title { font-size: 14px; font-weight: 650; fill: var(--text); }
.legend { list-style: none; display: flex; flex-wrap: wrap; gap: 6px 16px; margin: 10px 0 0; padding: 0;
  font-size: 14px; color: var(--muted); }
.legend li { display: flex; align-items: center; gap: 6px; }
.swatch { width: 14px; height: 14px; border-radius: 3px; border: 1.4px solid; display: inline-block; }
.swatch.input { background: var(--input); border-color: var(--input-line); }
.swatch.control { background: var(--control); border-color: var(--control-line); }
.swatch.endpoint { background: var(--endpoint); border-color: var(--endpoint-line); }
.swatch.process { background: var(--process); border-color: var(--process-line); }
.swatch.store { background: var(--store); border-color: var(--store-line); }
.swatch.output { background: var(--output); border-color: var(--output-line); }
.swatch.signal { background: var(--signal); border-color: var(--signal-line); }
footer { color: var(--muted); font-size: 14px; padding: 24px 0 48px; border-top: 1px solid var(--line); }
@media (max-width: 640px) { nav ol { columns: 1; } h1 { font-size: 24px; } }
""".replace(
    "{{DARK}}",
    # El dashboard elige el tema con data-theme y se lo pasa a la guía cuando la muestra adentro.
    "--bg: #0f141b; --panel: #171e27; --text: #e6eaf0; --muted: #9ba7b6; --line: #2d3743; "
    "--accent: #8ab4ff; --code-bg: #212a35; --warn-bg: #2c2415; --warn-line: #d39e3e; "
    "--input: #1c2a4a; --input-line: #7f9ee8; --control: #3a281a; --control-line: #d98e50; "
    "--endpoint: #2a2750; --endpoint-line: #9a92ea; --process: #252d38; --process-line: #8e99a8; "
    "--store: #17352a; --store-line: #5cb98a; --output: #39310f; --output-line: #cdb23f; "
    "--signal: #3c1a24; --signal-line: #e8798f;",
)

BODY_ES = """
<nav aria-label="Contenido"><ol>
<li><a href="#que-es">Qué es</a></li>
<li><a href="#inicio">Probarlo en local</a></li>
<li><a href="#funcionamiento">Cómo funciona</a></li>
<li><a href="#informacion">Qué datos maneja</a></li>
<li><a href="#audiencia">Señales de audiencia</a></li>
<li><a href="#busqueda">Buscar y comparar canales</a></li>
<li><a href="#seguimiento">Seguir canales</a></li>
<li><a href="#planes">Planes</a></li>
<li><a href="#limitaciones">Limitaciones</a></li>
</ol></nav>

<section id="que-es"><h2>1. Qué es</h2>
<p>Un sistema que reúne los números públicos de canales de YouTube y TikTok, los pone en una misma escala y los analiza. Sirve para comparar canales, ver cómo se reparte la audiencia, seguir su evolución y detectar números que no cierran.</p>
<p>Además de esta guía, cada métrica tiene su ficha en el <a href="/manual/es">manual de métricas</a>, que también se lee desde la pestaña "Manual" del <a href="/dashboard">dashboard</a>.</p>
</section>

<section id="inicio"><h2>2. Probarlo en local</h2>
<p>Desde la carpeta del proyecto, con Python 3.11 o superior:</p>
<pre><code>python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe -m uvicorn app.main:app --reload</code></pre>
<p>Después abrí el <a href="/dashboard">dashboard</a> o la <a href="/docs">documentación de la API</a>. Los datos se guardan en el archivo <code>channel_analytics.db</code>.</p>
<div class="note"><strong>Con o sin datos reales.</strong> Si no hay credenciales, el sistema usa datos simulados y lo avisa en pantalla. Con <code>YOUTUBE_API_KEY</code> en el archivo <code>.env</code> consulta YouTube de verdad y gasta cuota de esa clave: cada búsqueda por tema cuesta 100 unidades de las 10.000 diarias gratuitas.</div>
</section>

<section id="funcionamiento"><h2>3. Cómo funciona</h2>
<p>Hay dos caminos: las consultas en el momento, de izquierda a derecha, y el seguimiento periódico, en la fila de abajo.</p>
<div class="graph">{{FLOW}}</div>{{LEGEND}}
<h3>Cómo leer el grafo</h3>
<ul>
<li><strong>Fuentes y colectores:</strong> cada colector habla con una plataforma. Si no hay credenciales, usa datos simulados.</li>
<li><strong>Normalización:</strong> convierte cada respuesta en un mismo formato de canal y calcula la interacción (NER).</li>
<li><strong>Motor estadístico y señales de audiencia:</strong> analizan esos canales. Las señales también leen el historial guardado.</li>
<li><strong>Sesión y planes:</strong> los planes existen, pero solo se exigen si se activa <code>REQUIRE_SUBSCRIPTION</code>. Por defecto, la estadística se usa sin iniciar sesión.</li>
<li><strong>Programador y worker:</strong> toman periódicamente una foto de los canales seguidos, consultando a los colectores.</li>
</ul>
</section>

<section id="informacion"><h2>4. Qué datos maneja</h2>
<p>El sistema guarda solo los canales que decidís seguir, sus fotos periódicas, los tipos de canal y las cuentas de usuario. Las búsquedas no se guardan. Solo trabaja con datos públicos de cada canal, no con datos de sus espectadores.</p>
<div class="graph">{{INFO}}</div>
<h3>Cómo leer el grafo</h3>
<ul>
<li><strong>Tipo de canal, Canal seguido y Foto del canal:</strong> cada tipo agrupa varios canales, y cada canal acumula una foto por día como máximo.</li>
<li><strong>Usuario:</strong> de la contraseña se guarda solo su hash. No está vinculado a los canales.</li>
<li><strong>Lo que no se guarda:</strong> los resultados de búsqueda, los videos recientes y las señales se calculan en cada consulta. Por eso las señales de un canal seguido usan su foto: no incluyen me gusta por video, pero tampoco gastan cuota.</li>
</ul>
</section>

<section id="audiencia"><h2>5. Señales de audiencia: ¿son creíbles los números?</h2>
<p>Comprar seguidores o vistas deja rastros: mucha gente que sigue a un canal y casi nadie que lo mira. Esta función busca esos rastros en los números públicos. Se usa desde la pestaña "Audiencia" del <a href="/dashboard">dashboard</a>.</p>
<div class="note"><strong>Son indicios, no una prueba.</strong> Con datos públicos no se puede ver quién mira ni identificar bots. Un canal legítimo también puede mostrar estas señales: conviene pedirle sus estadísticas internas antes de concluir algo.</div>
<div class="table"><table>
<tr><th>Señal</th><th>Qué se observa</th><th>Puntos</th></tr>
<tr><td>Pocas vistas para tantos seguidores</td><td>Menos de 3 vistas históricas por seguidor. Menos de 1 pesa más.</td><td>20 o 35</td></tr>
<tr><td>Interacción muy baja</td><td>Menos de 25% del piso de la plataforma. Menos de 10% pesa más.</td><td>15 o 30</td></tr>
<tr><td>Los seguidores casi no miran los videos nuevos</td><td>Un video reciente típico llega a menos de 1,5% de los seguidores. Menos de 0,5% pesa más. No aplica con 50 o más vistas históricas por seguidor: un medio con años de historia o miles de videos reparte sus vistas.</td><td>12 o 25</td></tr>
<tr><td>Muchas vistas, casi sin me gusta</td><td>Menos de 0,1% de me gusta sobre las vistas recientes.</td><td>20</td></tr>
<tr><td>Muchos me gusta, casi sin comentarios</td><td>Menos de 0,2% de comentarios sobre los me gusta.</td><td>15</td></tr>
<tr><td>Un video muy por encima del resto</td><td>20 veces las vistas típicas. Pesa poco porque los videos virales son comunes.</td><td>10</td></tr>
<tr><td>Interacción muy por debajo de canales parecidos</td><td>Entre los más grandes de su búsqueda, con interacción anormalmente baja para el grupo.</td><td>15</td></tr>
<tr><td>Salto brusco de seguidores</td><td>5% o más, muy por encima del ritmo habitual. Pesa más si las vistas no acompañan. Solo en canales seguidos.</td><td>30 o 40</td></tr>
<tr><td>Caída brusca de seguidores</td><td>5% o más entre dos fotos. Puede ser una depuración de cuentas falsas. Solo en canales seguidos.</td><td>25</td></tr>
</table></div>
<h3>Cómo leer el resultado</h3>
<div class="table"><table>
<tr><th>Resultado</th><th>Puntaje</th><th>Qué significa</th></tr>
<tr><td>Sin señales</td><td>Menos de 25</td><td>Nada llamativo en lo que se pudo medir. No garantiza que la audiencia sea real.</td></tr>
<tr><td>Señal leve</td><td>25 a 49</td><td>Algo llama la atención. Una sola señal nunca pasa de este nivel.</td></tr>
<tr><td>Para revisar</td><td>50 a 74</td><td>Varias señales juntas: conviene pedir datos internos.</td></tr>
<tr><td>Muchas señales</td><td>75 o más</td><td>Varias señales fuertes: no conviene decidir solo con estos números.</td></tr>
<tr><td>Datos insuficientes</td><td>—</td><td>Se pudieron calcular menos de 2 señales, o el canal tiene menos de 1.000 seguidores.</td></tr>
</table></div>
<p>El puntaje mide cuánto conviene revisar el canal, no la probabilidad de que haya fraude. Las señales sin datos se listan aparte y no cuentan: un me gusta oculto o un comentario desactivado no se toman como un cero.</p>
<h3>Qué pedirle a un canal para confirmarlo</h3>
<p>Estos datos solo los tiene el dueño del canal: usuarios únicos, tiempo de visualización, audiencia simultánea y origen del tráfico.</p>
<h3>Desde la API</h3>
<pre><code>curl "http://localhost:8000/api/v1/analytics/audience-integrity?query=fitness&amp;platform=youtube&amp;limit=30"
curl "http://localhost:8000/api/v1/tracking/channels/1/audience-integrity"</code></pre>
</section>

<section id="busqueda"><h2>6. Buscar y comparar canales</h2>
<p>Escribí un tema arriba en el <a href="/dashboard">dashboard</a> y el sistema trae sus canales:</p>
<ul>
<li><strong>Resumen:</strong> cantidad de canales por tamaño, desigualdad de audiencia, distribuciones y correlaciones.</li>
<li><strong>Por canal:</strong> tabla ordenable, con el detalle de cada canal.</li>
<li><strong>Por temática:</strong> compara las búsquedas hechas en la sesión.</li>
<li><strong>Por categoría:</strong> un ranking por categoría de YouTube, sin elegir un tema.</li>
<li><strong>Métricas del medio:</strong> valores de referencia de cada plataforma.</li>
</ul>
<p>Las rutas de la API están en <a href="/docs">/docs</a>.</p>
</section>

<section id="seguimiento"><h2>7. Seguir canales</h2>
<p>En la pestaña "Catálogo" podés agregar canales al seguimiento y clasificarlos por tipo. Cada uno recibe una foto al darse de alta y otra en cada corrida del programador, todos los días a las 09:00 UTC por defecto. También podés correrlo a mano con el botón "Correr job ahora". Sin ese historial no hay señales de saltos ni caídas: hacen falta al menos 4 fotos.</p>
</section>

<section id="planes"><h2>8. Planes</h2>
<div class="table"><table>
<tr><th>Plan</th><th>Acceso</th></tr>
<tr><td><code>free</code></td><td>Solo los valores de referencia de cada plataforma.</td></tr>
<tr><td><code>unica</code></td><td>Toda la estadística durante 24 horas por cada crédito.</td></tr>
<tr><td><code>mensual</code></td><td>Toda la estadística mientras el plan esté vigente.</td></tr>
<tr><td><code>premium</code></td><td>Lo anterior, más proyecciones y recomendaciones.</td></tr>
</table></div>
<p>Solo se exigen con <code>REQUIRE_SUBSCRIPTION=true</code>. No hay cobro real conectado: los planes se asignan a mano desde la pestaña "Cuenta".</p>
</section>

<section id="limitaciones"><h2>9. Limitaciones</h2>
<ul>
<li><strong>Umbrales sin validar contra fraude real:</strong> no se contrastaron con canales de fraude comprobado. En una prueba del 09/11/2026 con 69 canales reales de YouTube, ninguno llegó a "para revisar". Al simular compras sobre 55 de ellos, 1 de cada 50 llegó a "para revisar" con 10 veces más seguidores y la mitad con 20 veces más vistas: es prudente y <strong>un resultado sin señales no descarta una compra moderada</strong>.</li>
<li><strong>Solo datos públicos:</strong> no identifica bots ni cuentas individuales.</li>
<li><strong>Sin Instagram:</strong> hoy solo se analizan YouTube y TikTok.</li>
<li><strong>TikTok:</strong> no se evalúan los videos recientes, y la API oficial puede limitar qué se obtiene según el acceso aprobado.</li>
<li><strong>Canales chicos:</strong> con menos de 1.000 seguidores casi no se evalúan, porque las proporciones oscilan demasiado.</li>
<li><strong>Suscriptores redondeados:</strong> YouTube los informa redondeados a 3 cifras, por eso no se evalúan cambios menores a 5%.</li>
</ul>
</section>
"""

BODY_EN = """
<nav aria-label="Contents"><ol>
<li><a href="#what">What it is</a></li>
<li><a href="#start">Trying it locally</a></li>
<li><a href="#operation">How it works</a></li>
<li><a href="#information">What data it handles</a></li>
<li><a href="#audience">Audience signals</a></li>
<li><a href="#search">Searching and comparing channels</a></li>
<li><a href="#tracking">Tracking channels</a></li>
<li><a href="#plans">Plans</a></li>
<li><a href="#limitations">Limitations</a></li>
</ol></nav>

<section id="what"><h2>1. What it is</h2>
<p>A system that gathers the public numbers of YouTube and TikTok channels, puts them on a common scale and analyzes them. Use it to compare channels, see how audience is distributed, follow how channels evolve and spot numbers that do not add up.</p>
<p>Besides this guide, every metric has its entry in the <a href="/manual/en">metrics manual</a>, which you can also read from the "Manual" tab of the <a href="/dashboard">dashboard</a>.</p>
</section>

<section id="start"><h2>2. Trying it locally</h2>
<p>From the project folder, with Python 3.11 or later:</p>
<pre><code>python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe -m uvicorn app.main:app --reload</code></pre>
<p>Then open the <a href="/dashboard">dashboard</a> or the <a href="/docs">API documentation</a>. Data is stored in the <code>channel_analytics.db</code> file.</p>
<div class="note"><strong>With or without real data.</strong> With no credentials, the system uses simulated data and says so on screen. With <code>YOUTUBE_API_KEY</code> in the <code>.env</code> file it really queries YouTube and spends that key's quota: each topic search costs 100 of the 10,000 free daily units.</div>
</section>

<section id="operation"><h2>3. How it works</h2>
<p>There are two paths: on-the-spot queries, from left to right, and periodic tracking, along the bottom row.</p>
<div class="graph">{{FLOW}}</div>{{LEGEND}}
<h3>How to read the graph</h3>
<ul>
<li><strong>Sources and collectors:</strong> each collector talks to one platform. With no credentials, it uses simulated data.</li>
<li><strong>Normalization:</strong> turns every response into one channel format and calculates engagement (NER).</li>
<li><strong>Statistics engine and audience signals:</strong> analyze those channels. Signals also read the stored history.</li>
<li><strong>Session and plans:</strong> plans exist, but are only enforced if <code>REQUIRE_SUBSCRIPTION</code> is on. By default, statistics work without logging in.</li>
<li><strong>Scheduler and worker:</strong> periodically take a snapshot of tracked channels by querying the collectors.</li>
</ul>
</section>

<section id="information"><h2>4. What data it handles</h2>
<p>The system stores only the channels you choose to track, their periodic snapshots, channel types and user accounts. Searches are not stored. It only works with each channel's public data, not with data about its viewers.</p>
<div class="graph">{{INFO}}</div>
<h3>How to read the graph</h3>
<ul>
<li><strong>Channel type, Tracked channel and Channel snapshot:</strong> each type groups several channels, and each channel keeps at most one snapshot per day.</li>
<li><strong>User:</strong> only the password's hash is stored. Users are not linked to channels.</li>
<li><strong>What is not stored:</strong> search results, recent videos and signals are calculated on every query. That is why a tracked channel's signals use its snapshot: they do not include per-video likes, but they do not spend quota either.</li>
</ul>
</section>

<section id="audience"><h2>5. Audience signals: are the numbers credible?</h2>
<p>Buying followers or views leaves traces: many people following a channel and almost nobody watching it. This feature looks for those traces in public numbers. Use it from the "Audiencia" tab of the <a href="/dashboard">dashboard</a>.</p>
<div class="note"><strong>These are indications, not proof.</strong> Public data does not show who is watching or identify bots. A legitimate channel can show these signals too: ask for its internal statistics before concluding anything.</div>
<div class="table"><table>
<tr><th>Signal</th><th>What is observed</th><th>Points</th></tr>
<tr><td>Few views for so many followers</td><td>Fewer than 3 lifetime views per follower. Fewer than 1 weighs more.</td><td>20 or 35</td></tr>
<tr><td>Very low engagement</td><td>Below 25% of the platform's floor. Below 10% weighs more.</td><td>15 or 30</td></tr>
<tr><td>Followers barely watch new videos</td><td>A typical recent video reaches under 1.5% of followers. Under 0.5% weighs more. Does not apply with 50 or more lifetime views per follower: a media outlet with years of history or thousands of videos spreads its views.</td><td>12 or 25</td></tr>
<tr><td>Many views, hardly any likes</td><td>Under 0.1% likes on recent views.</td><td>20</td></tr>
<tr><td>Many likes, hardly any comments</td><td>Under 0.2% comments relative to likes.</td><td>15</td></tr>
<tr><td>One video far above the rest</td><td>20 times the typical views. It weighs little because viral videos are common.</td><td>10</td></tr>
<tr><td>Engagement far below similar channels</td><td>Among the largest in its search, with abnormally low engagement for the group.</td><td>15</td></tr>
<tr><td>Sudden follower jump</td><td>5% or more, far above the usual pace. Weighs more if views do not follow. Tracked channels only.</td><td>30 or 40</td></tr>
<tr><td>Sudden follower drop</td><td>5% or more between two snapshots. It may be a purge of fake accounts. Tracked channels only.</td><td>25</td></tr>
</table></div>
<h3>How to read the result</h3>
<div class="table"><table>
<tr><th>Result</th><th>Score</th><th>What it means</th></tr>
<tr><td>No signals</td><td>Under 25</td><td>Nothing notable in what could be measured. It does not guarantee the audience is real.</td></tr>
<tr><td>Mild signal</td><td>25 to 49</td><td>Something stands out. A single signal never goes beyond this level.</td></tr>
<tr><td>Worth reviewing</td><td>50 to 74</td><td>Several signals together: ask for internal data.</td></tr>
<tr><td>Many signals</td><td>75 or more</td><td>Several strong signals: do not decide on these numbers alone.</td></tr>
<tr><td>Insufficient data</td><td>—</td><td>Fewer than 2 signals could be calculated, or the channel has under 1,000 followers.</td></tr>
</table></div>
<p>The score measures how much a channel is worth reviewing, not the probability of fraud. Signals with no data are listed separately and do not count: hidden likes or disabled comments are not treated as zero.</p>
<h3>What to ask a channel for to confirm</h3>
<p>Only the channel owner has this data: unique users, watch time, concurrent audience and traffic sources.</p>
<h3>From the API</h3>
<pre><code>curl "http://localhost:8000/api/v1/analytics/audience-integrity?query=fitness&amp;platform=youtube&amp;limit=30"
curl "http://localhost:8000/api/v1/tracking/channels/1/audience-integrity"</code></pre>
</section>

<section id="search"><h2>6. Searching and comparing channels</h2>
<p>Type a topic at the top of the <a href="/dashboard">dashboard</a> and the system fetches its channels:</p>
<ul>
<li><strong>Resumen (summary):</strong> channels by size, audience inequality, distributions and correlations.</li>
<li><strong>Por canal (by channel):</strong> a sortable table, with each channel's details.</li>
<li><strong>Por temática (by topic):</strong> compares the searches made in the session.</li>
<li><strong>Por categoría (by category):</strong> a ranking per YouTube category, with no topic to choose.</li>
<li><strong>Métricas del medio (media metrics):</strong> each platform's reference values.</li>
</ul>
<p>The API routes are at <a href="/docs">/docs</a>.</p>
</section>

<section id="tracking"><h2>7. Tracking channels</h2>
<p>In the "Catálogo" tab you can add channels to tracking and classify them by type. Each one gets a snapshot when added and another on every scheduler run, daily at 09:00 UTC by default. You can also run it by hand with the "Correr job ahora" button. Without that history there are no jump or drop signals: they need at least 4 snapshots.</p>
</section>

<section id="plans"><h2>8. Plans</h2>
<div class="table"><table>
<tr><th>Plan</th><th>Access</th></tr>
<tr><td><code>free</code></td><td>Only each platform's reference values.</td></tr>
<tr><td><code>unica</code></td><td>All statistics for 24 hours per credit.</td></tr>
<tr><td><code>mensual</code></td><td>All statistics while the plan is active.</td></tr>
<tr><td><code>premium</code></td><td>All of the above, plus projections and recommendations.</td></tr>
</table></div>
<p>They are only enforced with <code>REQUIRE_SUBSCRIPTION=true</code>. No real payment is connected: plans are assigned by hand from the "Cuenta" tab.</p>
</section>

<section id="limitations"><h2>9. Limitations</h2>
<ul>
<li><strong>Thresholds not validated against real fraud:</strong> they have not been checked against channels with proven fraud. In a test on 09/11/2026 with 69 real YouTube channels, none reached "worth reviewing". When simulating purchases on 55 of them, 1 in 50 reached "worth reviewing" with 10 times more followers, and half with 20 times more views: it is cautious, and <strong>a result with no signals does not rule out a moderate purchase</strong>.</li>
<li><strong>Public data only:</strong> it does not identify bots or individual accounts.</li>
<li><strong>No Instagram:</strong> only YouTube and TikTok are analyzed today.</li>
<li><strong>TikTok:</strong> recent videos are not evaluated, and the official API may limit what can be obtained depending on approved access.</li>
<li><strong>Small channels:</strong> with under 1,000 followers they are barely evaluated, because ratios swing too much.</li>
<li><strong>Rounded subscribers:</strong> YouTube reports them rounded to 3 figures, so changes under 5% are not evaluated.</li>
</ul>
</section>
"""

PAGES = {
    "es": {
        "file": "guia.html", "title": "Guía de uso", "heading": "Guía de uso",
        "subtitle": "Analítica de canales de YouTube y TikTok, y señales de audiencia inusual",
        "switch_href": "/guia/en", "switch_label": "English", "body": BODY_ES,
        "footer": 'Referencia de la API: <a href="/docs">/docs</a> · <a href="/dashboard">Dashboard</a>',
    },
    "en": {
        "file": "guia_en.html", "title": "User guide", "heading": "User guide",
        "subtitle": "YouTube and TikTok channel analytics, and unusual audience signals",
        "switch_href": "/guia", "switch_label": "Español", "body": BODY_EN,
        "footer": 'API reference: <a href="/docs">/docs</a> · <a href="/dashboard">Dashboard</a>',
    },
}


def render(lang: str) -> str:
    page = PAGES[lang]
    body = (
        page["body"]
        .replace("{{FLOW}}", flow_graph(lang))
        .replace("{{INFO}}", info_graph(lang))
        .replace("{{LEGEND}}", legend(lang))
    )
    return (
        f'<!doctype html>\n<html lang="{lang}">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{page['title']}</title>\n<style>{CSS}</style>\n</head>\n<body>\n"
        f'<header><div class="wrap"><div><h1>{page["heading"]}</h1><p>{page["subtitle"]}</p></div>'
        f'<a class="lang" href="{page["switch_href"]}">{page["switch_label"]}</a></div></header>\n'
        f'<main class="wrap">{body}</main>\n'
        f'<div class="wrap"><footer>{page["footer"]}</footer></div>\n</body>\n</html>\n'
    )


def main() -> None:
    for lang, page in PAGES.items():
        (STATIC_DIR / page["file"]).write_text(render(lang), encoding="utf-8", newline="\n")
        print(f"Generado: {STATIC_DIR / page['file']}")


if __name__ == "__main__":
    main()
