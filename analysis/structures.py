"""Chart-structure detection: trading ranges, channels, and what came after.

Finds the structures a chartist would draw on a daily bar chart — sideways
boxes and straight channels — labels each box by what volume did *inside* it,
and measures the forward path from the breakout. The point is the last part:
given the structure a ticker is in today, show how the same structure resolved
in that ticker's own past.

    python -m analysis.structures ndx [--pooled] [--plot out.png]

Design rules, each of which the output depends on:

* Hindsight sets the EDGES of a structure and nothing else. Where a box starts
  and stops being a box comes from price containment. Which way it broke, how
  far, and how fast are never seen by the detector, so they stay valid things
  to measure.
* Every volume feature is a RATIO against the ticker's own trailing baseline.
  Raw share counts are not comparable across eras, and yfinance's auto_adjust
  does not scale volume the way it scales price.
* The last 10 sessions before a breakout are excluded from every feature. The
  days just before a break mechanically carry the break; including them lets
  the label read the answer. `audit_buffer()` proves the exclusion is enough.
* Channel rails are FROZEN at the seed fit and never refitted. A refitted
  channel bends to follow price, never breaks, and makes every channel in
  history look like it worked.
* Outcomes are measured in structure heights, not percent, so a 43%-wide 2000
  top and a 7%-wide 2016 box land on one scale.
"""
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
import db

# --- box tunables -----------------------------------------------------------
SEED = 60          # sessions in the seed window
L_MIN = 60         # shortest accepted box
W_K = 1.0          # width cap in units of a random walk's expected travel
W_FLOOR = 0.08     # cap never tighter than this (quiet eras)
W_CEIL = 0.35      # cap never looser than this (crashes)
DR_MAX = 0.50      # net move / box height. above this it's a pause in a trend
TOUCH_FRAC = 0.15  # within this fraction of height counts as touching an edge
TOUCH_MERGE = 5    # touch days this close collapse to one touch event
TOUCH_MIN = 2      # independent touches required on each edge
EPS_ATR = 0.25     # breakout tolerance, in ATR20

# --- channel tunables -------------------------------------------------------
CH_SEED = 90
CH_SLOPE_MIN = 0.15   # annualized log slope; below this it isn't trending
CH_R2_MIN = 0.60      # straightness
CH_WIDTH_K = 1.2      # rail separation cap, same vol currency as boxes
CH_BREAK = 0.5        # closes must clear a rail by this much of the height
CH_BREAK_N = 2        # ...on this many consecutive sessions
CH_MAX_MULT = 3       # force re-seed after seed * this many sessions

# --- volume / outcome tunables ----------------------------------------------
VOL_BASE = 250      # sessions in the volume normalizer
VOL_BASE_LONG = 750 # sessions in the up/down volume-ratio baseline
BUFFER = 10         # sessions before the break excluded from every feature
VOTE_MIN = 2        # |vote| needed to commit to a label
HORIZONS = (5, 10, 21, 42, 63, 126, 252)

ACC, DIST, UNRESOLVED = "accumulation", "distribution", "unresolved"


# ---------------------------------------------------------------------------
# data
# ---------------------------------------------------------------------------
def load(view, conn=None):
    """Daily OHLCV for a DuckDB view, date-indexed, prices already in dollars."""
    conn = conn or db.connect()
    v = str(view).strip().lstrip("^").lower().replace("-", "_").replace(".", "_")
    df = conn.execute(
        f"SELECT date, open, high, low, close, volume FROM {v} ORDER BY date"
    ).df()
    df = df.set_index("date")
    return df[df["close"] > 0].dropna(subset=["close"])


def _prep(df):
    """Attach the derived columns every stage reads."""
    d = df.copy()
    lc = np.log(d["close"])
    d["r"] = lc.diff()
    d["sigma"] = d["r"].rolling(60).std() * np.sqrt(252)
    tr = pd.concat([
        d["high"] - d["low"],
        (d["high"] - d["close"].shift()).abs(),
        (d["low"] - d["close"].shift()).abs(),
    ], axis=1).max(axis=1)
    d["atr"] = tr.rolling(20).mean()
    # volume relative to its own recent normal — the only form volume is used in
    d["vn"] = d["volume"] / d["volume"].shift(1).rolling(VOL_BASE).median()
    return d


def _wmax(sigma_ann, length):
    """How wide a box of this length may be, given how fast the ticker moves.

    A random walk at `sigma_ann` covers about sigma*sqrt(L/252) over L sessions.
    A box is a stretch that covered much less than that, so the cap scales the
    same way — which is what makes a 1987 box and a 2025 box the same object.
    """
    if not np.isfinite(sigma_ann):
        return np.nan
    return float(np.clip(W_K * sigma_ann * np.sqrt(length / 252.0), W_FLOOR, W_CEIL))


def _touch_events(vals, level, height, upper, merge=TOUCH_MERGE):
    """Count independent tests of an edge. Consecutive pokes are one test."""
    band = TOUCH_FRAC * height
    hit = (vals >= level - band) if upper else (vals <= level + band)
    idx = np.flatnonzero(hit)
    if len(idx) == 0:
        return 0
    return 1 + int((np.diff(idx) > merge).sum())


# ---------------------------------------------------------------------------
# boxes
# ---------------------------------------------------------------------------
@dataclass
class Box:
    kind: str = "box"
    start: int = 0            # positional index of first bar
    end: int = 0              # last bar inside the box
    brk: int = 0              # breakout bar
    hi: float = 0.0
    lo: float = 0.0
    direction: str = ""       # "up" | "down" | "open" (still forming)
    features: dict = field(default_factory=dict)
    label: str = UNRESOLVED
    vote: int = 0

    @property
    def length(self):
        return self.end - self.start + 1

    @property
    def height(self):
        """Box height in log units — the yardstick every outcome is measured in."""
        return float(np.log(self.hi / self.lo))

    @property
    def width(self):
        return self.hi / self.lo - 1.0


def detect_boxes(d, dr_max=DR_MAX, w_floor=W_FLOOR, l_min=L_MIN, seed=SEED,
                 allow_open=True):
    """Seed, grow, terminate. One mechanism sets the edges, the widening rule,
    and the break, so they cannot disagree with each other."""
    hi_a, lo_a, cl_a = d["high"].values, d["low"].values, d["close"].values
    sig_a, atr_a = d["sigma"].values, d["atr"].values
    n = len(d)
    out, i = [], 0

    while i + seed <= n:
        s, e0 = i, i + seed - 1
        sigma = sig_a[e0]
        if not np.isfinite(sigma):
            i += 1
            continue
        b_hi, b_lo = hi_a[s:e0 + 1].max(), lo_a[s:e0 + 1].min()
        mid = np.median(cl_a[s:e0 + 1])
        cap = _wmax(sigma, seed)
        cap = float(np.clip(cap, w_floor, W_CEIL))
        if not (b_hi - b_lo) / mid <= cap:
            i += 1
            continue

        # grow
        j, direction, brk = e0 + 1, "open", None
        while j < n:
            eps = EPS_ATR * atr_a[j]
            eps = 0.0 if not np.isfinite(eps) else eps
            length = j - s + 1
            cap_j = float(np.clip(_wmax(sigma, length), w_floor, W_CEIL))
            if cl_a[j] > b_hi + eps:
                cand = max(b_hi, hi_a[j])
                if (cand - b_lo) / mid <= cap_j:
                    b_hi = cand
                else:
                    direction, brk = "up", j
                    break
            elif cl_a[j] < b_lo - eps:
                cand = min(b_lo, lo_a[j])
                if (b_hi - cand) / mid <= cap_j:
                    b_lo = cand
                else:
                    direction, brk = "down", j
                    break
            j += 1
        end = (brk - 1) if brk is not None else (n - 1)

        box = Box(start=s, end=end, brk=(brk if brk is not None else n - 1),
                  hi=float(b_hi), lo=float(b_lo), direction=direction)

        ok = box.length >= l_min
        if ok:
            # did price actually go sideways, or is this a pause in a trend?
            dr = abs(np.log(cl_a[end] / cl_a[s])) / box.height
            ok = dr <= dr_max
        if ok:
            h = b_hi - b_lo
            ok = (_touch_events(hi_a[s:end + 1], b_hi, h, True) >= TOUCH_MIN and
                  _touch_events(lo_a[s:end + 1], b_lo, h, False) >= TOUCH_MIN)
        if ok and (brk is not None or allow_open):
            out.append(box)
            i = box.brk + 1
        else:
            i += 1
    return out


# ---------------------------------------------------------------------------
# volume behaviour inside a box
# ---------------------------------------------------------------------------
def volume_features(d, box, buffer=BUFFER):
    """Five ratios describing what volume did inside the box.

    Every one is measured on [start, breakout - buffer] so none of them can
    see the break. F1/F2 are compared to the ticker's own trailing baseline;
    F3/F4 are compared to zero, because inside a genuinely flat box the null
    for net accumulation IS zero (their trailing baselines are contaminated by
    trending stretches and are negative almost everywhere, which is trivially
    true and useless).
    """
    s = box.start
    e = max(box.brk - buffer, s + 20)
    e = min(e, box.end)
    seg = d.iloc[s:e + 1]
    r, vn = seg["r"].values, seg["vn"].values
    hi, lo, cl = seg["high"].values, seg["low"].values, seg["close"].values
    good = np.isfinite(vn) & np.isfinite(r)
    if good.sum() < 20:
        return {}

    f = {}
    # F1 — is selling drying up? back half of the box vs front half, down days only
    half = len(seg) // 2
    dn1 = vn[:half][(r[:half] < 0) & good[:half]]
    dn2 = vn[half:][(r[half:] < 0) & good[half:]]
    f["f1_dryup"] = float(dn2.mean() / dn1.mean()) if len(dn1) >= 3 and len(dn2) >= 3 \
        and dn1.mean() > 0 else np.nan

    # F2 — volume on up days vs down days, against this ticker's own normal.
    # The baseline matters: for an index the long-run ratio sits near 0.86, not
    # 1.0, because down days carry more volume. Comparing to 1.0 calls almost
    # everything distribution.
    up, dn = vn[(r > 0) & good], vn[(r < 0) & good]
    ratio = float(up.mean() / dn.mean()) if len(up) >= 3 and len(dn) >= 3 and dn.mean() > 0 else np.nan
    base = d.iloc[max(0, s - VOL_BASE_LONG):s]
    br, bv = base["r"].values, base["vn"].values
    bg = np.isfinite(br) & np.isfinite(bv)
    bu, bd = bv[(br > 0) & bg], bv[(br < 0) & bg]
    baseline = float(bu.mean() / bd.mean()) if len(bu) >= 30 and len(bd) >= 30 and bd.mean() > 0 else np.nan
    f["f2_ratio"], f["f2_base"] = ratio, baseline
    f["f2_rel"] = ratio / baseline if np.isfinite(ratio) and np.isfinite(baseline) and baseline > 0 else np.nan

    # F3 — where in each bar's range the close landed, volume weighted
    rng = hi - lo
    clv = np.where(rng > 0, ((cl - lo) - (hi - cl)) / np.where(rng > 0, rng, 1), 0.0)
    w = np.where(np.isfinite(vn), vn, 0.0)
    f["f3_clv"] = float((clv * w).sum() / w.sum()) if w.sum() > 0 else np.nan

    # F4 — net on-balance volume as a share of total volume traded in the box
    sgn = np.sign(np.where(np.isfinite(r), r, 0.0))
    f["f4_obv"] = float((sgn * w).sum() / w.sum()) if w.sum() > 0 else np.nan

    # F5 — springs minus upthrusts. Pokes below support that snap back are the
    # single most cited accumulation tell; the mirror image tops.
    f["f5_spring"] = _spring_count(d, box, e)
    return f


def _spring_count(d, box, e, recover=5):
    hi, lo, cl = d["high"].values, d["low"].values, d["close"].values
    springs = upthrusts = 0
    j = box.start
    while j <= e:
        if lo[j] < box.lo:
            k = min(j + recover, e)
            if (cl[j:k + 1] > box.lo).any():
                springs += 1
                j = k
        elif hi[j] > box.hi:
            k = min(j + recover, e)
            if (cl[j:k + 1] < box.hi).any():
                upthrusts += 1
                j = k
        j += 1
    return springs - upthrusts


def label_box(f):
    """Sign vote across the five features. Five hand-set thresholds is the
    whole parameter budget — deliberately fewer knobs than there are episodes,
    so nothing here is fitted."""
    v = 0
    if np.isfinite(f.get("f1_dryup", np.nan)):
        v += 1 if f["f1_dryup"] < 0.85 else (-1 if f["f1_dryup"] > 1.15 else 0)
    if np.isfinite(f.get("f2_rel", np.nan)):
        v += 1 if f["f2_rel"] > 1.05 else (-1 if f["f2_rel"] < 0.95 else 0)
    if np.isfinite(f.get("f3_clv", np.nan)):
        v += 1 if f["f3_clv"] > 0.05 else (-1 if f["f3_clv"] < -0.05 else 0)
    if np.isfinite(f.get("f4_obv", np.nan)):
        v += 1 if f["f4_obv"] > 0.05 else (-1 if f["f4_obv"] < -0.05 else 0)
    sp = f.get("f5_spring", 0)
    v += 1 if sp > 0 else (-1 if sp < 0 else 0)
    lab = ACC if v >= VOTE_MIN else (DIST if v <= -VOTE_MIN else UNRESOLVED)
    return lab, int(v)


# ---------------------------------------------------------------------------
# channels
# ---------------------------------------------------------------------------
@dataclass
class Channel:
    kind: str = "channel"
    start: int = 0
    end: int = 0
    brk: int = 0
    a: float = 0.0            # intercept of the frozen log-price fit
    b: float = 0.0            # slope per session
    up_off: float = 0.0       # rail offsets in log units
    lo_off: float = 0.0
    r2: float = 0.0
    direction: str = ""       # "open" | "up" | "down" (which rail was lost)
    label: str = ""           # "rising" | "falling"

    @property
    def length(self):
        return self.end - self.start + 1

    @property
    def height(self):
        return float(self.up_off - self.lo_off)

    @property
    def slope_ann(self):
        return float(self.b * 252)


def detect_channels(d, claimed=(), seed=CH_SEED):
    """Straight trends, on the stretches boxes didn't claim, so the two
    structure types never describe the same bars."""
    cl = np.log(d["close"].values)
    sig_a = d["sigma"].values
    n = len(d)
    blocked = np.zeros(n, dtype=bool)
    for s, e in claimed:
        blocked[s:e + 1] = True

    out, i = [], 0
    t = np.arange(seed, dtype=float)
    tc = t - t.mean()
    tss = (tc ** 2).sum()

    while i + seed <= n:
        if blocked[i:i + seed].any():
            i += 1
            continue
        y = cl[i:i + seed]
        b = float((tc * (y - y.mean())).sum() / tss)
        a = float(y.mean() - b * t.mean())
        e_ = y - (a + b * t)
        ssr = float((e_ ** 2).sum())
        sst = float(((y - y.mean()) ** 2).sum())
        r2 = 1.0 - ssr / sst if sst > 0 else 0.0
        sigma = sig_a[i + seed - 1]

        if abs(b * 252) < CH_SLOPE_MIN or r2 < CH_R2_MIN or not np.isfinite(sigma):
            i += 1
            continue
        up_off, lo_off = float(e_.max()), float(e_.min())
        h = up_off - lo_off
        if h > CH_WIDTH_K * W_K * sigma * np.sqrt(seed / 252.0):
            i += 1
            continue
        res = e_
        if not (_touch_events(res, up_off, h, True) >= TOUCH_MIN and
                _touch_events(res, lo_off, h, False) >= TOUCH_MIN):
            i += 1
            continue

        # extend with the rails FROZEN. Refitting is the one thing that would
        # make every historical channel look like it worked.
        j, direction, brk, run_up, run_dn = i + seed, "open", None, 0, 0
        limit = i + seed * CH_MAX_MULT
        while j < n and j < limit:
            dev = cl[j] - (a + b * (j - i))
            run_up = run_up + 1 if dev > up_off + CH_BREAK * h else 0
            run_dn = run_dn + 1 if dev < lo_off - CH_BREAK * h else 0
            if run_up >= CH_BREAK_N:
                direction, brk = "up", j
                break
            if run_dn >= CH_BREAK_N:
                direction, brk = "down", j
                break
            j += 1
        end = (brk - 1) if brk is not None else min(j, n - 1)
        ch = Channel(start=i, end=end, brk=(brk if brk is not None else end),
                     a=a, b=b, up_off=up_off, lo_off=lo_off, r2=r2,
                     direction=direction, label=("rising" if b > 0 else "falling"))
        if ch.length >= seed:
            out.append(ch)
            i = ch.brk + 1
        else:
            i += 1
    return out


# ---------------------------------------------------------------------------
# what happened next
# ---------------------------------------------------------------------------
def outcomes(d, anchor, height, box=None, horizons=HORIZONS):
    """Forward path from the breakout, measured in structure heights.

    Dividing by height is the measured-move rule made quantitative, and it is
    what lets a 43%-wide top and a 7%-wide base sit on one axis.
    """
    cl, hi, lo = d["close"].values, d["high"].values, d["low"].values
    n = len(cl)
    if anchor >= n - 1 or height <= 0:
        return {}
    p0 = cl[anchor]
    o = {"anchor_close": float(p0)}
    for h in horizons:
        j = anchor + h
        if j >= n:
            o[f"n{h}"] = o[f"mfe{h}"] = o[f"mae{h}"] = np.nan
            continue
        o[f"n{h}"] = float(np.log(cl[j] / p0) / height)
        o[f"mfe{h}"] = float(np.log(hi[anchor:j + 1].max() / p0) / height)
        o[f"mae{h}"] = float(np.log(lo[anchor:j + 1].min() / p0) / height)
    if box is not None:
        o["outcome"] = _breakout_tag(d, box)
    return o


def _breakout_tag(d, box, back=21, again=63):
    """Did the break hold? Failure is not noise here — on QQQ it is the base
    case, so it gets a column rather than a filter."""
    cl = d["close"].values
    n = len(cl)
    a = box.brk
    w = cl[a + 1:min(a + 1 + back, n)]
    if len(w) == 0:
        return "pending"
    inside = (w >= box.lo) & (w <= box.hi)
    if not inside.any():
        return "follow-through"
    ret = a + 1 + int(np.flatnonzero(inside)[0])
    w2 = cl[ret:min(ret + again, n)]
    if len(w2) == 0:
        return "pending"
    if box.direction == "up":
        if (w2 < box.lo).any():
            return "reversal"
        return "fakeout-recovered" if (w2 > box.hi).any() else "chopped"
    if (w2 > box.hi).any():
        return "reversal"
    return "fakeout-recovered" if (w2 < box.lo).any() else "chopped"


# ---------------------------------------------------------------------------
# one pass over a ticker
# ---------------------------------------------------------------------------
def scan(view, conn=None, dr_max=DR_MAX, w_floor=W_FLOOR, l_min=L_MIN,
         df=None, with_channels=True):
    """Every structure in a ticker's history, with its volume label and the
    forward path from its breakout. Returns (DataFrame, prepped prices)."""
    d = _prep(load(view, conn) if df is None else df)
    boxes = detect_boxes(d, dr_max=dr_max, w_floor=w_floor, l_min=l_min)
    rows = []
    for b in boxes:
        b.features = volume_features(d, b)
        b.label, b.vote = label_box(b.features) if b.features else (UNRESOLVED, 0)
        row = {
            "kind": "box", "start": d.index[b.start].date(), "end": d.index[b.end].date(),
            "brk_date": d.index[b.brk].date(), "days": b.length,
            "width": round(b.width * 100, 1), "height": round(b.height, 4),
            "direction": b.direction, "label": b.label, "vote": b.vote,
            "px_lo": round(b.lo, 2), "px_hi": round(b.hi, 2),
            "_start_i": b.start, "_brk_i": b.brk,
        }
        row.update({k: (round(v, 3) if isinstance(v, float) and np.isfinite(v) else v)
                    for k, v in b.features.items()})
        if b.direction != "open":
            row.update(outcomes(d, b.brk, b.height, box=b))
        rows.append(row)

    if with_channels:
        for c in detect_channels(d, claimed=[(b.start, b.brk) for b in boxes]):
            row = {
                "kind": "channel", "start": d.index[c.start].date(),
                "end": d.index[c.end].date(), "brk_date": d.index[c.brk].date(),
                "days": c.length, "height": round(c.height, 4),
                "direction": c.direction, "label": c.label, "vote": 0,
                "slope_ann": round(c.slope_ann * 100, 1), "r2": round(c.r2, 2),
                "_start_i": c.start, "_brk_i": c.brk,
            }
            if c.direction != "open":
                row.update(outcomes(d, c.brk, c.height))
            rows.append(row)

    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.sort_values("start").reset_index(drop=True)
    return out, d


def audit_buffer(view, conn=None, extra=10, df=None):
    """Prove the labels aren't reading the breakout: relabel every box with the
    feature window cut a further `extra` sessions short and count the flips.
    A non-zero count means BUFFER is too small and the label is contaminated."""
    d = _prep(load(view, conn) if df is None else df)
    flips, n = 0, 0
    for b in detect_boxes(d):
        f1 = volume_features(d, b, buffer=BUFFER)
        f2 = volume_features(d, b, buffer=BUFFER + extra)
        if not f1 or not f2:
            continue
        n += 1
        if label_box(f1)[0] != label_box(f2)[0]:
            flips += 1
    return {"boxes": n, "label_flips": flips, "extra_sessions": extra}
