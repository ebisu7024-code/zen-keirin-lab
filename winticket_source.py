from __future__ import annotations

import re
import ssl
from dataclasses import dataclass
from datetime import datetime, timedelta
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from keirin_logic import line_position_map, parse_line_summary


BASE_URL = "https://www.winticket.jp"
SOURCE_RACE_ID_RE = re.compile(r"(?:raceId=)?([0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{2}_[0-9]{2})")
WINTICKET_RACE_URL_RE = re.compile(
    r"/(?:racecard|raceresult)/(?P<event_date>[0-9]{8})(?P<venue_code>[0-9]{2})/"
    r"(?P<day_index>[0-9]+)/(?P<race_no>[0-9]+)"
)
TICKET_TYPES = ("3連単", "3連複", "2車単", "2車複", "2枠単", "2枠複", "ワイド", "単勝", "複勝")
RIDER_RE = re.compile(
    r"^(?P<name>.+?)\s+"
    r"(?P<prefecture>[^\s]+)\s+"
    r"(?P<rider_class>[A-Z]\d)\s+"
    r"(?:(?P<age>[0-9]+)歳\s+)?"
    r"(?P<term>[0-9]+)期$"
)
CLASS_RE = re.compile(r"^(?P<rider_class>[A-Z]\d)\s+(?:(?P<age>[0-9]+)歳\s+)?(?P<term>[0-9]+)期$")
VENUE_SLUGS = {
    "函館": "hakodate",
    "青森": "aomori",
    "いわき平": "iwakidaira",
    "弥彦": "yahiko",
    "前橋": "maebashi",
    "取手": "toride",
    "宇都宮": "utsunomiya",
    "大宮": "omiya",
    "西武園": "seibuen",
    "京王閣": "keiokaku",
    "立川": "tachikawa",
    "松戸": "matsudo",
    "千葉": "chiba",
    "川崎": "kawasaki",
    "平塚": "hiratsuka",
    "小田原": "odawara",
    "伊東": "ito",
    "静岡": "shizuoka",
    "名古屋": "nagoya",
    "岐阜": "gifu",
    "大垣": "ogaki",
    "豊橋": "toyohashi",
    "富山": "toyama",
    "松阪": "matsusaka",
    "四日市": "yokkaichi",
    "福井": "fukui",
    "奈良": "nara",
    "向日町": "mukomachi",
    "和歌山": "wakayama",
    "岸和田": "kishiwada",
    "玉野": "tamano",
    "広島": "hiroshima",
    "防府": "hofu",
    "高松": "takamatsu",
    "小松島": "komatsushima",
    "高知": "kochi",
    "松山": "matsuyama",
    "小倉": "kokura",
    "久留米": "kurume",
    "武雄": "takeo",
    "佐世保": "sasebo",
    "別府": "beppu",
    "熊本": "kumamoto",
}


class WinticketSourceError(RuntimeError):
    pass


@dataclass(frozen=True)
class WinticketRider:
    car_no: int
    rider_name: str
    prefecture: str = ""
    rider_class: str = ""
    age: int = 0
    term: str = ""
    racing_score: float = 0.0
    style: str = "不明"
    rider_comment: str = ""
    line_name: str = ""
    line_position: str = "不明"
    post_race_comment: str = ""


@dataclass(frozen=True)
class WinticketResultRow:
    finish_order: int
    car_no: int
    rider_name: str = ""
    margin: str = ""
    agari: str = ""
    decision: str = ""
    sb: str = ""


@dataclass(frozen=True)
class WinticketPayout:
    ticket_type: str
    combination: str
    payout: int
    popularity: str = ""


@dataclass(frozen=True)
class WinticketRaceSource:
    source_race_id: str
    racecard_url: str
    result_url: str
    line_summary: str
    riders: tuple[WinticketRider, ...]
    result_rows: tuple[WinticketResultRow, ...]
    payouts: tuple[WinticketPayout, ...]


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: list[str] = []

    def handle_data(self, data: str) -> None:
        text = clean_text(data)
        if text:
            self.lines.append(text)


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\u3000", " ")).strip()


def html_to_lines(source: str) -> list[str]:
    if "<" not in source or ">" not in source:
        return [clean_text(line) for line in source.splitlines() if clean_text(line)]
    parser = _TextParser()
    parser.feed(source)
    return [line for line in parser.lines if line]


def extract_source_race_id(text: str | None) -> str:
    if not text:
        return ""
    match = SOURCE_RACE_ID_RE.search(text)
    if match:
        return match.group(1)
    winticket_match = WINTICKET_RACE_URL_RE.search(text)
    if not winticket_match:
        return ""
    event_date = datetime.strptime(winticket_match.group("event_date"), "%Y%m%d")
    race_date = event_date + timedelta(days=int(winticket_match.group("day_index")) - 1)
    race_no = int(winticket_match.group("race_no"))
    return f"{race_date:%Y-%m-%d}_{winticket_match.group('venue_code')}_{race_no:02d}"


def fetch_url(url: str, timeout: int = 20) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 zenKeirinLab/1.0",
            "Accept-Language": "ja,en;q=0.8",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(charset, errors="replace")
    except URLError as exc:
        if not isinstance(exc.reason, ssl.SSLCertVerificationError):
            raise
        context = ssl._create_unverified_context()
        with urlopen(request, timeout=timeout, context=context) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(charset, errors="replace")


def compact_date(race_date: str) -> str:
    return race_date.replace("-", "").replace("/", "")


def source_race_parts(source_race_id: str) -> tuple[str, str, int]:
    parts = source_race_id.split("_")
    if len(parts) != 3:
        raise WinticketSourceError(f"WINTICKET/TIPSTAR raceId の形式が不正です: {source_race_id}")
    return compact_date(parts[0]), parts[1], int(parts[2])


def race_title_day_index(race_title: str) -> int:
    if "初日" in race_title:
        return 1
    match = re.search(r"([0-9]+)日目", race_title)
    if match:
        return int(match.group(1))
    if "最終日" in race_title:
        return 3
    return 1


def date_with_offset(date_compact: str, offset_days: int) -> str:
    day = datetime.strptime(date_compact, "%Y%m%d")
    return (day + timedelta(days=offset_days)).strftime("%Y%m%d")


def unique_values(values: list[int]) -> list[int]:
    result: list[int] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


def candidate_racecard_urls(date_compact: str, venue_code: str, race_no: int, venue: str, race_title: str) -> list[str]:
    slug = VENUE_SLUGS.get(venue, "")
    if not slug:
        return []

    preferred_day = race_title_day_index(race_title)
    day_indexes = unique_values([preferred_day, 1, 2, 3, 4, 5, 6])
    event_dates = unique_values(
        [
            date_with_offset(date_compact, -(day_index - 1))
            for day_index in day_indexes
        ]
        + [date_with_offset(date_compact, -offset) for offset in range(0, 7)]
    )
    urls: list[str] = []
    for event_date in event_dates:
        event_id = f"{event_date}{venue_code}"
        for day_index in day_indexes:
            urls.append(f"{BASE_URL}/keirin/{slug}/racecard/{event_id}/{day_index}/{race_no}")
    return urls


def resolve_race_urls(
    race_date: str,
    race_no: int,
    source_race_id: str,
    venue: str = "",
    race_title: str = "",
    fetcher=fetch_url,
) -> tuple[str, str]:
    date_compact, venue_code, source_race_no = source_race_parts(source_race_id)
    target_race_no = int(race_no or source_race_no)
    event_id = f"{date_compact}{venue_code}"
    index_url = f"{BASE_URL}/keirin/racecard/{compact_date(race_date)}"
    html = fetcher(index_url)
    hrefs = re.findall(r"href=[\"']([^\"']+)[\"']", html)
    for href in hrefs:
        path = href.split("?")[0].rstrip("/")
        if f"{venue_code}/" in path and f"/racecard/" in path and path.endswith(f"/{target_race_no}"):
            racecard_url = urljoin(BASE_URL, path)
            return racecard_url, racecard_url.replace("/racecard/", "/raceresult/")

    for fallback in candidate_racecard_urls(date_compact, venue_code, target_race_no, venue, race_title):
        try:
            fetcher(fallback)
        except HTTPError as exc:
            if exc.code == 404:
                continue
            raise
        except URLError:
            continue
        return fallback, fallback.replace("/racecard/", "/raceresult/")

    raise WinticketSourceError(f"WINTICKETの出走表URLを解決できませんでした: {source_race_id}")


def fallback_racecard_url(event_id: str, race_no: int, venue: str, race_title: str) -> str:
    slug = VENUE_SLUGS.get(venue, "")
    if not slug:
        return ""
    day_index = 1
    if "2日目" in race_title:
        day_index = 2
    elif "3日目" in race_title or "最終日" in race_title:
        day_index = 3
    return f"{BASE_URL}/keirin/{slug}/racecard/{event_id}/{day_index}/{race_no}"


def _previous_car_no(lines: list[str], index: int) -> int:
    for line in reversed(lines[max(0, index - 8) : index]):
        if re.fullmatch(r"[1-9]", line):
            return int(line)
    return 0


def _next_rider_index(lines: list[str], index: int) -> int:
    for next_index in range(index + 1, len(lines)):
        if RIDER_RE.match(lines[next_index]):
            return next_index
        if CLASS_RE.match(lines[next_index]) and next_index >= 2:
            return max(index + 1, next_index - 2)
    return min(index + 28, len(lines))


def _extract_racing_score(lines: list[str]) -> float:
    for line in lines:
        for value in re.findall(r"[0-9]+(?:\.[0-9]+)?", line):
            score = float(value)
            if 40 <= score <= 130:
                return score
    return 0.0


def _extract_style(lines: list[str]) -> str:
    style_map = {"逃": "逃げ", "追": "追込", "両": "自在"}
    for line in lines:
        if line in style_map:
            return style_map[line]
        parts = line.split()
        if parts and parts[-1] in style_map:
            return style_map[parts[-1]]
    return "不明"


def _extract_pre_race_comment(lines: list[str]) -> str:
    for line in lines:
        match = re.search(r"[0-9]+(?:\.[0-9]+)?\s+[0-9]+(?:\.[0-9]+)?\s+(.+)$", line)
        if match:
            comment = clean_text(match.group(1))
            if comment and not re.fullmatch(r"[0-9. ]+", comment):
                return comment
    for index, line in enumerate(lines[:-1]):
        if not re.fullmatch(r"[0-9]\.[0-9]{2}", line):
            continue
        comment = clean_text(lines[index + 1])
        if comment and not re.fullmatch(r"[0-9.()（） ]+", comment):
            return comment
    return ""


def _split_rider_match(lines: list[str], index: int):
    class_match = CLASS_RE.match(lines[index])
    if not class_match or index < 2:
        return None
    name = lines[index - 2]
    prefecture = lines[index - 1]
    if re.fullmatch(r"[0-9]+", name) or prefecture in {"選手名", "車", "枠"}:
        return None
    return {
        "name": name,
        "prefecture": prefecture,
        "rider_class": class_match.group("rider_class"),
        "age": class_match.group("age") or "0",
        "term": class_match.group("term"),
        "name_index": index - 2,
    }


def _parse_line_summary_from_lines(lines: list[str]) -> str:
    try:
        start = lines.index("並び予想")
    except ValueError:
        return ""

    groups: list[list[int]] = []
    current: list[int] = []
    stop_words = {
        "結果",
        "勝ち上がり条件",
        "着順 ビデオ 映像を観る",
        "着 車 選手名 着差 上り 決 SB",
        "※基本情報は直近4か月の成績を表示しています",
    }
    for line in lines[start + 1 :]:
        if line in stop_words or line.startswith("※") or line.startswith("着順"):
            break
        if line == "区切り":
            if current:
                groups.append(current)
                current = []
            continue
        if re.fullmatch(r"[1-9](?:\s+[1-9])*", line):
            current.extend(int(number) for number in line.split())
    if current:
        groups.append(current)
    return " / ".join("-".join(str(number) for number in group) for group in groups)


def parse_winticket_racecard_html(source: str) -> tuple[str, tuple[WinticketRider, ...]]:
    lines = html_to_lines(source)
    line_summary = _parse_line_summary_from_lines(lines)
    positions = line_position_map(parse_line_summary(line_summary))
    riders: list[WinticketRider] = []
    seen: set[int] = set()

    for index, line in enumerate(lines):
        match = RIDER_RE.match(line)
        split_match = None if match else _split_rider_match(lines, index)
        if not match and not split_match:
            continue
        name_index = index if match else int(split_match["name_index"])
        car_no = _previous_car_no(lines, name_index)
        if not car_no or car_no in seen:
            continue
        seen.add(car_no)
        next_index = _next_rider_index(lines, index)
        detail_lines = lines[index + 1 : next_index]
        line_name, line_position = positions.get(car_no, ("", "不明"))
        name = match.group("name") if match else split_match["name"]
        prefecture = match.group("prefecture") if match else split_match["prefecture"]
        rider_class = match.group("rider_class") if match else split_match["rider_class"]
        age = match.group("age") if match else split_match["age"]
        term = match.group("term") if match else split_match["term"]
        riders.append(
            WinticketRider(
                car_no=car_no,
                rider_name=name,
                prefecture=prefecture,
                rider_class=rider_class,
                age=int(age or 0),
                term=term,
                racing_score=_extract_racing_score(detail_lines),
                style=_extract_style(detail_lines),
                rider_comment=_extract_pre_race_comment(detail_lines),
                line_name=line_name,
                line_position=line_position,
            )
        )
    return line_summary, tuple(sorted(riders, key=lambda rider: rider.car_no))


def _parse_result_detail(line: str) -> tuple[str, str, str, str]:
    parts = line.split()
    agari_index = -1
    for index, part in enumerate(parts):
        if re.fullmatch(r"[0-9]+\.[0-9]+", part):
            agari_index = index
            break
    if agari_index == -1:
        return "", "", "", ""
    margin = " ".join(parts[:agari_index])
    agari = parts[agari_index]
    decision = ""
    sb = ""
    for part in parts[agari_index + 1 :]:
        if part in {"逃", "捲", "差", "マ"} and not decision:
            decision = part
        elif part in {"S", "B", "SB", "BS"}:
            sb = part
    return margin, agari, decision, sb


def _parse_result_detail_lines(lines: list[str]) -> tuple[str, str, str, str]:
    if not lines:
        return "", "", "", ""
    joined = " ".join(lines[:4])
    if re.search(r"[0-9]+\.[0-9]+", joined):
        margin, agari, decision, sb = _parse_result_detail(joined)
        if agari:
            return margin, agari, decision, sb

    agari_index = -1
    for index, line in enumerate(lines):
        if re.fullmatch(r"[0-9]+\.[0-9]+", line):
            agari_index = index
            break
    if agari_index == -1:
        return "", "", "", ""
    margin_parts = [line for line in lines[:agari_index] if not re.fullmatch(r"[1-9]", line)]
    margin = " ".join(margin_parts)
    agari = lines[agari_index]
    decision = ""
    sb = ""
    for line in lines[agari_index + 1 : agari_index + 4]:
        if line in {"逃", "捲", "差", "マ"} and not decision:
            decision = line
        elif line in {"S", "B", "SB", "BS"}:
            sb = line
    return margin, agari, decision, sb


def parse_winticket_result_html(source: str) -> tuple[str, tuple[WinticketResultRow, ...], tuple[WinticketPayout, ...]]:
    lines = html_to_lines(source)
    line_summary = _parse_line_summary_from_lines(lines)
    result_rows: list[WinticketResultRow] = []

    try:
        start = lines.index("着順 ビデオ 映像を観る")
    except ValueError:
        try:
            start = lines.index("着順")
        except ValueError:
            start = 0
    try:
        end = lines.index("払戻金")
    except ValueError:
        end = len(lines)

    for index in range(start, end):
        match = RIDER_RE.match(lines[index])
        split_match = None if match else _split_rider_match(lines, index)
        if not match and not split_match:
            continue
        name_index = index if match else int(split_match["name_index"])
        numbers = [int(line) for line in lines[max(start, name_index - 6) : name_index] if re.fullmatch(r"[1-9]", line)]
        if len(numbers) < 2:
            continue
        finish_order, car_no = numbers[-2], numbers[-1]
        next_index = _next_rider_index(lines, index)
        margin, agari, decision, sb = _parse_result_detail_lines(lines[index + 1 : min(next_index, end)])
        name = match.group("name") if match else split_match["name"]
        result_rows.append(
            WinticketResultRow(
                finish_order=finish_order,
                car_no=car_no,
                rider_name=name,
                margin=margin,
                agari=agari,
                decision=decision,
                sb=sb,
            )
        )

    payouts: list[WinticketPayout] = []
    current_type = ""
    if end < len(lines):
        payout_re = re.compile(
            rf"^(?:(?P<type>{'|'.join(TICKET_TYPES)})\s+)?"
            r"(?P<combination>[0-9=\-]+)\s+"
            r"(?P<payout>[0-9,]+)\s*円\((?P<popularity>[^)]*)\)"
        )
        index = end + 1
        while index < len(lines):
            line = lines[index]
            if line.startswith("## ") or line == "レース情報" or line.endswith("結果"):
                break
            match = payout_re.match(line)
            if match:
                current_type = match.group("type") or current_type
                if current_type:
                    payouts.append(
                        WinticketPayout(
                            ticket_type=current_type,
                            combination=match.group("combination").replace("=", "-"),
                            payout=int(match.group("payout").replace(",", "")),
                            popularity=match.group("popularity"),
                        )
                    )
                index += 1
                continue

            if line in TICKET_TYPES:
                current_type = line
                index += 1
                continue
            if (
                current_type
                and re.fullmatch(r"[0-9=\-]+", line)
                and index + 3 < len(lines)
                and re.fullmatch(r"[0-9,]+", lines[index + 1])
                and lines[index + 2] == "円"
                and re.fullmatch(r"\([^)]*\)", lines[index + 3])
            ):
                payouts.append(
                    WinticketPayout(
                        ticket_type=current_type,
                        combination=line.replace("=", "-"),
                        payout=int(lines[index + 1].replace(",", "")),
                        popularity=lines[index + 3].strip("()"),
                    )
                )
                index += 4
                continue
            index += 1
    return line_summary, tuple(sorted(result_rows, key=lambda row: row.finish_order)), tuple(payouts)


def fetch_winticket_race(
    race_date: str,
    race_no: int,
    source_race_id: str,
    venue: str = "",
    race_title: str = "",
    fetcher=fetch_url,
) -> WinticketRaceSource:
    racecard_url, result_url = resolve_race_urls(race_date, race_no, source_race_id, venue, race_title, fetcher=fetcher)
    racecard_html = fetcher(racecard_url)
    result_html = fetcher(result_url)
    card_line_summary, riders = parse_winticket_racecard_html(racecard_html)
    result_line_summary, result_rows, payouts = parse_winticket_result_html(result_html)
    return WinticketRaceSource(
        source_race_id=source_race_id,
        racecard_url=racecard_url,
        result_url=result_url,
        line_summary=card_line_summary or result_line_summary,
        riders=riders,
        result_rows=result_rows,
        payouts=payouts,
    )
