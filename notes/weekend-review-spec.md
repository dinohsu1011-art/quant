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
| IPO cohort | Doesn't work | 11 real names under 252 bars, most already in baskets |

The split between the last two rows is the important one. The *count* of flags is a
market-state reading and it's informative on large caps. The *names* it returns are
large caps, which is not where the setup lives. One scan, two products, only one of
which is usable today.

---

## Data to add now (cheap)

Four symbols, no schema change:

- `IWM` — Russell 2000 ETF (closes leg 1)
- `^RUT` — Russell 2000 index, for deeper history than the ETF
- `RSP` — equal-weight S&P, for cap-weight vs equal-weight leadership
- `MDY` — mid-cap, fills the gap between R2K and the S&P

Deferred until the universe question is settled: Russell 2000 constituents (~2,000
tickers, ~550MB, ~6 min of fetch). Note that the wide universe only needs to be
current on Saturday, so it belongs on a weekly pull, not in `ops/daily.sh`.

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

---

## Leg 3c — IPO cohort

Specced, not buildable. Eleven single stocks have under 252 bars, and most are 2026
listings already inside the theme baskets (SPCX, INIO, FDXF, XE, FPS, Q, SOLS, FLY,
AMBQ). That is not a cohort you can read risk appetite from.

When the universe expands, the intended output is:

- an equal-weight index of every name that listed in the last 252 sessions, rebased
  against SPY — the cohort either holds up or it doesn't
- % of the cohort above its 50-day average, and above its first-day close
- the best and worst 10 by return since listing

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

Design direction to be chosen at build time; it must diverge from the themes page.

---

## Open questions

1. **Flag geometry.** The 40-session run and ≤25% pullback come from the routine's own
   "100% in under eight weeks". Flag length of 10–35 sessions and the 15% off-high
   limit are mine. Worth setting against how the setup is actually traded.
2. **Volume dry-up as a filter or a column.** Currently reported. HPE sits at 0.91,
   which is barely a dry-up; a 0.8 cut would have dropped it.
3. **Universe.** Everything in leg 3b and 3c is gated on this. Nothing else is.
