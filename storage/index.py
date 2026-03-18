"""
index.py — Thread-safe inverted index backed by SQLite.

Relevancy scoring
-----------------
Search is a single SQL query that runs entirely inside the SQLite engine:

    SELECT url, origin, depth, SUM(frequency) AS score
    FROM word_index
    WHERE word IN (?, ?, ...)
    GROUP BY url
    ORDER BY score DESC

This is more scalable than loading all records into Python dicts: the DB
engine can use the idx_word index, leverage its page cache, and push the
aggregation to disk for arbitrarily large indexes.

Concurrent search while indexing
---------------------------------
SQLite WAL mode allows readers to proceed concurrently with the single active
writer. Each thread has its own connection (threading.local), so no Python-
level lock is needed for read/write separation. add_page() commits after every
page, so search() immediately sees newly indexed content.
"""

import sqlite3
import time
import threading
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from storage.database import DB_PATH, _ThreadLocalDB
from crawler.parser import tokenize


class InvertedIndex(_ThreadLocalDB):
    """
    Thread-safe inverted index.

    Methods
    -------
    add_page(url, origin, depth, word_counts) — called by crawler workers
    search(query)                             — may run concurrently
    page_count() / word_count()               — stats
    save()                                    — no-op (SQLite auto-commits)
    recent_pages(limit)                       — for the dashboard
    """

    def __init__(self, index_path: str = DB_PATH):
        super().__init__(index_path)

    def add_page(self, url: str, origin: str, depth: int,
                 word_counts: Dict[str, int]) -> bool:
        """
        Index one page.  Returns False if URL was already indexed (idempotent).
        Safe to call from multiple worker threads simultaneously.
        """
        conn = self._conn()
        try:
            conn.execute(
                "INSERT OR IGNORE INTO pages(url, origin, depth, indexed_at) "
                "VALUES (?, ?, ?, ?)",
                (url, origin, depth, time.time()),
            )
            if conn.execute("SELECT changes()").fetchone()[0] == 0:
                return False  # already indexed

            conn.executemany(
                "INSERT OR REPLACE INTO word_index"
                "(word, url, origin, depth, frequency) VALUES (?, ?, ?, ?, ?)",
                [(w, url, origin, depth, f) for w, f in word_counts.items()],
            )
            conn.commit()
            return True
        except sqlite3.Error:
            conn.rollback()
            return False

    def search(self, query: str) -> List[Tuple[str, str, int]]:
        """
        Return ranked list of (relevant_url, origin_url, depth).

        Relevancy = SUM(frequency) across all matching query terms per URL.
        Pages containing more query words, or containing them more often,
        rank higher.  Scoring runs entirely in SQLite (no Python iteration
        over full index).
        """
        words = tokenize(query)
        if not words:
            return []

        placeholders = ",".join("?" * len(words))
        sql = f"""
            SELECT url, origin, depth, SUM(frequency) AS score
            FROM word_index
            WHERE word IN ({placeholders})
            GROUP BY url
            ORDER BY score DESC
        """
        rows = self._conn().execute(sql, words).fetchall()
        return [(r["url"], r["origin"], r["depth"]) for r in rows]

    def page_count(self) -> int:
        return self._conn().execute("SELECT COUNT(*) FROM pages").fetchone()[0]

    def word_count(self) -> int:
        return self._conn().execute(
            "SELECT COUNT(DISTINCT word) FROM word_index"
        ).fetchone()[0]

    def recent_pages(self, limit: int = 10) -> List[dict]:
        rows = self._conn().execute(
            "SELECT url, origin, depth, indexed_at FROM pages "
            "ORDER BY indexed_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def save(self) -> None:
        """No-op: SQLite commits happen on every add_page call."""
        pass
