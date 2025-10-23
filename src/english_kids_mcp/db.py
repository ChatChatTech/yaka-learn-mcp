"""SQLite persistence layer for the Kid English MCP server."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional


@dataclass(slots=True)
class SessionRow:
    session_id: str
    user_id: str
    age_band: str
    goal: str
    locale: str
    state_json: str
    created_at: int
    updated_at: int


@dataclass(slots=True)
class ProgressRow:
    user_id: str
    item_id: str
    ease: float
    interval_days: float
    due_at: int
    streak: int


class SQLiteStore:
    """Simple SQLite wrapper providing typed helpers."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _init(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    age_band TEXT NOT NULL,
                    goal TEXT NOT NULL,
                    locale TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS progress (
                    user_id TEXT NOT NULL,
                    item_id TEXT NOT NULL,
                    ease REAL NOT NULL,
                    interval_days REAL NOT NULL,
                    due_at INTEGER NOT NULL,
                    streak INTEGER NOT NULL,
                    PRIMARY KEY (user_id, item_id)
                );

                CREATE TABLE IF NOT EXISTS parent_notes (
                    session_id TEXT PRIMARY KEY,
                    note_cn TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                );
                """
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # session helpers -------------------------------------------------

    def upsert_session(
        self,
        session_id: str,
        user_id: str,
        age_band: str,
        goal: str,
        locale: str,
        state: dict,
        timestamp: int,
    ) -> None:
        payload = {
            "session_id": session_id,
            "user_id": user_id,
            "age_band": age_band,
            "goal": goal,
            "locale": locale,
            "state_json": json.dumps(state, separators=(",", ":")),
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sessions(session_id,user_id,age_band,goal,locale,state_json,created_at,updated_at)
                VALUES(:session_id,:user_id,:age_band,:goal,:locale,:state_json,:created_at,:updated_at)
                ON CONFLICT(session_id) DO UPDATE SET
                    age_band=excluded.age_band,
                    goal=excluded.goal,
                    locale=excluded.locale,
                    state_json=excluded.state_json,
                    updated_at=excluded.updated_at
                """,
                payload,
            )

    def update_session_state(self, session_id: str, state: dict, timestamp: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE sessions SET state_json=?, updated_at=? WHERE session_id=?",
                (json.dumps(state, separators=(",", ":")), timestamp, session_id),
            )

    def get_session(self, session_id: str) -> Optional[SessionRow]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM sessions WHERE session_id=?",
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return SessionRow(**row)

    def get_latest_session_for_user(self, user_id: str) -> Optional[SessionRow]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM sessions WHERE user_id=? ORDER BY updated_at DESC LIMIT 1",
                (user_id,),
            ).fetchone()
        if row is None:
            return None
        return SessionRow(**row)

    # progress helpers -----------------------------------------------

    def get_progress(self, user_id: str, item_id: str) -> Optional[ProgressRow]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM progress WHERE user_id=? AND item_id=?",
                (user_id, item_id),
            ).fetchone()
        if row is None:
            return None
        return ProgressRow(**row)

    def upsert_progress(
        self,
        user_id: str,
        item_id: str,
        ease: float,
        interval_days: float,
        due_at: int,
        streak: int,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO progress(user_id,item_id,ease,interval_days,due_at,streak)
                VALUES(?,?,?,?,?,?)
                ON CONFLICT(user_id,item_id) DO UPDATE SET
                    ease=excluded.ease,
                    interval_days=excluded.interval_days,
                    due_at=excluded.due_at,
                    streak=excluded.streak
                """,
                (user_id, item_id, ease, interval_days, due_at, streak),
            )

    def iter_progress(self, user_id: str) -> Iterator[ProgressRow]:
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT * FROM progress WHERE user_id=?",
                (user_id,),
            )
            for row in cursor:
                yield ProgressRow(**row)

    # parent note helpers --------------------------------------------

    def save_parent_note(self, session_id: str, note_cn: str, timestamp: int) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO parent_notes(session_id,note_cn,created_at)
                VALUES(?,?,?)
                ON CONFLICT(session_id) DO UPDATE SET
                    note_cn=excluded.note_cn,
                    created_at=excluded.created_at
                """,
                (session_id, note_cn, timestamp),
            )

    def get_parent_note(self, session_id: str) -> Optional[str]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT note_cn FROM parent_notes WHERE session_id=?",
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return str(row[0])


__all__ = ["SQLiteStore", "SessionRow", "ProgressRow"]
