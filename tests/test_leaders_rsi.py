"""RSI on the Leaders screen: the number itself, and the promise around it.

The arithmetic is checked against Wilder's own recursive definition rather than
against the pandas call the exporter happens to use, so a change to the
implementation has to keep agreeing with the thing it claims to be.

The page assertions exist for a different reason. RSI tested badly on this
database — the middle of the range was a coin flip and the tails were thin — so
it ships as a readout with the finding written under the table. That disclosure
is the feature. A later edit that quietly drops it would turn the column into
the score the evidence says it is not, which is exactly the failure worth
pinning down in a test.
"""
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from export.leaders import RSI_PERIODS, _rsi  # noqa: E402

PAGE = ROOT / "web" / "market-lab-leaders.html"


def wilder(c, n):
    """RSI the way Wilder wrote it in 1978: a simple mean to seed, then a
    recursive smoothing of gains and losses. Deliberately a plain loop."""
    d = np.diff(c)
    up = np.where(d > 0, d, 0.0)
    dn = np.where(d < 0, -d, 0.0)
    au, ad = up[:n].mean(), dn[:n].mean()
    for i in range(n, len(d)):
        au = (au * (n - 1) + up[i]) / n
        ad = (ad * (n - 1) + dn[i]) / n
    return 100.0 if ad == 0 else 100 - 100 / (1 + au / ad)


class RsiMathTests(unittest.TestCase):
    def series(self, seed, n=400):
        rng = np.random.default_rng(seed)
        return 100 * np.exp(np.cumsum(rng.normal(0, 0.015, n)))

    def test_matches_wilders_recursive_definition(self):
        for seed in range(6):
            c = self.series(seed)
            for n in RSI_PERIODS:
                self.assertAlmostEqual(_rsi(c, n), round(wilder(c, n), 1), places=1,
                                       msg=f"seed {seed}, n {n}")

    def test_monotone_series_pin_the_ends(self):
        self.assertEqual(_rsi(np.arange(1, 201, dtype=float), 14), 100.0)
        self.assertEqual(_rsi(np.arange(200, 0, -1, dtype=float), 14), 0.0)

    def test_history_shorter_than_the_burn_in_returns_none(self):
        c = self.series(0, n=60)
        self.assertIsNone(_rsi(c, 21))     # needs 105
        self.assertIsNotNone(_rsi(c, 7))   # needs 35

    def test_stays_inside_the_range(self):
        for seed in range(20):
            v = _rsi(self.series(seed), 14)
            self.assertTrue(0 <= v <= 100, v)


class RsiPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = PAGE.read_text()
        start = cls.html.rindex("<script>") + len("<script>")
        cls.script = cls.html[start:cls.html.index("</script>", start)]

    def test_lookback_is_selectable_and_named_in_the_header(self):
        self.assertIn('id="rsis"', self.html)
        self.assertIn("RSIN.map(n => [n, String(n)])", self.script)
        self.assertIn("l:'RSI '+st.rsiN", self.script)

    def test_rsi_ranks_the_most_oversold_first(self):
        self.assertIn("['rsi','RSI']", self.script)
        self.assertIn("st.rank === 'rsi' ? rsiOf(r)", self.script)
        self.assertIn("(st.rank === 'worst' || st.rank === 'rsi') ? 1 : -1", self.script)
        self.assertIn("const dir = st.rank === 'rsi' ? -st.dir : st.dir", self.script)
        self.assertIn("most oversold", self.script)

    def test_the_page_says_it_is_a_readout_and_not_a_signal(self):
        self.assertIn("readout of where a name sits in its own recent range", self.script)
        self.assertIn("inside a coin flip", self.script)
        self.assertIn("Use it to decide what to look at, not what to buy.", self.script)

    def test_tails_are_tinted_and_the_middle_is_not(self):
        self.assertIn("const OVERSOLD = 30, OVERBOUGHT = 70;", self.script)
        self.assertIn("v <= OVERSOLD ? ' cold' : v >= OVERBOUGHT ? ' hot' : ''", self.script)
        # cold/hot, never the return palette — the number is not a profit
        self.assertIn("td .rsiv.cold", self.html)
        self.assertNotIn("rsiv.pos", self.html)

    def test_rsi_stays_on_price_under_the_dividend_toggle(self):
        exporter = (ROOT / "export" / "leaders.py").read_text()
        self.assertIn('"rsi": {str(n): _rsi(c, n) for n in RSI_PERIODS}', exporter)
        self.assertIn("volatility, liquidity, RSI —", exporter)
        # applyBasis swaps r/z only; nothing may repoint rsi at adj_close
        self.assertNotIn("rt.rsi", self.script)


if __name__ == "__main__":
    unittest.main()
