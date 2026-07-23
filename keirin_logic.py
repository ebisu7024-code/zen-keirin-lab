from __future__ import annotations

import re
from typing import Sequence


TICKET_TYPES = [
    "単勝",
    "複勝",
    "2車単",
    "2車複",
    "ワイド",
    "3連単",
    "3連複",
]


def parse_numbers(value: str | None) -> tuple[int, ...]:
    """買い目文字列から車番だけを取り出す。"""
    if not value:
        return ()
    return tuple(int(part) for part in re.findall(r"\d+", str(value)))


def parse_line_summary(value: str | None) -> tuple[tuple[int, ...], ...]:
    """並び予想文字列をライン単位の車番タプルにする。"""
    if not value:
        return ()
    groups: list[tuple[int, ...]] = []
    for group_text in re.split(r"\s*/\s*|\s+区切り\s+", str(value).strip()):
        numbers = parse_numbers(group_text)
        if numbers:
            groups.append(numbers)
    return tuple(groups)


def line_position_map(line_groups: Sequence[Sequence[int]]) -> dict[int, tuple[str, str]]:
    positions: dict[int, tuple[str, str]] = {}
    for line_index, group in enumerate(line_groups, start=1):
        line_key = f"ライン{line_index}"
        for rider_index, car_no in enumerate(group):
            if len(group) == 1:
                position = "単騎"
            elif rider_index == 0:
                position = "先頭"
            elif rider_index == 1:
                position = "番手"
            else:
                position = "3番手"
            positions[int(car_no)] = (line_key, position)
    return positions


def line_function_status(line_numbers: Sequence[int], result: Sequence[int]) -> str:
    result_numbers = tuple(int(number) for number in result if int(number) > 0)
    line = tuple(int(number) for number in line_numbers if int(number) > 0)
    if not line or not result_numbers:
        return "未評価"
    if len(line) == 1:
        return "単騎"
    top_three = set(result_numbers[:3])
    matched = len(set(line).intersection(top_three))
    if matched >= 2:
        return "機能"
    if matched == 1:
        return "半機能"
    return "崩れ"


def format_combination_with_names(combination: str | None, rider_names: dict[int, str]) -> str:
    numbers = parse_numbers(combination)
    if not numbers:
        return str(combination or "")
    labels = []
    for number in numbers:
        name = rider_names.get(int(number), "")
        labels.append(f"{number} {name}" if name else str(number))
    return " - ".join(labels)


def normalize_result(first: int | None, second: int | None, third: int | None) -> tuple[int, ...]:
    result = []
    for number in (first, second, third):
        if number is not None and int(number) > 0:
            result.append(int(number))
    return tuple(result)


def judge_ticket_hit(ticket_type: str, combination: str, result: Sequence[int]) -> bool:
    numbers = parse_numbers(combination)
    result_numbers = tuple(int(number) for number in result if int(number) > 0)

    if not numbers or not result_numbers:
        return False

    if ticket_type == "単勝":
        return len(result_numbers) >= 1 and numbers[0] == result_numbers[0]

    if ticket_type == "複勝":
        return len(result_numbers) >= 3 and numbers[0] in result_numbers[:3]

    if ticket_type == "2車単":
        return len(numbers) >= 2 and len(result_numbers) >= 2 and numbers[:2] == result_numbers[:2]

    if ticket_type == "2車複":
        return len(numbers) >= 2 and len(result_numbers) >= 2 and set(numbers[:2]) == set(result_numbers[:2])

    if ticket_type == "ワイド":
        return len(numbers) >= 2 and len(result_numbers) >= 3 and set(numbers[:2]).issubset(set(result_numbers[:3]))

    if ticket_type == "3連単":
        return len(numbers) >= 3 and len(result_numbers) >= 3 and numbers[:3] == result_numbers[:3]

    if ticket_type == "3連複":
        return len(numbers) >= 3 and len(result_numbers) >= 3 and set(numbers[:3]) == set(result_numbers[:3])

    return False


def ability_score(base: int | float, development: int | float) -> float:
    return round(float(base) * 0.6 + float(development) * 0.4, 1)


def human_score(mental: int | float, relationship: int | float) -> float:
    return round(float(mental) * 0.55 + float(relationship) * 0.45, 1)


def blended_score(base: int | float, development: int | float, mental: int | float, relationship: int | float) -> float:
    ability = ability_score(base, development)
    human = human_score(mental, relationship)
    return round(ability * 0.75 + human * 0.25, 1)


def profit(stake: int | float, payout: int | float) -> int:
    return int(payout or 0) - int(stake or 0)


def recovery_rate(total_stake: int | float, total_payout: int | float) -> float:
    if not total_stake:
        return 0.0
    return round((float(total_payout) / float(total_stake)) * 100, 1)


def hit_rate(hit_count: int, bet_count: int) -> float:
    if not bet_count:
        return 0.0
    return round((hit_count / bet_count) * 100, 1)
