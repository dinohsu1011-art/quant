import unittest
from pathlib import Path

from ingestion.baskets import BASKETS
from export.leaders import THEME_LABEL
from export.themes import GROUPS


ROOT = Path(__file__).parent.parent


class BiotechThemeTests(unittest.TestCase):
    def test_basket_has_commercial_and_platform_biotech(self):
        members = set(BASKETS["biotech"])
        self.assertTrue({"AMGN", "GILD", "VRTX", "REGN", "ALNY"}.issubset(members))
        self.assertTrue({"MRNA", "CRSP", "BEAM", "NTLA", "RXRX"}.issubset(members))
        self.assertEqual(len(members), 20)

    def test_theme_is_exposed_everywhere_without_reordering_existing_groups(self):
        groups = dict(GROUPS)
        self.assertIn(("biotech", "Biotechnology"), groups["Healthcare — baskets"])
        self.assertEqual(THEME_LABEL["biotech"], "Biotechnology")
        cube = (ROOT / "export" / "cube.py").read_text()
        self.assertIn('{"id": "biotech", "label": "Biotechnology (basket)"}', cube)


if __name__ == "__main__":
    unittest.main()
