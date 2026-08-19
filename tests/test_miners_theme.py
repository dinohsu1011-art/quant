import unittest

from config import file_stem
from ingestion.baskets import BASKETS


class MinersThemeTests(unittest.TestCase):
    def test_requested_names_and_each_metal_group_are_present(self):
        miners = set(BASKETS["miners"])
        self.assertTrue({"HL", "AG", "RGLD"}.issubset(miners))
        self.assertTrue({"FCX", "SCCO", "HBM", "ERO"}.issubset(miners))
        self.assertTrue({"NEM", "B", "AEM", "KGC"}.issubset(miners))
        self.assertTrue({"PAAS", "CDE", "EXK"}.issubset(miners))
        self.assertTrue({"RGLD", "FNV", "WPM"}.issubset(miners))

    def test_barrick_does_not_collide_with_gold_futures(self):
        self.assertEqual(file_stem("B"), "B")
        self.assertEqual(file_stem("GC=F"), "GOLD")
        self.assertNotEqual(file_stem("B"), file_stem("GC=F"))


if __name__ == "__main__":
    unittest.main()
