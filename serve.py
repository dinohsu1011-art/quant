"""
Optional local backend for the Trader Profile interactive panel.

Serves the reports folder (so the HTML loads same-origin) AND exposes the live
event_study engine over HTTP, so the panel can run arbitrary queries — any of
the 523 tickers, any threshold/condition, and the full occurrence list — beyond
the pre-computed cube. Pure stdlib, no extra dependencies.

    python serve.py                 # serves ~/Desktop/.../reports on :8765
    python serve.py 8800 /some/dir

Then open  http://localhost:8765/trader-profile.html  — the panel auto-detects
the server (via /api/health) and switches from "Offline (cube)" to "Live".

Endpoints:
    GET /api/health
    GET /api/event?subject=spy&threshold=-0.03&day=fri&when=vix>30&horizon=1
        (or worst_n=20 instead of threshold)  ->  {summary, bins, rows}
"""
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote

sys.path.insert(0, str(Path(__file__).parent))
import db
from analysis.events import event_study, summarize_event, MON, TUE, WED, THU, FRI
from export.cube import EDGES, BIN_LABELS

import numpy as np
import pandas as pd

DEFAULT_DIR = Path.home() / "Desktop/Obsidian/trading-brain/reports"
_DAY = {"any": None, "": None, "mon": MON, "tue": TUE, "wed": WED, "thu": THU, "fri": FRI}
CONN = None
ROOT = None


def _run_event(q):
    """q = dict of single-valued query params -> result dict."""
    subject = q.get("subject", "spy")
    kw = {"horizon": int(q.get("horizon", 1))}
    d = q.get("day", "any").lower()
    kw["day"] = _DAY.get(d, int(d) if d.isdigit() else None)
    if q.get("streak_n"):
        kw["streak"] = int(q["streak_n"])
        kw["streak_dir"] = q.get("streak_dir", "down")
        kw["streak_gap"] = q.get("streak_gap") or None
    elif q.get("worst_n"):
        kw["worst_n"] = int(q["worst_n"])
    elif q.get("threshold") not in (None, ""):
        kw["threshold"] = float(q["threshold"])
    if q.get("when"):
        kw["when"] = unquote(q["when"])
    if q.get("price"):
        kw["price"] = q["price"]
    if q.get("measure_field"):
        kw["measure_field"] = q["measure_field"]

    df = event_study(CONN, subject, **kw)
    out = df["outcome_ret"].dropna().to_numpy("float64") * 100.0
    st = summarize_event(df) if len(out) else {
        "n": 0, "win_rate": float("nan"), "mean_pct": float("nan"),
        "t_stat": float("nan"), "ci_95_lo": float("nan"), "ci_95_hi": float("nan")}
    counts = [int(x) for x in np.histogram(out, bins=EDGES)[0]] if len(out) else [0] * len(BIN_LABELS)

    # pd.isna handles NaN/NaT/pd.NA — pending outcomes (trigger within `horizon`
    # sessions of the data edge) arrive as pandas NA, where `x != x` raises.
    def _v(x, f):
        return None if pd.isna(x) else f(x)

    rows = []
    for r in df.itertuples():
        rows.append({
            "trigger_date": str(r.trigger_date)[:10],
            "trigger_dow": _v(r.trigger_dow, int),
            "trigger_ret": _v(r.trigger_ret, lambda y: round(y * 100, 2)),
            "outcome_date": _v(r.outcome_date, lambda y: str(y)[:10]),
            "outcome_dow": _v(r.outcome_dow, int),
            "outcome_ret": _v(r.outcome_ret, lambda y: round(y * 100, 2)),
        })

    def f(x):
        return None if (x is None or (isinstance(x, float) and x != x)) else round(float(x), 3)

    return {
        "summary": {"n": int(st["n"]), "up_pct": f(st["win_rate"] * 100 if st["n"] else float("nan")),
                    "mean_pct": f(st["mean_pct"]), "t": f(st["t_stat"]),
                    "ci_lo": f(st["ci_95_lo"]), "ci_hi": f(st["ci_95_hi"])},
        "bins": {"labels": BIN_LABELS, "counts": counts},
        "rows": rows[:1500],
    }


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/api/health":
            n = CONN.execute("select count(*) from (select table_name from information_schema.tables)").fetchone()[0]
            as_of = CONN.execute("select max(date) from spy").fetchone()[0]
            return self._send(200, json.dumps({"ok": True, "tickers": n, "as_of": str(as_of)}))
        if u.path == "/api/event":
            q = {k: v[0] for k, v in parse_qs(u.query, keep_blank_values=True).items()}
            try:
                return self._send(200, json.dumps(_run_event(q)))
            except Exception as e:
                return self._send(400, json.dumps({"error": str(e)}))
        # static file fallback (serve the reports dir)
        rel = unquote(u.path.lstrip("/")) or "trader-profile.html"
        fp = (ROOT / rel).resolve()
        if ROOT in fp.parents and fp.is_file():
            ctype = "text/html" if fp.suffix == ".html" else (
                "application/javascript" if fp.suffix == ".js" else "application/octet-stream")
            return self._send(200, fp.read_bytes(), ctype)
        return self._send(404, json.dumps({"error": "not found"}))

    def log_message(self, *a):
        pass  # quiet


def main():
    global CONN, ROOT
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    ROOT = (Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_DIR).resolve()
    CONN = db.connect()
    print(f"Serving {ROOT}\n  → http://localhost:{port}/trader-profile.html")
    print(f"  → http://localhost:{port}/api/health")
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
