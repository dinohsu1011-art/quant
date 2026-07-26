"""Forward price projection from a ticker's own history, with the honesty tests attached.

Answers one question: "the chart looks like THIS today — what happened the other
times it looked like this?" It answers by finding past dates whose trailing chart
state matched today's, drawing each one's forward year as its own dated line, and
putting a block-bootstrap cone behind them so you can see whether the matching
narrowed anything.

    python -m analysis.projection qqq [--horizon 252] [--plot out.png]

Rules this module will not break, each one because it was tested and mattered:

* State is computed from a TRAILING window only. Nothing about how a structure
  ended is allowed into the match. "Forward return after a long uptrend ENDED"
  is +6%; "forward return while merely IN one" is +13%; the whole gap is the
  look-ahead. `audit_causal()` proves the state function never reads the future.
* Matches are filtered on realized volatility, not just shape. Shape matching
  alone (z-scored correlation) throws amplitude away and will happily project a
  utility's 2004 onto the Nasdaq.
* Anchors are spaced at least one horizon apart, so no two projected paths share
  a day of the future.
* Episodes are drawn individually, never as a smoothed percentile ribbon. At
  n<40 the p10 and p90 ARE the min and max, and a ribbon claims a distribution
  that does not exist.
* Every projection ships with the two nulls, the walk-forward calibration, and
  the beat-the-naive test. If the fan loses, that prints on the chart.
"""
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
import db
from analysis import structures as st

HORIZON = 252
LOOKBACK = 420        # deepest trailing window the state function may see
MIN_AGE = 60          # a structure younger than this is not a structure
POS_TOL = 0.25        # how close a past day's position in its structure must be
AGE_LO, AGE_HI = 0.5, 2.0   # allowed age ratio to today's structure
VOL_LO, VOL_HI = 0.6, 1.7   # allowed realized-vol ratio. amplitude is not optional
SPACING = HORIZON     # minimum sessions between two accepted anchors
BLOCK = 63            # bootstrap block, one quarter — preserves vol clustering
DRAWS = 2000
TREND_R2 = 0.55
TREND_SLOPE = 0.12    # annualized log slope that counts as trending


# ---------------------------------------------------------------------------
# where are we, using only the past
# ---------------------------------------------------------------------------
@dataclass
class State:
    kind: str = "none"        # "range" | "trend"
    label: str = ""           # "range" | "rising" | "falling"
    age: int = 0              # sessions in the structure
    pos: float = np.nan       # 0 = lower edge/rail, 1 = upper
    height: float = np.nan    # log height of the structure
    slope_ann: float = np.nan
    r2: float = np.nan
    vol: float = np.nan       # 60d annualized, for the amplitude filter
    lo: float = np.nan        # dollar levels of the edges/rails at this bar
    hi: float = np.nan


def _fit_channel(lc, n):
    """Least squares on the last n log closes. Returns slope, r2, residuals."""
    y = lc[-n:]
    t = np.arange(n, dtype=float)
    tc = t - t.mean()
    b = float((tc * (y - y.mean())).sum() / (tc ** 2).sum())
    a = float(y.mean() - b * t.mean())
    e = y - (a + b * t)
    sst = float(((y - y.mean()) ** 2).sum())
    r2 = 1.0 - float((e ** 2).sum()) / sst if sst > 0 else 0.0
    return a, b, r2, e


def state_at(d, t, lookback=LOOKBACK):
    """The chart state on bar `t`, computed from bars <= t and nothing else.

    Tries a range first, then a trend, longest qualifying window wins. This is
    the whole conditioning variable, so it has to be something you could have
    computed live on the day — which is why it never touches d.iloc[t+1:].
    """
    if t < MIN_AGE:
        return State()
    s0 = max(0, t - lookback + 1)
    seg = d.iloc[s0:t + 1]
    hi_a, lo_a, cl_a = seg["high"].values, seg["low"].values, seg["close"].values
    lc = np.log(cl_a)
    sigma = float(d["sigma"].values[t])
    vol = sigma
    if not np.isfinite(sigma):
        return State()
    m = len(seg)

    # --- range: longest window ending at t that stays under the width cap
    best = None
    for L in range(m, MIN_AGE - 1, -5):
        w = slice(m - L, m)
        b_hi, b_lo = hi_a[w].max(), lo_a[w].min()
        mid = float(np.median(cl_a[w]))
        cap = st._wmax(sigma, L)
        if (b_hi - b_lo) / mid > cap:
            continue
        height = float(np.log(b_hi / b_lo))
        dr = abs(float(lc[-1] - lc[m - L])) / height if height > 0 else 9.9
        if dr > st.DR_MAX:
            continue
        h = b_hi - b_lo
        if not (st._touch_events(hi_a[w], b_hi, h, True) >= st.TOUCH_MIN and
                st._touch_events(lo_a[w], b_lo, h, False) >= st.TOUCH_MIN):
            continue
        best = State(kind="range", label="range", age=L,
                     pos=float((cl_a[-1] - b_lo) / h) if h > 0 else np.nan,
                     height=height, vol=vol, lo=float(b_lo), hi=float(b_hi))
        break
    if best is not None:
        return best

    # --- trend: longest straight channel ending at t
    for L in (252, 189, 126, 90, 60):
        if L > m:
            continue
        a, b, r2, e = _fit_channel(lc, L)
        if r2 < TREND_R2 or abs(b * 252) < TREND_SLOPE:
            continue
        up, dn = float(e.max()), float(e.min())
        h = up - dn
        if h <= 0:
            continue
        px = float(lc[-1] - (a + b * (L - 1)))
        return State(kind="trend", label=("rising" if b > 0 else "falling"), age=L,
                     pos=float((px - dn) / h), height=float(h),
                     slope_ann=float(b * 252), r2=float(r2), vol=vol,
                     lo=float(np.exp(a + b * (L - 1) + dn)),
                     hi=float(np.exp(a + b * (L - 1) + up)))
    return State()


def audit_causal(d, t, forward=60):
    """Prove state_at can't see the future: recompute it with every bar after t
    deleted. Any difference means a look-ahead leak."""
    a = state_at(d, t)
    b = state_at(d.iloc[:t + 1], t)
    keys = ("kind", "label", "age")
    same = all(getattr(a, k) == getattr(b, k) for k in keys)
    return {"date": str(d.index[t].date()), "causal": bool(same),
            "full": a.label, "truncated": b.label}


# ---------------------------------------------------------------------------
# find the matching days
# ---------------------------------------------------------------------------
def find_matches(d, now_state, horizon=HORIZON, spacing=SPACING, end=None,
                 pos_tol=POS_TOL, step=5):
    """Past bars whose trailing state matched today's, spaced so their forward
    windows never overlap. Returns a list of (index, State)."""
    if now_state.kind == "none":
        return []
    end = (len(d) - horizon - 1) if end is None else end
    hits = []
    for t in range(MIN_AGE, end, step):
        s = state_at(d, t)
        if s.kind != now_state.kind or s.label != now_state.label:
            continue
        if not np.isfinite(s.pos) or abs(s.pos - now_state.pos) > pos_tol:
            continue
        ratio = s.age / max(now_state.age, 1)
        if not (AGE_LO <= ratio <= AGE_HI):
            continue
        vr = s.vol / now_state.vol if now_state.vol > 0 else np.nan
        if not (VOL_LO <= vr <= VOL_HI):
            continue
        hits.append((t, s))

    # keep the closest match in each cluster, one per `spacing` sessions
    kept, last = [], -10 ** 9
    for t, s in sorted(hits, key=lambda x: x[0]):
        if t - last < spacing:
            continue
        kept.append((t, s))
        last = t
    return kept


def paths_from(d, anchors, horizon=HORIZON):
    """Forward log-return paths from each anchor, one column per episode."""
    cl = np.log(d["close"].values)
    n = len(cl)
    cols = {}
    for t, s in anchors:
        j = min(t + horizon, n - 1)
        p = cl[t:j + 1] - cl[t]
        if len(p) < horizon + 1:
            p = np.concatenate([p, np.full(horizon + 1 - len(p), np.nan)])
        cols[str(d.index[t].date())] = p
    return pd.DataFrame(cols, index=np.arange(horizon + 1))


# ---------------------------------------------------------------------------
# the nulls
# ---------------------------------------------------------------------------
def block_bootstrap(d, horizon=HORIZON, block=BLOCK, draws=DRAWS, end=None,
                    seed=0):
    """Unconditional forward paths from a circular block bootstrap of the
    ticker's own daily log returns. This is honest uncertainty — the cone the
    conditional episodes have to beat to have said anything."""
    r = d["r"].values
    r = r[np.isfinite(r)]
    if end is not None:
        r = r[:end]
    n = len(r)
    rng = np.random.default_rng(seed)
    nb = int(np.ceil(horizon / block))
    starts = rng.integers(0, n, size=(draws, nb))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]) % n
    sim = r[idx].reshape(draws, nb * block)[:, :horizon]
    return np.concatenate([np.zeros((draws, 1)), np.cumsum(sim, axis=1)], axis=1)


def random_windows(d, horizon=HORIZON, draws=5000, k=None, end=None, seed=1):
    """Null A: the same number of forward windows, drawn at random instead of
    matched. Medians of these are what the conditional median must beat."""
    cl = np.log(d["close"].values)
    n = end if end is not None else len(cl)
    hi = n - horizon - 1
    if hi <= 0:
        return np.array([])
    rng = np.random.default_rng(seed)
    k = k or 10
    out = np.empty(draws)
    for i in range(draws):
        t = rng.integers(0, hi, size=k)
        out[i] = float(np.median(cl[t + horizon] - cl[t]))
    return out


def pctile_of(value, sample):
    sample = np.asarray(sample)
    sample = sample[np.isfinite(sample)]
    if len(sample) == 0 or not np.isfinite(value):
        return np.nan
    return float((sample < value).mean() * 100)


# ---------------------------------------------------------------------------
# does any of it work
# ---------------------------------------------------------------------------
def walkforward(d, horizon=HORIZON, step=63, start_frac=0.35, min_n=4):
    """Rebuild the projection at past dates using only data available then, and
    score it. Coverage that misses nominal, or a median error worse than the
    trailing unconditional median, means the fan is decoration."""
    cl = np.log(d["close"].values)
    n = len(cl)
    t0 = int(n * start_frac)
    rows = []
    for t in range(t0, n - horizon - 1, step):
        s = state_at(d, t)
        if s.kind == "none":
            continue
        m = find_matches(d, s, horizon=horizon, end=t - horizon, step=10)
        if len(m) < min_n:
            continue
        p = paths_from(d.iloc[:t + 1], m, horizon=horizon)
        fin = p.iloc[-1].dropna().values
        if len(fin) < min_n:
            continue
        real = float(cl[t + horizon] - cl[t])
        past = cl[horizon:t + 1] - cl[:t + 1 - horizon]
        naive = float(np.median(past)) if len(past) else np.nan
        rows.append({
            "date": d.index[t].date(), "state": s.label, "n": len(fin),
            "med": float(np.median(fin)), "naive": naive, "real": real,
            "p25": float(np.percentile(fin, 25)), "p75": float(np.percentile(fin, 75)),
            "p10": float(np.percentile(fin, 10)), "p90": float(np.percentile(fin, 90)),
        })
    wf = pd.DataFrame(rows)
    if wf.empty:
        return wf, {}
    wf["in50"] = (wf["real"] >= wf["p25"]) & (wf["real"] <= wf["p75"])
    wf["in80"] = (wf["real"] >= wf["p10"]) & (wf["real"] <= wf["p90"])
    wf["err"] = (wf["med"] - wf["real"]).abs()
    wf["err_naive"] = (wf["naive"] - wf["real"]).abs()
    score = {
        "forecasts": len(wf),
        "cover50": float(wf["in50"].mean()),
        "cover80": float(wf["in80"].mean()),
        "mae": float(wf["err"].median()),
        "mae_naive": float(wf["err_naive"].median()),
        "beat_naive": float((wf["err"] < wf["err_naive"]).mean()),
    }
    score["verdict"] = ("usable" if score["cover80"] >= 0.70 and
                        score["mae"] < score["mae_naive"] else "MISCALIBRATED")
    return wf, score


# ---------------------------------------------------------------------------
# assemble
# ---------------------------------------------------------------------------
def project(view, conn=None, horizon=HORIZON, df=None, run_walkforward=True):
    """Everything needed to draw and judge one projection."""
    d = st._prep(st.load(view, conn) if df is None else df)
    t_now = len(d) - 1
    now = state_at(d, t_now)
    matches = find_matches(d, now, horizon=horizon)
    paths = paths_from(d, matches, horizon=horizon)

    p0 = float(d["close"].values[t_now])
    prices = np.exp(paths) * p0
    cone = block_bootstrap(d, horizon=horizon)
    cone_q = {q: np.exp(np.percentile(cone, q, axis=0)) * p0
              for q in (10, 25, 50, 75, 90)}

    fin = paths.iloc[-1].dropna().values
    med = float(np.median(fin)) if len(fin) else np.nan
    nulls = {
        "null_a_pct": pctile_of(med, random_windows(d, horizon, k=max(len(fin), 1))),
        "null_b_pct": pctile_of(med, cone[:, -1]),
        "uncond_med": float(np.median(cone[:, -1])),
    }

    wf, score = (walkforward(d, horizon=horizon) if run_walkforward
                 else (pd.DataFrame(), {}))
    return {
        "ticker": str(view).lower(), "asof": d.index[t_now].date(), "close": p0,
        "state": now, "matches": matches, "paths": paths, "prices": prices,
        "cone": cone_q, "median_logret": med, "nulls": nulls,
        "walkforward": wf, "score": score, "prices_hist": d,
    }


def report(res):
    s, n = res["state"], res["nulls"]
    L = [f"{res['ticker'].upper()}  {res['asof']}  close {res['close']:.2f}"]
    L.append(f"state: {s.label}  age {s.age}d  position {s.pos:.0%} of structure"
             f"  height {s.height:.1%}  vol {s.vol:.0%}"
             + (f"  slope {s.slope_ann:+.0%}/yr r2 {s.r2:.2f}" if s.kind == "trend" else ""))
    fin = res["paths"].iloc[-1].dropna()
    L.append(f"matches: n={len(fin)}  from {res['ticker'].upper()} itself, "
             f"dates {', '.join(fin.index[:10])}" + (" ..." if len(fin) > 10 else ""))
    if len(fin):
        L.append(f"forward {len(res['paths']) - 1}d:  median {np.exp(fin.median()) - 1:+.1%}"
                 f"   range {np.exp(fin.min()) - 1:+.1%} to {np.exp(fin.max()) - 1:+.1%}")
    L.append(f"unconditional median (block bootstrap): {np.exp(n['uncond_med']) - 1:+.1%}")
    L.append(f"null A (random windows): {n['null_a_pct']:.0f}th pct"
             f"   null B (bootstrap): {n['null_b_pct']:.0f}th pct")
    sc = res["score"]
    if sc:
        L.append(f"walk-forward over {sc['forecasts']} rebuilds: "
                 f"50% band covered {sc['cover50']:.0%} (want 50), "
                 f"80% band covered {sc['cover80']:.0%} (want 80)")
        L.append(f"median error {sc['mae']:.1%} vs naive {sc['mae_naive']:.1%}, "
                 f"beats naive {sc['beat_naive']:.0%} of the time  ->  {sc['verdict']}")
    return "\n".join(L)


if __name__ == "__main__":
    view = sys.argv[1] if len(sys.argv) > 1 else "qqq"
    res = project(view)
    print(report(res))
