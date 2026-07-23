import unittest

from venue_features import get_venue_feature, venue_feature_rows, venue_feature_url


class VenueFeaturesTest(unittest.TestCase):
    def test_get_known_venue_feature(self):
        feature = get_venue_feature("松阪")
        self.assertEqual(feature["track_m"], 400)
        self.assertEqual(feature["straight_m"], 61.5)
        self.assertIn("捲り", feature["bias"])

    def test_unknown_venue_row_is_safe(self):
        rows = venue_feature_rows(["未登録場"])
        self.assertEqual(rows[0]["傾向"], "未登録")

    def test_venue_url(self):
        self.assertEqual(venue_feature_url("いわき平"), "https://www.winticket.jp/keirin/iwakidaira/")


if __name__ == "__main__":
    unittest.main()
