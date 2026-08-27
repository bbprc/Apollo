"""SQLite persistence for leagues and draft sessions.

Stdlib sqlite3, no ORM: there are two tables and the payloads are pydantic
models that already know how to serialise themselves. A UI arriving later wants
sessions that survive a restart, which is the only reason this exists at all.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from contextlib import contextmanager
from typing import Any, Iterator

from app.config import get_settings

log = logging.getLogger(__name__)

_LOCAL = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS leagues (
    league_id  TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    payload    TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id        TEXT PRIMARY KEY,
    league_id         TEXT,
    sleeper_draft_id  TEXT,
    payload           TEXT NOT NULL,
    created_at        TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_sessions_league ON sessions(league_id);
"""


def _connection() -> sqlite3.Connection:
    """One connection per thread — sqlite objects are not thread-safe."""
    connection = getattr(_LOCAL, "connection", None)
    if connection is None:
        path = get_settings().db_path
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.executescript(SCHEMA)
        _LOCAL.connection = connection
    return connection


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    connection = _connection()
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def init_db() -> None:
    _connection()


# --- leagues --------------------------------------------------------------

def save_league(league_id: str, name: str, payload: dict[str, Any]) -> None:
    with transaction() as connection:
        connection.execute(
            """
            INSERT INTO leagues (league_id, name, payload) VALUES (?, ?, ?)
            ON CONFLICT(league_id) DO UPDATE SET
                name = excluded.name,
                payload = excluded.payload,
                updated_at = datetime('now')
            """,
            (league_id, name, json.dumps(payload)),
        )


def get_league(league_id: str) -> dict[str, Any] | None:
    row = _connection().execute(
        "SELECT payload FROM leagues WHERE league_id = ?", (league_id,)
    ).fetchone()
    return json.loads(row["payload"]) if row else None


def list_leagues() -> list[dict[str, Any]]:
    rows = _connection().execute(
        "SELECT league_id, name, payload, updated_at FROM leagues ORDER BY updated_at DESC"
    ).fetchall()
    return [
        {
            "league_id": r["league_id"],
            "name": r["name"],
            "updated_at": r["updated_at"],
            **json.loads(r["payload"]),
        }
        for r in rows
    ]


def delete_league(league_id: str) -> bool:
    with transaction() as connection:
        cursor = connection.execute(
            "DELETE FROM leagues WHERE league_id = ?", (league_id,)
        )
    return cursor.rowcount > 0


# --- sessions -------------------------------------------------------------

def save_session(session_id: str, league_id: str | None,
                 sleeper_draft_id: str | None, payload: dict[str, Any]) -> None:
    with transaction() as connection:
        connection.execute(
            """
            INSERT INTO sessions (session_id, league_id, sleeper_draft_id, payload)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                league_id = excluded.league_id,
                sleeper_draft_id = excluded.sleeper_draft_id,
                payload = excluded.payload,
                updated_at = datetime('now')
            """,
            (session_id, league_id, sleeper_draft_id, json.dumps(payload)),
        )


def get_session(session_id: str) -> dict[str, Any] | None:
    row = _connection().execute(
        "SELECT payload FROM sessions WHERE session_id = ?", (session_id,)
    ).fetchone()
    return json.loads(row["payload"]) if row else None


def list_sessions() -> list[dict[str, Any]]:
    rows = _connection().execute(
        "SELECT session_id, league_id, sleeper_draft_id, updated_at "
        "FROM sessions ORDER BY updated_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def delete_session(session_id: str) -> bool:
    with transaction() as connection:
        cursor = connection.execute(
            "DELETE FROM sessions WHERE session_id = ?", (session_id,)
        )
    return cursor.rowcount > 0
