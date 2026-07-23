import unittest

from keirin_logic import (
    ability_score,
    blended_score,
    format_combination_with_names,
    hit_rate,
    human_score,
    judge_ticket_hit,
    line_function_status,
    line_position_map,
    normalize_result,
    parse_line_summary,
    parse_numbers,
    recovery_rate,
)


class KeirinLogicTest(unittest.TestCase):
    def test_parse_numbers_accepts_common_separators(self):
        self.assertEqual(parse_numbers("1-3-7"), (1, 3, 7))
        self.assertEqual(parse_numbers("1=3=7"), (1, 3, 7))
        self.assertEqual(parse_numbers("1, 3, 7"), (1, 3, 7))

    def test_judge_three_exacta(self):
        result = normalize_result(1, 3, 7)
        self.assertTrue(judge_ticket_hit("3連単", "1-3-7", result))
        self.assertFalse(judge_ticket_hit("3連単", "1-7-3", result))

    def test_judge_three_quinella(self):
        result = normalize_result(1, 3, 7)
        self.assertTrue(judge_ticket_hit("3連複", "7-1-3", result))
        self.assertFalse(judge_ticket_hit("3連複", "1-3-5", result))

    def test_judge_wide(self):
        result = normalize_result(1, 3, 7)
        self.assertTrue(judge_ticket_hit("ワイド", "7-1", result))
        self.assertFalse(judge_ticket_hit("ワイド", "7-5", result))

    def test_scores(self):
        self.assertEqual(ability_score(80, 70), 76.0)
        self.assertEqual(human_score(80, 60), 71.0)
        self.assertEqual(blended_score(80, 70, 80, 60), 74.8)

    def test_rates(self):
        self.assertEqual(recovery_rate(1000, 1250), 125.0)
        self.assertEqual(hit_rate(2, 5), 40.0)

    def test_line_summary_and_status(self):
        lines = parse_line_summary("1-7-5 / 6-2 / 3-4")
        self.assertEqual(lines, ((1, 7, 5), (6, 2), (3, 4)))
        self.assertEqual(line_position_map(lines)[7], ("ライン1", "番手"))
        self.assertEqual(line_function_status((1, 7, 5), normalize_result(6, 3, 1)), "半機能")
        self.assertEqual(line_function_status((6, 2), normalize_result(6, 3, 1)), "半機能")
        self.assertEqual(line_function_status((3, 4), normalize_result(6, 3, 1)), "半機能")
        self.assertEqual(line_function_status((8,), normalize_result(6, 3, 1)), "単騎")

    def test_format_combination_with_names(self):
        names = {6: "谷本奨輝", 2: "岡崎祥伍"}
        self.assertEqual(format_combination_with_names("6-2-3", names), "6 谷本奨輝 - 2 岡崎祥伍 - 3")


if __name__ == "__main__":
    unittest.main()
