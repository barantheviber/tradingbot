"""SQLite persistence: positions, trade history, live-editable settings,
daily equity snapshots, decision/event log, dashboard commands and small
runtime key-value state.

Migrations
----------
``_run_migrations`` is called exactly once from ``__init__``. It reads
``schema_version`` and applies every migration in ``MIGRATIONS`` whose
version is higher, each inside its own transaction. Migrations must be
additive (new tables, ``ADD COLUMN`` with defaults) so older data keeps
working. To change the schema, append a new ``(version, function)`` pair;
never edit an already released migration.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from logging_setup import get_logger

log = get_logger("state")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def utc_today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


# ---------------------------------------------------------------- migrations
def _exec_statements(conn: sqlite3.Connection, script: str) -> None:
    """Run ';'-separated DDL one statement at a time. (``executescript`` would
    implicitly COMMIT and break the per-migration transaction.)"""
    for statement in script.split(";"):
        if statement.strip():
            conn.execute(statement)


def _migration_1_initial(conn: sqlite3.Connection) -> None:
    _exec_statements(
        conn,
        """
        CREATE TABLE IF NOT EXISTS settings (
            key         TEXT PRIMARY KEY,
            value       TEXT NOT NULL,          -- JSON encoded
            description TEXT NOT NULL DEFAULT '',
            updated_at  TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS positions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol          TEXT NOT NULL,
            side            TEXT NOT NULL CHECK (side IN ('long', 'short')),
            quantity        REAL NOT NULL,
            entry_price     REAL NOT NULL,
            stop_loss       REAL NOT NULL,
            take_profit     REAL,
            initial_stop    REAL NOT NULL,
            highest_price   REAL NOT NULL,
            lowest_price    REAL NOT NULL,
            atr_at_entry    REAL,
            status          TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed')),
            mode            TEXT NOT NULL DEFAULT 'paper',
            opened_at       TEXT NOT NULL,
            closed_at       TEXT,
            exit_price      REAL,
            pnl             REAL,
            fees            REAL NOT NULL DEFAULT 0,
            exit_reason     TEXT,
            entry_order_id  TEXT,
            exit_order_id   TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_positions_status ON positions(status, mode);

        CREATE TABLE IF NOT EXISTS trades (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            position_id INTEGER REFERENCES positions(id),
            symbol      TEXT NOT NULL,
            side        TEXT NOT NULL,          -- buy / sell
            action      TEXT NOT NULL,          -- open / close
            quantity    REAL NOT NULL,
            price       REAL NOT NULL,
            fee         REAL NOT NULL DEFAULT 0,
            pnl         REAL,                   -- realised, net of fees (close only)
            reason      TEXT,
            mode        TEXT NOT NULL DEFAULT 'paper',
            order_id    TEXT,
            timestamp   TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_trades_ts ON trades(timestamp);

        CREATE TABLE IF NOT EXISTS daily_stats (
            date         TEXT NOT NULL,         -- YYYY-MM-DD (UTC)
            mode         TEXT NOT NULL,
            start_equity REAL NOT NULL,
            created_at   TEXT NOT NULL,
            PRIMARY KEY (date, mode)
        );

        CREATE TABLE IF NOT EXISTS event_log (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            level     TEXT NOT NULL,
            category  TEXT NOT NULL,
            symbol    TEXT,
            message   TEXT NOT NULL,
            data      TEXT
        );

        CREATE TABLE IF NOT EXISTS commands (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            command      TEXT NOT NULL,
            payload      TEXT,
            status       TEXT NOT NULL DEFAULT 'pending',
            created_at   TEXT NOT NULL,
            processed_at TEXT,
            note         TEXT
        );

        CREATE TABLE IF NOT EXISTS runtime_state (
            key        TEXT PRIMARY KEY,
            value      TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )


# Append new migrations here: (version, function(conn)). Never edit old ones.
MIGRATIONS: List[Tuple[int, Callable[[sqlite3.Connection], None]]] = [
    (1, _migration_1_initial),
]


def add_column_if_missing(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    """Helper for future additive migrations, e.g.
    ``add_column_if_missing(conn, 'positions', 'strategy', "TEXT DEFAULT 'default'")``."""
    cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


POSITION_FIELDS = (
    "symbol", "side", "quantity", "entry_price", "stop_loss", "take_profit", "initial_stop", "highest_price",
    "lowest_price", "atr_at_entry", "status", "mode", "opened_at", "closed_at", "exit_price", "pnl", "fees",
    "exit_reason", "entry_order_id", "exit_order_id",
)


class StateManager:
    def __init__(self, db_path: str):
        self.db_path = db_path
        if db_path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False, timeout=10, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA busy_timeout = 10000")
        if db_path != ":memory:":
            self._conn.execute("PRAGMA journal_mode = WAL")  # bot + dashboard read/write concurrently
        self._run_migrations()

    # ---------------------------------------------------------- infrastructure
    def _run_migrations(self) -> None:
        with self._lock:
            self._conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
            row = self._conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
            current = row["v"] or 0
            for version, migrate in MIGRATIONS:
                if version <= current:
                    continue
                self._conn.execute("BEGIN IMMEDIATE")
                try:
                    # re-check inside the write lock: another process may have migrated meanwhile
                    latest = self._conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()["v"] or 0
                    if version > latest:
                        migrate(self._conn)
                        self._conn.execute("INSERT INTO schema_version(version) VALUES (?)", (version,))
                    self._conn.execute("COMMIT")
                except Exception:
                    self._conn.execute("ROLLBACK")
                    log.exception("Migration failed", extra={"version": version})
                    raise
                log.info("Applied schema migration", extra={"version": version})

    def schema_version(self) -> int:
        row = self._query_one("SELECT MAX(version) AS v FROM schema_version")
        return int(row["v"] or 0)

    def _execute(self, sql: str, params: Tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._conn.execute(sql, params)

    def _query(self, sql: str, params: Tuple = ()) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, params).fetchall()]

    def _query_one(self, sql: str, params: Tuple = ()) -> Optional[Dict[str, Any]]:
        rows = self._query(sql, params)
        return rows[0] if rows else None

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ---------------------------------------------------------------- settings
    def seed_default_settings(self, defaults: Mapping[str, Tuple[Any, str]]) -> None:
        """Insert missing keys only - values edited by the user are kept."""
        now = utc_now_iso()
        with self._lock:
            for key, (value, description) in defaults.items():
                self._conn.execute(
                    "INSERT OR IGNORE INTO settings(key, value, description, updated_at) VALUES (?, ?, ?, ?)",
                    (key, json.dumps(value), description, now),
                )
                self._conn.execute("UPDATE settings SET description = ? WHERE key = ?", (description, key))

    def get_setting(self, key: str, default: Any = None) -> Any:
        row = self._query_one("SELECT value FROM settings WHERE key = ?", (key,))
        return json.loads(row["value"]) if row else default

    def get_all_settings(self) -> Dict[str, Any]:
        return {r["key"]: json.loads(r["value"]) for r in self._query("SELECT key, value FROM settings ORDER BY key")}

    def get_settings_with_meta(self) -> List[Dict[str, Any]]:
        rows = self._query("SELECT key, value, description, updated_at FROM settings ORDER BY key")
        for r in rows:
            r["value"] = json.loads(r["value"])
        return rows

    def set_setting(self, key: str, value: Any, description: Optional[str] = None) -> Any:
        """Upsert a setting. If the key exists, the new value is coerced to the
        existing value's type (bool/int/float/str); a ValueError is raised if
        that is impossible. Returns the stored value."""
        current = self.get_setting(key, None)
        if current is not None:
            value = coerce_to_type(value, type(current))
        now = utc_now_iso()
        with self._lock:
            self._conn.execute(
                "INSERT INTO settings(key, value, description, updated_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
                (key, json.dumps(value), description or "", now),
            )
        log.info("Setting updated", extra={"key": key, "value": value})
        return value

    # --------------------------------------------------------------- positions
    def open_position(self, **fields: Any) -> int:
        fields.setdefault("status", "open")
        fields.setdefault("opened_at", utc_now_iso())
        fields.setdefault("highest_price", fields["entry_price"])
        fields.setdefault("lowest_price", fields["entry_price"])
        fields.setdefault("initial_stop", fields["stop_loss"])
        cols = [k for k in fields if k in POSITION_FIELDS]
        sql = f"INSERT INTO positions({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})"
        cur = self._execute(sql, tuple(fields[c] for c in cols))
        return int(cur.lastrowid)

    def update_position(self, position_id: int, **fields: Any) -> None:
        cols = [k for k in fields if k in POSITION_FIELDS]
        if not cols:
            return
        sql = f"UPDATE positions SET {', '.join(f'{c} = ?' for c in cols)} WHERE id = ?"
        self._execute(sql, tuple(fields[c] for c in cols) + (position_id,))

    def mark_position_closed(self, position_id: int, exit_price: float, pnl: float, fees: float,
                             reason: str, exit_order_id: Optional[str] = None) -> None:
        self.update_position(position_id, status="closed", closed_at=utc_now_iso(), exit_price=exit_price,
                             pnl=pnl, fees=fees, exit_reason=reason, exit_order_id=exit_order_id)

    def get_position(self, position_id: int) -> Optional[Dict[str, Any]]:
        return self._query_one("SELECT * FROM positions WHERE id = ?", (position_id,))

    def get_open_positions(self, mode: Optional[str] = None, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        sql, params = "SELECT * FROM positions WHERE status = 'open'", []
        if mode:
            sql += " AND mode = ?"
            params.append(mode)
        if symbol:
            sql += " AND symbol = ?"
            params.append(symbol)
        return self._query(sql + " ORDER BY id", tuple(params))

    def get_closed_positions(self, mode: Optional[str] = None, limit: int = 500) -> List[Dict[str, Any]]:
        sql, params = "SELECT * FROM positions WHERE status = 'closed'", []
        if mode:
            sql += " AND mode = ?"
            params.append(mode)
        return self._query(sql + " ORDER BY closed_at DESC, id DESC LIMIT ?", tuple(params + [limit]))

    # ------------------------------------------------------------------ trades
    def record_trade(self, **fields: Any) -> int:
        fields.setdefault("timestamp", utc_now_iso())
        cols = list(fields)
        sql = f"INSERT INTO trades({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})"
        return int(self._execute(sql, tuple(fields[c] for c in cols)).lastrowid)

    def get_trades(self, mode: Optional[str] = None, limit: int = 500) -> List[Dict[str, Any]]:
        sql, params = "SELECT * FROM trades", []
        if mode:
            sql += " WHERE mode = ?"
            params.append(mode)
        return self._query(sql + " ORDER BY id DESC LIMIT ?", tuple(params + [limit]))

    def realized_pnl(self, mode: str, since_iso: Optional[str] = None) -> float:
        sql, params = "SELECT COALESCE(SUM(pnl), 0) AS s FROM positions WHERE status = 'closed' AND mode = ?", [mode]
        if since_iso:
            sql += " AND closed_at >= ?"
            params.append(since_iso)
        return float(self._query_one(sql, tuple(params))["s"])

    def open_fees(self, mode: str) -> float:
        """Entry fees already paid on still-open positions."""
        row = self._query_one("SELECT COALESCE(SUM(fees), 0) AS s FROM positions WHERE status = 'open' AND mode = ?",
                              (mode,))
        return float(row["s"])

    # ------------------------------------------------------------- daily stats
    def get_or_create_day_start_equity(self, mode: str, equity: float, date: Optional[str] = None) -> float:
        """Start-of-day equity for the UTC date; created from ``equity`` on first call of the day."""
        date = date or utc_today()
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO daily_stats(date, mode, start_equity, created_at) VALUES (?, ?, ?, ?)",
                (date, mode, equity, utc_now_iso()),
            )
            row = self._conn.execute("SELECT start_equity FROM daily_stats WHERE date = ? AND mode = ?",
                                     (date, mode)).fetchone()
        return float(row["start_equity"])

    def get_day_start_equity(self, mode: str, date: Optional[str] = None) -> Optional[float]:
        row = self._query_one("SELECT start_equity FROM daily_stats WHERE date = ? AND mode = ?",
                              (date or utc_today(), mode))
        return float(row["start_equity"]) if row else None

    # --------------------------------------------------------------- event log
    def log_event(self, level: str, category: str, message: str, symbol: Optional[str] = None,
                  data: Optional[Mapping[str, Any]] = None) -> None:
        try:
            self._execute(
                "INSERT INTO event_log(timestamp, level, category, symbol, message, data) VALUES (?, ?, ?, ?, ?, ?)",
                (utc_now_iso(), level, category, symbol, message,
                 json.dumps(data, default=str) if data else None),
            )
        except sqlite3.Error:  # logging must never crash the bot
            pass

    def get_events(self, limit: int = 200) -> List[Dict[str, Any]]:
        return self._query("SELECT * FROM event_log ORDER BY id DESC LIMIT ?", (limit,))

    def prune_events(self, keep: int = 20000) -> None:
        self._execute("DELETE FROM event_log WHERE id <= (SELECT MAX(id) FROM event_log) - ?", (keep,))

    # ---------------------------------------------------------------- commands
    def enqueue_command(self, command: str, payload: Optional[Mapping[str, Any]] = None) -> int:
        cur = self._execute("INSERT INTO commands(command, payload, created_at) VALUES (?, ?, ?)",
                            (command, json.dumps(payload or {}), utc_now_iso()))
        return int(cur.lastrowid)

    def get_pending_commands(self) -> List[Dict[str, Any]]:
        rows = self._query("SELECT * FROM commands WHERE status = 'pending' ORDER BY id")
        for r in rows:
            r["payload"] = json.loads(r["payload"] or "{}")
        return rows

    def complete_command(self, command_id: int, status: str = "done", note: str = "") -> None:
        self._execute("UPDATE commands SET status = ?, processed_at = ?, note = ? WHERE id = ?",
                      (status, utc_now_iso(), note, command_id))

    # ----------------------------------------------------------- runtime state
    def set_state(self, key: str, value: Any) -> None:
        self._execute(
            "INSERT INTO runtime_state(key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            (key, json.dumps(value, default=str), utc_now_iso()),
        )

    def get_state(self, key: str, default: Any = None) -> Any:
        row = self._query_one("SELECT value FROM runtime_state WHERE key = ?", (key,))
        return json.loads(row["value"]) if row else default


def coerce_to_type(value: Any, target: type) -> Any:
    """Coerce dashboard / string input to the stored setting type."""
    if target is bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        text = str(value).strip().lower()
        if text in {"1", "true", "yes", "y", "on", "evet"}:
            return True
        if text in {"0", "false", "no", "n", "off", "hayir", "hayır"}:
            return False
        raise ValueError(f"cannot interpret {value!r} as bool")
    if target is int:
        if isinstance(value, bool):
            raise ValueError("bool is not a valid int setting")
        as_float = float(value)
        if not as_float.is_integer():
            raise ValueError(f"{value!r} is not an integer")
        return int(as_float)
    if target is float:
        if isinstance(value, bool):
            raise ValueError("bool is not a valid float setting")
        return float(value)
    return target(value)
