# Weekend review — spec

A Saturday page that answers the three questions the weekend routine exists to answer:

1. Risk-on or risk-off?
2. If the market is trending, which groups and themes?
3. Is there enough across the watchlists to build a focus list for Monday?

Everything below is scoped to the **current universe** — 628 single stocks (503 S&P
members plus basket/reco extras), no Russell 2000, no IPO cohort. Where that universe
can't support a leg, this says so and specs the leg anyway rather than pretending.

All numbers in this document were measured against data through **2026-07-24**.

---

## What the universe supports

| Leg | State | Evidence |
|---|---|---|
| Index review | Two of three indexes | SPY, QQQ, NDX, IXIC present. **No IWM, RUT, RSP, MDY.** |
| Thematic review | Already built | 30+ baskets on `market-lab-themes.html`; needs a ranking view, not new data |
| High volume edge | Works | 13 names over the last 5 sessions; base rate 0.51% of name-sessions ≈ 3/day, ~15/week |
| High tight flag — as a gauge | Works | Count swings 0 → 12 across regimes (table below) |
| High tight flag — as a name source | Doesn't work | **1 match** on 628 names. The setup lives in small caps. |
| IPO cohort | **Dropped** | Not important enough to carry; see below |

The split between the last two rows is the important one. The *count* of flags is a
market-state reading and it's informative on large caps. The *names* it returns are
large caps, which is not where the setup lives. One scan, two products, only one of
which is usable today.

---

## Data added — done

Four index-level series, no constituents. In `INDEX_SYMBOLS`, so they carry full
available history, and on the themes rail under Indices:

| Series | History | Purpose |
|---|---|---|
| `^RUT` | 1987-09-10, 9,791 bars | Russell 2000, closes leg 1 |
| `IWM` | 2000-05-26, 6,578 bars | the tradeable Russell proxy |
| `MDY` | 1995-05-04, 7,857 bars | mid-caps, between R2K and the S&P |
| `RSP` | 2003-05-01, 5,845 bars | equal weight vs cap weight |

`RUT` and `IWM` are in `validate.py`'s `CORE`, so they fail hard rather than warn if
they go stale.

**Russell 2000 constituents are not being pulled.** Index level only. The consequence
is fixed and worth stating plainly: the high tight flag scan stays a market-state
gauge and never becomes a small-cap name source, because the small caps aren't in the
database. Leg 3b below is specced against that reality.

---

## Module layout

```
analysis/breadth.py     % above MA, new highs/lows, up/down volume, per membership set
analysis/setups.py      high_volume_edge(), high_tight_flag(), ipo_cohort()
export/weekend.py       runs the above -> cube/weekend.js
web/market-lab-weekend.html
```

Wire `export/weekend.py` into `update.py` after `export/themes.py`, and add the page
to the `market-lab.html` hub.

### Scan universe

Single stocks only. Built the same way the probe built it: `data/tickers.csv` ∪ every
`BASKETS` constituent ∪ `reco_tickers()`, minus the synthetic basket and `_reco`
series, intersected with what's on disk. 628 today, 627 of which trade on the US
calendar (the `.T` / `.KS` / `.DE` names run their own sessions and are excluded from
breadth, included in scans on their own bars).

---

## Leg 1 — index review

A three-column panel, one per index, each showing:

- last close vs 20 / 50 / 200-day average (above/below, and distance)
- % off the 52-week high
- return over 1W / 1M / 3M / YTD
- the index's own breadth (see leg 4)

Plus four ratio lines, each rebased over the last 6 months, because the routine is
looking for *which* part of the market is doing the work:

| Ratio | Reads as |
|---|---|
| `IWM / SPY` | small caps vs large |
| `RSP / SPY` | broad participation vs mega-cap concentration |
| `QQQ / SPY` | growth/tech vs the market |
| `XLP / SPY` | defensives carrying it (risk-off tell) |

A rising `XLP/SPY` with a falling `IWM/SPY` is the staples-doing-the-heavy-lifting
case, stated numerically instead of eyeballed.

Reading as of 2026-07-24, now that the series exist:

| Index | 1W | 1M | 3M | YTD | off 52wH | vs 50dma |
|---|---|---|---|---|---|---|
| S&P 500 (SPY) | −0.59% | +0.78% | +4.57% | +8.94% | −2.47% | −0.70% |
| Nasdaq-100 (QQQ) | −1.60% | −3.71% | +5.15% | +11.64% | −8.20% | −4.69% |
| Russell 2000 (RUT) | −1.09% | −1.90% | +5.58% | **+18.05%** | −3.12% | −0.01% |
| Midcap (MDY) | +0.28% | −0.05% | +4.44% | +15.06% | −1.80% | +1.07% |
| S&P equal weight (RSP) | +0.09% | +1.52% | +5.90% | +12.40% | −0.69% | +1.87% |

| Ratio | 1M | 3M |
|---|---|---|
| IWM/SPY | −2.62% | +1.30% |
| RSP/SPY | +0.73% | +1.27% |
| QQQ/SPY | −4.46% | +0.56% |
| XLP/SPY | −1.13% | −2.96% |

Equal weight beating cap weight while the Nasdaq-100 lags by 4.5 points on the month,
and defensives falling rather than bid. That is money leaving mega-cap tech and
spreading out, not leaving the market. The panel makes that a two-line read instead of
an inference from flipping charts.

---

## Leg 2 — theme leaderboard

No new computation. Reads the levels already in `cube/themes.js`.

A table of all 30+ baskets, sorted by 1-week return, with columns for 1W / 1M / 3M
return, the name's rank in each, and **Δrank over 4 weeks** — which is where rotation
shows up. Themes that gained 10+ ranks in a month are the money moving in; themes that
lost 10+ are the money moving out.

Clicking a theme jumps to it on the existing themes page with the window preset.

---

## Leg 3a — high volume edge

**Window: the last 5 sessions, not the last bar.** This is the one design decision the
measurements forced. On the current universe:

| Lookback | Names at a 252-day volume high |
|---|---|
| 1 session | 0 |
| 5 sessions | 13 |
| 10 sessions | 16 |

The base rate is 0.51% of name-sessions, so ~3 hits a day and ~15 a week across 627
names. A one-bar scan returns nothing most Saturdays. A week-long window returns a
list the right size to review.

**Definition.** For each name, for each of the last 5 sessions, flag the bar if its
volume is the maximum over a trailing window, and dollar volume that day ≥ $10m:

| Flag | Window |
|---|---|
| `hv_year` | trailing 252 sessions |
| `hv_ever` | the full stored history |
| `hv_ipo` | full history **and** the name has < 252 bars total |
| `hv_earn` | since the last earnings date |

`hv_earn` needs earnings dates, which aren't stored. Fetch them **only for names that
already passed the other flags** — 13 to 20 tickers, not 628 — and cache to
`data/earnings.parquet`. A per-ticker `yfinance` call is slow at universe scale and
free at hit-list scale.

**Reported per hit**, so a volume high on a breakout is separable from one on a
collapse: date of the hit, volume as a multiple of the 50-day median, that day's
return, where the close sat in the day's range, % off the 52-week high, and dollar
volume.

**Volume is split-adjusted in this data.** Verified on NVDA's 10-for-1 in June 2024:
the pre-split bars carry ~412M shares against a ~$120 adjusted close, i.e. actual
shares × 10. So "highest volume ever" compares cleanly across splits and needs no
normalisation. (This contradicts the caution in `analysis/structures.py`; that comment
should be revisited, since it may be over-cautious for volume as well.)

---

## Leg 3b — high tight flag

**Definition** (the version that survived testing):

1. Run: ≥100% gain from the lowest close in the 40 sessions before the flag, up to the
   last close of the run. 40 sessions ≈ the eight weeks in the routine.
2. **The run's peak must be within 5% of the 52-week high.**
3. Flag: 10–35 sessions long, maximum drawdown from the peak ≤25%.
4. Today's close still within 15% of the 52-week high.
5. Reported, not filtered: average flag volume ÷ average run volume. Below 1.0 is the
   dry-up you want.

Condition 2 is load-bearing and was not in the first draft. Without it the scan
returned HUM, CNC, DVA — beaten-down healthcare names doubling off a 2025 low. A 100%
move off a crash low is not a high tight flag; the run has to make a new high. Adding
it cut the match list from 14 to 1.

**Result on the current universe: one match.**

```
HPE   +119% in <=40d, 34d flag, 23% pullback, flag volume x0.91, 15% off high
```

Loosening the gain threshold gives 13 at +60%, 24 at +40%, 36 at +30% — but those are
just strong large caps, not the setup. The threshold isn't the problem. The universe is.

**So this leg ships as a gauge, not a screen.** The output is the count and its
history (leg 4), plus whatever names do match, listed without any pretence that one
match is a focus list. Revisit only if Russell 2000 constituents are ever pulled.

---

## Leg 3c — IPO cohort — dropped

Not built. Eleven single stocks have under 252 bars and most are 2026 listings already
sitting inside the theme baskets, so there was no cohort to read risk appetite from,
and without Russell 2000 constituents there won't be one. Volume edge and the flag
count carry the risk-appetite reading instead.

---

## Leg 4 — the risk-on / risk-off scoreboard

Six gauges, each shown as a current value **and its own percentile against its
history**, so "high" means something. Values as of 2026-07-24:

| Gauge | Today | Source |
|---|---|---|
| % above 20-day | 55.6% | S&P members, n=502 |
| % above 50-day | 66.1% | n=501 |
| % above 200-day | 66.4% | n=500 |
| 52-week highs − lows | +26 (32 vs 6) | S&P members |
| High tight flag count | 1 (13 at the loosened +60%) | leg 3b |
| Volume-edge count, 5 sessions | 13 | leg 3a |

The last two are the ones a standard breadth panel doesn't have, and they're the point
of the exercise: the flag count is speculative appetite, the volume count is
participation.

**The flag count moves with the tape.** Measured on the current universe:

| Date | Flags (+100%) | Flags (+60%) | % above 50-day |
|---|---|---|---|
| 2022-07-18 | 0 | 0 | 25.9% |
| 2023-07-19 | 1 | 7 | 85.5% |
| 2024-07-19 | 0 | 1 | 63.0% |
| 2025-01-21 | 5 | 11 | 56.5% |
| 2025-07-23 | 2 | 13 | 79.6% |
| 2026-01-22 | 2 | 6 | 71.7% |
| 2026-04-23 | 0 | 8 | 59.7% |
| 2026-06-24 | **12** | **29** | 61.3% |
| 2026-07-24 | 1 | 13 | 56.6% |

Zero flags through the 2022 bear, twelve in June 2026, back to one a month later. It
also carries information the moving-average line doesn't: July 2023 had 85% of names
above their 50-day and only one flag, while June 2026 had 61% above and twelve. Broad
and slow is a different tape from narrow and hot, and the flag count separates them.

Ship this as a time series, not just today's number.

---

## Page

`web/market-lab-weekend.html`, in the routine's own order: scoreboard first (the
risk-on/risk-off answer), then indexes, then the theme leaderboard, then the three
watchlists. Focus-list candidates — the names that appear in more than one scan —
pinned at the top of the watchlist section.

### Shipped 2026-07-27

Built as a single-column editorial report rather than a dashboard — it is read top to
bottom once a week, so it is laid out as a document. It shares the Market Lab type and
colour tokens on purpose: this is a sibling page in the same product, not a new one.

What is on it:

* A **verdict line** — decided on two axes, risk and participation, because they are not
  the same question. See the rework below.
* **Risk appetite** — four cohort gauges, three risk ratios (QQQ, SMH, ARKK against SPY),
  and a chart of high-beta/low-beta with the leader-minus-index breadth spread under it.
* **Participation** — the six breadth gauges, each with its value and a rail showing where
  that value sits in its own history. The percentile is the point; the raw number alone
  says little.
* **Indexes** — the five-row table, plus the four ratios with sparklines.
* **Themes** — a rotating-in / rotating-out callout off Δrank, then the full 38-row table.
* **High volume edge** and **High tight flags**, both sortable. Where a name appears in
  both scans it is called out as the focus list; when the overlap is empty the page says
  so rather than showing an empty block.
* The **flag count against % above the 50-day**, on one chart, with 1y/3y/5y/max spans and
  a hover readout. The two series answer different questions and the chart exists to show
  that they come apart.

Wired into `update.py` as step 6, so `cube/weekend.js` regenerates on every daily run.

### Reworked the same day: breadth is not risk

The first version called 2026-07-24 "risk-on". It was wrong, and the mistake was
structural rather than a bug. Every gauge was measured on all 503 S&P names, equally
weighted. When money leaves semiconductors for staples, utilities and energy, most names
stay above their moving averages — so breadth reads healthy while risk appetite is being
sold. Breadth cannot tell a broad *advance* from a broad *rotation*. The tape that day:

| 2 weeks | SOXX −9.3% · ARKK −10.4% · SMH −8.2% · QQQ −5.7% · SPY −2.1% · XLU +1.9% · XLE +8.2% |

Both readings were right. Only one of them was about risk. So:

* Risk moved to cohorts, in `analysis/risk.py`, ranked out of the universe rather than
  hand-picked. **High beta** is the equal-weight top quintile by 126-day beta to SPY over
  the bottom quintile. **Leaders** are the top quintile by 6-month return, measured to a
  month ago so the cohort is not selected on the window it is scored over. What is scored
  is the *change* in each ratio, not its level — the level drifts with the long-run beta
  premium and its percentile would mean nothing.
* Breadth was relabelled **Participation** and the page says outright it is a trend
  measure, not a risk measure.
* The verdict now reads both axes and names the disagreement, because the disagreement is
  the rotation. `risk-off / broad` prints "Risk-off under a firm index — the index is
  holding because money rotated to defensives, not because risk is being taken."

On 2026-07-24 the two axes read: high-beta vs low-beta −10.7% (5th percentile of five
years), leaders less index breadth −7.7pt (8th), against 66.1% of S&P names above their
50-day (68th).

**The caveat this cannot fix:** leadership itself rotates. Energy and health names have
now entered the 6-month momentum cohort, so "leaders" is drifting away from "trendy
names". That is why beta is the primary gauge and momentum the secondary one.

---

## Open questions

1. **Flag geometry.** The 40-session run and ≤25% pullback come from the routine's own
   "100% in under eight weeks". Flag length of 10–35 sessions and the 15% off-high
   limit are mine. Worth setting against how the setup is actually traded.
2. **Volume dry-up as a filter or a column.** Currently reported. HPE sits at 0.91,
   which is barely a dry-up; a 0.8 cut would have dropped it.
3. ~~**Universe.**~~ Settled: index level only, no Russell 2000 constituents. Leg 3b
   is a gauge, leg 3c is dropped.
