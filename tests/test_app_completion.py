import tempfile
import unittest
from pathlib import Path

import pandas as pd

import app
from winticket_source import WinticketResultRow


class AppCompletionTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_data_dir = app.DATA_DIR
        self.original_db_path = app.DB_PATH
        app.DATA_DIR = Path(self.temp_dir.name)
        app.DB_PATH = app.DATA_DIR / "test.sqlite3"
        app.init_db()

    def tearDown(self):
        app.DATA_DIR = self.original_data_dir
        app.DB_PATH = self.original_db_path
        self.temp_dir.cleanup()

    def test_upsert_race_materializes_manual_line_summary(self):
        race_id = app.upsert_race(
            None,
            {
                "race_date": "2026-07-23",
                "venue": "小田原",
                "race_no": 1,
                "grade": "F2",
                "distance": 1625,
                "weather": "",
                "wind": 0.0,
                "amount_unit": "円",
                "status": "予想中",
                "race_title": "F2 初日 1R",
                "source_ref": "",
                "line_summary": "1-2 / 3",
                "race_memo": "",
            },
        )

        lines = app.fetch_lines(race_id)
        self.assertEqual(lines["car_numbers"].tolist(), ["1-2", "3"])
        self.assertEqual(lines["auto_status"].tolist(), ["未評価", "未評価"])

    def test_winticket_candidates_include_missing_riders_or_lines(self):
        races = pd.DataFrame(
            [
                {"id": 1, "race_date": "2026-07-23", "source_race_id": "2026-07-23_36_01", "rider_count": 0, "line_count": 0},
                {"id": 2, "race_date": "2026-07-23", "source_race_id": "2026-07-23_36_02", "rider_count": 7, "line_count": 0},
                {"id": 3, "race_date": "2026-07-23", "source_race_id": "2026-07-23_36_03", "rider_count": 7, "line_count": 3},
                {"id": 4, "race_date": "2026-07-23", "source_race_id": "", "rider_count": 0, "line_count": 0},
            ]
        )

        candidates = app.winticket_sync_candidates(races, limit=10)
        self.assertEqual(candidates["id"].tolist(), [2, 1])

    def test_result_rows_allow_same_finish_order_for_dead_heat(self):
        race_id = app.upsert_race(
            None,
            {
                "race_date": "2026-07-23",
                "venue": "富山",
                "race_no": 10,
                "grade": "F1",
                "distance": 2015,
                "weather": "",
                "wind": 0.0,
                "amount_unit": "円",
                "status": "結果入力済み",
                "race_title": "F1 最終日 10R",
                "source_ref": "",
                "line_summary": "",
                "race_memo": "",
            },
        )

        with app.get_conn() as conn:
            app.save_result_rows(
                conn,
                race_id,
                (
                    WinticketResultRow(1, 5, "田中大我"),
                    WinticketResultRow(2, 1, "畑段嵐士"),
                    WinticketResultRow(3, 6, "坂上樹大"),
                    WinticketResultRow(3, 7, "山下渡"),
                ),
            )

        rows = app.fetch_result_rows(race_id)
        self.assertEqual(rows["finish_order"].tolist(), [1, 2, 3, 3])
        self.assertEqual(rows["car_no"].tolist(), [5, 1, 6, 7])


if __name__ == "__main__":
    unittest.main()
