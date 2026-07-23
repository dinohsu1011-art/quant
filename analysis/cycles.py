"""Wyckoff-style market-cycle phase labeling for any price series.

Segments a close series into the four classic phases —

    Accumulation -> Mark-Up -> Distribution -> Mark-Down -> (Accumulation ...)

— using only trailing information (no look-ahead), so the same classifier that
labels history also gives a live read on where a name/theme sits *today*.

Method (close-only, so it works on the flat-OHLC baskets too):
  * 200-day moving average is the master trend filter; the annualized slope of
    that MA decides trending (Mark-Up / Mark-Down) vs ranging.
  * Inside the flat-slope ranges, drawdown from the trailing 3-year high splits
    the two ranges: near the high = Distribution (topping), well below =
    Accumulation (basing).
  * Short whipsaw runs are merged into their neighbours so cycles count once,
    not once per wiggle.

The two *trending* phases are robust; the two *ranging* phases are the fuzzy
transition zones by construction and are labeled, not divined — read them as
"basing" / "topping", not gospel.

    python -m analysis.cycles [smh gpu ...] [--plot]
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
import db

ACCUM, MARKUP, DIST, MARKDOWN = "Accumulation", "Mark-Up", "Distribution", "Mark-Down"
PHASES = [ACCUM, MARKUP, DIST, MARKDOWN]
COLORS = {ACCUM: "#8aa9c2", MARKUP: "#4a9d6a", DIST: "#d9a441", MARKDOWN: "#c25b5b"}

# --- tunables ---------------------------------------------------------------
MA_LONG = 200      # master trend MA (trading days)
SLOPE_WIN = 21     # lookback to measure the MA's slope
SLOPE_BAND = 0.05  # |annualized MA slope| below this = "flat" (ranging)
PEAK_WIN = 756     # ~3y trailing high that drawdown is measured against
RANGE_DD = -0.10   # in a flat zone: shallower than this = topping, deeper = basing
MIN_DAYS = 40      # merge phase runs shorter than this into a neighbour
VOL_WIN = 21       # realized-vol window (reported, not gated on)


def classify(close, ma_long=MA_LONG, slope_win=SLOPE_WIN, slope_band=SLOPE_BAND,
             peak_win=PEAK_WIN, range_dd=RANGE_DD, min_days=MIN_DAYS):
    """Return a DataFrame indexed by date with close, the signals, and `phase`."""
    close = close.dropna().astype(float)
    df = pd.DataFrame({"close": close})
    df["ma"] = close.rolling(ma_long, min_periods=ma_long // 2).mean()
    # annualized slope of the trend MA
    df["slope"] = df["ma"].pct_change(slope_win) * (252.0 / slope_win)
    df["peak"] = close.rolling(peak_win, min_periods=1).max()
    df["dd"] = close / df["peak"] - 1.0
    df["vol"] = close.pct_change().rolling(VOL_WIN).std() * np.sqrt(252)

    rising = df["slope"] > slope_band
    falling = df["slope"] < -slope_band
    above = df["close"] >= df["ma"]

    ph = pd.Series(index=df.index, dtype=object)
    ph[rising & above] = MARKUP
    ph[falling & ~above] = MARKDOWN
    ranging = ph.isna() & df["ma"].notna()
    ph[ranging & (df["dd"] >= range_dd)] = DIST
    ph[ranging & (df["dd"] < range_dd)] = ACCUM
    # warm-up (no MA yet): forward-carry the first real label back
    ph = ph.bfill().ffill()

    df["phase"] = _merge_short_runs(ph, min_days)
    return df


def _runs(ph):
    """Contiguous (phase, start_idx, end_idx) runs over a positional series."""
    vals = ph.to_numpy(dtype=object)
    out, i, n = [], 0, len(vals)
    while i < n:
        j = i
        while j + 1 < n and vals[j + 1] == vals[i]:
            j += 1
        out.append([vals[i], i, j])
        i = j + 1
    return out


def _merge_short_runs(ph, min_days):
    """Absorb any run shorter than min_days into its longer adjacent run,
    repeatedly, so brief whipsaws don't spawn phantom cycles."""
    vals = ph.to_numpy(dtype=object).copy()
    while True:
        runs = _runs(pd.Series(vals, index=ph.index))
        if len(runs) <= 1:
            break
        lens = [e - s + 1 for _, s, e in runs]
        k = int(np.argmin(lens))
        if lens[k] >= min_days:
            break
        # relabel run k to whichever neighbour's run is longer
        left = lens[k - 1] if k > 0 else -1
        right = lens[k + 1] if k < len(runs) - 1 else -1
        label = runs[k - 1][0] if left >= right else runs[k + 1][0]
        _, s, e = runs[k]
        vals[s:e + 1] = label
    return pd.Series(vals, index=ph.index)


def segments(df):
    """List of phase segments with duration, price move, and avg vol."""
    out = []
    for phase, s, e in _runs(df["phase"]):
        seg = df.iloc[s:e + 1]
        out.append({
            "phase": phase,
            "start": seg.index[0].date(),
            "end": seg.index[-1].date(),
            "days": len(seg),
            "px_start": round(float(seg["close"].iloc[0]), 2),
            "px_end": round(float(seg["close"].iloc[-1]), 2),
            "ret_pct": round((float(seg["close"].iloc[-1]) / float(seg["close"].iloc[0]) - 1) * 100, 1),
            "avg_vol": round(float(seg["vol"].mean()) * 100, 1),
        })
    return out


def summary(df, label=""):
    segs = segments(df)
    trading_yr = 252.0
    lines = [f"=== {label} ===" if label else "==="]
    cur = segs[-1]
    lines.append(f"CURRENT: {cur['phase']}  ·  {cur['days']} sessions "
                 f"(~{cur['days']/trading_yr:.1f}y) in phase  ·  "
                 f"drawdown from 3y high {df['dd'].iloc[-1]*100:+.1f}%")
    lines.append(f"history {df.index[0].date()} -> {df.index[-1].date()}  "
                 f"({len(segs)} segments)")
    lines.append(f"{'phase':<13}{'n':>3}{'median mo':>11}{'median move':>13}{'avg vol':>9}")
    for p in PHASES:
        s = [x for x in segs if x["phase"] == p]
        if not s:
            lines.append(f"{p:<13}{0:>3}{'--':>11}{'--':>13}{'--':>9}")
            continue
        med_mo = np.median([x["days"] for x in s]) / trading_yr * 12
        med_move = np.median([x["ret_pct"] for x in s])
        med_vol = np.median([x["avg_vol"] for x in s])
        lines.append(f"{p:<13}{len(s):>3}{med_mo:>10.1f}m{med_move:>+12.1f}%{med_vol:>8.0f}%")
    return "\n".join(lines), segs


P2I = {ACCUM: 0, MARKUP: 1, DIST: 2, MARKDOWN: 3}


def _basket_rows():
    """Ordered (id, label) for every basket, following the rail order in
    export.themes, so the heatmap reads top-to-bottom like the site's rail."""
    try:
        from export.themes import GROUPS as _G
        from ingestion.baskets import BASKETS
        return [(sid, lbl) for _, items in _G for sid, lbl in items if sid in BASKETS]
    except Exception:
        from ingestion.baskets import BASKETS
        return [(k, k.upper()) for k in BASKETS]


def phase_matrix(views):
    """Classify each view and lay the phases on a shared calendar.

    Returns (labels, cal, mat) where mat[i, t] is the phase-index (0..3) of
    row i on calendar day t, or NaN before that series exists."""
    frames, kept = {}, []
    for sid, lbl in views:
        try:
            ph = classify(load(sid))["phase"]
        except Exception:
            continue
        if len(ph):
            frames[sid] = ph
            kept.append((sid, lbl))
    cal = pd.DatetimeIndex(sorted(set().union(*[set(p.index) for p in frames.values()])))
    mat = np.full((len(kept), len(cal)), np.nan)
    for i, (sid, _) in enumerate(kept):
        s = frames[sid].reindex(cal)
        mat[i] = [P2I[v] if v in P2I else np.nan for v in s.to_numpy(dtype=object)]
    return [lbl for _, lbl in kept], cal, mat


def _plot(subjects, out_path, heatmap_rows=None):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from matplotlib.colors import ListedColormap
    from matplotlib.patches import Patch

    if heatmap_rows is None:
        heatmap_rows = _basket_rows()
    labels, cal, mat = phase_matrix(heatmap_rows)

    nd = len(subjects)
    nrows = len(labels)
    fig = plt.figure(figsize=(13, 4.4 * nd + max(3.2, 0.24 * nrows) + 0.6))
    fig.patch.set_facecolor("#fafafa")
    gs = fig.add_gridspec(nd + 1, 1, height_ratios=[4.4] * nd + [max(3.2, 0.24 * nrows)],
                          hspace=0.28)

    x0, x1 = cal[0], cal[-1]
    detail_axes = [fig.add_subplot(gs[k, 0]) for k in range(nd)]
    for ax, (label, df) in zip(detail_axes, subjects):
        ax.set_facecolor("#fafafa")
        ax.set_yscale("log")
        for phase, s, e in _runs(df["phase"]):
            ax.axvspan(df.index[s], df.index[min(e + 1, len(df) - 1)],
                       color=COLORS[phase], alpha=0.22, linewidth=0)
        ax.plot(df.index, df["close"], color="#141414", linewidth=1.0)
        ax.plot(df.index, df["ma"], color="#141414", linewidth=0.6, alpha=0.35, linestyle="--")
        cur = df["phase"].iloc[-1]
        ax.set_title(f"{label}   —   now: {cur}", loc="left",
                     fontsize=13, color="#141414", fontweight="bold", pad=8)
        ax.grid(True, which="major", color="#141414", alpha=0.06)
        ax.set_xlim(x0, x1)
        for sp in ax.spines.values():
            sp.set_color("#141414"); sp.set_alpha(0.15)
        ax.tick_params(colors="#141414", labelsize=9)
    detail_axes[0].legend(
        handles=[Patch(facecolor=COLORS[p], alpha=0.5, label=p) for p in PHASES],
        loc="upper left", frameon=False, fontsize=9, ncol=4)

    # --- phase heatmap: one row per theme, color = phase on that day ---
    hx = fig.add_subplot(gs[nd, 0])
    hx.set_facecolor("#fafafa")
    cmap = ListedColormap([COLORS[ACCUM], COLORS[MARKUP], COLORS[DIST], COLORS[MARKDOWN]])
    cmap.set_bad("#fafafa")
    xn = mdates.date2num(cal.to_pydatetime())
    hx.imshow(np.ma.masked_invalid(mat), aspect="auto", origin="upper", cmap=cmap,
              vmin=-0.5, vmax=3.5, interpolation="nearest",
              extent=[xn[0], xn[-1], nrows, 0])
    hx.xaxis_date()
    hx.set_xlim(mdates.date2num(x0.to_pydatetime()), mdates.date2num(x1.to_pydatetime()))
    hx.set_yticks(np.arange(nrows) + 0.5)
    hx.set_yticklabels(labels, fontsize=7.5, color="#141414")
    hx.tick_params(colors="#141414", labelsize=8, length=0)
    hx.set_title("Theme phase map — every basket, current phase at the right edge",
                 loc="left", fontsize=12, color="#141414", fontweight="bold", pad=8)
    for sp in hx.spines.values():
        sp.set_color("#141414"); sp.set_alpha(0.15)
    hx.hlines(np.arange(1, nrows), xn[0], xn[-1], color="#fafafa", linewidth=0.6)

    fig.suptitle("Market-cycle phases (Wyckoff 4-phase, trailing-only classifier)",
                 x=0.09, y=0.997, ha="left", fontsize=15, color="#141414", fontweight="bold")
    fig.tight_layout(rect=[0, 0, 1, 0.985])
    fig.savefig(out_path, dpi=130, facecolor="#fafafa")
    print(f"wrote {out_path}  ({nrows} themes in heatmap)")


def load(view):
    conn = db.connect()
    d = conn.execute(f'select date, close from "{view}" order by date').fetchdf()
    s = pd.Series(d["close"].values, index=pd.to_datetime(d["date"]))
    return s[s > 0].dropna()


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--") and not a.endswith(".png")]
    do_plot = "--plot" in sys.argv
    subjects = args or ["smh", "gpu"]
    loaded = []
    for v in subjects:
        df = classify(load(v))
        txt, _ = summary(df, v.upper())
        print(txt + "\n")
        loaded.append((v.upper(), df))
    if do_plot:
        out = next((a for a in sys.argv[1:] if a.endswith(".png")), "cycles.png")
        _plot(loaded, out)


if __name__ == "__main__":
    main()
