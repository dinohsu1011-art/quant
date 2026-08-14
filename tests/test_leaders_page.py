import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "web" / "market-lab-leaders.html"


class LeadersPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = PAGE.read_text()
        start = cls.html.rindex("<script>") + len("<script>")
        end = cls.html.index("</script>", start)
        cls.script = cls.html[start:end]

    def test_inline_javascript_parses(self):
        with tempfile.NamedTemporaryFile("w", suffix=".js") as source:
            source.write(self.script)
            source.flush()
            result = subprocess.run(
                ["node", "--check", source.name],
                capture_output=True,
                text=True,
            )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_table_is_default_and_both_alternate_views_exist(self):
        self.assertIn("view:'table'", self.script)
        self.assertIn("['table','Table']", self.script)
        self.assertIn("['loom','Loom']", self.script)
        self.assertIn("['summit','Summit']", self.script)
        self.assertIn('id="viz"', self.html)

    def test_loom_is_limited_to_two_windows(self):
        self.assertIn("if (st.windows.length > 2) st.windows.shift()", self.script)
        self.assertIn("if (wins.length !== 2)", self.script)
        self.assertIn("const leftWin = newerWin, rightWin = olderWin", self.script)
        self.assertIn("newer", self.script)
        self.assertIn("older", self.script)

    def test_summit_route_depends_on_cohort_and_can_be_redrawn(self):
        self.assertIn("cohort.map(r=>r.t).join(',')", self.script)
        self.assertIn("st.route", self.script)
        self.assertIn('id="reroute"', self.html)
        self.assertIn("drawPennant", self.script)
        self.assertIn("Dashed switchbacks", self.script)
        self.assertNotIn("Short downhill hachures", self.script)
        self.assertNotIn("for (let i=0;i<115;i++)", self.script)
        self.assertIn("SECTORS · pennant notch", self.script)
        self.assertNotIn("Median baseline", self.script)
        self.assertIn("const sub=st.rank==='sigma'", self.script)
        self.assertIn("Every flag trails left", self.script)
        self.assertNotIn("const keyItems", self.script)
        self.assertNotIn("Rank + ticker", self.script)
        self.assertNotIn("p.x>plotLeft+span*.63", self.script)
        self.assertNotIn("branchEnds", self.script)

    def test_summit_replaces_top_composition_with_clickable_sector_theme_table(self):
        self.assertIn(".comp[hidden]", self.html)
        self.assertIn("document.querySelector('.comp').hidden=st.view==='summit'", self.script)
        self.assertIn('<div class="summit-comp" id="summit-comp" hidden>', self.html)
        self.assertIn("summitComp.hidden=st.view!=='summit'", self.script)
        self.assertIn("drawSummitComp(secs,thms,medianLabel,cohort.length)", self.script)
        self.assertIn("SECTORS · pennant notch", self.script)
        self.assertIn("st.theme=st.theme===row.dataset.key ? '' : row.dataset.key", self.script)

    def test_sigma_rank_uses_same_window_historical_move_distribution(self):
        self.assertIn("['sigma','Sigma']", self.script)
        self.assertIn("r.z?.[win]", self.script)
        self.assertIn("st.sortK = st.rank === 'sigma' ? 'sigma'", self.script)
        self.assertIn("Top '+cohort.length+' by sigma", self.script)
        exporter = (ROOT / "export" / "leaders.py").read_text()
        self.assertIn("def _sigma(c, k, current):", exporter)
        self.assertIn("Use every rolling k-session move", exporter)
        self.assertNotIn("end = end[-756:]", exporter)
        self.assertIn("(current / 100) - mean", exporter)
        self.assertIn('"z": z', exporter)


if __name__ == "__main__":
    unittest.main()
