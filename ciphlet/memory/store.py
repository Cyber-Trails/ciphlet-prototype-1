"""SQLite foundational memory (architecture §5, §25).

This is the working/episodic memory tier for Version One: durable
conversation history per session, kept until the user deletes it.
Project memory and semantic memory (§5.1) are later, separate tiers and are
not implemented here — this store must not be described as semantic memory
merely because it persists facts (§5.4).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from ciphlet.brain.base import Message

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    no_memory INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);
"""


class MemoryStore:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def start_session(self, session_id: str, *, no_memory: bool) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO sessions (id, started_at, no_memory) VALUES (?, datetime('now'), ?)",
            (session_id, int(no_memory)),
        )
        self._conn.commit()

    def add_message(self, session_id: str, message: Message) -> None:
        self._conn.execute(
            "INSERT INTO messages (session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (session_id, message.role, message.content, message.created_at.isoformat()),
        )
        self._conn.commit()

    def latest_session_id(self) -> str | None:
        """The persisted (non-no-memory) session that most recently actually
        received a message, for cross-restart conversation continuity
        (§5.2: important learning history should remain available unless
        deleted).

        Deliberately keyed off message activity (messages.id, the table's
        own autoincrement — a reliable global insertion-order tiebreaker),
        not sessions.started_at: a session row exists as soon as it's
        started even with zero messages (e.g. `--new-session` immediately
        exited without saying anything). If "latest" were "most recently
        started," that empty session would become what the next plain
        `ciphlet chat` resumes into — silently orphaning the real
        conversation instead of continuing it. Requiring an actual message
        means an empty session is never eligible to be resumed into.

        Returns None if no persisted session has any messages yet (fresh
        install / first run) — callers should start a new session then."""
        row = self._conn.execute(
            """
            SELECT m.session_id
            FROM messages m
            JOIN sessions s ON s.id = m.session_id
            WHERE s.no_memory = 0
            ORDER BY m.id DESC
            LIMIT 1
            """
        ).fetchone()
        return row[0] if row else None

    def count_messages(self, session_id: str) -> int:
        """How many messages actually exist for a session. Diagnostic: lets
        the CLI show ground truth ("resuming — N prior messages") instead of
        an opaque "(resuming previous conversation)" claim, so a future
        recall failure is immediately localized — either N is 0/low (a
        persistence/resolution problem) or N is as-expected (the problem is
        downstream of storage, e.g. in a specific provider or HISTORY_LIMIT)
        — without guessing."""
        row = self._conn.execute("SELECT COUNT(*) FROM messages WHERE session_id = ?", (session_id,)).fetchone()
        return row[0] if row else 0

    def recent_messages(self, session_id: str, limit: int = 20) -> list[Message]:
        rows = self._conn.execute(
            """
            SELECT role, content, created_at FROM (
                SELECT role, content, created_at, id FROM messages
                WHERE session_id = ?
                ORDER BY id DESC
                LIMIT ?
            ) ORDER BY id ASC
            """,
            (session_id, limit),
        ).fetchall()
        return [Message(role=role, content=content) for role, content, _ in rows]

    def delete_session(self, session_id: str) -> None:
        self._conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        self._conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
