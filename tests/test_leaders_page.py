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
        self.assertIn("earlier start", self.script)
        self.assertIn("later start", self.script)

    def test_summit_route_depends_on_cohort_and_can_be_redrawn(self):
        self.assertIn("cohort.map(r=>r.t).join(',')", self.script)
        self.assertIn("st.route", self.script)
        self.assertIn('id="reroute"', self.html)


if __name__ == "__main__":
    unittest.main()
