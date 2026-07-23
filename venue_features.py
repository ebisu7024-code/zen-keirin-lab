from __future__ import annotations


VENUE_FEATURES = {
    "いわき平": {
        "slug": "iwakidaira",
        "track_m": 400,
        "straight_m": 62.7,
        "bias": "追込・捲り寄り",
        "summary": "直線が長い空中バンク。決め脚ある選手は3、4番手からでも届きやすい。",
        "watch": "冬場の風は先行に重く、風が弱い季節は力勝負になりやすい。",
    },
    "久留米": {
        "slug": "kurume",
        "track_m": 400,
        "straight_m": 50.7,
        "bias": "標準",
        "summary": "クセの少ない400バンク。脚質の有利不利は小さめ。",
        "watch": "3コーナーの癖と不規則な風。捲りは早めに出切りたい。",
    },
    "京王閣": {
        "slug": "keiokaku",
        "track_m": 400,
        "straight_m": 51.5,
        "bias": "標準・内有利",
        "summary": "傾斜差が少なく走りやすいが、風向きの変化が大きい。",
        "watch": "全速で踏むと外へ膨れやすい。併走時はイン側を重視。",
    },
    "伊東": {
        "slug": "ito",
        "track_m": 333,
        "straight_m": 46.6,
        "bias": "捲り・追込寄り",
        "summary": "333ながら直線が長く、ゴール前で追い込みが届きやすい。",
        "watch": "バックからの捲りが決まりやすい。競りはイン有利。",
    },
    "佐世保": {
        "slug": "sasebo",
        "track_m": 400,
        "straight_m": 40.2,
        "bias": "先行寄り",
        "summary": "400バンクでは直線がかなり短く、逃げ・先行タイプが粘りやすい。",
        "watch": "海風とバック向かい風。直線は中から内の伸びを意識。",
    },
    "函館": {
        "slug": "hakodate",
        "track_m": 400,
        "straight_m": 51.3,
        "bias": "標準",
        "summary": "クセの少ない400バンク。脚質差は小さく総合力を見たい。",
        "watch": "1センター側が海に近く、海風の影響を受けることがある。",
    },
    "前橋": {
        "slug": "maebashi",
        "track_m": 335,
        "straight_m": 46.7,
        "bias": "高速・先行寄り",
        "summary": "ドーム型で風がない高速バンク。積極性とスピード持続が重要。",
        "watch": "カントがきつく、競りはイン優勢。前団のかかりを重視。",
    },
    "取手": {
        "slug": "toride",
        "track_m": 400,
        "straight_m": 54.8,
        "bias": "標準",
        "summary": "リニューアル後はクセの少ない走りやすい400バンク。",
        "watch": "冬場の風で重くなる。3、4コーナーの競りは外も残る。",
    },
    "名古屋": {
        "slug": "nagoya",
        "track_m": 400,
        "straight_m": 58.8,
        "bias": "捲り寄り",
        "summary": "カントがきついスピードバンク。どの戦法も力を出しやすい。",
        "watch": "直線も十分あり、遅すぎなければ捲りが前を捕らえやすい。",
    },
    "和歌山": {
        "slug": "wakayama",
        "track_m": 400,
        "straight_m": 59.9,
        "bias": "標準・差し届く",
        "summary": "改修後はクセが少なく、直線も長めで実力を出しやすい。",
        "watch": "直線中に強襲コース。3番手の差し込みに注意。",
    },
    "大宮": {
        "slug": "omiya",
        "track_m": 500,
        "straight_m": 66.7,
        "bias": "追込寄り",
        "summary": "500バンクで直線が長い。先行は苦しく追い込みが届きやすい。",
        "watch": "中から外の伸び。脚があれば4コーナー後方からでも圏内。",
    },
    "奈良": {
        "slug": "nara",
        "track_m": 333,
        "straight_m": 38.0,
        "bias": "先行・ライン寄り",
        "summary": "小さく丸い333バンク。長く踏める先行型とライン決着を重視。",
        "watch": "バック向かい風や渦巻く風。直線で伸びるコースは少なめ。",
    },
    "宇都宮": {
        "slug": "utsunomiya",
        "track_m": 500,
        "straight_m": 63.3,
        "bias": "追込寄り",
        "summary": "500バンクで直線が長く、番手のさらに後ろからの差しもある。",
        "watch": "先行は楽ではない。長い直線で後位の脚を残す形に注意。",
    },
    "富山": {
        "slug": "toyama",
        "track_m": 333,
        "straight_m": 43.0,
        "bias": "先行寄り",
        "summary": "333の小回りで先行有利だが、直線中バンクの伸びもある。",
        "watch": "バック追い風や夏場の追い風条件では先行を高めに見る。",
    },
    "小倉": {
        "slug": "kokura",
        "track_m": 400,
        "straight_m": 56.9,
        "bias": "高速・差し寄り",
        "summary": "ドーム型で風がない高速バンク。力と位置取りが素直に出る。",
        "watch": "直線は中より外が伸びやすい。競りはイン有利。",
    },
    "小松島": {
        "slug": "komatsushima",
        "track_m": 400,
        "straight_m": 55.5,
        "bias": "標準",
        "summary": "500から400へ改修された走りやすいバンク。力勝負になりやすい。",
        "watch": "バック風が重要。冬場の向かい風では先行が苦しくなる。",
    },
    "小田原": {
        "slug": "odawara",
        "track_m": 333,
        "straight_m": 36.1,
        "bias": "先行寄り",
        "summary": "すりばちバンク。短走路で先行有利だが、1コーナー捲りも効く。",
        "watch": "カントが急で外からの捲りは難しい。早い仕掛けを重視。",
    },
    "岐阜": {
        "slug": "gifu",
        "track_m": 400,
        "straight_m": 59.3,
        "bias": "標準・差し届く",
        "summary": "直線が長くクセは少ない。先行、捲り、追い込みどれも力を出せる。",
        "watch": "4コーナーから中バンクが伸びる。外で粘る捲りにも注意。",
    },
    "岸和田": {
        "slug": "kishiwada",
        "track_m": 400,
        "straight_m": 56.7,
        "bias": "標準",
        "summary": "クセの少ない400バンク。直線は中と外に強襲コースがある。",
        "watch": "横風で重くなることがある。3番手の交わしに注意。",
    },
    "平塚": {
        "slug": "hiratsuka",
        "track_m": 400,
        "straight_m": 54.2,
        "bias": "標準",
        "summary": "軽くてクセの少ない走路。力通りになりやすい。",
        "watch": "湿度、池、ナイター温度差で重さが変わる。選手談話を重視。",
    },
    "広島": {
        "slug": "hiroshima",
        "track_m": 400,
        "straight_m": 57.9,
        "bias": "捲り・差し寄り",
        "summary": "直線長めでクセは少ないが、風が強く重いバンクになりやすい。",
        "watch": "カントがきつく山おろしの捲りが効く。直線は外伸び傾向。",
    },
    "弥彦": {
        "slug": "yahiko",
        "track_m": 400,
        "straight_m": 63.1,
        "bias": "追込寄り",
        "summary": "みなし直線が長く、追い込み・捲りが届きやすい。",
        "watch": "4、5番手からの突き抜けあり。バック過ぎの仕掛けも有効。",
    },
    "松山": {
        "slug": "matsuyama",
        "track_m": 400,
        "straight_m": 58.6,
        "bias": "高速・前残り",
        "summary": "高速バンクでタイムが出やすい。回転型の自力に合う。",
        "watch": "川沿いで風の影響が大きい。バック向かい風なら逃げを下げる。",
    },
    "松戸": {
        "slug": "matsudo",
        "track_m": 333,
        "straight_m": 38.2,
        "bias": "先行・ライン寄り",
        "summary": "直線が短い小回り。機動型と先手ラインが残りやすい。",
        "watch": "後手は苦しい。筋違いは好配当になりやすい。",
    },
    "松阪": {
        "slug": "matsusaka",
        "track_m": 400,
        "straight_m": 61.5,
        "bias": "捲り・追込寄り",
        "summary": "直線が長く、カントもややきつい。先行には厳しめ。",
        "watch": "競りはイン有利。番手のコース取りを強く見る。",
    },
    "武雄": {
        "slug": "takeo",
        "track_m": 400,
        "straight_m": 64.4,
        "bias": "追込・捲り寄り",
        "summary": "400バンクでは直線が最長級。ゴール前の逆転が多い。",
        "watch": "最大カントがきつく捲りや捲り追い込みが決まりやすい。",
    },
    "熊本": {
        "slug": "kumamoto",
        "track_m": 400,
        "straight_m": 60.3,
        "bias": "差し届く",
        "summary": "2024年に400バンクとしてリニューアル。直線は約60mで長め。",
        "watch": "旧500時代の印象に引っ張られすぎず、新400条件で評価する。",
    },
    "玉野": {
        "slug": "tamano",
        "track_m": 400,
        "straight_m": 47.9,
        "bias": "先行寄り",
        "summary": "直線短めで走りやすいが、風の影響が強く単純な先行有利ではない。",
        "watch": "昼は風、ミッドナイトは風が弱まり先行有利へ寄りやすい。",
    },
    "西武園": {
        "slug": "seibuen",
        "track_m": 400,
        "straight_m": 47.6,
        "bias": "先行寄り",
        "summary": "400ながら333に近い性格。直線短めで逃げ・先行が有利。",
        "watch": "風向きが定まりにくい。3、4コーナー中バンク内寄りの強襲もある。",
    },
    "豊橋": {
        "slug": "toyohashi",
        "track_m": 400,
        "straight_m": 60.3,
        "bias": "標準・捲り届く",
        "summary": "直線が長く、クセの少ない走路。どの戦法でも力を出しやすい。",
        "watch": "先行がかかっていても2コーナーからの捲りが届く。",
    },
    "青森": {
        "slug": "aomori",
        "track_m": 400,
        "straight_m": 58.9,
        "bias": "追込・捲り寄り",
        "summary": "直線が比較的長く、後方からの追い込みにもチャンスがある。",
        "watch": "2コーナーから3コーナーの捲りで山おろしが効く。",
    },
    "静岡": {
        "slug": "shizuoka",
        "track_m": 400,
        "straight_m": 56.4,
        "bias": "捲り寄り",
        "summary": "クセの少ない平均的な400だが、逃げより捲りが決まりやすい。",
        "watch": "2コーナーからの捲りでラインが崩れる展開に注意。",
    },
    "高知": {
        "slug": "kochi",
        "track_m": 500,
        "straight_m": 52.0,
        "bias": "先手ライン寄り",
        "summary": "500ながら直線は短め。先手ラインが優勢になりやすい。",
        "watch": "コーナーで脚を使わせず流せる先行ラインを評価する。",
    },
}


def get_venue_feature(venue: str | None) -> dict:
    if not venue:
        return {}
    return VENUE_FEATURES.get(str(venue), {})


def venue_feature_url(venue: str | None) -> str:
    feature = get_venue_feature(venue)
    slug = feature.get("slug")
    return f"https://www.winticket.jp/keirin/{slug}/" if slug else ""


def venue_feature_rows(venues: list[str] | tuple[str, ...] | None = None) -> list[dict]:
    names = list(venues) if venues else sorted(VENUE_FEATURES)
    rows = []
    for venue in names:
        feature = get_venue_feature(venue)
        if not feature:
            rows.append(
                {
                    "競輪場": venue,
                    "周長": "",
                    "見なし直線": "",
                    "傾向": "未登録",
                    "特徴": "特徴データを追加してください。",
                    "注意点": "",
                }
            )
            continue
        rows.append(
            {
                "競輪場": venue,
                "周長": f"{feature['track_m']}m",
                "見なし直線": f"{feature['straight_m']}m",
                "傾向": feature["bias"],
                "特徴": feature["summary"],
                "注意点": feature["watch"],
            }
        )
    return rows
