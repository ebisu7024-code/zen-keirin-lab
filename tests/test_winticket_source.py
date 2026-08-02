import unittest
from urllib.error import HTTPError

from winticket_source import (
    extract_source_race_id,
    parse_winticket_race_metadata,
    parse_winticket_racecard_html,
    parse_winticket_racecard_index_html,
    parse_winticket_result_html,
    resolve_race_urls,
)


RACECARD_FIXTURE = """
枠 車
選手名
1
1
戸邉捺希 埼玉 A1 27歳 117期
単穴 84.86
1
4
8 逃
25.0
41.6 3.92 先行基本。
2
2
岡崎祥伍 岐阜 A2 37歳 97期
81.08
0
0
0 追
8.3
16.6 3.92 谷本君。
3
3
谷口友真 大阪 A1 37歳 109期
本命 89.85
3
3
1 逃
37.0
48.1 3.92 自力。
4
4
四宮哲郎 京都 A1 53歳 71期
連下 82.71
0
0
0 追
23.7
33.3 3.92 谷口君。
5
5
若林耕司 群馬 A2 45歳 87期
81.11
0
0
0 追
11.5
19.2 3.85 関東３番手。
6
6
谷本奨輝 岐阜 A2 31歳 107期
79.10
11
6
5 両
76.6
83.3 3.93 自力自在。
7
7
梅山英樹 群馬 A1 54歳 72期
対抗 85.48
2
0
0 追
37.0
44.4 3.92 戸邉君。
並び予想
1
7
5
区切り
6
2
区切り
3
4
結果
"""


RESULT_FIXTURE = """
並び予想
1
7
5
区切り
6
2
区切り
3
4
着順 ビデオ 映像を観る
着 車 選手名 着差 上り 決 SB
1
6
谷本奨輝 岐阜 A2 31歳 107期
11.6 捲 B
2
3
谷口友真 大阪 A1 37歳 109期
1車輪 11.5 逃
3
1
戸邉捺希 埼玉 A1 27歳 117期
3/4車身 11.4 S
払戻金
賭け式 払戻金 人気
2車複 3=6 610 円(4)
2車単 6-3 1,440 円(7)
3連複 1=3=6 930 円(4)
3連単 6-3-1 7,170 円(32)
ワイド 1=3 370 円(6)
1=6 420 円(7)
3=6 240 円(3)
## 松阪競輪 F2 初日 8R 結果
"""


RACECARD_INDEX_FIXTURE = """
<h1>2026年7月26日 競輪出走表</h1>
<h2>2026年7月26日 出走表一覧</h2>
<a href="/keirin/wakayama">和歌山競輪</a>
<p>7月24日 〜 7月26日</p>
<p>ＲＣケイリン賞パチ７カップ</p>
<a href="/keirin/wakayama/racecard/2026072455/3/1">1R</a>
<a href="/keirin/wakayama/racecard/2026072455/3/2">2R A級チ一般</a>
<a href="/keirin/kokura">小倉競輪</a>
<p>7月24日 〜 7月26日</p>
<p>門司港地ビール杯×こがね市場杯</p>
<a href="/keirin/kokura/racecard/2026072481/3/11">11R</a>
"""


RACECARD_INDEX_SPLIT_VENUE_FIXTURE = """
<h1>2026年7月26日 競輪出走表</h1>
<h2>出走表一覧</h2>
<a href="/keirin/wakayama/racecard">和歌山<span>競輪</span></a>
<span>F2</span>
<span>ガールズ</span>
<span>7月24日</span><span>〜</span><span>7月26日</span>
<span>ＲＣケイリン賞パチ７カップ</span>
<a href="/keirin/wakayama/racecard/2026072455/3/1">1R</a>
<a href="/keirin/wakayama/racecard/2026072455/3/11">11R</a>
"""


class WinticketSourceTest(unittest.TestCase):
    def test_parse_racecard_riders_and_lines(self):
        line_summary, riders = parse_winticket_racecard_html(RACECARD_FIXTURE)
        self.assertEqual(line_summary, "1-7-5 / 6-2 / 3-4")
        self.assertEqual(len(riders), 7)
        first = riders[0]
        self.assertEqual(first.rider_name, "戸邉捺希")
        self.assertEqual(first.rider_comment, "先行基本。")
        self.assertEqual(first.line_name, "ライン1")
        self.assertEqual(first.line_position, "先頭")
        self.assertEqual(riders[5].line_name, "ライン2")
        self.assertEqual(riders[5].line_position, "先頭")

    def test_parse_racecard_accepts_ss_class_rider(self):
        fixture = """
        枠 車
        選手名
        1
        1
        郡司浩平 神奈川 SS 34歳 99期
        本命 120.50
        4
        3
        2 両
        60.0
        75.0 3.92 自力。
        2
        7
        嶋津拓弥 神奈川 S1 40歳 103期
        112.96
        0
        0
        0 追
        37.0
        44.4 3.92 郡司君。
        並び予想
        1
        7
        結果
        """
        line_summary, riders = parse_winticket_racecard_html(fixture)
        self.assertEqual(line_summary, "1-7")
        self.assertEqual([rider.car_no for rider in riders], [1, 7])
        self.assertEqual(riders[0].rider_name, "郡司浩平")
        self.assertEqual(riders[0].rider_class, "SS")
        self.assertEqual(riders[0].line_name, "ライン1")
        self.assertEqual(riders[0].line_position, "先頭")

    def test_parse_result_rows_and_payouts(self):
        line_summary, rows, payouts = parse_winticket_result_html(RESULT_FIXTURE)
        self.assertEqual(line_summary, "1-7-5 / 6-2 / 3-4")
        self.assertEqual([row.car_no for row in rows], [6, 3, 1])
        self.assertEqual(rows[0].decision, "捲")
        self.assertEqual(rows[0].sb, "B")
        self.assertEqual(payouts[3].ticket_type, "3連単")
        self.assertEqual(payouts[3].combination, "6-3-1")
        self.assertEqual(payouts[3].payout, 7170)
        self.assertEqual(payouts[-1].ticket_type, "ワイド")

    def test_resolve_final_day_uses_cup_start_date(self):
        found_url = "https://www.winticket.jp/keirin/matsudo/racecard/2026071931/3/1"

        def fake_fetcher(url):
            if url == "https://www.winticket.jp/keirin/racecard/20260721":
                return "<html></html>"
            if url == found_url:
                return "松戸 出走表"
            raise HTTPError(url, 404, "not found", {}, None)

        racecard_url, result_url = resolve_race_urls(
            "2026-07-21",
            1,
            "2026-07-21_31_01",
            "松戸",
            "F2 最終日 1R",
            fetcher=fake_fetcher,
        )
        self.assertEqual(racecard_url, found_url)
        self.assertEqual(result_url, found_url.replace("/racecard/", "/raceresult/"))

    def test_extract_source_race_id_from_winticket_url(self):
        self.assertEqual(extract_source_race_id("2026-07-23_85_01"), "2026-07-23_85_01")
        self.assertEqual(
            extract_source_race_id("https://www.winticket.jp/keirin/sasebo/racecard/2026072285/2/1"),
            "2026-07-23_85_01",
        )
        self.assertEqual(
            extract_source_race_id("https://www.winticket.jp/keirin/sasebo/raceresult/2026072285/2/12"),
            "2026-07-23_85_12",
        )

    def test_parse_racecard_index_listings(self):
        listings = parse_winticket_racecard_index_html(RACECARD_INDEX_FIXTURE, "2026-07-26")
        self.assertEqual(len(listings), 3)
        self.assertEqual(listings[0].venue, "和歌山")
        self.assertEqual(listings[0].race_title, "ＲＣケイリン賞パチ７カップ")
        self.assertEqual(listings[0].race_no, 1)
        self.assertEqual(listings[0].source_race_id, "2026-07-26_55_01")
        self.assertEqual(listings[1].grade, "A級チ一般")
        self.assertEqual(listings[2].venue, "小倉")
        self.assertEqual(listings[2].source_race_id, "2026-07-26_81_11")

    def test_parse_racecard_index_split_venue_tokens(self):
        listings = parse_winticket_racecard_index_html(RACECARD_INDEX_SPLIT_VENUE_FIXTURE, "2026-07-26")
        self.assertEqual(len(listings), 2)
        self.assertEqual(listings[0].venue, "和歌山")
        self.assertEqual(listings[0].race_title, "ＲＣケイリン賞パチ７カップ")
        self.assertEqual(listings[0].grade, "F2")
        self.assertEqual(listings[1].source_race_id, "2026-07-26_55_11")

    def test_parse_race_metadata(self):
        metadata = parse_winticket_race_metadata(
            """
            ＲＣケイリン賞パチ７カップ
            A級チ一般
            発走 10:59 締切 10:54
            2026年7月26日 1,625m (4周) 曇34.0℃北北西1.0m/s
            """
        )
        self.assertEqual(metadata["grade"], "A級チ一般")
        self.assertEqual(metadata["distance"], 1625)
        self.assertEqual(metadata["weather"], "曇")
        self.assertEqual(metadata["wind"], 1.0)
        self.assertEqual(metadata["start_time"], "10:59")
        self.assertEqual(metadata["close_time"], "10:54")


if __name__ == "__main__":
    unittest.main()
