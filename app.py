from __future__ import annotations

import html
import hmac
import importlib
import math
import os
import shutil
import sqlite3
import re
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st
import streamlit.components.v1 as components

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
import winticket_source as winticket_source_module
from venue_features import get_venue_feature, venue_feature_rows, venue_feature_url

winticket_source_module = importlib.reload(winticket_source_module)
WinticketSourceError = winticket_source_module.WinticketSourceError
extract_source_race_id = winticket_source_module.extract_source_race_id
fetch_winticket_race = winticket_source_module.fetch_winticket_race
fetch_winticket_race_by_urls = winticket_source_module.fetch_winticket_race_by_urls
fetch_winticket_race_listings = winticket_source_module.fetch_winticket_race_listings


APP_DIR = Path(__file__).resolve().parent


def configured_db_path() -> Path:
    db_path = os.environ.get("ZEN_KEIRIN_DB_PATH", "").strip()
    if db_path:
        return Path(db_path).expanduser()
    return APP_DIR / "data" / "zen_keirin_lab.sqlite3"


DB_PATH = configured_db_path()
DATA_DIR = DB_PATH.parent
LINEUP_BOARD_COMPONENT = components.declare_component(
    "lineup_board",
    path=str(APP_DIR / "components" / "lineup_board"),
)

MARK_OPTIONS = ["", "◎", "○", "▲", "△", "☆", "消", "見送り"]
INFO_TYPES = ["事実", "本人発言", "過去レース観察", "Hypothesis", "出所不明"]
CONFIDENCE_LEVELS = ["高", "中", "低"]
STATUS_OPTIONS = ["開催前", "予想中", "購入済み", "終了", "結果入力済み", "振り返り済み", "見送り"]
STYLE_OPTIONS = ["逃げ", "捲り", "差し", "追込", "自在", "不明"]
POSITION_OPTIONS = ["先頭", "番手", "3番手", "単騎", "別線", "不明"]
AMOUNT_UNITS = ["円", "TIPメダル", "TIPマネー", "ポイント", "枚", "単位混在"]
BET_AMOUNT_UNITS = [unit for unit in AMOUNT_UNITS if unit != "単位混在"]
STRATEGY_TYPES = ["", "1〜3着候補", "軸1人流し", "軸2人流し", "他人のっかり", "適当", "見送り", "その他"]
PREDICTION_SOURCES = ["", "自分予想", "他人のっかり", "AI提案", "適当", "記録のみ"]
ORDERED_HEAD_TICKET_TYPES = {"単勝", "2車単", "3連単"}
LINE_STATUS_OPTIONS = ["", "機能", "半機能", "崩れ", "単騎", "未評価"]
DEVELOPMENT_SCENARIOS = {
    "ライン順走": {
        "metric": "line_exact_top2",
        "title": "ライン順走",
        "summary": "先頭が踏み切り、番手まで続く形",
    },
    "番手差し": {
        "metric": "second_first",
        "title": "番手差し",
        "summary": "番手が最後に前を交わす形",
    },
    "別線まくり": {
        "metric": "leader_first",
        "title": "別線まくり",
        "summary": "選択ラインの先頭が頭まで届く形",
    },
    "単騎差し込み": {
        "metric": "single_top3",
        "title": "単騎差し込み",
        "summary": "単騎が3着内へ入り込む形",
    },
    "競り・分断": {
        "metric": "line_collapse",
        "title": "競り・分断",
        "summary": "選択ラインが上位でまとまらない形",
    },
}
BANK_LINE_COLORS = ["#38bdf8", "#22c55e", "#f59e0b", "#f43f5e", "#a78bfa", "#14b8a6", "#fb7185", "#84cc16"]
CAR_NUMBER_COLORS = {
    1: {"name": "白", "background": "#f8fafc", "text": "#020617", "border": "#e2e8f0"},
    2: {"name": "黒", "background": "#111827", "text": "#f8fafc", "border": "#64748b"},
    3: {"name": "赤", "background": "#dc2626", "text": "#ffffff", "border": "#ef4444"},
    4: {"name": "青", "background": "#2563eb", "text": "#ffffff", "border": "#60a5fa"},
    5: {"name": "黄", "background": "#facc15", "text": "#020617", "border": "#fde047"},
    6: {"name": "緑", "background": "#16a34a", "text": "#ffffff", "border": "#22c55e"},
    7: {"name": "橙", "background": "#f97316", "text": "#020617", "border": "#fb923c"},
    8: {"name": "桃", "background": "#ec4899", "text": "#ffffff", "border": "#f472b6"},
    9: {"name": "紫", "background": "#7c3aed", "text": "#ffffff", "border": "#a78bfa"},
}
TIP_MEDAL_DAILY_GRANT = 10000
TIP_MEDAL_RESET_TEXT = "翌日3:00"
TODAY_SYNC_VERSION = "racecard-index-v4"
ADJUSTMENT_SOURCE_STATUSES = {"TIPSTAR年次差額調整"}
REQUIRED_DB_TABLES = (
    "races",
    "riders",
    "bets",
    "results",
    "race_result_rows",
    "race_payouts",
    "race_lines",
)


def streamlit_secret_text(*keys: str) -> str:
    try:
        current = st.secrets
        for key in keys:
            current = current[key]
    except (FileNotFoundError, KeyError, TypeError):
        return ""
    except Exception:
        return ""
    return str(current).strip()


def configured_app_password() -> str:
    return (
        os.environ.get("ZEN_KEIRIN_APP_PASSWORD", "").strip()
        or streamlit_secret_text("ZEN_KEIRIN_APP_PASSWORD")
        or streamlit_secret_text("app_password")
        or streamlit_secret_text("auth", "password")
    )


def require_app_password() -> None:
    expected_password = configured_app_password()
    if not expected_password or st.session_state.get("app_authenticated"):
        return

    st.title("zenKeirin Lab")
    st.caption("外部公開モード")
    with st.form("app_login_form"):
        password = st.text_input("パスワード", type="password")
        submitted = st.form_submit_button("開く")

    if submitted:
        if hmac.compare_digest(password, expected_password):
            st.session_state["app_authenticated"] = True
            st.rerun()
        st.error("パスワードが違います。")

    st.stop()


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
                start_time TEXT DEFAULT '',
                close_time TEXT DEFAULT '',
                amount_unit TEXT DEFAULT '円',
                status TEXT DEFAULT '予想中',
                race_title TEXT DEFAULT '',
                line_summary TEXT DEFAULT '',
                race_memo TEXT DEFAULT '',
                source_race_id TEXT DEFAULT '',
                source_racecard_url TEXT DEFAULT '',
                source_result_url TEXT DEFAULT '',
                source_synced_at TEXT DEFAULT '',
                source_status TEXT DEFAULT '',
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
                strategy_type TEXT DEFAULT '',
                prediction_source TEXT DEFAULT '',
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
        ensure_column(conn, "races", "start_time", "TEXT DEFAULT ''")
        ensure_column(conn, "races", "close_time", "TEXT DEFAULT ''")
        ensure_column(conn, "races", "source_race_id", "TEXT DEFAULT ''")
        ensure_column(conn, "races", "source_racecard_url", "TEXT DEFAULT ''")
        ensure_column(conn, "races", "source_result_url", "TEXT DEFAULT ''")
        ensure_column(conn, "races", "source_synced_at", "TEXT DEFAULT ''")
        ensure_column(conn, "races", "source_status", "TEXT DEFAULT ''")
        ensure_column(conn, "riders", "rider_class", "TEXT DEFAULT ''")
        ensure_column(conn, "riders", "term", "TEXT DEFAULT ''")
        ensure_column(conn, "riders", "post_race_comment", "TEXT DEFAULT ''")
        ensure_column(conn, "riders", "comment_eval", "TEXT DEFAULT ''")
        ensure_column(conn, "bets", "amount_unit", "TEXT DEFAULT ''")
        ensure_column(conn, "bets", "strategy_type", "TEXT DEFAULT ''")
        ensure_column(conn, "bets", "prediction_source", "TEXT DEFAULT ''")
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


def database_counts(db_path: Path = DB_PATH) -> dict[str, int]:
    if not db_path.exists():
        return {}
    with sqlite3.connect(db_path) as conn:
        table_names = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        counts: dict[str, int] = {}
        for table in REQUIRED_DB_TABLES:
            if table in table_names:
                counts[table] = int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        return counts


def validate_database_file(db_path: Path) -> dict[str, int]:
    if not db_path.exists() or db_path.stat().st_size == 0:
        raise ValueError("SQLiteファイルが空です。")
    try:
        with sqlite3.connect(db_path) as conn:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise ValueError(f"SQLite integrity_check が失敗しました: {integrity}")
            table_names = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            missing = [table for table in REQUIRED_DB_TABLES if table not in table_names]
            if missing:
                raise ValueError(f"必要なテーブルがありません: {', '.join(missing)}")
            return database_counts(db_path)
    except sqlite3.DatabaseError as exc:
        raise ValueError(f"SQLiteとして読み込めません: {exc}") from exc


def restore_database(uploaded_file) -> dict[str, int]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    upload_path = DB_PATH.with_name(f".{DB_PATH.name}.upload")
    upload_path.write_bytes(uploaded_file.getbuffer())
    counts = validate_database_file(upload_path)

    if DB_PATH.exists():
        backup_dir = DATA_DIR / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_name = f"{DB_PATH.stem}.{datetime.now().strftime('%Y%m%d-%H%M%S')}.bak{DB_PATH.suffix}"
        shutil.copy2(DB_PATH, backup_dir / backup_name)

    os.replace(upload_path, DB_PATH)
    init_db()
    return counts


def row_to_dict(row: sqlite3.Row | None) -> dict:
    return dict(row) if row else {}


def race_amount_unit(race: dict | pd.Series | None) -> str:
    if race is None:
        return "円"
    unit = race.get("amount_unit") if hasattr(race, "get") else None
    return unit if unit in AMOUNT_UNITS else "円"


def compact_tip_medal_text(value: int | float) -> str:
    amount = int(value or 0)
    sign = "-" if amount < 0 else ""
    absolute = abs(amount)
    if absolute >= 10000:
        compact = f"{absolute / 10000:.1f}".rstrip("0").rstrip(".")
        return f"{sign}{compact}万枚"
    return f"{amount:,}枚"


def amount_text(value: int | float, unit: str, *, compact_tip: bool = False) -> str:
    amount = int(value or 0)
    if compact_tip and unit == "TIPメダル":
        return compact_tip_medal_text(amount)
    if unit == "単位混在":
        return f"{amount:,}（単位混在）"
    if unit == "円":
        return f"{amount:,}円"
    return f"{amount:,} {unit}"


def metric_amount_text(value: int | float, unit: str) -> str:
    return amount_text(value, unit, compact_tip=True)


def summary_unit(bets: pd.DataFrame) -> str:
    if bets.empty or "amount_unit" not in bets.columns:
        return "円"
    units = sorted(unit for unit in bets["amount_unit"].fillna("円").unique() if unit)
    return units[0] if len(units) == 1 else "単位混在"


def amount_summary_text(bets: pd.DataFrame, column: str, *, compact_tip: bool = False) -> str:
    if bets.empty or column not in bets.columns:
        return amount_text(0, "円")
    if "amount_unit" not in bets.columns:
        return amount_text(int(bets[column].sum()), "円")
    grouped = bets.groupby("amount_unit")[column].sum().sort_index()
    return " / ".join(amount_text(value, unit, compact_tip=compact_tip) for unit, value in grouped.items())


def profit_summary_text(bets: pd.DataFrame, *, compact_tip: bool = False) -> str:
    if bets.empty:
        return amount_text(0, "円")
    work = bets.copy()
    if "収支" not in work.columns:
        work["収支"] = work.apply(lambda row: profit(row["stake"], row["payout"]), axis=1)
    return amount_summary_text(work, "収支", compact_tip=compact_tip)


def bet_unit_sort_key(unit: str) -> tuple[int, str]:
    priority = {"円": 0, "TIPメダル": 1, "TIPマネー": 2, "ポイント": 3, "枚": 4}
    unit_text = str(unit or "円")
    return priority.get(unit_text, 99), unit_text


def build_bet_unit_summary(bets: pd.DataFrame) -> pd.DataFrame:
    if bets.empty:
        return pd.DataFrame()
    work = bets.copy()
    if "amount_unit" not in work.columns:
        work["amount_unit"] = "円"
    work["amount_unit"] = work["amount_unit"].fillna("円").replace("", "円")
    if "収支" not in work.columns:
        work["収支"] = work.apply(lambda row: profit(row["stake"], row["payout"]), axis=1)
    financial_summary = (
        work.groupby("amount_unit", dropna=False)
        .agg(購入=("stake", "sum"), 払戻=("payout", "sum"), 差分=("収支", "sum"))
        .reset_index()
    )

    hit_work = exclude_adjustment_bets(work)
    if hit_work.empty:
        hit_summary = pd.DataFrame(columns=["amount_unit", "買い目数", "的中"])
    else:
        hit_summary = (
            hit_work.groupby("amount_unit", dropna=False)
            .agg(買い目数=("hit", "count"), 的中=("hit", "sum"))
            .reset_index()
        )
    summary = financial_summary.merge(hit_summary, on="amount_unit", how="left")
    summary[["買い目数", "的中"]] = summary[["買い目数", "的中"]].fillna(0).astype(int)
    summary["的中率"] = summary.apply(lambda row: hit_rate(int(row["的中"]), int(row["買い目数"])), axis=1)
    summary["回収率"] = summary.apply(lambda row: recovery_rate(row["購入"], row["払戻"]), axis=1)
    summary["sort_key"] = summary["amount_unit"].apply(bet_unit_sort_key)
    return summary.sort_values("sort_key").drop(columns=["sort_key"]).reset_index(drop=True)


def hit_rate_metric_text(hit_count: int, bet_count: int) -> str:
    return f"{hit_rate(int(hit_count), int(bet_count))}%"


def default_bet_unit(race_unit: str) -> str:
    return race_unit if race_unit in BET_AMOUNT_UNITS else "TIPメダル"


def race_time_text(value: str | None) -> str:
    return str(value or "").strip()


def has_passed_race_close(race_date: str | None, close_time: str | None) -> bool:
    race_date_text = str(race_date or "").strip()
    close_text = race_time_text(close_time)
    if not race_date_text or not close_text:
        return False
    try:
        close_at = datetime.strptime(f"{race_date_text} {close_text}", "%Y-%m-%d %H:%M")
    except ValueError:
        return False
    return datetime.now() >= close_at


def status_after_public_sync(current_status: str | None, race_date: str | None, close_time: str | None, has_result: bool) -> str:
    current = str(current_status or "").strip()
    if current in {"結果入力済み", "振り返り済み", "見送り"}:
        return current
    if has_result or has_passed_race_close(race_date, close_time):
        return "終了"
    if current in {"", "予想中", "開催前"}:
        return "開催前"
    return current


def source_status_after_public_sync(current_source_status: str | None, incoming_source_status: str | None) -> str:
    current = str(current_source_status or "").strip()
    incoming = str(incoming_source_status or "").strip()
    if current in {"TIPSTAR取込", "補完済み"}:
        return current
    return incoming or current


def refresh_public_statuses(target_date: str | None = None) -> None:
    params: tuple = ()
    where = ""
    if target_date:
        where = "WHERE r.race_date = ?"
        params = (target_date,)
    with get_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT
                r.id,
                r.race_date,
                r.status,
                r.close_time,
                COALESCE(rr.result_row_count, 0) AS result_row_count
            FROM races r
            LEFT JOIN (
                SELECT race_id, COUNT(*) AS result_row_count
                FROM race_result_rows
                GROUP BY race_id
            ) rr ON rr.race_id = r.id
            {where}
            """,
            params,
        ).fetchall()
        for row in rows:
            next_status = status_after_public_sync(
                row["status"],
                row["race_date"],
                row["close_time"],
                int(row["result_row_count"] or 0) > 0,
            )
            if next_status != row["status"]:
                conn.execute(
                    "UPDATE races SET status = ?, updated_at = ? WHERE id = ?",
                    (next_status, now_text(), int(row["id"])),
                )


def is_tip_medal(unit: str) -> bool:
    return unit == "TIPメダル"


def net_label(unit: str) -> str:
    if is_tip_medal(unit):
        return "メダル差分"
    if unit == "円":
        return "円収支"
    if unit == "単位混在":
        return "差分"
    return "収支"


def training_hit_label(unit: str) -> str:
    return "的中率" if is_tip_medal(unit) else "的中率"


def remaining_tip_medals(stake: int | float) -> int:
    return max(TIP_MEDAL_DAILY_GRANT - int(stake or 0), 0)


def render_unit_summary_metrics(row: pd.Series) -> None:
    unit = str(row["amount_unit"] or "円")
    bet_count = int(row["買い目数"] or 0)
    hit_count = int(row["的中"] or 0)
    stake = int(row["購入"] or 0)
    payout = int(row["払戻"] or 0)
    net = int(row["差分"] or 0)
    hit_delta = f"{hit_count}/{bet_count}"

    if is_tip_medal(unit):
        st.markdown("##### TIPメダル（練習）")
        col1, col2, col3, col4, col5 = st.columns(5)
        col1.metric("的中率", hit_rate_metric_text(hit_count, bet_count), hit_delta)
        col2.metric("利用", metric_amount_text(stake, unit))
        col3.metric("的中払戻", metric_amount_text(payout, unit))
        col4.metric("残り目安", metric_amount_text(remaining_tip_medals(stake), unit))
        col5.metric(net_label(unit), metric_amount_text(net, unit))
        st.caption(
            f"TIPメダルは毎日{compact_tip_medal_text(TIP_MEDAL_DAILY_GRANT)}付与、{TIP_MEDAL_RESET_TEXT}に失効。"
            "現金損益ではなく、的中率と買い目の絞り込みを見る練習用の差分です。"
        )
        return

    if unit == "円":
        st.markdown("##### 現金収支（円）")
        col1, col2, col3, col4, col5 = st.columns(5)
        col1.metric("的中率", hit_rate_metric_text(hit_count, bet_count), hit_delta)
        col2.metric("購入合計", metric_amount_text(stake, unit))
        col3.metric("払戻合計", metric_amount_text(payout, unit))
        col4.metric(net_label(unit), metric_amount_text(net, unit))
        col5.metric("回収率", f"{recovery_rate(stake, payout)}%")
        return

    st.markdown(f"##### {unit}")
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("的中率", hit_rate_metric_text(hit_count, bet_count), hit_delta)
    col2.metric("購入合計", metric_amount_text(stake, unit))
    col3.metric("払戻合計", metric_amount_text(payout, unit))
    col4.metric(net_label(unit), metric_amount_text(net, unit))
    col5.metric("回収率", f"{recovery_rate(stake, payout)}%")


def render_bet_performance_summary(bets: pd.DataFrame) -> None:
    if bets.empty:
        st.info("買い目を登録すると、投票癖と的中精度の分析が始まります。")
        return

    summary = build_bet_unit_summary(bets)
    if len(summary) > 1:
        st.caption("円とTIPメダルは別単位なので、合算せず単位別に表示します。")
    for _, row in summary.iterrows():
        render_unit_summary_metrics(row)


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
            COALESCE(bc.missing_bet_reason_count, 0) AS missing_bet_reason_count,
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
                SUM(CASE WHEN COALESCE(note, '') = '' THEN 1 ELSE 0 END) AS missing_bet_reason_count,
                SUM(stake) AS total_stake,
                SUM(payout) AS total_payout
            FROM bets
            GROUP BY race_id
        ) bc ON bc.race_id = r.id
        WHERE COALESCE(r.source_status, '') NOT IN ('TIPSTAR年次差額調整')
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
            b.strategy_type,
            b.prediction_source,
            b.note,
            b.created_at,
            b.updated_at,
            r.race_date,
            r.venue,
            r.race_no,
            r.grade,
            r.status,
            r.source_status
        FROM bets b
        JOIN races r ON r.id = b.race_id
        ORDER BY r.race_date DESC, b.id DESC
    """
    with get_conn() as conn:
        df = pd.read_sql_query(query, conn)
    if not df.empty:
        df["収支"] = df.apply(lambda row: profit(row["stake"], row["payout"]), axis=1)
    return df


def exclude_adjustment_bets(bets: pd.DataFrame) -> pd.DataFrame:
    if bets.empty or "source_status" not in bets.columns:
        return bets
    return bets[~bets["source_status"].fillna("").astype(str).isin(ADJUSTMENT_SOURCE_STATUSES)].copy()


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


def prepare_rider_result_details(details: pd.DataFrame) -> pd.DataFrame:
    if details.empty:
        return details.copy()

    prepared = details.copy()
    prepared["finish_order"] = pd.to_numeric(prepared.get("finish_order"), errors="coerce")
    prepared["racing_score"] = pd.to_numeric(prepared.get("racing_score"), errors="coerce").fillna(0.0)
    agari_text = prepared.get("agari", pd.Series([""] * len(prepared))).fillna("").astype(str)
    prepared["agari_num"] = pd.to_numeric(agari_text.str.extract(r"(\d+(?:\.\d+)?)", expand=False), errors="coerce")

    prepared["result_done"] = prepared["finish_order"].notna()
    prepared["first"] = prepared["finish_order"].eq(1)
    prepared["second"] = prepared["finish_order"].eq(2)
    prepared["third"] = prepared["finish_order"].eq(3)
    prepared["top2"] = prepared["finish_order"].isin([1, 2])
    prepared["top3"] = prepared["finish_order"].isin([1, 2, 3])
    prepared["out"] = prepared["result_done"] & ~prepared["top3"]

    line_status = prepared.get("line_auto_status", pd.Series([""] * len(prepared))).fillna("").astype(str)
    prepared["line_status_done"] = line_status.isin(["機能", "半機能", "崩れ"])
    prepared["line_function"] = line_status.isin(["機能", "半機能"])
    prepared["line_collapse"] = line_status.eq("崩れ")

    position = prepared.get("line_position", pd.Series(["不明"] * len(prepared))).fillna("不明").astype(str)
    prepared["leader_first"] = position.eq("先頭") & prepared["first"]
    prepared["leader_top3"] = position.eq("先頭") & prepared["top3"]
    prepared["second_first"] = position.eq("番手") & prepared["first"]
    prepared["second_top2"] = position.eq("番手") & prepared["top2"]
    prepared["second_top3"] = position.eq("番手") & prepared["top3"]
    prepared["third_top3"] = position.eq("3番手") & prepared["top3"]
    prepared["single_first"] = position.eq("単騎") & prepared["first"]
    prepared["single_top3"] = position.eq("単騎") & prepared["top3"]
    return prepared


def fetch_rider_result_details() -> pd.DataFrame:
    query = """
        SELECT
            r.race_id,
            races.race_date,
            races.venue,
            races.race_no,
            races.grade,
            r.car_no,
            r.rider_name,
            r.prefecture,
            r.racing_score,
            r.style,
            COALESCE(NULLIF(r.line_name, ''), '未設定') AS line_name,
            COALESCE(NULLIF(r.line_position, ''), '不明') AS line_position,
            r.final_mark,
            COALESCE(lines.auto_status, '') AS line_auto_status,
            result_rows.finish_order,
            result_rows.agari,
            result_rows.decision,
            result_rows.sb
        FROM riders r
        JOIN races ON races.id = r.race_id
        LEFT JOIN race_lines lines
            ON lines.race_id = r.race_id
           AND lines.line_key = r.line_name
        LEFT JOIN race_result_rows result_rows
            ON result_rows.race_id = r.race_id
           AND result_rows.car_no = r.car_no
        WHERE COALESCE(r.rider_name, '') <> ''
          AND COALESCE(races.source_status, '') NOT IN ('TIPSTAR年次差額調整')
        ORDER BY races.race_date DESC, races.id DESC, r.car_no
    """
    with get_conn() as conn:
        details = pd.read_sql_query(query, conn)
    return prepare_rider_result_details(details)


def rider_position_watch_point(row: pd.Series | dict) -> str:
    position = row.get("line_position", "不明")
    result_count = int(row.get("結果あり", 0) or 0)
    if result_count == 0:
        return "結果補完待ち。着順が入ると位置別の癖を見られます。"

    first_rate = float(row.get("1着率", 0.0) or 0.0)
    top2_rate = float(row.get("2着以内率", 0.0) or 0.0)
    top3_rate = float(row.get("3着内率", 0.0) or 0.0)
    collapse_rate = float(row.get("ライン崩れ率", 0.0) or 0.0)

    if position == "先頭":
        if first_rate >= 30.0:
            return "先頭で頭まで取り切る形を確認。1着固定の候補。"
        if top3_rate >= 60.0:
            return "先頭で残るが頭までは慎重。折り返しや2・3着残りを確認。"
        return "先頭でも残り切れない傾向。別線まくりや番手差しに注意。"
    if position == "番手":
        if first_rate >= 25.0:
            return "番手差し候補。先頭との折り返しを検討。"
        if top2_rate >= 60.0:
            return "番手で連対しやすい。2着固定・ワンツー候補。"
        return "番手でも伸び切らない傾向。ライン機能率と展開待ちを確認。"
    if position == "3番手":
        if top3_rate >= 45.0:
            return "3番手で3着に残る形あり。三連系の押さえ候補。"
        return "3番手からの残りは薄め。ライン独占を買う根拠を確認。"
    if position == "単騎":
        if top3_rate >= 30.0:
            return "単騎で3着内に入る余地あり。穴の3着候補。"
        return "単騎の浮上は低め。位置取りと展開待ちの根拠を確認。"
    if collapse_rate >= 50.0:
        return "ライン崩れが多め。位置情報を補正してから扱いたい選手。"
    return "サンプルを蓄積中。場・級班・並びと一緒に確認。"


def build_rider_position_summary(details: pd.DataFrame, min_races: int = 1) -> pd.DataFrame:
    if details.empty:
        return pd.DataFrame()

    prepared = prepare_rider_result_details(details)
    summary = (
        prepared.groupby(["rider_name", "prefecture", "line_position"], dropna=False)
        .agg(
            出走数=("race_id", "nunique"),
            結果あり=("result_done", "sum"),
            一着=("first", "sum"),
            二着=("second", "sum"),
            三着=("third", "sum"),
            三着内=("top3", "sum"),
            着外=("out", "sum"),
            平均競走得点=("racing_score", "mean"),
            平均上がり=("agari_num", "mean"),
            ライン判定数=("line_status_done", "sum"),
            ライン機能数=("line_function", "sum"),
            ライン崩れ数=("line_collapse", "sum"),
            先頭一着=("leader_first", "sum"),
            先頭三着内=("leader_top3", "sum"),
            番手一着=("second_first", "sum"),
            番手二着以内=("second_top2", "sum"),
            番手三着内=("second_top3", "sum"),
            三番手三着内=("third_top3", "sum"),
            単騎一着=("single_first", "sum"),
            単騎三着内=("single_top3", "sum"),
            最終出走日=("race_date", "max"),
        )
        .reset_index()
    )
    if min_races > 1:
        summary = summary[summary["出走数"] >= int(min_races)].copy()
    if summary.empty:
        return summary

    count_columns = [
        "出走数",
        "結果あり",
        "一着",
        "二着",
        "三着",
        "三着内",
        "着外",
        "ライン判定数",
        "ライン機能数",
        "ライン崩れ数",
        "先頭一着",
        "先頭三着内",
        "番手一着",
        "番手二着以内",
        "番手三着内",
        "三番手三着内",
        "単騎一着",
        "単騎三着内",
    ]
    for column in count_columns:
        summary[column] = summary[column].fillna(0).astype(int)

    summary["1着率"] = summary.apply(lambda row: hit_rate(int(row["一着"]), int(row["結果あり"])), axis=1)
    summary["2着以内率"] = summary.apply(
        lambda row: hit_rate(int(row["一着"] + row["二着"]), int(row["結果あり"])),
        axis=1,
    )
    summary["3着内率"] = summary.apply(lambda row: hit_rate(int(row["三着内"]), int(row["結果あり"])), axis=1)
    summary["ライン機能率"] = summary.apply(
        lambda row: hit_rate(int(row["ライン機能数"]), int(row["ライン判定数"])),
        axis=1,
    )
    summary["ライン崩れ率"] = summary.apply(
        lambda row: hit_rate(int(row["ライン崩れ数"]), int(row["ライン判定数"])),
        axis=1,
    )
    summary["平均競走得点"] = summary["平均競走得点"].fillna(0.0).round(2)
    summary["平均上がり"] = summary["平均上がり"].round(2)
    summary["選手"] = summary.apply(
        lambda row: f"{row['rider_name']}（{row['prefecture']}）" if row.get("prefecture") else row["rider_name"],
        axis=1,
    )
    summary["選手位置"] = summary["選手"] + " / " + summary["line_position"].fillna("不明")
    summary["見るポイント"] = summary.apply(rider_position_watch_point, axis=1)
    return summary.sort_values(["出走数", "3着内率", "1着率"], ascending=False).reset_index(drop=True)


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
    values = [payload.get(field, "") for field in fields]
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
                strategy_type,
                prediction_source,
                note,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                payload.get("strategy_type", ""),
                payload.get("prediction_source", ""),
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
                strategy_type = ?,
                prediction_source = ?,
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
                payload.get("strategy_type", ""),
                payload.get("prediction_source", ""),
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
        race = conn.execute("SELECT race_date, status, close_time, source_status FROM races WHERE id = ?", (race_id,)).fetchone()
        synced_status = status_after_public_sync(
            race["status"] if race else "",
            race["race_date"] if race else "",
            getattr(source, "close_time", "") or (race["close_time"] if race else ""),
            bool(result_numbers),
        )
        synced_source_status = source_status_after_public_sync(race["source_status"] if race else "", "補完済み")
        conn.execute(
            """
            UPDATE races
            SET source_race_id = CASE WHEN COALESCE(source_race_id, '') = '' THEN ? ELSE source_race_id END,
                source_racecard_url = ?,
                source_result_url = CASE WHEN ? = 'TIPSTAR取込' AND COALESCE(source_result_url, '') <> '' THEN source_result_url ELSE ? END,
                source_synced_at = ?,
                source_status = ?,
                status = ?,
                grade = CASE WHEN COALESCE(grade, '') = '' THEN ? ELSE grade END,
                distance = CASE WHEN COALESCE(distance, 0) = 0 THEN ? ELSE distance END,
                weather = CASE WHEN COALESCE(weather, '') = '' THEN ? ELSE weather END,
                wind = CASE WHEN COALESCE(wind, 0) = 0 THEN ? ELSE wind END,
                start_time = CASE WHEN COALESCE(start_time, '') = '' THEN ? ELSE start_time END,
                close_time = CASE WHEN COALESCE(close_time, '') = '' THEN ? ELSE close_time END,
                line_summary = CASE WHEN COALESCE(line_summary, '') = '' THEN ? ELSE line_summary END,
                updated_at = ?
            WHERE id = ?
            """,
            (
                source.source_race_id,
                source.racecard_url,
                synced_source_status,
                source.result_url,
                timestamp,
                synced_source_status,
                synced_status,
                getattr(source, "grade", ""),
                int(getattr(source, "distance", 0) or 0),
                getattr(source, "weather", ""),
                float(getattr(source, "wind", 0.0) or 0.0),
                getattr(source, "start_time", ""),
                getattr(source, "close_time", ""),
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


def sync_winticket_for_race(race_id: int, fetcher=None):
    race = fetch_race(race_id)
    if not race:
        raise WinticketSourceError("選択レースが見つかりません。")
    source_race_id = race.get("source_race_id") or extract_source_race_id(race.get("race_memo", ""))
    if not source_race_id:
        raise WinticketSourceError("raceId が未登録のため、WINTICKET補完URLを解決できません。")
    if race.get("source_racecard_url"):
        source = fetch_winticket_race_by_urls(
            source_race_id=source_race_id,
            racecard_url=race["source_racecard_url"],
            result_url=race.get("source_result_url", ""),
            fetcher=fetcher or winticket_source_module.fetch_url,
        )
    else:
        source = fetch_winticket_race(
            race_date=race["race_date"],
            race_no=int(race["race_no"]),
            source_race_id=source_race_id,
            venue=race.get("venue", ""),
            race_title=race.get("race_title", ""),
            fetcher=fetcher or winticket_source_module.fetch_url,
        )
    apply_winticket_source(race_id, source)
    return source


def upsert_winticket_race_listing(listing) -> tuple[int, bool]:
    timestamp = now_text()
    racecard_url = listing.racecard_url
    result_url = racecard_url.replace("/racecard/", "/raceresult/") if racecard_url else ""
    with get_conn() as conn:
        existing = None
        if listing.source_race_id:
            existing = conn.execute(
                "SELECT id, status, source_status FROM races WHERE source_race_id = ? ORDER BY id LIMIT 1",
                (listing.source_race_id,),
            ).fetchone()
        if not existing:
            existing = conn.execute(
                """
                SELECT id, status, source_status
                FROM races
                WHERE race_date = ? AND venue = ? AND race_no = ?
                ORDER BY id
                LIMIT 1
                """,
                (listing.race_date, listing.venue, int(listing.race_no)),
            ).fetchone()

        if existing:
            race_id = int(existing["id"])
            listing_status = status_after_public_sync(existing["status"], listing.race_date, listing.close_time, False)
            listing_source_status = source_status_after_public_sync(existing["source_status"], listing.source_status)
            conn.execute(
                """
                UPDATE races
                SET source_race_id = CASE WHEN COALESCE(source_race_id, '') = '' THEN ? ELSE source_race_id END,
                    source_racecard_url = CASE WHEN ? <> '' THEN ? ELSE source_racecard_url END,
                    source_result_url = CASE
                        WHEN COALESCE(source_status, '') = 'TIPSTAR取込' AND COALESCE(source_result_url, '') <> '' THEN source_result_url
                        WHEN ? <> '' THEN ?
                        ELSE source_result_url
                    END,
                    source_synced_at = ?,
                    source_status = ?,
                    status = ?,
                    race_title = CASE WHEN COALESCE(race_title, '') = '' THEN ? ELSE race_title END,
                    grade = CASE WHEN COALESCE(grade, '') = '' THEN ? ELSE grade END,
                    start_time = CASE WHEN COALESCE(start_time, '') = '' THEN ? ELSE start_time END,
                    close_time = CASE WHEN COALESCE(close_time, '') = '' THEN ? ELSE close_time END,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    listing.source_race_id,
                    racecard_url,
                    racecard_url,
                    result_url,
                    result_url,
                    timestamp,
                    listing_source_status,
                    listing_status,
                    listing.race_title,
                    listing.grade,
                    listing.start_time,
                    listing.close_time,
                    timestamp,
                    race_id,
                ),
            )
            return race_id, False

        cursor = conn.execute(
            """
            INSERT INTO races (
                race_date,
                venue,
                race_no,
                grade,
                distance,
                weather,
                wind,
                start_time,
                close_time,
                amount_unit,
                status,
                race_title,
                line_summary,
                race_memo,
                source_race_id,
                source_racecard_url,
                source_result_url,
                source_synced_at,
                source_status,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, 0, '', 0, ?, ?, '円', '開催前', ?, '', '', ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                listing.race_date,
                listing.venue,
                int(listing.race_no),
                listing.grade,
                listing.start_time,
                listing.close_time,
                listing.race_title,
                listing.source_race_id,
                racecard_url,
                result_url,
                timestamp,
                listing.source_status,
                timestamp,
                timestamp,
            ),
        )
        return int(cursor.lastrowid), True


def sync_winticket_details_for_race_ids(race_ids: list[int], limit: int | None = None, fetcher=None) -> dict:
    if not race_ids:
        return {"synced": [], "failed": [], "skipped": 0}
    races = fetch_races()
    if races.empty:
        return {"synced": [], "failed": [], "skipped": 0}
    candidates = races[races["id"].astype(int).isin([int(race_id) for race_id in race_ids])].copy()
    if candidates.empty:
        return {"synced": [], "failed": [], "skipped": len(race_ids)}

    source_ids = candidates["source_race_id"].fillna("").astype(str)
    rider_counts = candidates["rider_count"].fillna(0).astype(int)
    line_counts = candidates["line_count"].fillna(0).astype(int)
    result_row_counts = candidates["result_row_count"].fillna(0).astype(int)
    payout_counts = candidates["payout_count"].fillna(0).astype(int)
    bet_counts = candidates["bet_count"].fillna(1).astype(int) if "bet_count" in candidates.columns else pd.Series(1, index=candidates.index)
    needs_rider_or_line = (rider_counts == 0) | (line_counts == 0)
    needs_result_for_bets = (bet_counts > 0) & ((result_row_counts == 0) | (payout_counts == 0))
    candidates = candidates[
        (source_ids != "")
        & (needs_rider_or_line | needs_result_for_bets)
    ].copy()
    candidates = candidates.sort_values(["race_date", "race_no"], ascending=[False, True])
    if limit is not None:
        candidates = candidates.head(int(limit))

    result = {"synced": [], "failed": [], "skipped": max(len(race_ids) - len(candidates), 0)}
    for _, row in candidates.iterrows():
        race_id = int(row["id"])
        label = f"{row['race_date']} {row['venue']} {int(row['race_no'])}R"
        try:
            source = sync_winticket_for_race(race_id, fetcher=fetcher)
        except Exception as exc:
            result["failed"].append({"レース": label, "理由": str(exc)})
        else:
            result["synced"].append(
                {
                    "レース": label,
                    "選手": len(source.riders),
                    "ライン": len(parse_line_summary(source.line_summary)),
                    "結果": len(source.result_rows),
                    "払戻": len(source.payouts),
                }
            )
    return result


def sync_winticket_race_list_for_date(
    target_date: str | date | None = None,
    fetcher=None,
    hydrate: bool = False,
    hydrate_limit: int | None = None,
) -> dict:
    target = target_date or date.today()
    target_text = target.isoformat() if isinstance(target, date) else str(target)
    listings = fetch_winticket_race_listings(target_text, fetcher=fetcher)
    created = 0
    updated = 0
    race_ids: list[int] = []
    for listing in listings:
        race_id, is_created = upsert_winticket_race_listing(listing)
        race_ids.append(race_id)
        if is_created:
            created += 1
        else:
            updated += 1
    refresh_public_statuses(target_text)
    result = {
        "race_date": target_text,
        "fetched": len(listings),
        "created": created,
        "updated": updated,
        "race_ids": race_ids,
    }
    if hydrate:
        result["details"] = sync_winticket_details_for_race_ids(race_ids, limit=hydrate_limit, fetcher=fetcher)
    return result


def sync_today_winticket_races_once() -> dict | None:
    today_text = date.today().isoformat()
    session_key = f"winticket_today_synced_{today_text}_{TODAY_SYNC_VERSION}"
    if st.session_state.get(session_key):
        return st.session_state.get("winticket_today_sync_result")
    try:
        result = sync_winticket_race_list_for_date(today_text)
    except Exception as exc:
        result = {"race_date": today_text, "error": str(exc), "fetched": 0, "created": 0, "updated": 0}
    st.session_state[session_key] = True
    st.session_state["winticket_today_sync_result"] = result
    return result


def winticket_sync_candidates(races: pd.DataFrame, limit: int = 30) -> pd.DataFrame:
    if races.empty:
        return pd.DataFrame()
    source_ids = races["source_race_id"].fillna("").astype(str)
    rider_counts = races["rider_count"].fillna(0).astype(int)
    line_counts = races["line_count"].fillna(0).astype(int)
    result_row_counts = races["result_row_count"].fillna(0).astype(int)
    payout_counts = races["payout_count"].fillna(0).astype(int)
    bet_counts = races["bet_count"].fillna(1).astype(int) if "bet_count" in races.columns else pd.Series(1, index=races.index)
    needs_rider_or_line = (rider_counts == 0) | (line_counts == 0)
    needs_result_for_bets = (bet_counts > 0) & ((result_row_counts == 0) | (payout_counts == 0))
    candidates = races[
        (source_ids != "")
        & (needs_rider_or_line | needs_result_for_bets)
    ].copy()
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
        .virtual-bank {
            position: relative;
            min-height: 430px;
            border: 1px solid #334155;
            border-radius: 8px;
            background:
                radial-gradient(ellipse at center, rgba(15, 23, 42, 0.88) 0%, rgba(15, 23, 42, 0.88) 43%, transparent 44%),
                linear-gradient(135deg, #111827, #18212f 55%, #111827);
            overflow: hidden;
        }
        .virtual-bank::before {
            content: "";
            position: absolute;
            inset: 34px 56px;
            border: 28px solid #475569;
            border-radius: 50%;
            box-shadow: 0 0 0 2px rgba(226, 232, 240, 0.14) inset, 0 0 0 2px rgba(226, 232, 240, 0.18);
        }
        .virtual-bank::after {
            content: "FINISH";
            position: absolute;
            top: 42px;
            right: 72px;
            padding: 4px 8px;
            border-left: 3px solid #f8fafc;
            color: #f8fafc;
            font-size: 12px;
            font-weight: 800;
            letter-spacing: 0;
            background: rgba(15, 23, 42, 0.72);
        }
        .bank-center-label {
            position: absolute;
            left: 50%;
            top: 50%;
            transform: translate(-50%, -50%);
            color: #cbd5e1;
            text-align: center;
            font-weight: 700;
            line-height: 1.6;
        }
        .rider-chip {
            position: absolute;
            width: 92px;
            min-height: 58px;
            transform: translate(-50%, -50%);
            border-radius: 8px;
            border: 2px solid var(--car-border-color);
            background: var(--car-color);
            color: var(--car-text-color);
            padding: 7px 8px;
            box-shadow: 0 12px 24px rgba(0, 0, 0, 0.28);
        }
        .rider-chip.is-active {
            box-shadow: 0 0 0 3px rgba(248, 250, 252, 0.22), 0 12px 24px rgba(0, 0, 0, 0.28);
        }
        .rider-chip.is-projected {
            box-shadow: 0 0 0 3px rgba(34, 197, 94, 0.34), 0 12px 24px rgba(0, 0, 0, 0.28);
        }
        .rider-no {
            display: inline-block;
            min-width: 24px;
            height: 24px;
            line-height: 24px;
            text-align: center;
            border-radius: 50%;
            background: rgba(15, 23, 42, 0.16);
            color: var(--car-text-color);
            font-weight: 900;
            margin-right: 5px;
            box-shadow: 0 0 0 1px rgba(248, 250, 252, 0.2) inset;
        }
        .rider-chip strong {
            color: var(--car-text-color);
        }
        .rider-name {
            display: block;
            margin-top: 4px;
            font-size: 12px;
            color: var(--car-text-color);
            opacity: 0.82;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .rider-rank {
            position: absolute;
            top: -12px;
            right: -10px;
            border-radius: 999px;
            padding: 2px 7px;
            background: #f8fafc;
            color: #020617;
            font-size: 12px;
            font-weight: 900;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def race_label(row: pd.Series | dict) -> str:
    title = row.get("race_title") or "無題"
    return f"{row.get('race_date')} {row.get('venue')} {int(row.get('race_no', 0))}R | {title}"


def render_page_race_selector(
    races: pd.DataFrame,
    selected_race_id: int | None,
    *,
    label: str,
    key_prefix: str,
) -> int | None:
    if races.empty:
        return selected_race_id

    ordered = sort_latest_races(races).reset_index(drop=True)
    labels = [race_label(row) for _, row in ordered.iterrows()]
    race_ids = [int(row["id"]) for _, row in ordered.iterrows()]
    selected_value = None
    try:
        selected_value = int(selected_race_id) if selected_race_id is not None else None
    except (TypeError, ValueError):
        selected_value = None
    default_index = race_ids.index(selected_value) if selected_value in race_ids else 0
    selector_key = f"{key_prefix}_race_selector"
    selector_state_key = f"{key_prefix}_race_selector_id"
    default_label = labels[default_index]

    if st.session_state.get(selector_state_key) != selected_value and st.session_state.get(selector_key) != default_label:
        st.session_state[selector_key] = default_label
        st.session_state[selector_state_key] = selected_value

    selected_label = st.selectbox(label, labels, index=default_index, key=selector_key)
    next_race_id = race_ids[labels.index(selected_label)]
    if selected_value != next_race_id:
        st.session_state["selected_race_id"] = next_race_id
        st.session_state[selector_state_key] = next_race_id
        st.rerun()
    return next_race_id


def render_database_admin_panel() -> None:
    with st.sidebar.expander("DBバックアップ/復元"):
        counts = database_counts()
        if counts:
            st.caption(
                "現在: "
                f"レース{counts.get('races', 0):,}件 / "
                f"選手{counts.get('riders', 0):,}件 / "
                f"買い目{counts.get('bets', 0):,}件 / "
                f"結果{counts.get('results', 0):,}件"
            )
            try:
                st.download_button(
                    "現在のDBをダウンロード",
                    data=DB_PATH.read_bytes(),
                    file_name="zen_keirin_lab.sqlite3",
                    mime="application/octet-stream",
                    use_container_width=True,
                )
            except OSError as exc:
                st.warning(f"DBを読み出せませんでした: {exc}")
        else:
            st.caption("現在のDBはまだ作成されていません。")

        uploaded_db = st.file_uploader(
            "SQLite DBをアップロード",
            type=["sqlite3", "sqlite", "db"],
            key="restore_database_upload",
        )
        overwrite_confirmed = st.checkbox(
            "Render側DBをこのファイルで上書きする",
            key="restore_database_confirm",
        )
        restore_clicked = st.button(
            "DBを復元",
            disabled=uploaded_db is None or not overwrite_confirmed,
            use_container_width=True,
        )
        if restore_clicked and uploaded_db is not None:
            try:
                restored_counts = restore_database(uploaded_db)
            except ValueError as exc:
                st.error(str(exc))
            else:
                st.session_state.pop("selected_race_id", None)
                st.success(
                    "DBを復元しました。"
                    f"レース{restored_counts.get('races', 0):,}件 / "
                    f"選手{restored_counts.get('riders', 0):,}件 / "
                    f"買い目{restored_counts.get('bets', 0):,}件"
                )
                st.rerun()


def sidebar_select_race(races: pd.DataFrame) -> int | None:
    st.sidebar.title("zenKeirin Lab")
    page_options = ["ダッシュボード", "競輪場特徴", "レース登録", "選手評価", "展開予想", "買い目・結果", "振り返り"]
    current_page = st.session_state.get("page", "ダッシュボード")
    page = st.sidebar.radio(
        "画面",
        page_options,
        index=page_options.index(current_page) if current_page in page_options else 0,
    )
    st.session_state["page"] = page
    render_database_admin_panel()

    if races.empty:
        st.sidebar.info("まだレースがありません。")
        with st.sidebar.expander("初期データ"):
            if st.button("サンプルレースを追加"):
                seed_demo_data()
                st.rerun()
        return None

    labels = [race_label(row) for _, row in races.iterrows()]
    selected_id_from_state = st.session_state.get("selected_race_id")
    race_ids = [int(row["id"]) for _, row in races.iterrows()]
    try:
        selected_id_value = int(selected_id_from_state) if selected_id_from_state is not None else None
    except (TypeError, ValueError):
        selected_id_value = None
    default_index = race_ids.index(selected_id_value) if selected_id_value in race_ids else 0
    selected_label = st.sidebar.selectbox("対象レース", labels, index=default_index)
    selected_index = labels.index(selected_label)
    selected_id = int(races.iloc[selected_index]["id"])
    st.session_state["selected_race_id"] = selected_id

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
    if int(row.get("bet_count", 0) or 0) == 0:
        issues.append("買い目未入力")
    if int(row.get("missing_bet_reason_count", 0) or 0) > 0:
        issues.append("買い目理由なし")
    if int(row.get("line_count", 0) or 0) > 0 and int(row.get("line_review_count", 0) or 0) == 0:
        issues.append("ライン未評価")
    if int(row.get("review_done", 0) or 0) == 0:
        issues.append("振り返り未完了")
    return issues


def sort_latest_races(races: pd.DataFrame) -> pd.DataFrame:
    if races.empty:
        return races
    work = races.copy()
    if "source_synced_at" not in work.columns:
        work["source_synced_at"] = ""
    return work.sort_values(["race_date", "source_synced_at", "race_no"], ascending=[False, False, False])


def queue_row(row: pd.Series, issue: str = "") -> dict:
    return {
        "race_id": int(row["id"]),
        "日付": row["race_date"],
        "場": row["venue"],
        "R": int(row["race_no"]),
        "発走": row.get("start_time", ""),
        "締切": row.get("close_time", ""),
        "レース": row.get("race_title") or "無題",
        "状態": row.get("status", ""),
        "未入力": issue,
    }


def build_unbet_race_queue(races: pd.DataFrame, limit: int = 30) -> pd.DataFrame:
    if races.empty:
        return pd.DataFrame()
    rows = [
        queue_row(row, "買い目")
        for _, row in sort_latest_races(races).iterrows()
        if int(row.get("bet_count", 0) or 0) == 0
    ]
    return pd.DataFrame(rows).head(limit)


def build_missing_bet_reason_queue(races: pd.DataFrame, limit: int = 30) -> pd.DataFrame:
    if races.empty:
        return pd.DataFrame()
    rows = [
        queue_row(row, f"理由 {int(row.get('missing_bet_reason_count', 0) or 0)}件")
        for _, row in sort_latest_races(races).iterrows()
        if int(row.get("missing_bet_reason_count", 0) or 0) > 0
    ]
    return pd.DataFrame(rows).head(limit)


def build_unreviewed_race_queue(races: pd.DataFrame, limit: int = 30) -> pd.DataFrame:
    if races.empty:
        return pd.DataFrame()
    rows = [
        queue_row(row, "振り返り")
        for _, row in sort_latest_races(races).iterrows()
        if int(row.get("review_done", 0) or 0) == 0
    ]
    return pd.DataFrame(rows).head(limit)


def build_research_queue(races: pd.DataFrame, limit: int = 30) -> pd.DataFrame:
    rows = []
    for _, row in races.iterrows():
        issues = research_issues(row)
        if not issues:
            continue
        rows.append(
            {
                "race_id": int(row["id"]),
                "日付": row["race_date"],
                "場": row["venue"],
                "R": int(row["race_no"]),
                "発走": row.get("start_time", ""),
                "締切": row.get("close_time", ""),
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


def normalize_line_groups(line_groups: tuple[tuple[int, ...], ...] | list[tuple[int, ...]]) -> tuple[tuple[int, ...], ...]:
    normalized: list[tuple[int, ...]] = []
    used: set[int] = set()
    for group in line_groups:
        clean_group: list[int] = []
        for raw_number in group:
            number = int(raw_number)
            if number < 1 or number > 9 or number in clean_group or number in used:
                continue
            clean_group.append(number)
            used.add(number)
        if clean_group:
            normalized.append(tuple(clean_group))
    return tuple(normalized)


def flatten_line_groups(line_groups: tuple[tuple[int, ...], ...] | list[tuple[int, ...]]) -> tuple[int, ...]:
    return tuple(number for group in line_groups for number in group)


def format_line_groups(line_groups: tuple[tuple[int, ...], ...] | list[tuple[int, ...]]) -> str:
    return " / ".join("-".join(str(number) for number in group) for group in line_groups)


def format_car_label(car_no: int, names: dict[int, str]) -> str:
    name = names.get(int(car_no), "")
    return f"{int(car_no)} {name}" if name else str(int(car_no))


def line_group_label(index: int, group: tuple[int, ...] | list[int], names: dict[int, str]) -> str:
    return f"ライン{index + 1}: " + " - ".join(format_car_label(number, names) for number in group)


def race_line_groups(race: dict, lines: pd.DataFrame) -> tuple[tuple[int, ...], ...]:
    groups: list[tuple[int, ...]] = []
    if not lines.empty:
        for _, row in lines.iterrows():
            parsed = parse_line_summary(row.get("car_numbers", ""))
            if parsed:
                groups.append(parsed[0])
    if not groups:
        groups = list(parse_line_summary(race.get("line_summary", "")))
    return normalize_line_groups(groups)


def move_line_group(
    line_groups: tuple[tuple[int, ...], ...] | list[tuple[int, ...]],
    active_index: int,
    target_index: int,
) -> tuple[tuple[int, ...], ...]:
    groups = [tuple(group) for group in line_groups]
    if not groups:
        return ()
    active_index = max(0, min(int(active_index), len(groups) - 1))
    target_index = max(0, min(int(target_index), len(groups) - 1))
    group = groups.pop(active_index)
    groups.insert(target_index, group)
    return tuple(groups)


def scenario_options_for_group(group: tuple[int, ...]) -> list[str]:
    options = ["ライン順走", "別線まくり", "競り・分断"]
    if len(group) >= 2:
        options.insert(1, "番手差し")
    if len(group) == 1:
        options.insert(0, "単騎差し込み")
    return options


def unique_top_numbers(numbers: list[int] | tuple[int, ...]) -> tuple[int, ...]:
    top_numbers: list[int] = []
    for raw_number in numbers:
        number = int(raw_number)
        if number > 0 and number not in top_numbers:
            top_numbers.append(number)
        if len(top_numbers) >= 3:
            break
    return tuple(top_numbers)


def project_development_top3(
    line_groups: tuple[tuple[int, ...], ...] | list[tuple[int, ...]],
    active_index: int,
    scenario: str,
) -> tuple[int, ...]:
    groups = [tuple(group) for group in line_groups if group]
    if not groups:
        return ()
    active_index = max(0, min(int(active_index), len(groups) - 1))
    active = groups[active_index]
    others = [group for index, group in enumerate(groups) if index != active_index]

    if scenario == "番手差し" and len(active) >= 2:
        return unique_top_numbers([active[1], active[0], *active[2:], *flatten_line_groups(others)])
    if scenario == "競り・分断":
        other_leaders = [group[0] for group in others if group]
        other_followers = [number for group in others for number in group[1:]]
        return unique_top_numbers([active[0], *other_leaders, *(active[1:] if len(active) > 1 else ()), *other_followers])
    if scenario == "単騎差し込み":
        single = active if len(active) == 1 else next((group for group in groups if len(group) == 1), active)
        remaining = [number for number in flatten_line_groups(groups) if number not in single]
        return unique_top_numbers([*single, *remaining])
    if scenario == "別線まくり":
        return unique_top_numbers([*active[:2], *(others[0][:1] if others else ()), *active[2:], *flatten_line_groups(others)])
    return unique_top_numbers([*active, *flatten_line_groups(others)])


def default_board_position(chip_index: int, total: int) -> dict[str, float]:
    spread = 320 if total > 1 else 0
    angle = math.radians(-24 + (spread * int(chip_index) / max(total - 1, 1)))
    return {
        "x": round(50 + 40 * math.cos(angle), 1),
        "y": round(50 + 34 * math.sin(angle), 1),
    }


def line_member_position(group: tuple[int, ...] | list[int], rider_index: int) -> str:
    if len(group) == 1:
        return "単騎"
    if rider_index == 0:
        return "先頭"
    if rider_index == 1:
        return "番手"
    return "3番手"


def car_number_color_style(car_no: int) -> dict[str, str]:
    return CAR_NUMBER_COLORS.get(
        int(car_no),
        {"name": "不明", "background": "#64748b", "text": "#f8fafc", "border": "#94a3b8"},
    )


def clamp_board_coordinate(value, fallback: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return round(float(fallback), 1)
    if not math.isfinite(number):
        return round(float(fallback), 1)
    return round(max(4.0, min(96.0, number)), 1)


def normalize_board_positions(
    positions,
    valid_car_numbers: tuple[int, ...] | list[int],
) -> dict[str, dict[str, float]]:
    if not isinstance(positions, dict):
        return {}
    valid_keys = {str(int(number)) for number in valid_car_numbers}
    normalized: dict[str, dict[str, float]] = {}
    for car_key, raw_position in positions.items():
        key = str(car_key).replace("car-", "")
        if key not in valid_keys or not isinstance(raw_position, dict):
            continue
        normalized[key] = {
            "x": clamp_board_coordinate(raw_position.get("x"), 50.0),
            "y": clamp_board_coordinate(raw_position.get("y"), 50.0),
        }
    return normalized


def lineup_board_pieces(
    line_groups: tuple[tuple[int, ...], ...] | list[tuple[int, ...]],
    active_index: int,
    projected_top3: tuple[int, ...],
    names: dict[int, str],
    saved_positions: dict[str, dict[str, float]] | None = None,
) -> list[dict]:
    total = len(flatten_line_groups(line_groups))
    if total == 0:
        return []
    saved_positions = saved_positions or {}
    active_numbers = set(line_groups[active_index]) if 0 <= active_index < len(line_groups) else set()
    projected_rank = {int(number): index + 1 for index, number in enumerate(projected_top3)}
    pieces: list[dict] = []
    chip_index = 0
    for line_index, group in enumerate(line_groups):
        line_color = BANK_LINE_COLORS[line_index % len(BANK_LINE_COLORS)]
        for rider_index, number in enumerate(group):
            car_no = int(number)
            car_color = car_number_color_style(car_no)
            default_position = default_board_position(chip_index, total)
            saved_position = saved_positions.get(str(car_no), {})
            x = clamp_board_coordinate(saved_position.get("x"), default_position["x"])
            y = clamp_board_coordinate(saved_position.get("y"), default_position["y"])
            pieces.append(
                {
                    "id": f"car-{car_no}",
                    "carNo": car_no,
                    "name": names.get(car_no, ""),
                    "lineLabel": f"ライン{line_index + 1}",
                    "lineIndex": line_index,
                    "linePosition": line_member_position(group, rider_index),
                    "lineColor": line_color,
                    "carColorName": car_color["name"],
                    "carColor": car_color["background"],
                    "carTextColor": car_color["text"],
                    "carBorderColor": car_color["border"],
                    "isActive": car_no in active_numbers,
                    "projectedRank": projected_rank.get(car_no, 0),
                    "x": x,
                    "y": y,
                    "defaultX": default_position["x"],
                    "defaultY": default_position["y"],
                }
            )
            chip_index += 1
    return pieces


def empty_development_history() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "race_id",
            "race_date",
            "venue",
            "grade",
            "car_numbers",
            "line_size",
            "line_function",
            "line_exact_top2",
            "leader_first",
            "leader_top3",
            "second_first",
            "second_top3",
            "third_top3",
            "single_top3",
            "line_top3_sweep",
            "line_collapse",
            "matched_top3",
            "winner_position",
        ]
    )


def fetch_development_history() -> pd.DataFrame:
    with get_conn() as conn:
        lines = pd.read_sql_query(
            """
            SELECT
                l.race_id,
                r.race_date,
                r.venue,
                r.grade,
                l.car_numbers
            FROM race_lines l
            JOIN races r ON r.id = l.race_id
            WHERE COALESCE(l.car_numbers, '') <> ''
            """,
            conn,
        )
        result_rows = pd.read_sql_query(
            """
            SELECT race_id, finish_order, car_no
            FROM race_result_rows
            WHERE finish_order > 0 AND car_no > 0
            ORDER BY race_id, finish_order, car_no
            """,
            conn,
        )
    if lines.empty or result_rows.empty:
        return empty_development_history()

    result_map: dict[int, tuple[int, ...]] = {}
    for race_id, rows in result_rows.groupby("race_id", sort=False):
        result_map[int(race_id)] = unique_top_numbers(rows.sort_values(["finish_order", "car_no"])["car_no"].astype(int).tolist())

    history_rows: list[dict] = []
    for _, line in lines.iterrows():
        race_id = int(line["race_id"])
        result = result_map.get(race_id, ())
        if not result:
            continue
        parsed = parse_line_summary(line["car_numbers"])
        if not parsed:
            continue
        line_numbers = tuple(parsed[0])
        if not line_numbers:
            continue
        top_set = set(result[:3])
        line_set = set(line_numbers)
        matched = len(line_set.intersection(top_set))
        leader = line_numbers[0]
        second = line_numbers[1] if len(line_numbers) >= 2 else None
        third = line_numbers[2] if len(line_numbers) >= 3 else None
        winner = result[0] if result else 0
        winner_position = "別線"
        if winner == leader:
            winner_position = "先頭"
        elif second and winner == second:
            winner_position = "番手"
        elif third and winner == third:
            winner_position = "3番手"
        elif len(line_numbers) == 1 and winner == leader:
            winner_position = "単騎"
        elif winner in line_set:
            winner_position = "ライン内"

        history_rows.append(
            {
                "race_id": race_id,
                "race_date": line["race_date"],
                "venue": line["venue"] or "",
                "grade": line["grade"] or "",
                "car_numbers": "-".join(str(number) for number in line_numbers),
                "line_size": len(line_numbers),
                "line_function": int((matched >= 2) if len(line_numbers) >= 2 else (leader in top_set)),
                "line_exact_top2": int(len(line_numbers) >= 2 and len(result) >= 2 and result[0] == leader and result[1] == second)
                if len(line_numbers) >= 2
                else None,
                "leader_first": int(winner == leader),
                "leader_top3": int(leader in top_set),
                "second_first": int(winner == second) if second else None,
                "second_top3": int(second in top_set) if second else None,
                "third_top3": int(third in top_set) if third else None,
                "single_top3": int(leader in top_set) if len(line_numbers) == 1 else None,
                "line_top3_sweep": int(len(line_numbers) >= 3 and set(line_numbers[:3]).issubset(top_set))
                if len(line_numbers) >= 3
                else None,
                "line_collapse": int(matched <= 1) if len(line_numbers) >= 2 else None,
                "matched_top3": matched,
                "winner_position": winner_position,
            }
        )

    if not history_rows:
        return empty_development_history()
    return pd.DataFrame(history_rows)


def select_development_sample(history: pd.DataFrame, active_group: tuple[int, ...], race: dict) -> tuple[pd.DataFrame, str]:
    if history.empty:
        return history, "過去データなし"
    line_size = len(active_group)
    same_size = history[history["line_size"].astype(int) == line_size].copy()
    if same_size.empty:
        return history, "全ライン"

    venue = str(race.get("venue", "") or "")
    grade = str(race.get("grade", "") or "")
    if venue and grade:
        same_venue_grade = same_size[(same_size["venue"] == venue) & (same_size["grade"] == grade)]
        if len(same_venue_grade) >= 5:
            return same_venue_grade, f"{venue} / {grade} / {line_size}車ライン"
    if venue:
        same_venue = same_size[same_size["venue"] == venue]
        if len(same_venue) >= 5:
            return same_venue, f"{venue} / {line_size}車ライン"
    if grade:
        same_grade = same_size[same_size["grade"] == grade]
        if len(same_grade) >= 5:
            return same_grade, f"{grade} / {line_size}車ライン"
    return same_size, f"{line_size}車ライン全体"


def probability_from_metric(sample: pd.DataFrame, metric: str) -> dict:
    if sample.empty or metric not in sample.columns:
        return {"hits": 0, "total": 0, "rate": 0.0}
    values = sample[metric].dropna()
    if values.empty:
        return {"hits": 0, "total": 0, "rate": 0.0}
    hits = int(values.astype(int).sum())
    total = int(len(values))
    return {"hits": hits, "total": total, "rate": hit_rate(hits, total)}


def development_metric_plan(active_group: tuple[int, ...]) -> list[tuple[str, str]]:
    if len(active_group) == 1:
        return [("単騎3着内", "single_top3"), ("単騎1着", "leader_first")]
    plan = [
        ("ライン機能", "line_function"),
        ("ライン順走", "line_exact_top2"),
        ("先頭1着", "leader_first"),
        ("番手1着", "second_first"),
        ("崩れ", "line_collapse"),
    ]
    if len(active_group) >= 3:
        plan.extend([("ライン3車上位独占", "line_top3_sweep"), ("3番手3着内", "third_top3")])
    return plan


def build_development_probability_summary(
    history: pd.DataFrame,
    active_group: tuple[int, ...],
    race: dict,
    scenario: str,
) -> tuple[pd.DataFrame, dict, str]:
    sample, scope = select_development_sample(history, active_group, race)
    rows: list[dict] = []
    for label, metric in development_metric_plan(active_group):
        probability = probability_from_metric(sample, metric)
        rows.append(
            {
                "項目": label,
                "確率": probability["rate"],
                "該当": probability["hits"],
                "件数": probability["total"],
                "metric": metric,
            }
        )
    summary = pd.DataFrame(rows)
    scenario_metric = DEVELOPMENT_SCENARIOS.get(scenario, {}).get("metric", "line_function")
    focus_rows = summary[summary["metric"] == scenario_metric] if not summary.empty else pd.DataFrame()
    focus = focus_rows.iloc[0].to_dict() if not focus_rows.empty else {"項目": scenario, "確率": 0.0, "該当": 0, "件数": 0}
    return summary.drop(columns=["metric"], errors="ignore"), focus, scope


def mean_or_zero(values: list[float]) -> float:
    clean_values = [float(value) for value in values if value is not None]
    if not clean_values:
        return 0.0
    return round(sum(clean_values) / len(clean_values), 1)


def rider_dict_by_car(riders: pd.DataFrame) -> dict[int, dict]:
    if riders.empty:
        return {}
    return {int(row["car_no"]): dict(row) for _, row in riders.iterrows()}


def rider_forecast_scores(riders: pd.DataFrame) -> dict[int, float]:
    if riders.empty:
        return {}
    racing_scores = [float(value or 0) for value in riders["racing_score"].fillna(0).tolist()]
    active_racing = [value for value in racing_scores if value > 0]
    min_racing = min(active_racing) if active_racing else 0.0
    max_racing = max(active_racing) if active_racing else 0.0
    mark_bonus = {"◎": 8.0, "○": 5.0, "▲": 3.0, "△": 1.5, "☆": 1.0}

    scores: dict[int, float] = {}
    for _, row in riders.iterrows():
        racing_score = float(row.get("racing_score", 0) or 0)
        if max_racing > min_racing and racing_score > 0:
            normalized_racing = 45.0 + ((racing_score - min_racing) / (max_racing - min_racing)) * 45.0
        elif racing_score > 0:
            normalized_racing = 70.0
        else:
            normalized_racing = 50.0
        subjective_score = float(row.get("総合", 50) or 50)
        bonus = mark_bonus.get(str(row.get("final_mark", "") or ""), 0.0)
        scores[int(row["car_no"])] = round(min(normalized_racing * 0.65 + subjective_score * 0.35 + bonus, 100.0), 1)
    return scores


def line_watch_point(group: tuple[int, ...], probability: dict[str, dict]) -> str:
    if len(group) == 1:
        top3 = probability.get("single_top3", {}).get("rate", 0.0)
        return f"単騎3着内 {top3:.1f}% を見て、位置取り待ちにするか判断"
    line_function = probability.get("line_function", {}).get("rate", 0.0)
    second_first = probability.get("second_first", {}).get("rate", 0.0)
    collapse = probability.get("line_collapse", {}).get("rate", 0.0)
    if collapse >= line_function:
        return f"崩れ {collapse:.1f}% が高め。別線・単騎の差し込みを確認"
    if len(group) >= 2 and second_first >= 20:
        return f"番手1着 {second_first:.1f}% あり。折り返し候補"
    return f"ライン機能 {line_function:.1f}% を軸候補として確認"


def build_prerace_line_reference(
    line_groups: tuple[tuple[int, ...], ...],
    riders: pd.DataFrame,
    race: dict,
    history: pd.DataFrame,
    names: dict[int, str],
) -> pd.DataFrame:
    rider_lookup = rider_dict_by_car(riders)
    score_map = rider_forecast_scores(riders)
    rows: list[dict] = []
    for index, group in enumerate(line_groups):
        sample, scope = select_development_sample(history, group, race)
        metrics = {
            metric: probability_from_metric(sample, metric)
            for _, metric in development_metric_plan(group)
        }
        racing_values = [float(rider_lookup.get(number, {}).get("racing_score", 0) or 0) for number in group]
        forecast_values = [score_map.get(number, 50.0) for number in group]
        leader = group[0]
        second = group[1] if len(group) >= 2 else 0
        rows.append(
            {
                "ライン": f"ライン{index + 1}",
                "並び": " - ".join(format_car_label(number, names) for number in group),
                "人数": len(group),
                "先頭": format_car_label(leader, names),
                "番手": format_car_label(second, names) if second else "",
                "平均競走得点": mean_or_zero([value for value in racing_values if value > 0]),
                "参考指数": mean_or_zero(forecast_values),
                "ライン機能率": metrics.get("line_function", {}).get("rate", 0.0),
                "番手1着率": metrics.get("second_first", {}).get("rate", 0.0),
                "崩れ率": metrics.get("line_collapse", {}).get("rate", 0.0),
                "サンプル": metrics.get("line_function", metrics.get("single_top3", {})).get("total", 0),
                "集計範囲": scope,
                "見るポイント": line_watch_point(group, metrics),
            }
        )
    return pd.DataFrame(rows)


def build_prerace_scenario_candidates(
    line_groups: tuple[tuple[int, ...], ...],
    riders: pd.DataFrame,
    race: dict,
    history: pd.DataFrame,
    names: dict[int, str],
) -> pd.DataFrame:
    score_map = rider_forecast_scores(riders)
    rows: list[dict] = []
    for line_index, group in enumerate(line_groups):
        line_values = [score_map.get(number, 50.0) for number in group]
        line_score = mean_or_zero(line_values) or 50.0
        for scenario in scenario_options_for_group(group):
            top3 = project_development_top3(line_groups, line_index, scenario)
            scenario_metric = DEVELOPMENT_SCENARIOS.get(scenario, {}).get("metric", "line_function")
            sample, scope = select_development_sample(history, group, race)
            probability = probability_from_metric(sample, scenario_metric)
            top_values = [score_map.get(number, 50.0) for number in top3]
            top_score = mean_or_zero(top_values) or 50.0
            sample_weight = min(float(probability["total"]) / 20.0, 1.0)
            reference_index = round((probability["rate"] * 0.5 * sample_weight) + (top_score * 0.35) + (line_score * 0.15), 1)
            rows.append(
                {
                    "ライン": f"ライン{line_index + 1}",
                    "展開": scenario,
                    "想定上位": " - ".join(format_car_label(number, names) for number in top3),
                    "過去目安": probability["rate"],
                    "該当": probability["hits"],
                    "件数": probability["total"],
                    "選手指数": top_score,
                    "参考指数": reference_index,
                    "集計範囲": scope,
                }
            )
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(["参考指数", "過去目安", "選手指数"], ascending=False).reset_index(drop=True)


def prerace_note_text(
    race: dict,
    line_reference: pd.DataFrame,
    scenario_candidates: pd.DataFrame,
) -> str:
    race_label_text = f"{race.get('venue', '')} {race.get('race_no', '')}R"
    if line_reference.empty or scenario_candidates.empty:
        return f"{race_label_text} 開催前メモ\nライン構成、選手評価、過去目安を確認する。"
    top_line = line_reference.sort_values(["参考指数", "ライン機能率"], ascending=False).iloc[0]
    top_scenario = scenario_candidates.iloc[0]
    return (
        f"{race_label_text} 開催前メモ\n"
        f"注目ライン: {top_line['ライン']} {top_line['並び']}\n"
        f"見るポイント: {top_line['見るポイント']}\n"
        f"展開候補: {top_scenario['展開']} / {top_scenario['想定上位']}\n"
        f"過去目安: {top_scenario['過去目安']}% ({int(top_scenario['該当'])}/{int(top_scenario['件数'])}, {top_scenario['集計範囲']})\n"
        "判断: ここに自分の読み、切る車番、押さえる形を追記する。"
    )


def render_prerace_reference_panel(
    race: dict,
    line_groups: tuple[tuple[int, ...], ...],
    riders: pd.DataFrame,
    history: pd.DataFrame,
    names: dict[int, str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    st.markdown("#### 開催前の予想材料")
    if riders.empty:
        st.info("選手情報を補完すると、ライン別の参考指数とシナリオ候補を表示できます。")
        return pd.DataFrame(), pd.DataFrame()

    line_reference = build_prerace_line_reference(line_groups, riders, race, history, names)
    scenario_candidates = build_prerace_scenario_candidates(line_groups, riders, race, history, names)
    if line_reference.empty:
        st.info("ライン構成を入力すると、開催前の予想材料を表示できます。")
        return line_reference, scenario_candidates

    best_line = line_reference.sort_values(["参考指数", "ライン機能率"], ascending=False).iloc[0]
    best_scenario = scenario_candidates.iloc[0] if not scenario_candidates.empty else {}
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("ライン数", f"{len(line_groups)}")
    col2.metric("補完選手", f"{len(riders)}")
    col3.metric("注目ライン", str(best_line["ライン"]), f"{float(best_line['参考指数']):.1f}")
    col4.metric("上位展開", str(best_scenario.get("展開", "未計算")), f"{float(best_scenario.get('参考指数', 0.0)):.1f}")

    st.dataframe(
        line_reference,
        use_container_width=True,
        hide_index=True,
    )
    if not scenario_candidates.empty:
        st.markdown("#### 展開候補")
        st.dataframe(
            scenario_candidates.head(12),
            use_container_width=True,
            hide_index=True,
        )
    st.text_area("開催前メモ草案", value=prerace_note_text(race, line_reference, scenario_candidates), height=140)
    return line_reference, scenario_candidates


def virtual_bank_html(
    line_groups: tuple[tuple[int, ...], ...],
    active_index: int,
    projected_top3: tuple[int, ...],
    names: dict[int, str],
) -> str:
    total = len(flatten_line_groups(line_groups))
    if total == 0:
        return ""

    active_numbers = set(line_groups[active_index]) if 0 <= active_index < len(line_groups) else set()
    projected_rank = {number: index + 1 for index, number in enumerate(projected_top3)}
    chips: list[str] = []
    chip_index = 0
    spread = 320 if total > 1 else 0
    for line_index, group in enumerate(line_groups):
        line_color = BANK_LINE_COLORS[line_index % len(BANK_LINE_COLORS)]
        for number in group:
            car_color = car_number_color_style(int(number))
            angle = math.radians(-24 + (spread * chip_index / max(total - 1, 1)))
            left = 50 + 40 * math.cos(angle)
            top = 50 + 34 * math.sin(angle)
            classes = ["rider-chip"]
            if number in active_numbers:
                classes.append("is-active")
            if number in projected_rank:
                classes.append("is-projected")
            rank_html = f"<span class='rider-rank'>{projected_rank[number]}着</span>" if number in projected_rank else ""
            chips.append(
                (
                    f'<div class="{" ".join(classes)}" '
                    f'style="left:{left:.1f}%; top:{top:.1f}%; '
                    f'--line-color:{line_color}; '
                    f'--car-color:{car_color["background"]}; '
                    f'--car-text-color:{car_color["text"]}; '
                    f'--car-border-color:{car_color["border"]};">'
                    f"{rank_html}"
                    f'<span class="rider-no">{int(number)}</span>'
                    f"<strong>{html.escape(f'ライン{line_index + 1}')}</strong>"
                    f'<span class="rider-name">{html.escape(names.get(int(number), ""))}</span>'
                    "</div>"
                )
            )
            chip_index += 1

    return "".join(
        [
            '<div class="virtual-bank">',
            f'<div class="bank-center-label">仮想バンク<br>{html.escape(format_line_groups(line_groups))}</div>',
            *chips,
            "</div>",
        ]
    )


def render_virtual_bank(
    line_groups: tuple[tuple[int, ...], ...],
    active_index: int,
    projected_top3: tuple[int, ...],
    names: dict[int, str],
) -> None:
    bank_html = virtual_bank_html(line_groups, active_index, projected_top3, names)
    if not bank_html:
        st.info("ライン構成を入力すると仮想バンクを表示します。")
        return
    st.markdown(bank_html, unsafe_allow_html=True)


def render_interactive_lineup_board(
    race_id: int,
    line_groups: tuple[tuple[int, ...], ...],
    active_index: int,
    projected_top3: tuple[int, ...],
    names: dict[int, str],
) -> None:
    positions_key = f"development_board_positions_{race_id}"
    saved_positions = st.session_state.get(positions_key, {})
    valid_car_numbers = flatten_line_groups(line_groups)
    saved_positions = normalize_board_positions(saved_positions, valid_car_numbers)
    pieces = lineup_board_pieces(line_groups, active_index, projected_top3, names, saved_positions)
    if not pieces:
        render_virtual_bank(line_groups, active_index, projected_top3, names)
        return

    value = LINEUP_BOARD_COMPONENT(
        pieces=pieces,
        line_summary=format_line_groups(line_groups),
        active_line=f"ライン{active_index + 1}",
        projected_top3=list(projected_top3),
        key=f"development_lineup_board_{race_id}",
        default=None,
    )
    if not isinstance(value, dict):
        return

    next_positions = normalize_board_positions(value.get("positions", {}), valid_car_numbers)
    if next_positions and next_positions != saved_positions:
        st.session_state[positions_key] = next_positions
        st.rerun()


def development_note_text(
    race: dict,
    active_label: str,
    scenario: str,
    projected_top3: tuple[int, ...],
    focus: dict,
    scope: str,
    names: dict[int, str],
) -> str:
    top_text = " - ".join(format_car_label(number, names) for number in projected_top3) or "未設定"
    return (
        f"{race.get('venue', '')} {race.get('race_no', '')}R 展開仮説\n"
        f"狙いライン: {active_label}\n"
        f"展開タイプ: {scenario}（{DEVELOPMENT_SCENARIOS.get(scenario, {}).get('summary', '')}）\n"
        f"想定上位: {top_text}\n"
        f"過去目安: {focus.get('項目', scenario)} {focus.get('確率', 0.0)}% "
        f"({int(focus.get('該当', 0))}/{int(focus.get('件数', 0))}, {scope})"
    )


def display_queue_table(df: pd.DataFrame, *, key: str, empty_message: str, target_page: str = "買い目・結果") -> None:
    if df.empty:
        st.caption(empty_message)
        return
    display_df = df.drop(columns=["race_id"], errors="ignore")
    state = st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
        key=key,
        on_select="rerun",
        selection_mode="single-row",
    )
    selected_rows = getattr(getattr(state, "selection", None), "rows", [])
    if not selected_rows:
        return
    selected_race_id = int(df.iloc[int(selected_rows[0])]["race_id"])
    handled_key = f"{key}_handled_race_id"
    if st.session_state.get(handled_key) == selected_race_id:
        return
    st.session_state[handled_key] = selected_race_id
    st.session_state["selected_race_id"] = selected_race_id
    st.session_state["page"] = target_page
    st.rerun()


def render_today_races_panel(races: pd.DataFrame, sync_result: dict | None) -> None:
    today_text = date.today().isoformat()
    st.subheader("本日開催")
    col_info, col_action = st.columns([3, 1])
    with col_info:
        if sync_result and sync_result.get("error"):
            st.warning(f"{today_text} のWINTICKET開催一覧を更新できませんでした: {sync_result['error']}")
        elif sync_result:
            details = sync_result.get("details") or {}
            detail_text = ""
            if details:
                detail_text = f" / 補完{len(details.get('synced', []))}件 / 失敗{len(details.get('failed', []))}件"
            st.caption(
                f"{sync_result['race_date']} 更新: 取得{sync_result['fetched']}件 / "
                f"新規{sync_result['created']}件 / 更新{sync_result['updated']}件{detail_text}"
            )
        else:
            st.caption("アプリ起動・再読み込み時にWINTICKET開催一覧を確認します。")
    with col_action:
        if st.button("本日開催を更新", use_container_width=True):
            with st.spinner("WINTICKETの本日開催を更新しています..."):
                try:
                    result = sync_winticket_race_list_for_date(today_text)
                except Exception as exc:
                    st.session_state["winticket_today_sync_result"] = {
                        "race_date": today_text,
                        "error": str(exc),
                        "fetched": 0,
                        "created": 0,
                        "updated": 0,
                    }
                    st.error(f"更新に失敗しました: {exc}")
                else:
                    st.session_state["winticket_today_sync_result"] = result
                    details = result.get("details") or {}
                    detail_text = ""
                    if details:
                        detail_text = f" / 補完{len(details.get('synced', []))}件 / 失敗{len(details.get('failed', []))}件"
                    st.success(f"本日開催を更新しました。新規{result['created']}件 / 更新{result['updated']}件{detail_text}")
                st.rerun()

    if races.empty:
        st.info("本日開催の登録レースはまだありません。")
        return

    today_races = sort_latest_races(races[races["race_date"] == today_text])
    if today_races.empty:
        st.info("本日開催の登録レースはまだありません。更新ボタンでWINTICKETから取得できます。")
        return

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("本日レース", f"{len(today_races)}")
    col2.metric("未買い目", f"{int((today_races['bet_count'].fillna(0).astype(int) == 0).sum())}")
    col3.metric("理由なし", f"{int((today_races['missing_bet_reason_count'].fillna(0).astype(int) > 0).sum())}")
    col4.metric("未振り返り", f"{int((today_races['review_done'].fillna(0).astype(int) == 0).sum())}")

    today_view = today_races.copy()
    today_view["race_id"] = today_view["id"].astype(int)
    today_view["未入力"] = today_view.apply(lambda row: " / ".join(research_issues(row)) or "完了", axis=1)
    select_labels = [
        f"{row['venue']} {int(row['race_no'])}R {row.get('start_time') or '--:--'} / {row.get('status') or ''} / {row.get('race_title') or '無題'}"
        for _, row in today_view.iterrows()
    ]
    today_ids = [int(row["race_id"]) for _, row in today_view.iterrows()]
    selected_state_id = st.session_state.get("selected_race_id")
    try:
        selected_state_id = int(selected_state_id) if selected_state_id is not None else None
    except (TypeError, ValueError):
        selected_state_id = None
    default_select_index = today_ids.index(selected_state_id) if selected_state_id in today_ids else 0
    col_select, col_open, col_hydrate = st.columns([3, 1, 1])
    selected_today_label = col_select.selectbox(
        "本日開催からレースを選択",
        select_labels,
        index=default_select_index,
        key="today_race_selector",
    )
    selected_today_id = today_ids[select_labels.index(selected_today_label)]
    if col_open.button("選択レースを開く", use_container_width=True):
        st.session_state["selected_race_id"] = selected_today_id
        st.session_state["page"] = "買い目・結果"
        st.rerun()
    if col_hydrate.button("補完して開く", use_container_width=True):
        with st.spinner("選択レースの選手・ライン・結果を補完しています..."):
            try:
                source = sync_winticket_for_race(selected_today_id)
            except Exception as exc:
                st.error(f"選択レースの補完に失敗しました: {exc}")
            else:
                st.success(f"補完完了: 選手{len(source.riders)}名 / ライン{len(parse_line_summary(source.line_summary))}件 / 結果{len(source.result_rows)}行")
                st.session_state["selected_race_id"] = selected_today_id
                st.session_state["page"] = "買い目・結果"
                st.rerun()

    col_batch_count, col_batch_run = st.columns([1, 3])
    batch_limit = col_batch_count.selectbox("随時補完", [3, 5, 10, 20], index=1, key="today_batch_hydrate_limit")
    if col_batch_run.button("本日未補完を少し補完", use_container_width=True):
        with st.spinner(f"本日未補完レースを{int(batch_limit)}件まで補完しています..."):
            result = sync_winticket_details_for_race_ids(today_ids, limit=int(batch_limit))
        st.session_state["winticket_today_sync_result"] = {
            "race_date": today_text,
            "fetched": len(today_ids),
            "created": 0,
            "updated": len(today_ids),
            "race_ids": today_ids,
            "details": result,
        }
        if result["synced"]:
            st.success(f"{len(result['synced'])}件を補完しました。")
            st.dataframe(pd.DataFrame(result["synced"]), use_container_width=True, hide_index=True)
        if result["failed"]:
            st.warning(f"{len(result['failed'])}件は補完できませんでした。")
            st.dataframe(pd.DataFrame(result["failed"]), use_container_width=True, hide_index=True)
        st.rerun()

    display_queue_table(
        today_view[
            [
                "race_id",
                "race_date",
                "venue",
                "race_no",
                "start_time",
                "close_time",
                "race_title",
                "status",
                "source_status",
                "bet_count",
                "未入力",
            ]
        ].rename(
            columns={
                "race_date": "日付",
                "venue": "場",
                "race_no": "R",
                "start_time": "発走",
                "close_time": "締切",
                "race_title": "レース",
                "status": "状態",
                "source_status": "取得状態",
                "bet_count": "買い目数",
            }
        ),
        key="today_races_table",
        empty_message="本日開催の登録レースはありません。",
    )


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
                        "strategy_type",
                        "prediction_source",
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
                        "strategy_type": "買い方の型",
                        "prediction_source": "予想区分",
                        "note": "買い目理由",
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
    col4.metric("購入額", metric_amount_text(int(top_rider["購入額"]), selected_unit))

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


def render_rider_position_insights() -> None:
    st.subheader("選手別ポジション成績")
    details = fetch_rider_result_details()
    summary = build_rider_position_summary(details)
    if summary.empty:
        st.info("選手名と結果詳細が補完されると、位置別の1着率・3着内率・ライン機能率を表示できます。")
        return

    max_races = max(int(summary["出走数"].max()), 1)
    position_options = [position for position in POSITION_OPTIONS if position in summary["line_position"].unique()]
    default_positions = [position for position in ["先頭", "番手", "3番手", "単騎"] if position in position_options]
    col_filter, col_metric, col_count = st.columns([2, 1, 1])
    selected_positions = col_filter.multiselect(
        "見る位置",
        position_options,
        default=default_positions or position_options,
        key="rider_position_filter",
    )
    sort_metric = col_metric.selectbox(
        "見る指標",
        ["3着内率", "1着率", "2着以内率", "ライン機能率", "ライン崩れ率", "出走数", "平均競走得点"],
        key="rider_position_metric",
    )
    min_races = col_count.slider("最少出走数", min_value=1, max_value=max_races, value=min(3, max_races), key="rider_position_min")
    rider_query = st.text_input("選手名で絞り込み", value="", key="rider_position_query")

    view = summary[summary["出走数"] >= int(min_races)].copy()
    if selected_positions:
        view = view[view["line_position"].isin(selected_positions)].copy()
    if rider_query.strip():
        view = view[view["rider_name"].str.contains(rider_query.strip(), case=False, na=False)].copy()
    if view.empty:
        st.info("条件に合う選手データはありません。最少出走数や位置フィルタを緩めてください。")
        return

    top = view.sort_values([sort_metric, "出走数", "3着内率"], ascending=False).head(20)
    best_row = top.iloc[0]
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("対象選手", f"{view['rider_name'].nunique():,}人")
    col2.metric("対象サンプル", f"{int(view['出走数'].sum()):,}走")
    col3.metric("上位", str(best_row["選手位置"]))
    col4.metric(sort_metric, f"{float(best_row[sort_metric]):.1f}%" if sort_metric.endswith("率") else f"{float(best_row[sort_metric]):,.1f}")

    text_template = "%{x:.1f}%" if sort_metric.endswith("率") else ("%{x:,.0f}" if sort_metric == "出走数" else "%{x:.2f}")
    fig = horizontal_bar(
        top,
        label_col="選手位置",
        value_col=sort_metric,
        color_col="3着内率",
        continuous_color=True,
        title=f"選手別ポジション成績 TOP{len(top)}",
        x_title=sort_metric,
        hover_data=["出走数", "結果あり", "1着率", "2着以内率", "3着内率", "ライン機能率", "ライン崩れ率", "最終出走日"],
        text_template=text_template,
        color_scale=["#475569", "#38bdf8", "#22c55e"],
    )
    if sort_metric.endswith("率"):
        fig.update_xaxes(range=[0, 100])
    st.plotly_chart(fig, use_container_width=True)
    st.caption("着順・ライン位置・ライン自動判定だけを使った事実ベースの集計です。心理・関係性評価はここでは混ぜません。")

    display_columns = [
        "選手",
        "line_position",
        "出走数",
        "結果あり",
        "一着",
        "二着",
        "三着",
        "三着内",
        "1着率",
        "2着以内率",
        "3着内率",
        "ライン機能率",
        "ライン崩れ率",
        "平均競走得点",
        "平均上がり",
        "最終出走日",
        "見るポイント",
    ]
    st.dataframe(
        view.sort_values([sort_metric, "出走数", "3着内率"], ascending=False)[display_columns]
        .head(80)
        .rename(
            columns={
                "line_position": "位置",
                "一着": "1着",
                "二着": "2着",
                "三着": "3着",
            }
        ),
        use_container_width=True,
        hide_index=True,
    )

    rider_options = view.sort_values(["出走数", "3着内率"], ascending=False)["rider_name"].drop_duplicates().tolist()
    selected_rider = st.selectbox("選手カード", rider_options, key="rider_position_card")
    rider_rows = summary[summary["rider_name"] == selected_rider].sort_values(["出走数", "3着内率"], ascending=False)
    if rider_rows.empty:
        return

    st.markdown("#### 選手カード")
    card_cols = st.columns(4)
    card_cols[0].metric("出走サンプル", f"{int(rider_rows['出走数'].sum()):,}走")
    card_cols[1].metric("最高3着内率", f"{float(rider_rows['3着内率'].max()):.1f}%")
    card_cols[2].metric("最高1着率", f"{float(rider_rows['1着率'].max()):.1f}%")
    card_cols[3].metric("主な位置", str(rider_rows.iloc[0]["line_position"]))
    st.dataframe(
        rider_rows[
            [
                "line_position",
                "出走数",
                "結果あり",
                "1着率",
                "2着以内率",
                "3着内率",
                "ライン機能率",
                "ライン崩れ率",
                "平均競走得点",
                "平均上がり",
                "見るポイント",
            ]
        ].rename(columns={"line_position": "位置"}),
        use_container_width=True,
        hide_index=True,
    )

    rider_history = details[details["rider_name"] == selected_rider].copy()
    if not rider_history.empty:
        st.markdown("#### 直近履歴")
        rider_history["着順"] = rider_history["finish_order"].apply(lambda value: "" if pd.isna(value) else int(value))
        st.dataframe(
            rider_history[
                [
                    "race_date",
                    "venue",
                    "race_no",
                    "grade",
                    "car_no",
                    "line_position",
                    "line_auto_status",
                    "着順",
                    "agari",
                    "decision",
                    "sb",
                ]
            ]
            .head(12)
            .rename(
                columns={
                    "race_date": "日付",
                    "venue": "場",
                    "race_no": "R",
                    "grade": "級",
                    "car_no": "車番",
                    "line_position": "位置",
                    "line_auto_status": "ライン結果",
                    "agari": "上り",
                    "decision": "決まり手",
                    "sb": "S/B",
                }
            ),
            use_container_width=True,
            hide_index=True,
        )


def render_dashboard(races: pd.DataFrame, selected_race_id: int | None, sync_result: dict | None = None) -> None:
    render_header(None)
    if races.empty:
        render_today_races_panel(races, sync_result)
        st.info("まずはレース登録から始めます。サイドバーのサンプル投入も使えます。")
        return

    bets = fetch_all_bets()
    hit_rate_bets = exclude_adjustment_bets(bets)
    unit = summary_unit(bets)
    hit_count = int(hit_rate_bets["hit"].sum()) if not hit_rate_bets.empty else 0
    race_count = len(races)
    rider_done = int((races["rider_count"] > 0).sum())
    line_done = int((races["line_count"] > 0).sum())
    review_done = int((races["review_done"] > 0).sum())

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("登録レース", f"{len(races)}")
    col2.metric("選手補完率", rate_text(rider_done, race_count), f"{rider_done}/{race_count}")
    col3.metric("ライン補完率", rate_text(line_done, race_count), f"{line_done}/{race_count}")
    col4.metric("振り返り完了率", rate_text(review_done, race_count), f"{review_done}/{race_count}")
    col5.metric("的中率", f"{hit_rate(hit_count, len(hit_rate_bets))}%" if not hit_rate_bets.empty else "0.0%")

    render_today_races_panel(races, sync_result)

    render_winticket_sync_panel(selected_race_id, races)

    st.markdown("#### 投票トレーニング集計")
    render_bet_performance_summary(bets)

    st.subheader("入力キュー")
    col_unbet, col_reason, col_review = st.columns(3)
    with col_unbet:
        st.markdown("#### 未買い目予想")
        display_queue_table(
            build_unbet_race_queue(races, limit=20),
            key="unbet_queue_table",
            empty_message="買い目未入力のレースはありません。",
        )
    with col_reason:
        st.markdown("#### 買い目理由なし")
        display_queue_table(
            build_missing_bet_reason_queue(races, limit=20),
            key="missing_reason_queue_table",
            empty_message="買い目理由が空欄のレースはありません。",
        )
    with col_review:
        st.markdown("#### 振り返り未完了")
        display_queue_table(
            build_unreviewed_race_queue(races, limit=20),
            key="unreviewed_queue_table",
            empty_message="振り返り未完了のレースはありません。",
        )

    queue = build_research_queue(races)
    st.subheader("研究キュー")
    if queue.empty:
        st.success("未補完・未評価のレースはありません。いい感じに研究ノートが育っています。")
    else:
        st.dataframe(queue.drop(columns=["race_id"], errors="ignore"), use_container_width=True, hide_index=True)

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
    races_view["的中率"] = races_view.apply(lambda row: hit_rate(int(row["hit_count"]), int(row["bet_count"])), axis=1)
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
                "start_time",
                "close_time",
                "status",
                "amount_unit",
                "rider_count",
                "line_count",
                "result_row_count",
                "bet_count",
                "missing_bet_reason_count",
                "hit_count",
                "的中率",
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
                "start_time": "発走",
                "close_time": "締切",
                "status": "状態",
                "amount_unit": "単位",
                "rider_count": "選手数",
                "line_count": "ライン数",
                "result_row_count": "結果詳細",
                "bet_count": "買い目数",
                "missing_bet_reason_count": "理由なし",
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
        ticket_summary["的中率"] = ticket_summary.apply(lambda row: hit_rate(int(row["的中"]), int(row["件数"])), axis=1)
        ticket_summary["券種"] = ticket_summary["ticket_type"] + " / " + ticket_summary["amount_unit"]
        venue_summary = (
            bets.groupby(["amount_unit", "venue"])
            .agg(購入=("stake", "sum"), 払戻=("payout", "sum"), 的中=("hit", "sum"), 件数=("id", "count"))
            .reset_index()
        )
        venue_summary["差分"] = venue_summary["払戻"] - venue_summary["購入"]
        venue_summary["的中率"] = venue_summary.apply(lambda row: hit_rate(int(row["的中"]), int(row["件数"])), axis=1)
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
                hover_data=["購入", "払戻", "的中", "件数", "的中率"],
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
                hover_data=["購入", "払戻", "的中", "件数", "的中率"],
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


def render_development_forecast(selected_race_id: int | None, races: pd.DataFrame | None = None) -> None:
    races = races if races is not None else fetch_races()
    if races.empty:
        render_header(None)
        st.subheader("展開予想")
        st.info("先にレースを登録してください。")
        return

    if not selected_race_id:
        selected_race_id = int(sort_latest_races(races).iloc[0]["id"])
        st.session_state["selected_race_id"] = selected_race_id

    selected_race = fetch_race(selected_race_id)
    render_header(selected_race)
    st.subheader("展開予想")

    selected_race_id = render_page_race_selector(
        races,
        selected_race_id,
        label="展開予想で見るレース",
        key_prefix="development_forecast",
    )
    if not selected_race_id:
        st.info("先にレースを登録してください。")
        return

    selected_race = fetch_race(selected_race_id)
    lines = fetch_lines(selected_race_id)
    names = rider_name_map(selected_race_id)
    default_groups = race_line_groups(selected_race, lines)
    groups_key = f"development_bank_groups_{selected_race_id}"
    input_key = f"development_line_input_{selected_race_id}"
    active_key = f"development_active_index_{selected_race_id}"
    scenario_key = f"development_scenario_{selected_race_id}"
    message_key = f"development_sync_message_{selected_race_id}"
    positions_key = f"development_board_positions_{selected_race_id}"

    if input_key not in st.session_state:
        st.session_state[input_key] = format_line_groups(default_groups)
    if groups_key not in st.session_state:
        st.session_state[groups_key] = default_groups
    if active_key not in st.session_state:
        st.session_state[active_key] = 0
    current_state_groups = normalize_line_groups(tuple(tuple(group) for group in st.session_state.get(groups_key, ())))
    if default_groups and not current_state_groups and not str(st.session_state.get(input_key, "")).strip():
        st.session_state[input_key] = format_line_groups(default_groups)
        st.session_state[groups_key] = default_groups
        st.session_state[active_key] = 0

    sync_message = st.session_state.pop(message_key, None)
    if sync_message:
        if sync_message.get("level") == "warning":
            st.warning(sync_message.get("text", ""))
        else:
            st.success(sync_message.get("text", ""))

    source_race_id = selected_race.get("source_race_id") or extract_source_race_id(selected_race.get("race_memo", ""))
    if not default_groups:
        col_hydrate, col_hint = st.columns([1, 3])
        if col_hydrate.button("WINTICKET補完", use_container_width=True, disabled=not bool(source_race_id)):
            with st.spinner("選手・ライン・結果を補完しています..."):
                try:
                    source = sync_winticket_for_race(selected_race_id)
                except Exception as exc:
                    st.error(f"補完に失敗しました: {exc}")
                else:
                    refreshed_race = fetch_race(selected_race_id)
                    refreshed_lines = fetch_lines(selected_race_id)
                    refreshed_groups = race_line_groups(refreshed_race, refreshed_lines)
                    if refreshed_groups:
                        st.session_state[input_key] = format_line_groups(refreshed_groups)
                        st.session_state[groups_key] = refreshed_groups
                        st.session_state[active_key] = 0
                        st.session_state.pop(positions_key, None)
                        st.session_state[message_key] = {
                            "level": "success",
                            "text": f"補完完了: 選手{len(source.riders)}名 / ライン{len(refreshed_groups)}件。展開予想へ反映しました。",
                        }
                    else:
                        st.session_state[message_key] = {
                            "level": "warning",
                            "text": "補完しましたが、ライン構成は見つかりませんでした。手入力でラインを入れてください。",
                        }
                    st.rerun()
        if source_race_id:
            col_hint.info("このレースは開催一覧だけ登録済みです。WINTICKET補完でライン構成を取得できます。")
        else:
            col_hint.info("ライン構成を手入力してください。例: 123ー456ー789 / 1-2-3 ・ 4-5")

    col_input, col_apply, col_reset = st.columns([4, 1, 1])
    if col_reset.button("登録ライン", use_container_width=True, disabled=not bool(default_groups)):
        st.session_state[input_key] = format_line_groups(default_groups)
        st.session_state[groups_key] = default_groups
        st.session_state[active_key] = 0
        st.session_state.pop(positions_key, None)
        st.rerun()
    col_input.text_input("ライン構成", key=input_key, placeholder="例: 123ー456ー789 / 1-2-3 ・ 4-5")
    if col_apply.button("反映", use_container_width=True):
        parsed_groups = normalize_line_groups(parse_line_summary(st.session_state.get(input_key, "")))
        if not parsed_groups:
            st.error("ライン構成を読み取れませんでした。")
        else:
            st.session_state[groups_key] = parsed_groups
            st.session_state[active_key] = 0
            st.session_state.pop(positions_key, None)
            st.rerun()

    line_groups = normalize_line_groups(tuple(tuple(group) for group in st.session_state.get(groups_key, ())))
    if not line_groups:
        st.info("ライン構成を入力すると、仮想バンクと過去確率を表示します。")
        return

    riders = fetch_riders(selected_race_id)
    history = fetch_development_history()
    render_prerace_reference_panel(selected_race, line_groups, riders, history, names)

    active_index = max(0, min(int(st.session_state.get(active_key, 0) or 0), len(line_groups) - 1))
    group_labels = [line_group_label(index, group, names) for index, group in enumerate(line_groups)]
    selected_label = st.selectbox("狙いライン", group_labels, index=active_index)
    active_index = group_labels.index(selected_label)
    st.session_state[active_key] = active_index
    active_group = line_groups[active_index]

    col_front, col_prev, col_next, col_back, col_reverse = st.columns(5)
    if col_front.button("先頭へ", use_container_width=True, disabled=active_index == 0):
        st.session_state[groups_key] = move_line_group(line_groups, active_index, 0)
        st.session_state[active_key] = 0
        st.session_state.pop(positions_key, None)
        st.rerun()
    if col_prev.button("一つ前へ", use_container_width=True, disabled=active_index == 0):
        st.session_state[groups_key] = move_line_group(line_groups, active_index, active_index - 1)
        st.session_state[active_key] = active_index - 1
        st.session_state.pop(positions_key, None)
        st.rerun()
    if col_next.button("一つ後ろへ", use_container_width=True, disabled=active_index >= len(line_groups) - 1):
        st.session_state[groups_key] = move_line_group(line_groups, active_index, active_index + 1)
        st.session_state[active_key] = active_index + 1
        st.session_state.pop(positions_key, None)
        st.rerun()
    if col_back.button("最後尾へ", use_container_width=True, disabled=active_index >= len(line_groups) - 1):
        st.session_state[groups_key] = move_line_group(line_groups, active_index, len(line_groups) - 1)
        st.session_state[active_key] = len(line_groups) - 1
        st.session_state.pop(positions_key, None)
        st.rerun()
    if col_reverse.button("隊列反転", use_container_width=True):
        st.session_state[groups_key] = tuple(reversed(line_groups))
        st.session_state[active_key] = len(line_groups) - 1 - active_index
        st.session_state.pop(positions_key, None)
        st.rerun()

    scenario_options = scenario_options_for_group(active_group)
    if st.session_state.get(scenario_key) not in scenario_options:
        st.session_state[scenario_key] = scenario_options[0]
    scenario = st.radio("展開タイプ", scenario_options, horizontal=True, key=scenario_key)
    projected_top3 = project_development_top3(line_groups, active_index, scenario)
    probability_summary, focus, scope = build_development_probability_summary(history, active_group, selected_race, scenario)

    bank_col, probability_col = st.columns([2, 1])
    with bank_col:
        render_interactive_lineup_board(selected_race_id, line_groups, active_index, projected_top3, names)
    with probability_col:
        st.markdown("#### 過去目安")
        st.metric(
            str(focus.get("項目", scenario)),
            f"{float(focus.get('確率', 0.0)):.1f}%",
            f"{int(focus.get('該当', 0))}/{int(focus.get('件数', 0))}",
        )
        st.caption(f"集計範囲: {scope}")
        if projected_top3:
            st.markdown("#### 想定上位")
            for index, number in enumerate(projected_top3, start=1):
                st.write(f"{index}着候補: {format_car_label(number, names)}")
        st.caption("過去比率は保存済みレース内の目安で、的中や利益を保証するものではありません。")

    order_rows = [
        {
            "隊列": index + 1,
            "ライン": f"ライン{index + 1}",
            "車番": "-".join(str(number) for number in group),
            "名前付き": " - ".join(format_car_label(number, names) for number in group),
        }
        for index, group in enumerate(line_groups)
    ]
    col_order, col_probability = st.columns([1, 1])
    with col_order:
        st.markdown("#### 現在の隊列")
        st.dataframe(pd.DataFrame(order_rows), use_container_width=True, hide_index=True)
    with col_probability:
        st.markdown("#### 確率内訳")
        if probability_summary.empty:
            st.info("結果補完済みの過去レースが増えると確率内訳を表示できます。")
        else:
            st.dataframe(probability_summary, use_container_width=True, hide_index=True)

    note = development_note_text(selected_race, selected_label, scenario, projected_top3, focus, scope, names)
    st.text_area("展開メモ草案", value=note, height=150)


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
            col3, col4 = st.columns(2)
            strategy_type = col3.selectbox("買い方の型", STRATEGY_TYPES, index=0)
            prediction_source = col4.selectbox("予想区分", PREDICTION_SOURCES, index=1)
            expected_role = st.text_input("位置づけ", placeholder="本線 / 押さえ / 穴 / 見送り検証")
            note = st.text_area("買い目理由", height=90)
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
                        "strategy_type": strategy_type,
                        "prediction_source": prediction_source,
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
    bet_hit_count = int(bets["hit"].sum())
    bet_unit_summary = summary_unit(bets)
    if is_tip_medal(bet_unit_summary):
        col1, col2, col3, col4, col5, col6 = st.columns(6)
        col1.metric("買い目数", f"{len(bets)}")
        col2.metric("的中率", hit_rate_metric_text(bet_hit_count, len(bets)), f"{bet_hit_count}/{len(bets)}")
        col3.metric("利用", metric_amount_text(total_stake, bet_unit_summary))
        col4.metric("的中払戻", metric_amount_text(total_payout, bet_unit_summary))
        col5.metric("残り目安", metric_amount_text(remaining_tip_medals(total_stake), bet_unit_summary))
        col6.metric(net_label(bet_unit_summary), metric_amount_text(profit(total_stake, total_payout), bet_unit_summary))
        st.caption(
            f"TIPメダルは毎日{compact_tip_medal_text(TIP_MEDAL_DAILY_GRANT)}付与、{TIP_MEDAL_RESET_TEXT}に失効。"
            "この画面のメダル差分は現金損益ではなく、的中率トレーニング用の参考値です。"
        )
    elif bet_unit_summary == "単位混在":
        col1, col2, col3, col4, col5 = st.columns(5)
        col1.metric("買い目数", f"{len(bets)}")
        col2.metric("的中率", hit_rate_metric_text(bet_hit_count, len(bets)), f"{bet_hit_count}/{len(bets)}")
        col3.metric("購入", amount_summary_text(bets, "stake", compact_tip=True))
        col4.metric("払戻", amount_summary_text(bets, "payout", compact_tip=True))
        col5.metric("差分", profit_summary_text(bets, compact_tip=True))
        st.caption("複数単位が混ざっているため、円収支とメダル差分は明細の単位列で分けて確認します。")
    else:
        col1, col2, col3, col4, col5, col6 = st.columns(6)
        col1.metric("買い目数", f"{len(bets)}")
        col2.metric("的中率", hit_rate_metric_text(bet_hit_count, len(bets)), f"{bet_hit_count}/{len(bets)}")
        col3.metric("購入", metric_amount_text(total_stake, bet_unit_summary))
        col4.metric("払戻", metric_amount_text(total_payout, bet_unit_summary))
        col5.metric(net_label(bet_unit_summary), metric_amount_text(profit(total_stake, total_payout), bet_unit_summary))
        col6.metric("回収率", f"{recovery_rate(total_stake, total_payout)}%")

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
                "strategy_type",
                "prediction_source",
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
                "strategy_type": "買い方の型",
                "prediction_source": "予想区分",
                "note": "買い目理由",
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
        col6, col7 = st.columns(2)
        strategy_value = selected_bet.get("strategy_type", "") if hasattr(selected_bet, "get") else ""
        source_value = selected_bet.get("prediction_source", "") if hasattr(selected_bet, "get") else ""
        updated_strategy = col6.selectbox(
            "買い方の型",
            STRATEGY_TYPES,
            index=STRATEGY_TYPES.index(strategy_value) if strategy_value in STRATEGY_TYPES else 0,
        )
        updated_source = col7.selectbox(
            "予想区分",
            PREDICTION_SOURCES,
            index=PREDICTION_SOURCES.index(source_value) if source_value in PREDICTION_SOURCES else 0,
        )
        updated_role = st.text_input("位置づけ", value=selected_bet["expected_role"])
        updated_note = st.text_area("買い目理由", value=selected_bet["note"], height=80)
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
                "strategy_type": updated_strategy,
                "prediction_source": updated_source,
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
        unit = summary_unit(bets)
        render_bet_performance_summary(bets)

        ticket_summary = (
            bets.groupby(["amount_unit", "ticket_type"])
            .agg(件数=("id", "count"), 的中=("hit", "sum"), 購入=("stake", "sum"), 払戻=("payout", "sum"))
            .reset_index()
        )
        ticket_summary["差分"] = ticket_summary["払戻"] - ticket_summary["購入"]
        ticket_summary["回収率"] = ticket_summary.apply(lambda row: recovery_rate(row["購入"], row["払戻"]), axis=1)
        ticket_summary["的中率"] = ticket_summary.apply(lambda row: hit_rate(int(row["的中"]), int(row["件数"])), axis=1)
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
            hover_data=["件数", "的中", "購入", "払戻", "的中率", "回収率"],
            text_template="%{x:,.0f}",
            color_scale=["#ef4444", "#94a3b8", "#22c55e"],
        )
        fig.update_layout(coloraxis_cmid=100)
        st.plotly_chart(fig, use_container_width=True)

    render_rider_position_insights()

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
    require_app_password()
    init_db()
    refresh_public_statuses(date.today().isoformat())
    today_sync_result = sync_today_winticket_races_once()
    races = fetch_races()
    selected_race_id = sidebar_select_race(races)
    page = st.session_state.get("page", "ダッシュボード")

    if page == "ダッシュボード":
        render_dashboard(races, selected_race_id, today_sync_result)
    elif page == "競輪場特徴":
        render_venue_features_page(races, selected_race_id)
    elif page == "レース登録":
        render_race_form(selected_race_id)
    elif page == "選手評価":
        render_riders(selected_race_id)
    elif page == "展開予想":
        render_development_forecast(selected_race_id, races)
    elif page == "買い目・結果":
        render_bets_and_results(selected_race_id)
    elif page == "振り返り":
        render_review(selected_race_id)


if __name__ == "__main__":
    main()
