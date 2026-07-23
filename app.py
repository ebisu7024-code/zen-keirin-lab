from __future__ import annotations

import sqlite3
import re
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from keirin_logic import (
    TICKET_TYPES,
    ability_score,
    blended_score,
    format_combination_with_names,
    hit_rate,
    human_score,
    judge_ticket_hit,
    line_function_status,
    normalize_result,
    parse_line_summary,
    parse_numbers,
    profit,
    recovery_rate,
)
from winticket_source import WinticketSourceError, extract_source_race_id, fetch_winticket_race
from venue_features import get_venue_feature, venue_feature_rows, venue_feature_url


APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"
DB_PATH = DATA_DIR / "zen_keirin_lab.sqlite3"

MARK_OPTIONS = ["", "◎", "○", "▲", "△", "☆", "消", "見送り"]
INFO_TYPES = ["事実", "本人発言", "過去レース観察", "Hypothesis", "出所不明"]
CONFIDENCE_LEVELS = ["高", "中", "低"]
STATUS_OPTIONS = ["予想中", "購入済み", "結果入力済み", "振り返り済み", "見送り"]
STYLE_OPTIONS = ["逃げ", "捲り", "差し", "追込", "自在", "不明"]
POSITION_OPTIONS = ["先頭", "番手", "3番手", "単騎", "別線", "不明"]
AMOUNT_UNITS = ["円", "TIPメダル", "TIPマネー", "ポイント", "枚", "単位混在"]
BET_AMOUNT_UNITS = [unit for unit in AMOUNT_UNITS if unit != "単位混在"]
ORDERED_HEAD_TICKET_TYPES = {"単勝", "2車単", "3連単"}
LINE_STATUS_OPTIONS = ["", "機能", "半機能", "崩れ", "単騎", "未評価"]
TIP_MEDAL_DAILY_GRANT = 10000
TIP_MEDAL_RESET_TEXT = "翌日3:00"


def now_text() -> str:
    return datetime.now().isoformat(timespec="seconds")


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback) -> None:
        super().__exit__(exc_type, exc_value, traceback)
        self.close()


def get_conn() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, factory=ClosingConnection)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = [row["name"] for row in conn.execute(f"PRAGMA table_info({table})")]
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def backfill_source_race_ids(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        SELECT id, race_memo
        FROM races
        WHERE source_race_id IS NULL OR source_race_id = ''
        """
    ).fetchall()
    for row in rows:
        source_race_id = extract_source_race_id(row["race_memo"])
        if source_race_id:
            conn.execute("UPDATE races SET source_race_id = ? WHERE id = ?", (source_race_id, int(row["id"])))


def migrate_race_result_rows_primary_key(conn: sqlite3.Connection) -> None:
    pk_columns = tuple(
        row["name"]
        for row in sorted(
            (row for row in conn.execute("PRAGMA table_info(race_result_rows)") if int(row["pk"] or 0) > 0),
            key=lambda row: int(row["pk"]),
        )
    )
    if pk_columns == ("race_id", "finish_order", "car_no"):
        return

    conn.executescript(
        """
        ALTER TABLE race_result_rows RENAME TO race_result_rows_old;

        CREATE TABLE race_result_rows (
            race_id INTEGER NOT NULL,
            finish_order INTEGER NOT NULL,
            car_no INTEGER NOT NULL,
            rider_name TEXT DEFAULT '',
            margin TEXT DEFAULT '',
            agari TEXT DEFAULT '',
            decision TEXT DEFAULT '',
            sb TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (race_id, finish_order, car_no)
        );

        INSERT OR IGNORE INTO race_result_rows (
            race_id,
            finish_order,
            car_no,
            rider_name,
            margin,
            agari,
            decision,
            sb,
            created_at,
            updated_at
        )
        SELECT
            race_id,
            finish_order,
            car_no,
            rider_name,
            margin,
            agari,
            decision,
            sb,
            created_at,
            updated_at
        FROM race_result_rows_old;

        DROP TABLE race_result_rows_old;
        CREATE INDEX IF NOT EXISTS idx_result_rows_race_id ON race_result_rows(race_id);
        """
    )


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS races (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                race_date TEXT NOT NULL,
                venue TEXT NOT NULL,
                race_no INTEGER NOT NULL,
                grade TEXT DEFAULT '',
                distance INTEGER DEFAULT 0,
                weather TEXT DEFAULT '',
                wind REAL DEFAULT 0,
                amount_unit TEXT DEFAULT '円',
                status TEXT DEFAULT '予想中',
                race_title TEXT DEFAULT '',
                line_summary TEXT DEFAULT '',
                race_memo TEXT DEFAULT '',
                source_race_id TEXT DEFAULT '',
                source_racecard_url TEXT DEFAULT '',
                source_result_url TEXT DEFAULT '',
                source_synced_at TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS riders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                race_id INTEGER NOT NULL,
                car_no INTEGER NOT NULL,
                rider_name TEXT NOT NULL,
                prefecture TEXT DEFAULT '',
                age INTEGER DEFAULT 0,
                racing_score REAL DEFAULT 0,
                style TEXT DEFAULT '不明',
                line_name TEXT DEFAULT '',
                line_position TEXT DEFAULT '不明',
                recent_results TEXT DEFAULT '',
                rider_comment TEXT DEFAULT '',
                rider_class TEXT DEFAULT '',
                term TEXT DEFAULT '',
                post_race_comment TEXT DEFAULT '',
                comment_eval TEXT DEFAULT '',
                ability_score INTEGER DEFAULT 50,
                development_score INTEGER DEFAULT 50,
                mental_score INTEGER DEFAULT 50,
                relationship_score INTEGER DEFAULT 50,
                confidence TEXT DEFAULT '中',
                info_type TEXT DEFAULT 'Hypothesis',
                human_note TEXT DEFAULT '',
                final_mark TEXT DEFAULT '',
                user_note TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(race_id, car_no)
            );

            CREATE TABLE IF NOT EXISTS bets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                race_id INTEGER NOT NULL,
                ticket_type TEXT NOT NULL,
                combination TEXT NOT NULL,
                amount_unit TEXT DEFAULT '',
                stake INTEGER DEFAULT 0,
                payout INTEGER DEFAULT 0,
                hit INTEGER DEFAULT 0,
                expected_role TEXT DEFAULT '',
                note TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS results (
                race_id INTEGER PRIMARY KEY,
                first_no INTEGER DEFAULT 0,
                second_no INTEGER DEFAULT 0,
                third_no INTEGER DEFAULT 0,
                result_memo TEXT DEFAULT '',
                reflection TEXT DEFAULT '',
                cause_tag TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS race_result_rows (
                race_id INTEGER NOT NULL,
                finish_order INTEGER NOT NULL,
                car_no INTEGER NOT NULL,
                rider_name TEXT DEFAULT '',
                margin TEXT DEFAULT '',
                agari TEXT DEFAULT '',
                decision TEXT DEFAULT '',
                sb TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (race_id, finish_order, car_no)
            );

            CREATE TABLE IF NOT EXISTS race_payouts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                race_id INTEGER NOT NULL,
                ticket_type TEXT NOT NULL,
                combination TEXT NOT NULL,
                payout INTEGER DEFAULT 0,
                popularity TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(race_id, ticket_type, combination)
            );

            CREATE TABLE IF NOT EXISTS race_lines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                race_id INTEGER NOT NULL,
                line_key TEXT NOT NULL,
                car_numbers TEXT NOT NULL,
                auto_status TEXT DEFAULT '未評価',
                user_status TEXT DEFAULT '',
                note TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(race_id, line_key)
            );

            CREATE INDEX IF NOT EXISTS idx_riders_race_id ON riders(race_id);
            CREATE INDEX IF NOT EXISTS idx_bets_race_id ON bets(race_id);
            CREATE INDEX IF NOT EXISTS idx_result_rows_race_id ON race_result_rows(race_id);
            CREATE INDEX IF NOT EXISTS idx_payouts_race_id ON race_payouts(race_id);
            CREATE INDEX IF NOT EXISTS idx_lines_race_id ON race_lines(race_id);
            """
        )
        ensure_column(conn, "races", "amount_unit", "TEXT DEFAULT '円'")
        ensure_column(conn, "races", "source_race_id", "TEXT DEFAULT ''")
        ensure_column(conn, "races", "source_racecard_url", "TEXT DEFAULT ''")
        ensure_column(conn, "races", "source_result_url", "TEXT DEFAULT ''")
        ensure_column(conn, "races", "source_synced_at", "TEXT DEFAULT ''")
        ensure_column(conn, "riders", "rider_class", "TEXT DEFAULT ''")
        ensure_column(conn, "riders", "term", "TEXT DEFAULT ''")
        ensure_column(conn, "riders", "post_race_comment", "TEXT DEFAULT ''")
        ensure_column(conn, "riders", "comment_eval", "TEXT DEFAULT ''")
        ensure_column(conn, "bets", "amount_unit", "TEXT DEFAULT ''")
        migrate_race_result_rows_primary_key(conn)
        backfill_source_race_ids(conn)
        conn.execute(
            """
            UPDATE bets
            SET amount_unit = (
                SELECT amount_unit
                FROM races
                WHERE races.id = bets.race_id
            )
            WHERE amount_unit IS NULL OR amount_unit = ''
            """
        )


def row_to_dict(row: sqlite3.Row | None) -> dict:
    return dict(row) if row else {}


def race_amount_unit(race: dict | pd.Series | None) -> str:
    if race is None:
        return "円"
    unit = race.get("amount_unit") if hasattr(race, "get") else None
    return unit if unit in AMOUNT_UNITS else "円"


def amount_text(value: int | float, unit: str) -> str:
    amount = int(value or 0)
    if unit == "単位混在":
        return f"{amount:,}（単位混在）"
    if unit == "円":
        return f"{amount:,}円"
    return f"{amount:,} {unit}"


def summary_unit(bets: pd.DataFrame) -> str:
    if bets.empty or "amount_unit" not in bets.columns:
        return "円"
    units = sorted(unit for unit in bets["amount_unit"].fillna("円").unique() if unit)
    return units[0] if len(units) == 1 else "単位混在"


def amount_summary_text(bets: pd.DataFrame, column: str) -> str:
    if bets.empty or column not in bets.columns:
        return amount_text(0, "円")
    if "amount_unit" not in bets.columns:
        return amount_text(int(bets[column].sum()), "円")
    grouped = bets.groupby("amount_unit")[column].sum().sort_index()
    return " / ".join(amount_text(value, unit) for unit, value in grouped.items())


def profit_summary_text(bets: pd.DataFrame) -> str:
    if bets.empty:
        return amount_text(0, "円")
    work = bets.copy()
    if "収支" not in work.columns:
        work["収支"] = work.apply(lambda row: profit(row["stake"], row["payout"]), axis=1)
    return amount_summary_text(work, "収支")


def default_bet_unit(race_unit: str) -> str:
    return race_unit if race_unit in BET_AMOUNT_UNITS else "TIPメダル"


def is_tip_medal(unit: str) -> bool:
    return unit == "TIPメダル"


def net_label(unit: str) -> str:
    if is_tip_medal(unit):
        return "練習差分"
    if unit == "単位混在":
        return "差分"
    return "収支"


def training_hit_label(unit: str) -> str:
    return "的中率" if is_tip_medal(unit) else "的中率"


def remaining_tip_medals(stake: int | float) -> int:
    return max(TIP_MEDAL_DAILY_GRANT - int(stake or 0), 0)


def chart_height(row_count: int, base: int = 300, row_px: int = 30, max_height: int = 560) -> int:
    return min(max(base, 120 + int(row_count) * row_px), max_height)


def style_chart(fig, *, height: int = 360, x_title: str = "", y_title: str = "", legend_title: str = ""):
    fig.update_layout(
        template="plotly_dark",
        height=height,
        margin=dict(l=12, r=24, t=58, b=36),
        paper_bgcolor="#0f1720",
        plot_bgcolor="#0f1720",
        font=dict(color="#e5edf5", size=13),
        title=dict(font=dict(size=17, color="#f8fafc"), x=0.01, xanchor="left"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        legend_title_text=legend_title,
        coloraxis_colorbar=dict(title=""),
    )
    fig.update_xaxes(
        title=x_title,
        showgrid=True,
        gridcolor="rgba(148, 163, 184, 0.18)",
        zerolinecolor="rgba(148, 163, 184, 0.34)",
        tickfont=dict(color="#cbd5e1"),
        title_font=dict(color="#cbd5e1"),
    )
    fig.update_yaxes(
        title=y_title,
        showgrid=False,
        tickfont=dict(color="#e2e8f0"),
        title_font=dict(color="#cbd5e1"),
        automargin=True,
    )
    fig.update_traces(marker_line_width=0, opacity=0.9, hoverlabel=dict(bgcolor="#111827"))
    return fig


def horizontal_bar(
    data: pd.DataFrame,
    *,
    label_col: str,
    value_col: str,
    title: str,
    color_col: str | None = None,
    x_title: str = "",
    y_title: str = "",
    height: int | None = None,
    hover_data: list[str] | None = None,
    continuous_color: bool = False,
    color_scale=None,
    text_template: str = "%{x:,.1f}",
):
    chart = data.sort_values(value_col, ascending=True).copy()
    kwargs = {
        "x": value_col,
        "y": label_col,
        "orientation": "h",
        "title": title,
        "text": value_col,
        "hover_data": hover_data or [],
    }
    if color_col:
        kwargs["color"] = color_col
        if continuous_color:
            kwargs["color_continuous_scale"] = color_scale or ["#ef4444", "#f59e0b", "#22c55e"]
    fig = px.bar(chart, **kwargs)
    fig.update_traces(texttemplate=text_template, textposition="outside", cliponaxis=False)
    return style_chart(
        fig,
        height=height or chart_height(len(chart)),
        x_title=x_title or value_col,
        y_title=y_title,
        legend_title=color_col or "",
    )


def render_empty_chart_message(message: str) -> None:
    st.info(message)


def fetch_races() -> pd.DataFrame:
    query = """
        SELECT
            r.*,
            COALESCE(rc.rider_count, 0) AS rider_count,
            COALESCE(lc.line_count, 0) AS line_count,
            COALESCE(lc.line_review_count, 0) AS line_review_count,
            COALESCE(rrc.result_row_count, 0) AS result_row_count,
            COALESCE(pc.payout_count, 0) AS payout_count,
            COALESCE(rv.review_done, 0) AS review_done,
            COALESCE(bc.bet_count, 0) AS bet_count,
            COALESCE(bc.hit_count, 0) AS hit_count,
            COALESCE(bc.total_stake, 0) AS total_stake,
            COALESCE(bc.total_payout, 0) AS total_payout
        FROM races r
        LEFT JOIN (
            SELECT race_id, COUNT(*) AS rider_count
            FROM riders
            GROUP BY race_id
        ) rc ON rc.race_id = r.id
        LEFT JOIN (
            SELECT
                race_id,
                COUNT(*) AS line_count,
                SUM(CASE WHEN COALESCE(user_status, '') <> '' THEN 1 ELSE 0 END) AS line_review_count
            FROM race_lines
            GROUP BY race_id
        ) lc ON lc.race_id = r.id
        LEFT JOIN (
            SELECT race_id, COUNT(*) AS result_row_count
            FROM race_result_rows
            GROUP BY race_id
        ) rrc ON rrc.race_id = r.id
        LEFT JOIN (
            SELECT race_id, COUNT(*) AS payout_count
            FROM race_payouts
            GROUP BY race_id
        ) pc ON pc.race_id = r.id
        LEFT JOIN (
            SELECT
                race_id,
                CASE
                    WHEN COALESCE(reflection, '') <> ''
                         AND reflection NOT LIKE 'TIPSTAR取込%'
                         AND reflection NOT LIKE 'TIPSTARスクショ%'
                    THEN 1
                    ELSE 0
                END AS review_done
            FROM results
        ) rv ON rv.race_id = r.id
        LEFT JOIN (
            SELECT
                race_id,
                COUNT(*) AS bet_count,
                SUM(hit) AS hit_count,
                SUM(stake) AS total_stake,
                SUM(payout) AS total_payout
            FROM bets
            GROUP BY race_id
        ) bc ON bc.race_id = r.id
        ORDER BY r.race_date DESC, r.id DESC
    """
    with get_conn() as conn:
        return pd.read_sql_query(query, conn)


def fetch_race(race_id: int | None) -> dict:
    if not race_id:
        return {}
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM races WHERE id = ?", (race_id,)).fetchone()
    return row_to_dict(row)


def fetch_riders(race_id: int) -> pd.DataFrame:
    with get_conn() as conn:
        df = pd.read_sql_query(
            "SELECT * FROM riders WHERE race_id = ? ORDER BY car_no",
            conn,
            params=(race_id,),
        )
    if df.empty:
        return df
    df["能力基準"] = df.apply(lambda row: ability_score(row["ability_score"], row["development_score"]), axis=1)
    df["心理関係"] = df.apply(lambda row: human_score(row["mental_score"], row["relationship_score"]), axis=1)
    df["総合"] = df.apply(
        lambda row: blended_score(
            row["ability_score"],
            row["development_score"],
            row["mental_score"],
            row["relationship_score"],
        ),
        axis=1,
    )
    return df


def fetch_rider_by_car(race_id: int, car_no: int) -> dict:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM riders WHERE race_id = ? AND car_no = ?",
            (race_id, car_no),
        ).fetchone()
    return row_to_dict(row)


def fetch_bets(race_id: int) -> pd.DataFrame:
    with get_conn() as conn:
        df = pd.read_sql_query(
            "SELECT * FROM bets WHERE race_id = ? ORDER BY id DESC",
            conn,
            params=(race_id,),
        )
    if not df.empty:
        df["収支"] = df.apply(lambda row: profit(row["stake"], row["payout"]), axis=1)
    return df


def fetch_result(race_id: int) -> dict:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM results WHERE race_id = ?", (race_id,)).fetchone()
    return row_to_dict(row)


def fetch_result_rows(race_id: int) -> pd.DataFrame:
    with get_conn() as conn:
        return pd.read_sql_query(
            "SELECT * FROM race_result_rows WHERE race_id = ? ORDER BY finish_order",
            conn,
            params=(race_id,),
        )


def fetch_payouts(race_id: int) -> pd.DataFrame:
    with get_conn() as conn:
        return pd.read_sql_query(
            "SELECT * FROM race_payouts WHERE race_id = ? ORDER BY id",
            conn,
            params=(race_id,),
        )


def fetch_lines(race_id: int) -> pd.DataFrame:
    with get_conn() as conn:
        return pd.read_sql_query(
            "SELECT * FROM race_lines WHERE race_id = ? ORDER BY id",
            conn,
            params=(race_id,),
        )


def rider_name_map(race_id: int) -> dict[int, str]:
    riders = fetch_riders(race_id)
    if riders.empty:
        return {}
    return {int(row["car_no"]): str(row["rider_name"]) for _, row in riders.iterrows()}


def fetch_all_bets() -> pd.DataFrame:
    query = """
        SELECT
            b.id,
            b.race_id,
            b.ticket_type,
            b.combination,
            COALESCE(NULLIF(b.amount_unit, ''), r.amount_unit) AS amount_unit,
            b.stake,
            b.payout,
            b.hit,
            b.expected_role,
            b.note,
            b.created_at,
            b.updated_at,
            r.race_date,
            r.venue,
            r.race_no,
            r.grade,
            r.status
        FROM bets b
        JOIN races r ON r.id = b.race_id
        ORDER BY r.race_date DESC, b.id DESC
    """
    with get_conn() as conn:
        df = pd.read_sql_query(query, conn)
    if not df.empty:
        df["収支"] = df.apply(lambda row: profit(row["stake"], row["payout"]), axis=1)
    return df


def fetch_all_riders() -> pd.DataFrame:
    with get_conn() as conn:
        return pd.read_sql_query(
            """
            SELECT
                race_id,
                car_no,
                rider_name,
                prefecture,
                line_name,
                line_position
            FROM riders
            WHERE COALESCE(rider_name, '') <> ''
            """,
            conn,
        )


def fetch_rider_purchase_summary() -> pd.DataFrame:
    bets = fetch_all_bets()
    riders = fetch_all_riders()
    if bets.empty or riders.empty:
        return pd.DataFrame()

    rider_lookup = {
        (int(row["race_id"]), int(row["car_no"])): dict(row)
        for _, row in riders.iterrows()
    }
    rows = []
    for _, bet in bets.iterrows():
        numbers = list(dict.fromkeys(parse_numbers(bet["combination"])))
        if not numbers:
            continue
        race_id = int(bet["race_id"])
        is_ordered_head = bet["ticket_type"] in ORDERED_HEAD_TICKET_TYPES
        for position, car_no in enumerate(numbers, start=1):
            rider = rider_lookup.get((race_id, int(car_no)))
            if not rider:
                continue
            hit = int(bet["hit"] or 0)
            stake = int(bet["stake"] or 0)
            payout = int(bet["payout"] or 0) if hit else 0
            rows.append(
                {
                    "bet_id": int(bet["id"]),
                    "race_id": race_id,
                    "race_date": bet["race_date"],
                    "venue": bet["venue"],
                    "race_no": int(bet["race_no"]),
                    "amount_unit": bet["amount_unit"],
                    "ticket_type": bet["ticket_type"],
                    "car_no": int(car_no),
                    "rider_name": rider["rider_name"],
                    "prefecture": rider.get("prefecture", ""),
                    "line_position": rider.get("line_position", ""),
                    "stake": stake,
                    "payout": payout,
                    "hit": hit,
                    "head_pick": int(is_ordered_head and position == 1),
                    "head_stake": stake if is_ordered_head and position == 1 else 0,
                }
            )

    if not rows:
        return pd.DataFrame()

    details = pd.DataFrame(rows)
    summary = (
        details.groupby(["amount_unit", "rider_name", "prefecture"], dropna=False)
        .agg(
            購入レース数=("race_id", "nunique"),
            買い目登場数=("bet_id", "count"),
            購入額=("stake", "sum"),
            的中絡み数=("hit", "sum"),
            絡み払戻=("payout", "sum"),
            頭固定数=("head_pick", "sum"),
            頭固定購入額=("head_stake", "sum"),
            最終購入日=("race_date", "max"),
        )
        .reset_index()
    )
    summary["的中絡み率"] = summary.apply(
        lambda row: hit_rate(int(row["的中絡み数"]), int(row["買い目登場数"])),
        axis=1,
    )
    summary["絡み回収率"] = summary.apply(lambda row: recovery_rate(row["購入額"], row["絡み払戻"]), axis=1)
    summary["選手"] = summary.apply(
        lambda row: f"{row['rider_name']}（{row['prefecture']}）" if row.get("prefecture") else row["rider_name"],
        axis=1,
    )
    return summary.sort_values(["購入額", "買い目登場数"], ascending=False)


def upsert_race(race_id: int | None, payload: dict) -> int:
    timestamp = now_text()
    fields = [
        "race_date",
        "venue",
        "race_no",
        "grade",
        "distance",
        "weather",
        "wind",
        "amount_unit",
        "status",
        "race_title",
        "line_summary",
        "race_memo",
    ]
    values = [payload[field] for field in fields]
    source_race_id = extract_source_race_id(payload.get("source_ref", "")) or extract_source_race_id(payload.get("race_memo", ""))
    line_summary = payload.get("line_summary", "").strip()
    with get_conn() as conn:
        if race_id:
            assignments = ", ".join(f"{field} = ?" for field in fields)
            conn.execute(
                f"UPDATE races SET {assignments}, updated_at = ? WHERE id = ?",
                [*values, timestamp, race_id],
            )
            if source_race_id:
                conn.execute(
                    "UPDATE races SET source_race_id = ?, updated_at = ? WHERE id = ?",
                    (source_race_id, timestamp, race_id),
                )
            saved_id = race_id
        else:
            cursor = conn.execute(
                f"""
                INSERT INTO races ({", ".join(fields)}, created_at, updated_at)
                VALUES ({", ".join("?" for _ in fields)}, ?, ?)
                """,
                [*values, timestamp, timestamp],
            )
            saved_id = int(cursor.lastrowid)
            if source_race_id:
                conn.execute("UPDATE races SET source_race_id = ? WHERE id = ?", (source_race_id, saved_id))

        if line_summary:
            result = conn.execute("SELECT first_no, second_no, third_no FROM results WHERE race_id = ?", (saved_id,)).fetchone()
            result_numbers = normalize_result(
                result["first_no"] if result else 0,
                result["second_no"] if result else 0,
                result["third_no"] if result else 0,
            )
            save_lines(conn, saved_id, line_summary, result_numbers)
        return saved_id


def upsert_rider(race_id: int, car_no: int, payload: dict) -> None:
    timestamp = now_text()
    fields = [
        "rider_name",
        "prefecture",
        "age",
        "racing_score",
        "style",
        "line_name",
        "line_position",
        "recent_results",
        "rider_comment",
        "rider_class",
        "term",
        "post_race_comment",
        "comment_eval",
        "ability_score",
        "development_score",
        "mental_score",
        "relationship_score",
        "confidence",
        "info_type",
        "human_note",
        "final_mark",
        "user_note",
    ]
    values = [payload[field] for field in fields]
    with get_conn() as conn:
        conn.execute(
            f"""
            INSERT INTO riders (
                race_id,
                car_no,
                {", ".join(fields)},
                created_at,
                updated_at
            )
            VALUES (
                ?,
                ?,
                {", ".join("?" for _ in fields)},
                ?,
                ?
            )
            ON CONFLICT(race_id, car_no) DO UPDATE SET
                {", ".join(f"{field} = excluded.{field}" for field in fields)},
                updated_at = excluded.updated_at
            """,
            [race_id, car_no, *values, timestamp, timestamp],
        )


def add_bet(race_id: int, payload: dict) -> None:
    result = fetch_result(race_id)
    result_numbers = normalize_result(result.get("first_no"), result.get("second_no"), result.get("third_no"))
    hit = int(judge_ticket_hit(payload["ticket_type"], payload["combination"], result_numbers))
    timestamp = now_text()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO bets (
                race_id,
                ticket_type,
                combination,
                amount_unit,
                stake,
                payout,
                hit,
                expected_role,
                note,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                race_id,
                payload["ticket_type"],
                payload["combination"],
                payload.get("amount_unit", default_bet_unit(race_amount_unit(fetch_race(race_id)))),
                payload["stake"],
                payload["payout"],
                hit,
                payload["expected_role"],
                payload["note"],
                timestamp,
                timestamp,
            ),
        )


def update_bet(bet_id: int, payload: dict) -> None:
    result = fetch_result(payload["race_id"])
    result_numbers = normalize_result(result.get("first_no"), result.get("second_no"), result.get("third_no"))
    hit = int(judge_ticket_hit(payload["ticket_type"], payload["combination"], result_numbers))
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE bets
            SET ticket_type = ?,
                combination = ?,
                amount_unit = ?,
                stake = ?,
                payout = ?,
                hit = ?,
                expected_role = ?,
                note = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                payload["ticket_type"],
                payload["combination"],
                payload.get("amount_unit", default_bet_unit(race_amount_unit(fetch_race(payload["race_id"])))),
                payload["stake"],
                payload["payout"],
                hit,
                payload["expected_role"],
                payload["note"],
                now_text(),
                bet_id,
            ),
        )


def upsert_result(race_id: int, payload: dict) -> None:
    timestamp = now_text()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO results (
                race_id,
                first_no,
                second_no,
                third_no,
                result_memo,
                reflection,
                cause_tag,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(race_id) DO UPDATE SET
                first_no = excluded.first_no,
                second_no = excluded.second_no,
                third_no = excluded.third_no,
                result_memo = excluded.result_memo,
                reflection = excluded.reflection,
                cause_tag = excluded.cause_tag,
                updated_at = excluded.updated_at
            """,
            (
                race_id,
                payload["first_no"],
                payload["second_no"],
                payload["third_no"],
                payload["result_memo"],
                payload["reflection"],
                payload["cause_tag"],
                timestamp,
                timestamp,
            ),
        )
    recompute_hits_for_race(race_id)


def recompute_hits_for_race(race_id: int) -> None:
    result = fetch_result(race_id)
    result_numbers = normalize_result(result.get("first_no"), result.get("second_no"), result.get("third_no"))
    bets = fetch_bets(race_id)
    if bets.empty:
        return
    with get_conn() as conn:
        for _, bet in bets.iterrows():
            hit = int(judge_ticket_hit(bet["ticket_type"], bet["combination"], result_numbers))
            conn.execute("UPDATE bets SET hit = ?, updated_at = ? WHERE id = ?", (hit, now_text(), int(bet["id"])))


def _empty_preserving_text(column: str) -> str:
    return f"{column} = CASE WHEN COALESCE({column}, '') = '' THEN excluded.{column} ELSE {column} END"


def upsert_source_rider(conn: sqlite3.Connection, race_id: int, rider) -> None:
    timestamp = now_text()
    info_type = "本人発言" if rider.rider_comment else "事実"
    conn.execute(
        """
        INSERT INTO riders (
            race_id,
            car_no,
            rider_name,
            prefecture,
            age,
            racing_score,
            style,
            line_name,
            line_position,
            rider_comment,
            rider_class,
            term,
            post_race_comment,
            info_type,
            confidence,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '中', ?, ?)
        ON CONFLICT(race_id, car_no) DO UPDATE SET
            rider_name = CASE WHEN COALESCE(riders.rider_name, '') = '' THEN excluded.rider_name ELSE riders.rider_name END,
            prefecture = CASE WHEN COALESCE(riders.prefecture, '') = '' THEN excluded.prefecture ELSE riders.prefecture END,
            age = CASE WHEN COALESCE(riders.age, 0) = 0 THEN excluded.age ELSE riders.age END,
            racing_score = CASE WHEN COALESCE(riders.racing_score, 0) = 0 THEN excluded.racing_score ELSE riders.racing_score END,
            style = CASE WHEN COALESCE(riders.style, '') = '' OR riders.style = '不明' THEN excluded.style ELSE riders.style END,
            line_name = CASE WHEN COALESCE(riders.line_name, '') = '' THEN excluded.line_name ELSE riders.line_name END,
            line_position = CASE WHEN COALESCE(riders.line_position, '') = '' OR riders.line_position = '不明' THEN excluded.line_position ELSE riders.line_position END,
            rider_comment = CASE WHEN COALESCE(riders.rider_comment, '') = '' THEN excluded.rider_comment ELSE riders.rider_comment END,
            rider_class = CASE WHEN COALESCE(riders.rider_class, '') = '' THEN excluded.rider_class ELSE riders.rider_class END,
            term = CASE WHEN COALESCE(riders.term, '') = '' THEN excluded.term ELSE riders.term END,
            post_race_comment = CASE WHEN COALESCE(riders.post_race_comment, '') = '' THEN excluded.post_race_comment ELSE riders.post_race_comment END,
            info_type = CASE WHEN COALESCE(riders.info_type, '') = '' OR riders.info_type = 'Hypothesis' THEN excluded.info_type ELSE riders.info_type END,
            updated_at = excluded.updated_at
        """,
        (
            race_id,
            int(rider.car_no),
            rider.rider_name,
            rider.prefecture,
            int(rider.age or 0),
            float(rider.racing_score or 0),
            rider.style or "不明",
            rider.line_name,
            rider.line_position or "不明",
            rider.rider_comment,
            rider.rider_class,
            rider.term,
            rider.post_race_comment,
            info_type,
            timestamp,
            timestamp,
        ),
    )


def save_result_rows(conn: sqlite3.Connection, race_id: int, result_rows: tuple) -> None:
    timestamp = now_text()
    conn.execute("DELETE FROM race_result_rows WHERE race_id = ?", (race_id,))
    for row in result_rows:
        conn.execute(
            """
            INSERT INTO race_result_rows (
                race_id,
                finish_order,
                car_no,
                rider_name,
                margin,
                agari,
                decision,
                sb,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                race_id,
                int(row.finish_order),
                int(row.car_no),
                row.rider_name,
                row.margin,
                row.agari,
                row.decision,
                row.sb,
                timestamp,
                timestamp,
            ),
        )


def save_payouts(conn: sqlite3.Connection, race_id: int, payouts: tuple) -> None:
    timestamp = now_text()
    conn.execute("DELETE FROM race_payouts WHERE race_id = ?", (race_id,))
    for payout in payouts:
        conn.execute(
            """
            INSERT INTO race_payouts (
                race_id,
                ticket_type,
                combination,
                payout,
                popularity,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                race_id,
                payout.ticket_type,
                payout.combination,
                int(payout.payout or 0),
                payout.popularity,
                timestamp,
                timestamp,
            ),
        )


def save_lines(conn: sqlite3.Connection, race_id: int, line_summary: str, result_numbers: tuple[int, ...]) -> None:
    timestamp = now_text()
    groups = parse_line_summary(line_summary)
    active_keys: list[str] = []
    for index, group in enumerate(groups, start=1):
        line_key = f"ライン{index}"
        active_keys.append(line_key)
        car_numbers = "-".join(str(number) for number in group)
        auto_status = line_function_status(group, result_numbers)
        conn.execute(
            """
            INSERT INTO race_lines (
                race_id,
                line_key,
                car_numbers,
                auto_status,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(race_id, line_key) DO UPDATE SET
                car_numbers = excluded.car_numbers,
                auto_status = excluded.auto_status,
                updated_at = excluded.updated_at
            """,
            (race_id, line_key, car_numbers, auto_status, timestamp, timestamp),
        )

    if active_keys:
        placeholders = ", ".join("?" for _ in active_keys)
        conn.execute(
            f"""
            DELETE FROM race_lines
            WHERE race_id = ?
              AND line_key NOT IN ({placeholders})
              AND COALESCE(user_status, '') = ''
              AND COALESCE(note, '') = ''
            """,
            (race_id, *active_keys),
        )


def apply_winticket_source(race_id: int, source) -> None:
    timestamp = now_text()
    result_numbers = tuple(row.car_no for row in source.result_rows[:3])
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE races
            SET source_race_id = CASE WHEN COALESCE(source_race_id, '') = '' THEN ? ELSE source_race_id END,
                source_racecard_url = ?,
                source_result_url = ?,
                source_synced_at = ?,
                line_summary = CASE WHEN COALESCE(line_summary, '') = '' THEN ? ELSE line_summary END,
                updated_at = ?
            WHERE id = ?
            """,
            (
                source.source_race_id,
                source.racecard_url,
                source.result_url,
                timestamp,
                source.line_summary,
                timestamp,
                race_id,
            ),
        )

        for rider in source.riders:
            upsert_source_rider(conn, race_id, rider)
        save_result_rows(conn, race_id, source.result_rows)
        save_payouts(conn, race_id, source.payouts)
        if source.line_summary:
            save_lines(conn, race_id, source.line_summary, result_numbers)

        result = conn.execute("SELECT * FROM results WHERE race_id = ?", (race_id,)).fetchone()
        if result_numbers:
            numbers_payload = (
                int(result_numbers[0]) if len(result_numbers) > 0 else 0,
                int(result_numbers[1]) if len(result_numbers) > 1 else 0,
                int(result_numbers[2]) if len(result_numbers) > 2 else 0,
            )
            if result and not all(int(result[key] or 0) for key in ("first_no", "second_no", "third_no")):
                conn.execute(
                    """
                    UPDATE results
                    SET first_no = ?,
                        second_no = ?,
                        third_no = ?,
                        updated_at = ?
                    WHERE race_id = ?
                    """,
                    (*numbers_payload, timestamp, race_id),
                )
            elif not result:
                conn.execute(
                    """
                    INSERT INTO results (
                        race_id,
                        first_no,
                        second_no,
                        third_no,
                        result_memo,
                        reflection,
                        cause_tag,
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, '', '', '', ?, ?)
                    """,
                    (race_id, *numbers_payload, timestamp, timestamp),
                )
    recompute_hits_for_race(race_id)


def sync_winticket_for_race(race_id: int):
    race = fetch_race(race_id)
    if not race:
        raise WinticketSourceError("選択レースが見つかりません。")
    source_race_id = race.get("source_race_id") or extract_source_race_id(race.get("race_memo", ""))
    if not source_race_id:
        raise WinticketSourceError("raceId が未登録のため、WINTICKET補完URLを解決できません。")
    source = fetch_winticket_race(
        race_date=race["race_date"],
        race_no=int(race["race_no"]),
        source_race_id=source_race_id,
        venue=race.get("venue", ""),
        race_title=race.get("race_title", ""),
    )
    apply_winticket_source(race_id, source)
    return source


def winticket_sync_candidates(races: pd.DataFrame, limit: int = 30) -> pd.DataFrame:
    if races.empty:
        return pd.DataFrame()
    source_ids = races["source_race_id"].fillna("").astype(str)
    rider_counts = races["rider_count"].fillna(0).astype(int)
    line_counts = races["line_count"].fillna(0).astype(int)
    candidates = races[(source_ids != "") & ((rider_counts == 0) | (line_counts == 0))].copy()
    return candidates.sort_values(["race_date", "id"], ascending=[False, False]).head(limit)


def sync_winticket_candidates(limit: int = 5) -> dict:
    candidates = winticket_sync_candidates(fetch_races(), limit)
    result = {"synced": [], "failed": []}
    for _, row in candidates.iterrows():
        label = f"{row['race_date']} {row['venue']} {int(row['race_no'])}R"
        try:
            source = sync_winticket_for_race(int(row["id"]))
        except Exception as exc:
            result["failed"].append({"レース": label, "理由": str(exc)})
        else:
            result["synced"].append(
                {
                    "レース": label,
                    "選手": len(source.riders),
                    "結果": len(source.result_rows),
                    "払戻": len(source.payouts),
                }
            )
    return result


def update_line_review(line_id: int, user_status: str, note: str) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE race_lines
            SET user_status = ?,
                note = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (user_status, note.strip(), now_text(), line_id),
        )


def seed_demo_data() -> None:
    races = fetch_races()
    if not races.empty:
        return

    race_id = upsert_race(
        None,
        {
            "race_date": date.today().isoformat(),
            "venue": "小田原",
            "race_no": 9,
            "grade": "F1",
            "distance": 2025,
            "weather": "晴",
            "wind": 1.5,
            "amount_unit": "円",
            "status": "予想中",
            "race_title": "初期サンプル",
            "line_summary": "1-5 / 3-7-2 / 4-6",
            "race_memo": "心理・関係性レイヤーまで試すためのサンプルです。",
        },
    )

    sample_riders = [
        (1, "佐藤 迅", "神奈川", 32, 102.4, "逃げ", "南関", "先頭", 82, 78, 76, 70, "地元で積極策のコメント。"),
        (2, "高橋 蓮", "東京", 29, 99.1, "追込", "関東", "3番手", 70, 68, 58, 65, "位置は悪くないが強調材料は薄め。"),
        (3, "森田 翔", "大阪", 35, 104.8, "捲り", "近畿", "先頭", 86, 80, 72, 75, "同期の番手と連携実績あり。"),
        (5, "中村 拓", "千葉", 38, 101.2, "差し", "南関", "番手", 78, 74, 80, 85, "1番を残す意識が出やすい組み合わせ。"),
        (7, "井上 智", "京都", 31, 103.3, "差し", "近畿", "番手", 84, 77, 74, 82, "3番との過去連携をプラス評価。"),
    ]
    for car_no, name, prefecture, age, racing, style, line, pos, ability, development, mental, relation, note in sample_riders:
        upsert_rider(
            race_id,
            car_no,
            {
                "rider_name": name,
                "prefecture": prefecture,
                "age": age,
                "racing_score": racing,
                "style": style,
                "line_name": line,
                "line_position": pos,
                "recent_results": "1着-3着-4着",
                "rider_comment": "自力で。ラインから勝ち上がれるように。",
                "rider_class": "A1",
                "term": "",
                "post_race_comment": "",
                "comment_eval": "",
                "ability_score": ability,
                "development_score": development,
                "mental_score": mental,
                "relationship_score": relation,
                "confidence": "中",
                "info_type": "Hypothesis",
                "human_note": note,
                "final_mark": "",
                "user_note": "",
            },
        )

    add_bet(
        race_id,
        {
            "ticket_type": "3連複",
            "combination": "1-3-5",
            "stake": 500,
            "payout": 0,
            "expected_role": "本線",
            "note": "能力上位と南関番手評価を合わせた候補。",
        },
    )


def apply_style() -> None:
    st.markdown(
        """
        <style>
        .block-container {
            padding-top: 1.5rem;
            max-width: 1240px;
        }
        div[data-testid="stMetric"] {
            border: 1px solid #2f3a4a;
            border-radius: 8px;
            padding: 12px 14px;
            background: #151b23;
            box-shadow: 0 1px 0 rgba(255, 255, 255, 0.04) inset;
        }
        div[data-testid="stMetric"] [data-testid="stMetricLabel"] p {
            color: #aab4c2 !important;
            font-weight: 600;
        }
        div[data-testid="stMetric"] [data-testid="stMetricValue"] {
            color: #f7fafc !important;
            font-weight: 800;
        }
        div[data-testid="stMetric"] [data-testid="stMetricDelta"] {
            color: #8fb7ff !important;
        }
        .race-note {
            border-left: 4px solid #38bdf8;
            padding: 10px 12px;
            background: #101720;
            border-radius: 4px;
            color: #e5edf5;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def race_label(row: pd.Series | dict) -> str:
    title = row.get("race_title") or "無題"
    return f"{row.get('race_date')} {row.get('venue')} {int(row.get('race_no', 0))}R | {title}"


def sidebar_select_race(races: pd.DataFrame) -> int | None:
    st.sidebar.title("zenKeirin Lab")
    page = st.sidebar.radio(
        "画面",
        ["ダッシュボード", "競輪場特徴", "レース登録", "選手評価", "買い目・結果", "振り返り"],
    )
    st.session_state["page"] = page

    if races.empty:
        st.sidebar.info("まだレースがありません。")
        with st.sidebar.expander("初期データ"):
            if st.button("サンプルレースを追加"):
                seed_demo_data()
                st.rerun()
        return None

    labels = [race_label(row) for _, row in races.iterrows()]
    selected_label = st.sidebar.selectbox("対象レース", labels)
    selected_index = labels.index(selected_label)
    selected_id = int(races.iloc[selected_index]["id"])

    with st.sidebar.expander("初期データ"):
        st.caption("DBが空のときだけサンプルを投入できます。")
        if st.button("サンプルレースを追加"):
            seed_demo_data()
            st.rerun()

    return selected_id


def render_header(selected_race: dict | None) -> None:
    st.title("zenKeirin Lab")
    st.caption("競輪の予想、買い目、結果、心理・関係性の仮説を蓄積する個人研究アプリ")
    if selected_race:
        unit = race_amount_unit(selected_race)
        st.markdown(
            f"""
            <div class="race-note">
            選択中: {selected_race.get("race_date")} / {selected_race.get("venue")} {selected_race.get("race_no")}R /
            {selected_race.get("race_title") or "無題"} / 状態: {selected_race.get("status")} / 単位: {unit}
            </div>
            """,
            unsafe_allow_html=True,
        )
        if is_tip_medal(unit):
            st.info(
                f"TIPメダル記録です。現金収支ではなく、毎日{TIP_MEDAL_DAILY_GRANT:,}枚付与、"
                f"{TIP_MEDAL_RESET_TEXT}に失効する練習用の持ち点として扱います。主目的は的中率を高めるトレーニングです。"
            )


def rate_text(done: int, total: int) -> str:
    if not total:
        return "0.0%"
    return f"{round((done / total) * 100, 1)}%"


def research_issues(row: pd.Series) -> list[str]:
    issues: list[str] = []
    if int(row.get("rider_count", 0) or 0) == 0:
        issues.append("選手未補完")
    if int(row.get("line_count", 0) or 0) == 0:
        issues.append("ライン未補完")
    if int(row.get("result_row_count", 0) or 0) == 0:
        issues.append("結果詳細なし")
    if int(row.get("line_count", 0) or 0) > 0 and int(row.get("line_review_count", 0) or 0) == 0:
        issues.append("ライン未評価")
    if int(row.get("review_done", 0) or 0) == 0:
        issues.append("振り返り未完了")
    return issues


def build_research_queue(races: pd.DataFrame, limit: int = 30) -> pd.DataFrame:
    rows = []
    for _, row in races.iterrows():
        issues = research_issues(row)
        if not issues:
            continue
        rows.append(
            {
                "日付": row["race_date"],
                "場": row["venue"],
                "R": int(row["race_no"]),
                "レース": row.get("race_title") or "無題",
                "状態": row.get("status", ""),
                "研究キュー": " / ".join(issues),
            }
        )
    return pd.DataFrame(rows).head(limit)


def line_with_names(car_numbers: str, names: dict[int, str]) -> str:
    labels = []
    for number_text in re.findall(r"\d+", car_numbers or ""):
        number = int(number_text)
        name = names.get(number, "")
        labels.append(f"{number} {name}" if name else str(number))
    return " - ".join(labels)


def render_winticket_sync_panel(selected_race_id: int | None, races: pd.DataFrame | None = None) -> None:
    st.markdown("#### WINTICKET補完")
    if not selected_race_id:
        st.caption("サイドバーでレースを選ぶと補完できます。")
        return
    race = fetch_race(selected_race_id)
    source_race_id = race.get("source_race_id") or extract_source_race_id(race.get("race_memo", ""))
    col1, col2 = st.columns([3, 1])
    with col1:
        if source_race_id:
            st.caption(f"補完キー: {source_race_id}")
            if race.get("source_synced_at"):
                st.caption(f"最終補完: {race.get('source_synced_at')}")
        else:
            st.warning("raceId が見つかりません。レース登録画面で WINTICKET/TIPSTAR URL を保存すると補完できます。")
    with col2:
        if st.button("選択レースを補完", use_container_width=True, disabled=not bool(source_race_id)):
            with st.spinner("WINTICKETから公開情報を補完しています..."):
                try:
                    source = sync_winticket_for_race(selected_race_id)
                except Exception as exc:
                    st.error(f"補完に失敗しました: {exc}")
                else:
                    st.success(
                        f"補完完了: 選手{len(source.riders)}名 / 結果{len(source.result_rows)}行 / 払戻{len(source.payouts)}件"
                    )
                    st.rerun()
    all_races = races if races is not None else fetch_races()
    pending = winticket_sync_candidates(all_races, limit=200)
    with st.expander(f"未補完レースをまとめて補完（{len(pending)}件）", expanded=False):
        if pending.empty:
            st.caption("選手未補完かつ raceId 登録済みのレースはありません。")
            return
        col_limit, col_run = st.columns([1, 2])
        limit = col_limit.selectbox("補完件数", [3, 5, 10, 20], index=1)
        if col_run.button("未補完レースを補完", use_container_width=True):
            with st.spinner("未補完レースを順番に補完しています..."):
                result = sync_winticket_candidates(int(limit))
            if result["synced"]:
                st.success(f"{len(result['synced'])}件を補完しました。")
                st.dataframe(pd.DataFrame(result["synced"]), use_container_width=True, hide_index=True)
            if result["failed"]:
                st.warning(f"{len(result['failed'])}件は補完できませんでした。")
                st.dataframe(pd.DataFrame(result["failed"]), use_container_width=True, hide_index=True)
            st.rerun()


def render_venue_feature_card(venue: str | None) -> None:
    feature = get_venue_feature(venue)
    if not feature:
        st.info("この競輪場の特徴はまだ登録されていません。")
        return

    st.markdown("#### 競輪場の特徴")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("周長", f"{feature['track_m']}m")
    col2.metric("見なし直線", f"{feature['straight_m']}m")
    col3.metric("バンク傾向", feature["bias"])
    url = venue_feature_url(venue)
    with col4:
        if url:
            st.markdown(f"[WINTICKET競輪場情報]({url})")
    st.caption(feature["summary"])
    st.caption(f"見るポイント: {feature['watch']}")


def render_line_review_form(lines: pd.DataFrame) -> None:
    if lines.empty:
        return
    labels = [
        f"{row['line_key']} {row['car_numbers']} / 自動: {row['auto_status']}"
        for _, row in lines.iterrows()
    ]
    selected_label = st.selectbox("評価を上書きするライン", labels)
    selected_line = lines.iloc[labels.index(selected_label)]
    status_value = selected_line["user_status"] if selected_line["user_status"] in LINE_STATUS_OPTIONS else ""
    with st.form("line_review_form"):
        col1, col2 = st.columns([1, 3])
        user_status = col1.selectbox(
            "自分の判定",
            LINE_STATUS_OPTIONS,
            index=LINE_STATUS_OPTIONS.index(status_value),
        )
        note = col2.text_area("ラインメモ", value=selected_line["note"], height=80)
        submitted = st.form_submit_button("ライン評価を保存", use_container_width=True)
    if submitted:
        update_line_review(int(selected_line["id"]), user_status, note)
        st.success("ライン評価を保存しました。")
        st.rerun()


def render_selected_race_research(selected_race_id: int | None) -> None:
    st.subheader("選択レース詳細")
    if not selected_race_id:
        st.info("サイドバーで対象レースを選ぶと、着順・ライン・コメント・買い目をまとめて確認できます。")
        return

    race = fetch_race(selected_race_id)
    riders = fetch_riders(selected_race_id)
    result_rows = fetch_result_rows(selected_race_id)
    payouts = fetch_payouts(selected_race_id)
    lines = fetch_lines(selected_race_id)
    bets = fetch_bets(selected_race_id)
    names = rider_name_map(selected_race_id)

    st.markdown(f"#### {race_label(race)}")
    if race.get("source_racecard_url"):
        st.markdown(f"[WINTICKET出走表]({race['source_racecard_url']}) / [WINTICKET結果]({race['source_result_url']})")
    render_venue_feature_card(race.get("venue"))

    if result_rows.empty:
        result = fetch_result(selected_race_id)
        if result:
            result_numbers = normalize_result(result.get("first_no"), result.get("second_no"), result.get("third_no"))
            st.info(f"詳細結果は未補完です。着順メモ: {'-'.join(str(number) for number in result_numbers) or '未入力'}")
        else:
            st.info("結果は未入力です。")
    else:
        result_view = result_rows.copy()
        for column in ["ライン", "位置", "前検コメント", "レース後コメント", "自分メモ"]:
            result_view[column] = ""
        if not riders.empty:
            rider_lookup = riders.set_index("car_no").to_dict("index")
            result_view["ライン"] = result_view["car_no"].apply(lambda car: rider_lookup.get(car, {}).get("line_name", ""))
            result_view["位置"] = result_view["car_no"].apply(lambda car: rider_lookup.get(car, {}).get("line_position", ""))
            result_view["前検コメント"] = result_view["car_no"].apply(lambda car: rider_lookup.get(car, {}).get("rider_comment", ""))
            result_view["レース後コメント"] = result_view["car_no"].apply(
                lambda car: rider_lookup.get(car, {}).get("post_race_comment", "")
            )
            result_view["自分メモ"] = result_view["car_no"].apply(lambda car: rider_lookup.get(car, {}).get("user_note", ""))
        st.dataframe(
            result_view[
                [
                    "finish_order",
                    "car_no",
                    "rider_name",
                    "ライン",
                    "位置",
                    "margin",
                    "agari",
                    "decision",
                    "sb",
                    "前検コメント",
                    "レース後コメント",
                    "自分メモ",
                ]
            ].rename(
                columns={
                    "finish_order": "着順",
                    "car_no": "車番",
                    "rider_name": "選手名",
                    "margin": "着差",
                    "agari": "上り",
                    "decision": "決まり手",
                    "sb": "S/B",
                }
            ),
            use_container_width=True,
            hide_index=True,
        )

    col_left, col_right = st.columns(2)
    with col_left:
        st.markdown("#### ライン研究")
        if lines.empty:
            st.info("ラインは未補完です。WINTICKET補完またはレース登録のライン構成から追加します。")
        else:
            line_view = lines.copy()
            line_view["名前付きライン"] = line_view["car_numbers"].apply(lambda value: line_with_names(value, names))
            line_view["採用判定"] = line_view.apply(
                lambda row: row["user_status"] if row["user_status"] else row["auto_status"],
                axis=1,
            )
            st.dataframe(
                line_view[["line_key", "名前付きライン", "auto_status", "user_status", "採用判定", "note"]].rename(
                    columns={
                        "line_key": "ライン",
                        "auto_status": "自動判定",
                        "user_status": "自分の判定",
                        "note": "メモ",
                    }
                ),
                use_container_width=True,
                hide_index=True,
            )
            render_line_review_form(lines)

    with col_right:
        st.markdown("#### 投票癖")
        if bets.empty:
            st.info("買い目は未登録です。")
        else:
            bets_view = bets.copy()
            bets_view["名前付き買い目"] = bets_view["combination"].apply(lambda value: format_combination_with_names(value, names))
            st.dataframe(
                bets_view[
                    [
                        "ticket_type",
                        "名前付き買い目",
                        "amount_unit",
                        "stake",
                        "payout",
                        "hit",
                        "expected_role",
                        "note",
                    ]
                ].rename(
                    columns={
                        "ticket_type": "券種",
                        "amount_unit": "単位",
                        "stake": "購入",
                        "payout": "払戻",
                        "hit": "的中",
                        "expected_role": "位置づけ",
                        "note": "メモ",
                    }
                ),
                use_container_width=True,
                hide_index=True,
            )

    if not payouts.empty:
        st.markdown("#### 払戻詳細")
        st.dataframe(
            payouts[["ticket_type", "combination", "payout", "popularity"]].rename(
                columns={
                    "ticket_type": "賭け式",
                    "combination": "組番",
                    "payout": "払戻",
                    "popularity": "人気",
                }
            ),
            use_container_width=True,
            hide_index=True,
        )

    if not riders.empty:
        st.markdown("#### 選手コメント・検証メモ")
        comment_cols = [
            "car_no",
            "rider_name",
            "rider_class",
            "term",
            "line_name",
            "line_position",
            "rider_comment",
            "post_race_comment",
            "comment_eval",
            "human_note",
            "user_note",
        ]
        st.dataframe(
            riders[comment_cols].rename(
                columns={
                    "car_no": "車番",
                    "rider_name": "選手名",
                    "rider_class": "級班",
                    "term": "期",
                    "line_name": "ライン",
                    "line_position": "位置",
                    "rider_comment": "前検コメント",
                    "post_race_comment": "レース後コメント",
                    "comment_eval": "コメント検証",
                    "human_note": "心理・関係性メモ",
                    "user_note": "自分メモ",
                }
            ),
            use_container_width=True,
            hide_index=True,
        )


def render_rider_purchase_insights() -> None:
    st.subheader("よく買っている選手")
    summary = fetch_rider_purchase_summary()
    if summary.empty:
        st.info("選手名が補完されたレースの買い目が増えると、よく買っている選手を表示できます。")
        return

    units = sorted(summary["amount_unit"].dropna().unique().tolist())
    col_filter, col_metric = st.columns([1, 1])
    selected_unit = col_filter.selectbox("表示単位", units, key="rider_purchase_unit")
    sort_metric = col_metric.selectbox("見る指標", ["購入額", "買い目登場数", "頭固定数", "的中絡み率"], key="rider_purchase_metric")
    view = summary[summary["amount_unit"] == selected_unit].copy()
    if view.empty:
        st.info("選択した単位では、選手名付きの買い目がまだありません。")
        return

    top = view.sort_values([sort_metric, "購入額", "買い目登場数"], ascending=False).head(15)
    top_rider = top.iloc[0]
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("対象選手", f"{len(view)}人")
    col2.metric("買い目登場", f"{int(view['買い目登場数'].sum()):,}回")
    col3.metric("最多購入", str(top_rider["選手"]))
    col4.metric("購入額", amount_text(int(top_rider["購入額"]), selected_unit))

    fig = horizontal_bar(
        top,
        label_col="選手",
        value_col=sort_metric,
        color_col="的中絡み率",
        continuous_color=True,
        title=f"よく買っている選手 TOP{len(top)}",
        x_title=sort_metric,
        hover_data=["購入レース数", "買い目登場数", "購入額", "頭固定数", "的中絡み率", "絡み回収率", "最終購入日"],
        text_template="%{x:,.0f}" if sort_metric != "的中絡み率" else "%{x:.1f}%",
        color_scale=["#475569", "#f59e0b", "#22c55e"],
    )
    st.plotly_chart(fig, use_container_width=True)
    st.caption("同じ買い目に含まれる複数選手へ購入額をそれぞれ集計します。総購入額ではなく、買い癖の濃さを見る指標です。")

    table = view.sort_values(["購入額", "買い目登場数"], ascending=False).head(30)
    st.dataframe(
        table[
            [
                "選手",
                "amount_unit",
                "購入レース数",
                "買い目登場数",
                "購入額",
                "頭固定数",
                "頭固定購入額",
                "的中絡み数",
                "的中絡み率",
                "絡み払戻",
                "絡み回収率",
                "最終購入日",
            ]
        ].rename(columns={"amount_unit": "単位"}),
        use_container_width=True,
        hide_index=True,
    )


def render_dashboard(races: pd.DataFrame, selected_race_id: int | None) -> None:
    render_header(None)
    if races.empty:
        st.info("まずはレース登録から始めます。サイドバーのサンプル投入も使えます。")
        return

    bets = fetch_all_bets()
    total_stake = int(bets["stake"].sum()) if not bets.empty else 0
    total_payout = int(bets["payout"].sum()) if not bets.empty else 0
    hit_count = int(bets["hit"].sum()) if not bets.empty else 0
    unit = summary_unit(bets)
    race_count = len(races)
    rider_done = int((races["rider_count"] > 0).sum())
    line_done = int((races["line_count"] > 0).sum())
    review_done = int((races["review_done"] > 0).sum())

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("登録レース", f"{len(races)}")
    col2.metric("選手補完率", rate_text(rider_done, race_count), f"{rider_done}/{race_count}")
    col3.metric("ライン補完率", rate_text(line_done, race_count), f"{line_done}/{race_count}")
    col4.metric("振り返り完了率", rate_text(review_done, race_count), f"{review_done}/{race_count}")
    col5.metric("的中率", f"{hit_rate(hit_count, len(bets))}%" if not bets.empty else "0.0%")

    render_winticket_sync_panel(selected_race_id, races)

    st.markdown("#### 投票トレーニング集計")
    if bets.empty:
        st.info("買い目を登録すると、投票癖と的中精度の分析が始まります。")
    elif is_tip_medal(unit):
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("利用合計", amount_text(total_stake, unit))
        col2.metric("的中払戻", amount_text(total_payout, unit))
        col3.metric("残り目安", amount_text(remaining_tip_medals(total_stake), unit))
        col4.metric(net_label(unit), amount_text(profit(total_stake, total_payout), unit))
        st.caption(
            f"TIPメダルは毎日{TIP_MEDAL_DAILY_GRANT:,}枚から始まり、{TIP_MEDAL_RESET_TEXT}に失効します。"
            "ここでは現金ではなく、買い目精度を鍛える持ち点として扱います。"
        )
    elif unit == "単位混在":
        col1, col2, col3 = st.columns(3)
        col1.metric("購入合計", amount_summary_text(bets, "stake"))
        col2.metric("払戻合計", amount_summary_text(bets, "payout"))
        col3.metric("差分", profit_summary_text(bets))
    else:
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("購入合計", amount_text(total_stake, unit))
        col2.metric("払戻合計", amount_text(total_payout, unit))
        col3.metric(net_label(unit), amount_text(profit(total_stake, total_payout), unit))
        col4.metric("回収率", f"{recovery_rate(total_stake, total_payout)}%")

    queue = build_research_queue(races)
    st.subheader("研究キュー")
    if queue.empty:
        st.success("未補完・未評価のレースはありません。いい感じに研究ノートが育っています。")
    else:
        st.dataframe(queue, use_container_width=True, hide_index=True)

    st.subheader("競輪場特徴サマリ")
    venue_counts = races.groupby("venue").size().sort_values(ascending=False)
    top_venues = venue_counts.head(12).index.tolist()
    venue_summary = pd.DataFrame(venue_feature_rows(top_venues))
    venue_summary["登録レース数"] = venue_summary["競輪場"].map(venue_counts.to_dict()).fillna(0).astype(int)
    st.dataframe(
        venue_summary[["競輪場", "登録レース数", "周長", "見なし直線", "傾向", "特徴", "注意点"]],
        use_container_width=True,
        hide_index=True,
    )

    st.subheader("最近のレース")
    races_view = races.copy()
    races_view["差分"] = races_view["total_payout"] - races_view["total_stake"]
    races_view["回収率"] = races_view.apply(
        lambda row: recovery_rate(row["total_stake"], row["total_payout"]),
        axis=1,
    )
    races_view["研究キュー"] = races_view.apply(lambda row: " / ".join(research_issues(row)) or "完了", axis=1)
    if not bets.empty:
        unit_by_race = bets.groupby("race_id")["amount_unit"].nunique()
        races_view["amount_unit"] = races_view.apply(
            lambda row: "単位混在" if unit_by_race.get(row["id"], 0) > 1 else row["amount_unit"],
            axis=1,
        )
    st.dataframe(
        races_view[
            [
                "race_date",
                "venue",
                "race_no",
                "status",
                "amount_unit",
                "rider_count",
                "line_count",
                "result_row_count",
                "bet_count",
                "hit_count",
                "total_stake",
                "total_payout",
                "差分",
                "回収率",
                "研究キュー",
            ]
        ].rename(
            columns={
                "race_date": "日付",
                "venue": "場",
                "race_no": "R",
                "status": "状態",
                "amount_unit": "単位",
                "rider_count": "選手数",
                "line_count": "ライン数",
                "result_row_count": "結果詳細",
                "bet_count": "買い目数",
                "hit_count": "的中数",
                "total_stake": "購入",
                "total_payout": "払戻",
                "差分": net_label(unit),
            }
        ),
        use_container_width=True,
        hide_index=True,
    )

    if not bets.empty:
        col_a, col_b = st.columns(2)
        with col_a:
            role_summary = (
                bets.assign(expected_role=bets["expected_role"].replace("", "未分類").fillna("未分類"))
                .groupby("expected_role")
                .agg(件数=("id", "count"), 的中=("hit", "sum"), 購入=("stake", "sum"), 払戻=("payout", "sum"))
                .reset_index()
            )
            role_summary["的中率"] = role_summary.apply(lambda row: hit_rate(int(row["的中"]), int(row["件数"])), axis=1)
            fig = horizontal_bar(
                role_summary,
                label_col="expected_role",
                value_col="的中率",
                color_col="件数",
                continuous_color=True,
                title="位置づけ別 的中率",
                x_title="的中率（%）",
                hover_data=["件数", "的中", "購入", "払戻"],
                text_template="%{x:.1f}%",
                color_scale=["#475569", "#38bdf8", "#22c55e"],
            )
            fig.update_xaxes(range=[0, 100])
            st.plotly_chart(fig, use_container_width=True)
        with col_b:
            line_summary = (
                races_view.groupby("研究キュー")
                .agg(レース数=("id", "count"), 的中数=("hit_count", "sum"), 買い目数=("bet_count", "sum"))
                .reset_index()
            )
            fig = horizontal_bar(
                line_summary,
                label_col="研究キュー",
                value_col="レース数",
                color_col="的中数",
                continuous_color=True,
                title="研究キュー別 レース数",
                x_title="レース数",
                hover_data=["的中数", "買い目数"],
                text_template="%{x:,.0f}",
                color_scale=["#475569", "#f59e0b", "#22c55e"],
            )
            st.plotly_chart(fig, use_container_width=True)

        st.markdown("#### 券種別・場別の癖")
        ticket_summary = (
            bets.groupby(["amount_unit", "ticket_type"])
            .agg(購入=("stake", "sum"), 払戻=("payout", "sum"), 的中=("hit", "sum"), 件数=("id", "count"))
            .reset_index()
        )
        ticket_summary["回収率"] = ticket_summary.apply(lambda row: recovery_rate(row["購入"], row["払戻"]), axis=1)
        ticket_summary["券種"] = ticket_summary["ticket_type"] + " / " + ticket_summary["amount_unit"]
        venue_summary = (
            bets.groupby(["amount_unit", "venue"])
            .agg(購入=("stake", "sum"), 払戻=("payout", "sum"), 的中=("hit", "sum"), 件数=("id", "count"))
            .reset_index()
        )
        venue_summary["差分"] = venue_summary["払戻"] - venue_summary["購入"]
        venue_summary["場"] = venue_summary["venue"] + " / " + venue_summary["amount_unit"]
        col_c, col_d = st.columns(2)
        with col_c:
            fig = horizontal_bar(
                ticket_summary,
                label_col="券種",
                value_col="回収率",
                color_col="件数",
                continuous_color=True,
                title="券種別 回収率",
                x_title="回収率（%）",
                hover_data=["購入", "払戻", "的中", "件数"],
                text_template="%{x:.1f}%",
                color_scale=["#475569", "#38bdf8", "#22c55e"],
            )
            st.plotly_chart(fig, use_container_width=True)
        with col_d:
            fig = horizontal_bar(
                venue_summary,
                label_col="場",
                value_col="差分",
                color_col="差分",
                continuous_color=True,
                title=f"競輪場別 {net_label(unit)}",
                x_title=net_label(unit),
                hover_data=["購入", "払戻", "的中", "件数"],
                text_template="%{x:,.0f}",
                color_scale=["#ef4444", "#94a3b8", "#22c55e"],
            )
            fig.update_layout(coloraxis_cmid=0)
            st.plotly_chart(fig, use_container_width=True)

    render_rider_purchase_insights()
    render_selected_race_research(selected_race_id)


def render_venue_features_page(races: pd.DataFrame, selected_race_id: int | None) -> None:
    selected_race = fetch_race(selected_race_id)
    render_header(selected_race if selected_race else None)
    st.subheader("競輪場特徴")

    venues = sorted(races["venue"].dropna().unique().tolist()) if not races.empty else []
    if selected_race:
        render_venue_feature_card(selected_race.get("venue"))

    rows = venue_feature_rows(venues)
    features = pd.DataFrame(rows)
    st.markdown("#### 登録レースに出ている競輪場")
    st.dataframe(features, use_container_width=True, hide_index=True)

    if venues:
        selected_venue = st.selectbox(
            "競輪場を詳しく見る",
            venues,
            index=venues.index(selected_race["venue"]) if selected_race and selected_race.get("venue") in venues else 0,
        )
        render_venue_feature_card(selected_venue)
        url = venue_feature_url(selected_venue)
        if url:
            st.markdown(f"[{selected_venue}競輪場の公開情報を開く]({url})")


def render_race_form(selected_race_id: int | None) -> None:
    selected_race = fetch_race(selected_race_id)
    selected_rider_count = len(fetch_riders(selected_race_id)) if selected_race_id else 0
    render_header(selected_race)
    st.subheader("レース登録")

    default_date = date.today()
    if selected_race.get("race_date"):
        default_date = date.fromisoformat(selected_race["race_date"])

    with st.form("race_form"):
        col1, col2, col3, col4 = st.columns(4)
        race_date = col1.date_input("日付", value=default_date)
        venue = col2.text_input("開催場", value=selected_race.get("venue", ""))
        race_no = col3.number_input("レース番号", min_value=1, max_value=12, value=int(selected_race.get("race_no", 1) or 1))
        grade = col4.text_input("グレード", value=selected_race.get("grade", ""))

        col5, col6, col7, col8, col9 = st.columns(5)
        distance = col5.number_input("距離", min_value=0, value=int(selected_race.get("distance", 0) or 0), step=25)
        weather = col6.text_input("天候", value=selected_race.get("weather", ""))
        wind = col7.number_input("風速", value=float(selected_race.get("wind", 0) or 0), step=0.1)
        amount_unit_value = race_amount_unit(selected_race)
        amount_unit = col8.selectbox(
            "記録単位",
            AMOUNT_UNITS,
            index=AMOUNT_UNITS.index(amount_unit_value) if amount_unit_value in AMOUNT_UNITS else 0,
        )
        status_value = selected_race.get("status", "予想中")
        status = col9.selectbox("状態", STATUS_OPTIONS, index=STATUS_OPTIONS.index(status_value) if status_value in STATUS_OPTIONS else 0)

        race_title = st.text_input("レース名・メモ見出し", value=selected_race.get("race_title", ""))
        source_default = (
            selected_race.get("source_result_url")
            or selected_race.get("source_racecard_url")
            or selected_race.get("source_race_id")
            or extract_source_race_id(selected_race.get("race_memo", ""))
        )
        source_ref = st.text_input("WINTICKET/TIPSTAR URL・raceId", value=source_default)
        line_summary = st.text_area("ライン構成", value=selected_race.get("line_summary", ""), height=90)
        race_memo = st.text_area("予想前メモ", value=selected_race.get("race_memo", ""), height=120)
        auto_sync_source = st.checkbox(
            "保存後に選手名・結果を自動補完",
            value=bool(source_default and selected_rider_count == 0),
        )

        col_create, col_update = st.columns(2)
        create_clicked = col_create.form_submit_button("新規レースとして登録", use_container_width=True)
        update_clicked = col_update.form_submit_button("選択中レースを更新", use_container_width=True, disabled=not bool(selected_race_id))

    if create_clicked or update_clicked:
        if not venue.strip():
            st.error("開催場を入力してください。")
            return
        payload = {
            "race_date": race_date.isoformat(),
            "venue": venue.strip(),
            "race_no": int(race_no),
            "grade": grade.strip(),
            "distance": int(distance),
            "weather": weather.strip(),
            "wind": float(wind),
            "amount_unit": amount_unit,
            "status": status,
            "race_title": race_title.strip(),
            "source_ref": source_ref.strip(),
            "line_summary": line_summary.strip(),
            "race_memo": race_memo.strip(),
        }
        new_id = upsert_race(selected_race_id if update_clicked else None, payload)
        st.success(f"レースを保存しました。ID: {new_id}")
        source_race_id = extract_source_race_id(source_ref) or extract_source_race_id(race_memo)
        if auto_sync_source and source_race_id:
            with st.spinner("WINTICKETから選手名・結果を補完しています..."):
                try:
                    source = sync_winticket_for_race(new_id)
                except Exception as exc:
                    st.warning(f"レースは保存しましたが、公開情報の補完に失敗しました: {exc}")
                else:
                    st.success(f"補完完了: 選手{len(source.riders)}名 / 結果{len(source.result_rows)}行 / 払戻{len(source.payouts)}件")
        st.rerun()


def render_riders(selected_race_id: int | None) -> None:
    if not selected_race_id:
        render_header(None)
        st.info("先にレースを登録してください。")
        return

    selected_race = fetch_race(selected_race_id)
    render_header(selected_race)
    st.subheader("選手評価")

    riders = fetch_riders(selected_race_id)
    car_no = st.selectbox("入力する車番", list(range(1, 10)))
    existing = fetch_rider_by_car(selected_race_id, int(car_no))

    with st.form("rider_form"):
        col1, col2, col3, col4, col5, col6 = st.columns(6)
        rider_name = col1.text_input("選手名", value=existing.get("rider_name", ""))
        prefecture = col2.text_input("府県", value=existing.get("prefecture", ""))
        age = col3.number_input("年齢", min_value=0, max_value=80, value=int(existing.get("age", 0) or 0))
        racing_score = col4.number_input("競走得点", min_value=0.0, max_value=130.0, value=float(existing.get("racing_score", 0) or 0), step=0.1)
        rider_class = col5.text_input("級班", value=existing.get("rider_class", ""))
        term = col6.text_input("期", value=existing.get("term", ""))

        col7, col8, col9, col10 = st.columns(4)
        style_value = existing.get("style", "不明")
        style = col7.selectbox("脚質", STYLE_OPTIONS, index=STYLE_OPTIONS.index(style_value) if style_value in STYLE_OPTIONS else 5)
        line_name = col8.text_input("ライン名", value=existing.get("line_name", ""))
        position_value = existing.get("line_position", "不明")
        line_position = col9.selectbox(
            "ライン位置",
            POSITION_OPTIONS,
            index=POSITION_OPTIONS.index(position_value) if position_value in POSITION_OPTIONS else 5,
        )
        mark_value = existing.get("final_mark", "")
        final_mark = col10.selectbox("予想印", MARK_OPTIONS, index=MARK_OPTIONS.index(mark_value) if mark_value in MARK_OPTIONS else 0)

        st.markdown("#### 3層評価")
        col11, col12, col13, col14 = st.columns(4)
        score_ability = col11.slider("能力評価", 0, 100, int(existing.get("ability_score", 50) or 50))
        score_development = col12.slider("展開評価", 0, 100, int(existing.get("development_score", 50) or 50))
        score_mental = col13.slider("心理評価", 0, 100, int(existing.get("mental_score", 50) or 50))
        score_relationship = col14.slider("関係性評価", 0, 100, int(existing.get("relationship_score", 50) or 50))

        col15, col16 = st.columns(2)
        confidence_value = existing.get("confidence", "中")
        confidence = col15.selectbox(
            "確信度",
            CONFIDENCE_LEVELS,
            index=CONFIDENCE_LEVELS.index(confidence_value) if confidence_value in CONFIDENCE_LEVELS else 1,
        )
        info_value = existing.get("info_type", "Hypothesis")
        info_type = col16.selectbox("情報区分", INFO_TYPES, index=INFO_TYPES.index(info_value) if info_value in INFO_TYPES else 3)

        recent_results = st.text_input("直近成績", value=existing.get("recent_results", ""))
        rider_comment = st.text_area("本人コメント", value=existing.get("rider_comment", ""), height=90)
        post_race_comment = st.text_area("レース後コメント", value=existing.get("post_race_comment", ""), height=80)
        comment_eval = st.text_area("コメント検証", value=existing.get("comment_eval", ""), height=80)
        human_note = st.text_area("心理・関係性メモ", value=existing.get("human_note", ""), height=100)
        user_note = st.text_area("自分の予想メモ", value=existing.get("user_note", ""), height=100)

        submitted = st.form_submit_button("選手評価を保存", use_container_width=True)

    if submitted:
        if not rider_name.strip():
            st.error("選手名を入力してください。")
            return
        upsert_rider(
            selected_race_id,
            int(car_no),
            {
                "rider_name": rider_name.strip(),
                "prefecture": prefecture.strip(),
                "age": int(age),
                "racing_score": float(racing_score),
                "style": style,
                "line_name": line_name.strip(),
                "line_position": line_position,
                "recent_results": recent_results.strip(),
                "rider_comment": rider_comment.strip(),
                "rider_class": rider_class.strip(),
                "term": term.strip(),
                "post_race_comment": post_race_comment.strip(),
                "comment_eval": comment_eval.strip(),
                "ability_score": int(score_ability),
                "development_score": int(score_development),
                "mental_score": int(score_mental),
                "relationship_score": int(score_relationship),
                "confidence": confidence,
                "info_type": info_type,
                "human_note": human_note.strip(),
                "final_mark": final_mark,
                "user_note": user_note.strip(),
            },
        )
        st.success("選手評価を保存しました。")
        st.rerun()

    if riders.empty:
        st.info("選手評価を入力すると、能力基準と心理・関係性込みの比較が出ます。")
        return

    st.subheader("予想比較")
    display_cols = [
        "car_no",
        "rider_name",
        "prefecture",
        "rider_class",
        "term",
        "style",
        "line_name",
        "line_position",
        "final_mark",
        "racing_score",
        "ability_score",
        "development_score",
        "mental_score",
        "relationship_score",
        "能力基準",
        "心理関係",
        "総合",
        "confidence",
        "info_type",
        "rider_comment",
        "human_note",
        "comment_eval",
    ]
    st.dataframe(
        riders[display_cols].rename(
            columns={
                "car_no": "車番",
                "rider_name": "選手名",
                "prefecture": "府県",
                "rider_class": "級班",
                "term": "期",
                "style": "脚質",
                "line_name": "ライン",
                "line_position": "位置",
                "final_mark": "印",
                "racing_score": "競走得点",
                "ability_score": "能力",
                "development_score": "展開",
                "mental_score": "心理",
                "relationship_score": "関係性",
                "confidence": "確信度",
                "info_type": "情報区分",
                "rider_comment": "本人コメント",
                "human_note": "心理・関係性メモ",
                "comment_eval": "コメント検証",
            }
        ),
        use_container_width=True,
        hide_index=True,
    )

    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("#### 能力・展開だけの上位")
        st.dataframe(
            riders.sort_values("能力基準", ascending=False)[["car_no", "rider_name", "能力基準", "final_mark"]]
            .head(5)
            .rename(columns={"car_no": "車番", "rider_name": "選手名", "final_mark": "印"}),
            use_container_width=True,
            hide_index=True,
        )
    with col_b:
        st.markdown("#### 心理・関係性込みの上位")
        st.dataframe(
            riders.sort_values("総合", ascending=False)[["car_no", "rider_name", "総合", "心理関係", "final_mark"]]
            .head(5)
            .rename(columns={"car_no": "車番", "rider_name": "選手名", "final_mark": "印"}),
            use_container_width=True,
            hide_index=True,
        )


def render_bets_and_results(selected_race_id: int | None) -> None:
    if not selected_race_id:
        render_header(None)
        st.info("先にレースを登録してください。")
        return

    selected_race = fetch_race(selected_race_id)
    unit = race_amount_unit(selected_race)
    render_header(selected_race)
    st.subheader("買い目・結果")

    riders = fetch_riders(selected_race_id)
    names = rider_name_map(selected_race_id)
    if not riders.empty:
        st.caption("入力済み選手")
        st.dataframe(
            riders[["car_no", "rider_name", "final_mark", "総合", "line_name", "line_position"]].rename(
                columns={
                    "car_no": "車番",
                    "rider_name": "選手名",
                    "final_mark": "印",
                    "line_name": "ライン",
                    "line_position": "位置",
                }
            ),
            use_container_width=True,
            hide_index=True,
        )

    result_rows = fetch_result_rows(selected_race_id)
    if not result_rows.empty:
        st.caption("選手名付き結果詳細")
        st.dataframe(
            result_rows[["finish_order", "car_no", "rider_name", "margin", "agari", "decision", "sb"]].rename(
                columns={
                    "finish_order": "着順",
                    "car_no": "車番",
                    "rider_name": "選手名",
                    "margin": "着差",
                    "agari": "上り",
                    "decision": "決まり手",
                    "sb": "S/B",
                }
            ),
            use_container_width=True,
            hide_index=True,
        )

    col_left, col_right = st.columns(2)
    with col_left:
        with st.form("bet_form"):
            ticket_type = st.selectbox("券種", TICKET_TYPES, index=6)
            combination = st.text_input("買い目", placeholder="例: 1-3-5")
            col0, col1, col2 = st.columns(3)
            bet_unit = col0.selectbox(
                "単位",
                BET_AMOUNT_UNITS,
                index=BET_AMOUNT_UNITS.index(default_bet_unit(unit)),
            )
            stake = col1.number_input(f"購入（{bet_unit}）", min_value=0, value=100, step=100)
            payout = col2.number_input(f"払戻（{bet_unit}）", min_value=0, value=0, step=100)
            expected_role = st.text_input("位置づけ", placeholder="本線 / 押さえ / 穴 / 見送り検証")
            note = st.text_area("買い目メモ", height=90)
            submitted = st.form_submit_button("買い目を追加", use_container_width=True)
        if submitted:
            if not combination.strip():
                st.error("買い目を入力してください。")
            else:
                add_bet(
                    selected_race_id,
                    {
                        "ticket_type": ticket_type,
                        "combination": combination.strip(),
                        "amount_unit": bet_unit,
                        "stake": int(stake),
                        "payout": int(payout),
                        "expected_role": expected_role.strip(),
                        "note": note.strip(),
                    },
                )
                st.success("買い目を追加しました。")
                st.rerun()

    with col_right:
        result = fetch_result(selected_race_id)
        with st.form("result_form"):
            st.markdown("#### 結果入力")
            col1, col2, col3 = st.columns(3)
            first_no = col1.number_input("1着", min_value=0, max_value=9, value=int(result.get("first_no", 0) or 0))
            second_no = col2.number_input("2着", min_value=0, max_value=9, value=int(result.get("second_no", 0) or 0))
            third_no = col3.number_input("3着", min_value=0, max_value=9, value=int(result.get("third_no", 0) or 0))
            cause_tag = st.text_input("主な外れ・的中要因", value=result.get("cause_tag", ""))
            result_memo = st.text_area("レース結果メモ", value=result.get("result_memo", ""), height=90)
            reflection = st.text_area("振り返りメモ", value=result.get("reflection", ""), height=100)
            submitted_result = st.form_submit_button("結果を保存して的中判定", use_container_width=True)
        if submitted_result:
            upsert_result(
                selected_race_id,
                {
                    "first_no": int(first_no),
                    "second_no": int(second_no),
                    "third_no": int(third_no),
                    "result_memo": result_memo.strip(),
                    "reflection": reflection.strip(),
                    "cause_tag": cause_tag.strip(),
                },
            )
            st.success("結果を保存し、買い目の的中判定を更新しました。")
            st.rerun()

    bets = fetch_bets(selected_race_id)
    if bets.empty:
        st.info("買い目を登録すると、的中判定と成績が表示されます。")
        return

    st.subheader("登録済み買い目")
    total_stake = int(bets["stake"].sum())
    total_payout = int(bets["payout"].sum())
    bet_unit_summary = summary_unit(bets)
    if is_tip_medal(bet_unit_summary):
        col1, col2, col3, col4, col5 = st.columns(5)
        col1.metric("買い目数", f"{len(bets)}")
        col2.metric("的中率", f"{hit_rate(int(bets['hit'].sum()), len(bets))}%")
        col3.metric("利用", amount_text(total_stake, bet_unit_summary))
        col4.metric("残り目安", amount_text(remaining_tip_medals(total_stake), bet_unit_summary))
        col5.metric(net_label(bet_unit_summary), amount_text(profit(total_stake, total_payout), bet_unit_summary))
        st.caption(
            f"TIPメダルは毎日{TIP_MEDAL_DAILY_GRANT:,}枚付与、{TIP_MEDAL_RESET_TEXT}に失効。"
            "この画面の差分は現金の損益ではなく、的中率トレーニング用の参考値です。"
        )
    elif bet_unit_summary == "単位混在":
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("買い目数", f"{len(bets)}")
        col2.metric("的中率", f"{hit_rate(int(bets['hit'].sum()), len(bets))}%")
        col3.metric("購入", amount_summary_text(bets, "stake"))
        col4.metric("差分", profit_summary_text(bets))
    else:
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("買い目数", f"{len(bets)}")
        col2.metric("的中率", f"{hit_rate(int(bets['hit'].sum()), len(bets))}%")
        col3.metric("回収率", f"{recovery_rate(total_stake, total_payout)}%")
        col4.metric(net_label(bet_unit_summary), amount_text(profit(total_stake, total_payout), bet_unit_summary))

    bets_view = bets.copy()
    bets_view["名前付き買い目"] = bets_view["combination"].apply(lambda value: format_combination_with_names(value, names))
    st.dataframe(
        bets_view[
            [
                "id",
                "ticket_type",
                "combination",
                "名前付き買い目",
                "amount_unit",
                "stake",
                "payout",
                "hit",
                "収支",
                "expected_role",
                "note",
            ]
        ].rename(
            columns={
                "id": "ID",
                "ticket_type": "券種",
                "combination": "買い目",
                "amount_unit": "単位",
                "stake": "購入",
                "payout": "払戻",
                "hit": "的中",
                "収支": net_label(bet_unit_summary),
                "expected_role": "位置づけ",
                "note": "メモ",
            }
        ),
        use_container_width=True,
        hide_index=True,
    )

    st.markdown("#### 買い目の更新")
    bet_labels = [f"#{int(row['id'])} {row['ticket_type']} {row['combination']}" for _, row in bets.iterrows()]
    selected_bet_label = st.selectbox("更新する買い目", bet_labels)
    selected_bet = bets.iloc[bet_labels.index(selected_bet_label)]
    with st.form("update_bet_form"):
        col1, col2, col3, col4, col5 = st.columns(5)
        updated_ticket = col1.selectbox(
            "券種",
            TICKET_TYPES,
            index=TICKET_TYPES.index(selected_bet["ticket_type"]) if selected_bet["ticket_type"] in TICKET_TYPES else 0,
        )
        updated_combo = col2.text_input("買い目", value=selected_bet["combination"])
        updated_unit = col3.selectbox(
            "単位",
            BET_AMOUNT_UNITS,
            index=BET_AMOUNT_UNITS.index(selected_bet["amount_unit"])
            if selected_bet["amount_unit"] in BET_AMOUNT_UNITS
            else BET_AMOUNT_UNITS.index(default_bet_unit(unit)),
        )
        updated_stake = col4.number_input(f"購入（{updated_unit}）", min_value=0, value=int(selected_bet["stake"]), step=100)
        updated_payout = col5.number_input(f"払戻（{updated_unit}）", min_value=0, value=int(selected_bet["payout"]), step=100)
        updated_role = st.text_input("位置づけ", value=selected_bet["expected_role"])
        updated_note = st.text_area("メモ", value=selected_bet["note"], height=80)
        submitted_update = st.form_submit_button("買い目を更新", use_container_width=True)
    if submitted_update:
        update_bet(
            int(selected_bet["id"]),
            {
                "race_id": selected_race_id,
                "ticket_type": updated_ticket,
                "combination": updated_combo.strip(),
                "amount_unit": updated_unit,
                "stake": int(updated_stake),
                "payout": int(updated_payout),
                "expected_role": updated_role.strip(),
                "note": updated_note.strip(),
            },
        )
        st.success("買い目を更新しました。")
        st.rerun()


def render_review(selected_race_id: int | None) -> None:
    selected_race = fetch_race(selected_race_id)
    render_header(selected_race if selected_race else None)
    st.subheader("振り返り分析")

    races = fetch_races()
    bets = fetch_all_bets()
    if races.empty:
        st.info("データが蓄積されると、得意条件と苦手条件を見られます。")
        return

    if bets.empty:
        st.info("買い目を登録すると分析が始まります。")
    else:
        st.markdown("#### 全体成績")
        total_stake = int(bets["stake"].sum())
        total_payout = int(bets["payout"].sum())
        unit = summary_unit(bets)
        col1, col2, col3, col4 = st.columns(4)
        if is_tip_medal(unit):
            col1.metric("利用", amount_text(total_stake, unit))
            col2.metric("的中払戻", amount_text(total_payout, unit))
            col3.metric("残り目安", amount_text(remaining_tip_medals(total_stake), unit))
            col4.metric("的中率", f"{hit_rate(int(bets['hit'].sum()), len(bets))}%")
            st.caption(
                f"TIPメダルは毎日{TIP_MEDAL_DAILY_GRANT:,}枚付与、{TIP_MEDAL_RESET_TEXT}に失効。"
                "振り返りでは回収率より、的中率と買い目の絞り込み精度を優先して見ます。"
            )
        elif unit == "単位混在":
            col1.metric("購入", amount_summary_text(bets, "stake"))
            col2.metric("払戻", amount_summary_text(bets, "payout"))
            col3.metric("差分", profit_summary_text(bets))
            col4.metric("的中率", f"{hit_rate(int(bets['hit'].sum()), len(bets))}%")
        else:
            col1.metric("購入", amount_text(total_stake, unit))
            col2.metric("払戻", amount_text(total_payout, unit))
            col3.metric("回収率", f"{recovery_rate(total_stake, total_payout)}%")
            col4.metric("的中率", f"{hit_rate(int(bets['hit'].sum()), len(bets))}%")

        ticket_summary = (
            bets.groupby(["amount_unit", "ticket_type"])
            .agg(件数=("id", "count"), 的中=("hit", "sum"), 購入=("stake", "sum"), 払戻=("payout", "sum"))
            .reset_index()
        )
        ticket_summary["差分"] = ticket_summary["払戻"] - ticket_summary["購入"]
        ticket_summary["回収率"] = ticket_summary.apply(lambda row: recovery_rate(row["購入"], row["払戻"]), axis=1)
        st.dataframe(
            ticket_summary.rename(columns={"amount_unit": "単位", "ticket_type": "券種", "差分": net_label(unit)}),
            use_container_width=True,
            hide_index=True,
        )

        ticket_summary["券種"] = ticket_summary["ticket_type"] + " / " + ticket_summary["amount_unit"]
        fig = horizontal_bar(
            ticket_summary,
            label_col="券種",
            value_col="差分",
            color_col="回収率",
            continuous_color=True,
            title=f"券種別 {net_label(unit)}",
            x_title=net_label(unit),
            hover_data=["件数", "的中", "購入", "払戻", "回収率"],
            text_template="%{x:,.0f}",
            color_scale=["#ef4444", "#94a3b8", "#22c55e"],
        )
        fig.update_layout(coloraxis_cmid=100)
        st.plotly_chart(fig, use_container_width=True)

    if selected_race_id:
        riders = fetch_riders(selected_race_id)
        if not riders.empty:
            st.markdown("#### 選択レースの心理・関係性メモ")
            human_focus = riders[
                (riders["mental_score"] >= 70)
                | (riders["relationship_score"] >= 70)
                | (riders["info_type"].isin(["Hypothesis", "過去レース観察"]))
            ]
            if human_focus.empty:
                st.caption("強く記録された心理・関係性メモはまだありません。")
            else:
                st.dataframe(
                    human_focus[
                        [
                            "car_no",
                            "rider_name",
                            "mental_score",
                            "relationship_score",
                            "confidence",
                            "info_type",
                            "human_note",
                        ]
                    ].rename(
                        columns={
                            "car_no": "車番",
                            "rider_name": "選手名",
                            "mental_score": "心理",
                            "relationship_score": "関係性",
                            "confidence": "確信度",
                            "info_type": "情報区分",
                            "human_note": "メモ",
                        }
                    ),
                    use_container_width=True,
                    hide_index=True,
                )

        result = fetch_result(selected_race_id)
        if result:
            st.markdown("#### 選択レースの振り返り")
            st.write(f"着順: {result.get('first_no')}-{result.get('second_no')}-{result.get('third_no')}")
            st.write(f"要因: {result.get('cause_tag') or '未入力'}")
            st.write(result.get("reflection") or "振り返りメモは未入力です。")


def main() -> None:
    st.set_page_config(page_title="zenKeirin Lab", page_icon="K", layout="wide")
    apply_style()
    init_db()
    races = fetch_races()
    selected_race_id = sidebar_select_race(races)
    page = st.session_state.get("page", "ダッシュボード")

    if page == "ダッシュボード":
        render_dashboard(races, selected_race_id)
    elif page == "競輪場特徴":
        render_venue_features_page(races, selected_race_id)
    elif page == "レース登録":
        render_race_form(selected_race_id)
    elif page == "選手評価":
        render_riders(selected_race_id)
    elif page == "買い目・結果":
        render_bets_and_results(selected_race_id)
    elif page == "振り返り":
        render_review(selected_race_id)


if __name__ == "__main__":
    main()
