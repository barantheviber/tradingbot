"""
SQLite-backed persistence for:
  - open/closed positions
  - trade history
  - live-editable strategy/risk settings (key-value table)

Schema changes go through `_migrate`, called once from __init__. Each
migration is a numbered, idempotent step so an existing database is
brought forward without breaking backward compatibility. To add a new
migration:
  1. Add a new `_migration_00N` method.
  2. Append it to `self._migrations` in the order it must run.
  3. Bump nothing else - `schema_version` in the `meta` table tracks how
     far a given database has been migrated, and only pending migrations
     run.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional, Union

logger = logging.getLogger(__name__)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Position:
    id: Optional[int]
    symbol: str
    side: str  # "long" | "short"
    entry_price: float
    quantity: float
    stop_loss: float
    take_profit: float
    opened_at: str
    status: str = "open"  # "open" | "closed"
    closed_at: Optional[str] = None
    close_price: Optional[float] = None
    realized_pnl: Optional[float] = None
    exchange_order_id: Optional[str] = None
    meta: dict = field(default_factory=dict)


@dataclass
class TradeRecord:
    id: Optional[int]
    symbol: str
    side: str
    entry_price: float
    exit_price: float
    quantity: float
    pnl: float
    opened_at: str
    closed_at: str
    reason: str = ""


class StateManager:
    def __init__(self, db_path: Union[str, Path]):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._lock = threading.RLock()
        self._migrations = [
            self._migration_001_initial_schema,
            self._migration_002_add_positions_meta,
        ]
        self._migrate()

    # ------------------------------------------------------------------
    # Connection handling (one connection per thread - Streamlit and the
    # bot loop run in different threads/processes)
    # ------------------------------------------------------------------
    @property
    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA journal_mode = WAL")
            self._local.conn = conn
        return conn

    @contextmanager
    def _cursor(self) -> Iterator[sqlite3.Cursor]:
        with self._lock:
            conn = self._conn
            cur = conn.cursor()
            try:
                yield cur
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                cur.close()

    # ------------------------------------------------------------------
    # Migrations
    # ------------------------------------------------------------------
    def _get_schema_version(self, cur: sqlite3.Cursor) -> int:
        cur.execute(
            "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        cur.execute("SELECT value FROM meta WHERE key = 'schema_version'")
        row = cur.fetchone()
        return int(row["value"]) if row else 0

    def _set_schema_version(self, cur: sqlite3.Cursor, version: int) -> None:
        cur.execute(
            "INSERT INTO meta (key, value) VALUES ('schema_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(version),),
        )

    def _migrate(self) -> None:
        with self._cursor() as cur:
            current = self._get_schema_version(cur)
            for idx, migration in enumerate(self._migrations, start=1):
                if idx <= current:
                    continue
                logger.info("Running migration %03d: %s", idx, migration.__name__)
                migration(cur)
                self._set_schema_version(cur, idx)

    def _migration_001_initial_schema(self, cur: sqlite3.Cursor) -> None:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                entry_price REAL NOT NULL,
                quantity REAL NOT NULL,
                stop_loss REAL NOT NULL,
                take_profit REAL NOT NULL,
                opened_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                closed_at TEXT,
                close_price REAL,
                realized_pnl REAL,
                exchange_order_id TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                entry_price REAL NOT NULL,
                exit_price REAL NOT NULL,
                quantity REAL NOT NULL,
                pnl REAL NOT NULL,
                opened_at TEXT NOT NULL,
                closed_at TEXT NOT NULL,
                reason TEXT DEFAULT ''
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS event_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                level TEXT NOT NULL,
                message TEXT NOT NULL
            )
            """
        )

    def _migration_002_add_positions_meta(self, cur: sqlite3.Cursor) -> None:
        cur.execute("PRAGMA table_info(positions)")
        cols = {row["name"] for row in cur.fetchall()}
        if "meta" not in cols:
            cur.execute("ALTER TABLE positions ADD COLUMN meta TEXT DEFAULT '{}'")

    # ------------------------------------------------------------------
    # Settings (live-editable strategy/risk parameters)
    # ------------------------------------------------------------------
    def get_setting(self, key: str, default: Any = None) -> Any:
        with self._cursor() as cur:
            cur.execute("SELECT value FROM settings WHERE key = ?", (key,))
            row = cur.fetchone()
        if row is None:
            return default
        return json.loads(row["value"])

    def set_setting(self, key: str, value: Any) -> None:
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
                "updated_at = excluded.updated_at",
                (key, json.dumps(value), _utcnow_iso()),
            )

    def get_all_settings(self) -> dict:
        with self._cursor() as cur:
            cur.execute("SELECT key, value FROM settings")
            rows = cur.fetchall()
        return {row["key"]: json.loads(row["value"]) for row in rows}

    def seed_default_settings(self, defaults: dict) -> None:
        """Only sets keys that don't already exist - never overwrites a
        value the user may have already tuned live."""
        existing = self.get_all_settings()
        for key, value in defaults.items():
            if key not in existing:
                self.set_setting(key, value)

    # ------------------------------------------------------------------
    # Positions
    # ------------------------------------------------------------------
    def open_position(self, position: Position) -> int:
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO positions
                    (symbol, side, entry_price, quantity, stop_loss,
                     take_profit, opened_at, status, exchange_order_id, meta)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?, ?)
                """,
                (
                    position.symbol,
                    position.side,
                    position.entry_price,
                    position.quantity,
                    position.stop_loss,
                    position.take_profit,
                    position.opened_at,
                    position.exchange_order_id,
                    json.dumps(position.meta or {}),
                ),
            )
            return cur.lastrowid

    def update_position_stop(self, position_id: int, stop_loss: float) -> None:
        with self._cursor() as cur:
            cur.execute(
                "UPDATE positions SET stop_loss = ? WHERE id = ? AND status = 'open'",
                (stop_loss, position_id),
            )

    def close_position(
        self, position_id: int, close_price: float, realized_pnl: float, closed_at: Optional[str] = None
    ) -> None:
        closed_at = closed_at or _utcnow_iso()
        with self._cursor() as cur:
            cur.execute(
                """
                UPDATE positions
                SET status = 'closed', close_price = ?, realized_pnl = ?, closed_at = ?
                WHERE id = ? AND status = 'open'
                """,
                (close_price, realized_pnl, closed_at, position_id),
            )

    def get_open_positions(self, symbol: Optional[str] = None) -> list[Position]:
        with self._cursor() as cur:
            if symbol:
                cur.execute(
                    "SELECT * FROM positions WHERE status = 'open' AND symbol = ?",
                    (symbol,),
                )
            else:
                cur.execute("SELECT * FROM positions WHERE status = 'open'")
            rows = cur.fetchall()
        return [self._row_to_position(row) for row in rows]

    def get_position(self, position_id: int) -> Optional[Position]:
        with self._cursor() as cur:
            cur.execute("SELECT * FROM positions WHERE id = ?", (position_id,))
            row = cur.fetchone()
        return self._row_to_position(row) if row else None

    @staticmethod
    def _row_to_position(row: sqlite3.Row) -> Position:
        meta_raw = row["meta"] if "meta" in row.keys() else "{}"
        return Position(
            id=row["id"],
            symbol=row["symbol"],
            side=row["side"],
            entry_price=row["entry_price"],
            quantity=row["quantity"],
            stop_loss=row["stop_loss"],
            take_profit=row["take_profit"],
            opened_at=row["opened_at"],
            status=row["status"],
            closed_at=row["closed_at"],
            close_price=row["close_price"],
            realized_pnl=row["realized_pnl"],
            exchange_order_id=row["exchange_order_id"],
            meta=json.loads(meta_raw) if meta_raw else {},
        )

    # ------------------------------------------------------------------
    # Trade history
    # ------------------------------------------------------------------
    def record_trade(self, trade: TradeRecord) -> int:
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO trades
                    (symbol, side, entry_price, exit_price, quantity, pnl,
                     opened_at, closed_at, reason)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trade.symbol,
                    trade.side,
                    trade.entry_price,
                    trade.exit_price,
                    trade.quantity,
                    trade.pnl,
                    trade.opened_at,
                    trade.closed_at,
                    trade.reason,
                ),
            )
            return cur.lastrowid

    def get_trade_history(self, limit: int = 100) -> list[TradeRecord]:
        with self._cursor() as cur:
            cur.execute(
                "SELECT * FROM trades ORDER BY id DESC LIMIT ?", (limit,)
            )
            rows = cur.fetchall()
        return [
            TradeRecord(
                id=row["id"],
                symbol=row["symbol"],
                side=row["side"],
                entry_price=row["entry_price"],
                exit_price=row["exit_price"],
                quantity=row["quantity"],
                pnl=row["pnl"],
                opened_at=row["opened_at"],
                closed_at=row["closed_at"],
                reason=row["reason"],
            )
            for row in rows
        ]

    def realized_pnl_since(self, since_iso: str) -> float:
        with self._cursor() as cur:
            cur.execute(
                "SELECT COALESCE(SUM(pnl), 0) as total FROM trades WHERE closed_at >= ?",
                (since_iso,),
            )
            row = cur.fetchone()
        return float(row["total"])

    # ------------------------------------------------------------------
    # Event log (decisions/errors, mirrors the file logger for dashboard use)
    # ------------------------------------------------------------------
    def log_event(self, level: str, message: str) -> None:
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO event_log (ts, level, message) VALUES (?, ?, ?)",
                (_utcnow_iso(), level, message),
            )

    def get_recent_events(self, limit: int = 200) -> list[dict]:
        with self._cursor() as cur:
            cur.execute(
                "SELECT ts, level, message FROM event_log ORDER BY id DESC LIMIT ?",
                (limit,),
            )
            rows = cur.fetchall()
        return [dict(row) for row in rows]

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None
