# Metrics manual — Channel Analytics Core

This document explains, in plain language, every metric the system
computes: what it means, how it is calculated, and which endpoint returns
it. Written for someone using the dashboard or the API without having
read the source code.

> Versión en español: [`manual_metricas_es.md`](./manual_metricas_es.md) / Spanish version: [`manual_metricas_es.md`](./manual_metricas_es.md)

## 1. Channel metrics (inventory and audience)

| Field (API) | Name | What it is |
|---|---|---|
| `followers` | Subscribers / Followers | Total subscriber count (YouTube) or follower count (TikTok) for the channel, exactly as reported by the platform. |
| `total_views` | Total views | Historical sum of all playbacks across all of the channel's videos (this is not "views this week" — it's the channel's lifetime cumulative total). |
| `total_posts` | Posts | Number of videos published by the channel. |
| `raw_interactions` | Raw interactions | Sum of the available interaction signals (see below) from the latest snapshot taken. This is the basis for computing NER (normalized Engagement Rate). |
| `likes`, `comments`, `shares`, `saves` | Interaction breakdown | Individual components of `raw_interactions`. **Important**: YouTube's public API does not expose aggregated "likes" at the channel level, so on YouTube `likes`, `shares`, and `saves` stay at 0 and `raw_interactions` is approximated using only `comments`. On TikTok all four signals are summed. |
| `tier` | Audience tier | Automatic classification by follower count: **nano** (<10k), **micro** (10k–100k), **mid** (100k–500k), **macro** (500k–1M), **mega** (>1M). |

## 2. Engagement metrics

| Field / Acronym | Name | Formula | What it measures |
|---|---|---|---|
| `normalized_er` (NER) | Normalized Engagement Rate | `(Total interactions / Views) × 100` | How actively the audience reacts relative to how many people saw the content. A channel with many followers but low NER may have a passive (or inflated) audience. |
| AS (Attention Score) | Attention score | `Average watch time / Total content duration` | How much of each video the audience watches on average. **Not yet computed live**: it requires per-video playback telemetry (watch time, duration) that the search/profile API does not provide — it is kept as a ready-to-wire utility for when that data source is added. |
| PFI (Production Frequency Index) | Production frequency index | `Monthly posts × (1 / standard deviation of days between posts)` | How often AND how regularly a channel publishes (posting 12 evenly-spaced videos in a month is not the same as posting 12 videos in a burst and then going silent). **Not yet computed live**, for the same reason as AS: it needs the individual publish date of every video. |

## 3. Descriptive statistics (percentiles, spread, and shape)

Applied to a set of channels (for example, all the results of a search)
for a given metric (followers, NER, etc.). Endpoint: `GET
/analytics/distribution`.

| Field | What it is |
|---|---|
| `mean` / `median` | Average and median (central value). The median is more resistant to a single giant channel skewing the average. |
| `min` / `max` / `range` | Minimum, maximum, and the difference between the two. |
| `p5`, `p10`, `p25`, `p75`, `p90`, `p95` | Percentiles: for example, `p90` is the value below which 90% of channels fall — the remaining 10% is above it. |
| `iqr` | Interquartile range (`p75 − p25`): where the "typical channel" is concentrated, ignoring extremes. |
| `std_dev` | Standard deviation: how spread out the values are relative to the average. |
| `coefficient_of_variation` | `std_dev / mean`. Lets you compare the spread of metrics on very different scales (e.g. followers vs. NER) on a common relative unit. |
| `skewness` | Whether the distribution has a "tail" toward high values (positive, the most common case: a few giant channels) or toward low values (negative). |
| `kurtosis` | How "peaked" the distribution is compared to a normal distribution — high values indicate more outliers than expected. |

## 4. Inequality and audience concentration

Answer the question "how evenly is the audience spread across the
channels in this group?" Endpoint: `GET /analytics/inequality`.

| Field | Name | Range | What it measures |
|---|---|---|---|
| `gini_followers` | Gini coefficient | 0 to 1 | 0 = every channel has the same number of followers (perfect equality). 1 = a single channel holds the entire group's audience. |
| `pareto_alpha` | Pareto exponent (power law) | typically 1–3 | How pronounced the "80/20"-style inequality is: lower values (near 1) indicate a heavier tail (a few enormous channels dominate even more). `null` if there is not enough variation in the data to estimate it. |
| `top_10_pct_share` | Top-10% share | 0 to 1 | What proportion of the group's total followers is held by the top 10% largest channels. |

## 5. Correlation between variables

Answer questions like "does posting more often relate to more
engagement?" Endpoint: `GET /analytics/correlation`. Two coefficients are
computed in parallel, both between −1 (perfect inverse relationship) and
+1 (perfect direct relationship), 0 = no relationship:

- **Spearman (`spearman_rho`)**: **rank** correlation — it does not
  assume the relationship is a straight line, and is more resistant to a
  single viral outlier skewing everything. This is the primary
  coefficient the system uses to interpret results.
- **Pearson (`pearson_r`)**: classic **linear** correlation, shown as a
  complementary reference.

The `interpretation` field translates the number into a phrase (e.g.
"Moderate positive correlation").

## 6. Anomaly detection (possible metric inflation)

Endpoint: `GET /analytics/anomalies`. Rule applied over a search's group
of channels:

> A channel is flagged when **Followers ≥ P75** (it is in the 25% of the
> group with the most audience) **AND** **NER < Q1 − 1.5 × IQR** (its
> engagement falls well below what's expected, per the classic Tukey
> outlier criterion).

In plain terms: large channels whose audience looks abnormally inactive
compared to similarly-sized channels — a signal of possible
follower/view purchasing, **not definitive proof** (it can also happen
with legitimate very-passive niche channels, or because of YouTube's
limitation of not exposing aggregated likes).

## 7. Industry benchmarks (per-platform reference)

Endpoint: `GET /analytics/benchmarks`. These are industry-published
reference values (not recalculated per search), used to contextualize
whether the observed average ER is **"below"**, **"within"**, or
**"above"** the typical range.

| | YouTube | TikTok |
|---|---|---|
| Expected engagement rate range | 1.5% – 3.5% | 4.0% – 9.0% |
| Retention metric | Relative audience retention (AVD) | Completion rate |
| Typical posting frequency | 1–3 posts/week | 1–3 posts/day |
| Content lifespan | Long (months to years, driven by SEO/search) | Very short to medium (24h to 7 days) |
| Known bias risk | Clickbait inflates initial views without real retention | The algorithm rewards ephemeral virality over the follower base |

> **Note on YouTube and ER**: since the public API does not expose
> aggregated "likes" at the channel level, this system's YouTube NER is
> approximated using only comments — which is why it commonly shows up as
> "below" the benchmark. This is a documented limitation of the raw
> metric, not a system error.

## 8. "All topics" discovery (no category)

`GET /channels/discover` and `GET /channels/discover/by-category` do not
require a topic/keyword: they assemble a snapshot of channels by
combining YouTube's "trending" content across 15 categories (music,
gaming, entertainment, news & politics, sports, science & technology,
education, comedy, lifestyle, film & animation, autos & vehicles, pets &
animals, travel & events, blogs, nonprofits & activism) and several
regions at once (by default: Argentina, Mexico, Spain, United States), so
the user doesn't have to guess a specific topic. The result can be sorted
descending by any of the metrics in section 1 (`followers`,
`total_views`, `total_posts`, `normalized_er`).

## 9. Quick field glossary

| Field | One-line meaning |
|---|---|
| `universal_id` | Global unique channel identifier: `<platform>:<native_id>` (e.g. `youtube:UCxxxx`). |
| `native_id` | The source platform's own ID. |
| `platform` | `youtube` or `tiktok`. |
| `handle` | The channel's public @username. |
| `content_format` | `vod` (video on demand, YouTube) or `micro_video` (short-form, TikTok). |
| `fetched_at` | Exact moment that data point was captured. |

## 10. Subscription plans and what each one unlocks

Access to the metrics in this manual is organized into 4 plans
(`app/models/domain.py::Plan`). **There is no real payment gateway
connected yet** (Mercado Pago/Stripe are still pending — this is a
university project): plan changes are simulated manually via `POST
/api/v1/auth/admin/set-plan`, or from the "Cuenta" ("Account") tab of
the dashboard.

| Plan | What it unlocks |
|---|---|
| `free` | None of what's listed in sections 1 through 6 — only section 7 (`/analytics/benchmarks`), which is static reference data and stays public. |
| `unica` (one-time) | One-off access (consumes 1 "report credit" per query) to ALL the metrics in this manual: descriptive statistics, inequality, correlation, anomalies, and "all topics" discovery — national and international, including metrics not measured in Argentina/Latin America. |
| `mensual` (monthly) | Same as `unica`, but continuous (as long as the subscription hasn't expired), without consuming credits per query. |
| `premium` | Everything in `mensual` **+ the two sections below** (trend projections and recommendations), exclusive to this plan. |

### 10.1 Trend projections (premium)

Endpoint: `GET /premium/channels/{tracked_id}/projections`. Extrapolates
each numeric metric of a tracked channel (`followers`, `total_views`,
`total_posts`, `normalized_er`) forward in time, based on its **weekly**
snapshot history (see section 8 and the weekly tracking worker in
`README.md`).

How it's computed: a degree-1 least-squares fit (a straight line,
`numpy.polyfit`) over "days since the first snapshot" vs. the metric's
value — **this is not an AI model**. That's a deliberate choice: simple,
explainable, and one that improves on its own as more weeks of history
accumulate. It requires at least 3 snapshots per metric; with fewer,
that metric is skipped (it doesn't fail the rest of the response).

| Response field | What it is |
|---|---|
| `weekly_trend` | Slope of the fitted line, expressed per week (e.g. `+1200` followers/week). |
| `history_points` | Number of snapshots used for the fit — more points, a more reliable projection. |
| `projections[].weeks_ahead` / `projected_date` / `projected_value` | The extrapolated value at 1, 4, and 12 weeks from the last snapshot (configurable via `?weeks_ahead=`). |
| `confidence_note` | A reminder that this is a directional guide, not an exact prediction — especially with few snapshots so far. |

### 10.2 General policy recommendations (premium)

Endpoint: `GET /premium/channels/{tracked_id}/recommendations`. A
**fixed-rules engine** (not generative AI) that translates the industry
benchmark from section 7 and, when there's enough history, the weekly
follower trend computed in 10.1, into actionable suggestions per metric.

Examples of the rules applied:

- If the observed ER is **below** the platform's benchmark → "high"
  priority: suggests formats that invite comments and checking whether
  follower growth comes with a genuinely active audience.
- If the ER is **above** the benchmark → "informational" priority:
  suggests scaling up posting frequency while keeping the current format.
- If the weekly follower trend is **negative** → "high" priority: review
  the consistency of recent posting.
- If the trend is **zero** (stagnant audience) → "medium" priority: try a
  new format or subtopic.
- If no deviation is detected → an informational note that the current
  strategy is in line with what's expected.

Each recommendation carries `metric` (which metric it refers to),
`priority` (`alta` / `media` / `informativa` — high / medium /
informational), `finding` (what was detected), and `recommendation` (the
suggestion itself).
