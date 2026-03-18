"""
database.py — SQLite schema, initialization, and shared connection management.

Schema
------
  pages          (url PK, origin, depth, indexed_at)
  word_index     (word, url PK, origin, depth, frequency)
  visited        (url PK, visited_at)
  crawl_sessions (id PK, origin, depth, started_at, finished_at,
                  pages_indexed, urls_processed, urls_failed, status)

Design notes
------------
- WAL mode: multiple reader threads read concurrently while workers write.
- Per-thread connections via threading.local() avoid SQLite's thread-safety
  restrictions while sharing a single database file.
- INSERT OR IGNORE on `visited` makes the visited-URL check atomic without
  any application-level mutex.
"""

import os
import sqlite3
import threading
import time
from typing import Dict, List, Optional

DB_PATH = os.path.join("data", "mini_google.db")


def _open(path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")    # concurrent reads + writes
    conn.execute("PRAGMA synchronous=NORMAL")  # safe & faster than FULL
    conn.execute("PRAGMA cache_size=-32000")   # 32 MB page cache
    conn.row_factory = sqlite3.Row
    return conn


def init_db(path: str = DB_PATH) -> None:
    """Create all tables and indexes if they do not already exist."""
    conn = _open(path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS pages (
            url        TEXT PRIMARY KEY,
            origin     TEXT NOT NULL,
            depth      INTEGER NOT NULL,
            indexed_at REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS word_index (
            word      TEXT NOT NULL,
            url       TEXT NOT NULL,
            origin    TEXT NOT NULL,
            depth     INTEGER NOT NULL,
            frequency INTEGER NOT NULL,
            PRIMARY KEY (word, url)
        );

        CREATE INDEX IF NOT EXISTS idx_word ON word_index(word);

        CREATE TABLE IF NOT EXISTS visited (
            url        TEXT PRIMARY KEY,
            visited_at REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS crawl_sessions (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            origin         TEXT NOT NULL,
            depth          INTEGER NOT NULL,
            started_at     REAL NOT NULL,
            finished_at    REAL,
            pages_indexed  INTEGER,
            urls_processed INTEGER,
            urls_failed    INTEGER,
            status         TEXT NOT NULL DEFAULT 'running'
        );
    """)
    conn.commit()
    conn.close()


class _ThreadLocalDB:
    """Base class: per-thread SQLite connection pool."""

    def __init__(self, path: str):
        self._path = path
        self._local = threading.local()
        init_db(path)

    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn"):
            self._local.conn = _open(self._path)
        return self._local.conn

    def close(self) -> None:
        """Close the current thread's connection (useful in tests)."""
        if hasattr(self._local, "conn"):
            self._local.conn.close()
            del self._local.conn


# ---------------------------------------------------------------------------
# Visited-URL store
# ---------------------------------------------------------------------------

class VisitedDB(_ThreadLocalDB):
    """
    Atomic visited-URL set backed by SQLite.

    mark_visited() uses INSERT OR IGNORE: if two threads race on the same URL,
    exactly one will succeed (return True) and the other will return False.
    No application-level lock is required.
    """

    def mark_visited(self, url: str) -> bool:
        """Mark URL as visited. Returns True if new, False if already seen."""
        conn = self._conn()
        try:
            conn.execute(
                "INSERT OR IGNORE INTO visited(url, visited_at) VALUES (?, ?)",
                (url, time.time()),
            )
            conn.commit()
            return conn.execute("SELECT changes()").fetchone()[0] == 1
        except sqlite3.Error:
            return False

    def is_visited(self, url: str) -> bool:
        row = self._conn().execute(
            "SELECT 1 FROM visited WHERE url=?", (url,)
        ).fetchone()
        return row is not None

    def count(self) -> int:
        return self._conn().execute("SELECT COUNT(*) FROM visited").fetchone()[0]


# ---------------------------------------------------------------------------
# Crawl-session history
# ---------------------------------------------------------------------------

class SessionDB(_ThreadLocalDB):
    """
    Persistent record of every crawl run.

    create_session()  — called when a crawl starts, returns the session id.
    finish_session()  — called when the crawl monitor signals done.
    list_sessions()   — returns the most recent sessions for the UI.
    """

    def create_session(self, origin: str, depth: int) -> int:
        conn = self._conn()
        cur = conn.execute(
            "INSERT INTO crawl_sessions(origin, depth, started_at, status) "
            "VALUES (?, ?, ?, 'running')",
            (origin, depth, time.time()),
        )
        conn.commit()
        return cur.lastrowid

    def finish_session(self, session_id: int, pages_indexed: int,
                       urls_processed: int, urls_failed: int) -> None:
        conn = self._conn()
        conn.execute(
            "UPDATE crawl_sessions SET finished_at=?, pages_indexed=?, "
            "urls_processed=?, urls_failed=?, status='done' WHERE id=?",
            (time.time(), pages_indexed, urls_processed, urls_failed, session_id),
        )
        conn.commit()

    def list_sessions(self, limit: int = 20) -> List[Dict]:
        rows = self._conn().execute(
            "SELECT id, origin, depth, started_at, finished_at, "
            "pages_indexed, urls_processed, urls_failed, status "
            "FROM crawl_sessions ORDER BY started_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
