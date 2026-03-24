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
from typing import Dict, List, Optional, Tuple  # noqa: F401

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
                 word_counts: Dict[str, int],
                 session_id: Optional[int] = None) -> bool:
        """
        Index one page.  Returns False if URL was already indexed (idempotent).
        Safe to call from multiple worker threads simultaneously.
        """
        conn = self._conn()
        try:
            conn.execute(
                "INSERT OR IGNORE INTO pages"
                "(url, origin, depth, indexed_at, session_id) "
                "VALUES (?, ?, ?, ?, ?)",
                (url, origin, depth, time.time(), session_id),
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

    def search(self, query: str,
               partial: bool = True) -> List[Tuple[str, str, int]]:
        """
        Return ranked list of (relevant_url, origin_url, depth).

        Relevancy scoring
        -----------------
        Exact match: weight ×3 — pages that contain the exact query word
        Prefix match: weight ×1 — pages that contain a word *starting with*
                                  the query token (e.g. "artif" → "artificial")

        Both types run inside SQLite against the idx_word index, so no full
        table scan occurs.  partial=False falls back to exact-only matching
        (faster, useful when called programmatically with known tokens).
        """
        words = tokenize(query)
        if not words:
            return []

        if not partial:
            # Exact-only (original behaviour)
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

        # Partial: exact hit weighted ×3, prefix hit weighted ×1
        # Build: word IN (?,…) OR word LIKE ?% OR word LIKE ?% …
        exact_ph = ",".join("?" * len(words))
        like_clauses = " OR ".join("word LIKE ?" for _ in words)
        like_params = [w + "%" for w in words]

        sql = f"""
            SELECT url, origin, depth,
                   SUM(frequency *
                       CASE WHEN word IN ({exact_ph}) THEN 3 ELSE 1 END
                   ) AS score
            FROM word_index
            WHERE word IN ({exact_ph}) OR {like_clauses}
            GROUP BY url
            ORDER BY score DESC
        """
        # params order: exact (for CASE), exact (for WHERE IN), like patterns
        params = words + words + like_params
        rows = self._conn().execute(sql, params).fetchall()
        return [(r["url"], r["origin"], r["depth"]) for r in rows]

    def search_scored(self, query: str,
                      partial: bool = False) -> List[Tuple[str, str, int, int]]:
        """
        Return ranked list of (url, origin, depth, relevance_score).

        Scoring formula (assignment spec)
        -----------------------------------
        score = (frequency × 10) + 1000 (exact match bonus) - (depth × 5)

        partial=False (default): exact-word matches only.  Each matching word
        contributes (freq × 10) + 1000 - (depth × 5).  The formula applied
        per entry matches the manually-calculable formula exactly.

        partial=True: also includes prefix matches (word LIKE query%).  Prefix
        hits do not receive the +1000 exact-match bonus.  Scores will be
        slightly higher than a manual exact-only calculation.
        """
        words = tokenize(query)
        if not words:
            return []

        exact_ph = ",".join("?" * len(words))

        if not partial:
            # Exact-only: formula = (freq × 10) + 1000 - (depth × 5)
            sql = f"""
                SELECT url, origin, depth,
                       SUM(
                           (frequency * 10) + 1000 - (depth * 5)
                       ) AS score
                FROM word_index
                WHERE word IN ({exact_ph})
                GROUP BY url
                ORDER BY score DESC
            """
            rows = self._conn().execute(sql, words).fetchall()
            return [(r["url"], r["origin"], r["depth"], r["score"]) for r in rows]

        # Partial: exact (×1000 bonus) + prefix (no bonus)
        like_clauses = " OR ".join("word LIKE ?" for _ in words)
        like_params = [w + "%" for w in words]

        sql = f"""
            SELECT url, origin, depth,
                   SUM(
                       (frequency * 10) +
                       CASE WHEN word IN ({exact_ph}) THEN 1000 ELSE 0 END -
                       (depth * 5)
                   ) AS score
            FROM word_index
            WHERE word IN ({exact_ph}) OR {like_clauses}
            GROUP BY url
            ORDER BY score DESC
        """
        # params order: exact (for CASE), exact (for WHERE IN), like patterns
        params = words + words + like_params
        rows = self._conn().execute(sql, params).fetchall()
        return [(r["url"], r["origin"], r["depth"], r["score"]) for r in rows]

    def export_pdata(self, path: str) -> int:
        """
        Export the entire word_index to a plain-text p.data file.

        Format (one entry per line, space-separated):
            word  url  origin  depth  frequency

        Returns the number of entries written.
        """
        import os
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        rows = self._conn().execute(
            "SELECT word, url, origin, depth, frequency "
            "FROM word_index ORDER BY word, url"
        ).fetchall()
        with open(path, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(f"{r['word']} {r['url']} {r['origin']} {r['depth']} {r['frequency']}\n")
        return len(rows)

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

    def pages_for_session(self, session_id: int,
                          limit: int = 200) -> List[dict]:
        """Return pages indexed during a specific crawl session."""
        rows = self._conn().execute(
            "SELECT url, origin, depth, indexed_at FROM pages "
            "WHERE session_id=? ORDER BY indexed_at DESC LIMIT ?",
            (session_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def save(self) -> None:
        """No-op: SQLite commits happen on every add_page call."""
        pass
