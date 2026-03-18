"""
engine.py — Concurrent BFS web crawler.

Architecture
------------
  start(origin, k)
    └── seeds (origin, depth=0) into _work_q (bounded Queue)
         └── N worker threads consume items
              ├── extension pre-filter     ← skip binary/static files early
              ├── token-bucket rate limiter  ← back-pressure #1
              ├── urllib.request fetch       ← stdlib HTTP only
              ├── html.parser extraction     ← stdlib HTML only
              ├── InvertedIndex.add_page()   ← thread-safe SQLite
              └── child links → _work_q     ← back-pressure #2 (queue.Full drops)

Back-pressure
  1. queue.Queue(maxsize) — child URLs dropped when queue full
  2. Token-bucket rate limiter — workers sleep when bucket empty

URL filtering (reduces failures drastically)
  • Extension filter  — skip .jpg/.png/.pdf/… before even fetching
  • Same-domain guard — only follow links to the same host as origin
  • Non-HTML skip     — content-type check in _fetch; counted as "skipped",
                        NOT as "failed" (these are not errors)
  • Failure tracking  — real HTTP/network errors written to failed_urls table

Persistence
  Visited URLs live in SQLite (INSERT OR IGNORE is atomic).
  Failed URLs stored per session in failed_urls table.
  No separate JSON files needed; resume works across restarts.
"""

import os
import queue
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import List, Optional, Set

from crawler.parser import LinkParser, TextParser
from storage.database import DB_PATH, FailedURLDB, SessionDB, VisitedDB
from storage.index import InvertedIndex


# ---------------------------------------------------------------------------
# URL pre-filter: extensions that are never HTML
# ---------------------------------------------------------------------------

_SKIP_EXTENSIONS: Set[str] = frozenset({
    # Images
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico",
    ".bmp", ".tiff", ".tif", ".avif", ".heic",
    # Documents / data
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".zip", ".tar", ".gz", ".rar", ".7z",
    ".json", ".xml", ".csv", ".tsv", ".yaml", ".yml",
    # Media
    ".mp3", ".mp4", ".ogg", ".webm", ".avi", ".mov", ".mkv",
    ".wav", ".flac",
    # Code / static assets
    ".css", ".js", ".ts", ".woff", ".woff2", ".ttf", ".eot",
    ".map", ".txt",
})


# Wikipedia / MediaWiki namespaces that are not article content.
# Skipping these avoids talk pages, user pages, admin special pages, etc.
# The filter is path-prefix based so it works on any MediaWiki site.
_SKIP_PATH_PREFIXES: tuple = (
    "/special:", "/talk:", "/user:", "/user_talk:",
    "/wikipedia:", "/wikipedia_talk:", "/help:", "/help_talk:",
    "/portal:", "/portal_talk:", "/template:", "/template_talk:",
    "/category_talk:", "/file_talk:", "/mediawiki:",
    # Common query-parameter patterns that generate near-infinite URLs
    "action=edit", "action=history", "action=raw",
    "oldid=", "diff=", "printable=yes",
)


def _should_skip_url(url: str) -> bool:
    """
    Return True if the URL should be skipped without fetching.

    Checks (in order):
      1. File extension → binary/static resource
      2. Path prefix    → MediaWiki non-content namespaces
      3. Query string   → MediaWiki action/diff/oldid parameters
    """
    parsed = urllib.parse.urlparse(url)
    path_lower = parsed.path.lower()
    _, ext = os.path.splitext(path_lower)
    if ext in _SKIP_EXTENSIONS:
        return True
    # Check path prefixes (MediaWiki namespaces encoded in path)
    for prefix in _SKIP_PATH_PREFIXES[:14]:   # path-based prefixes only
        if prefix in path_lower:
            return True
    # Check query string for action-type parameters
    query_lower = parsed.query.lower()
    for qpat in _SKIP_PATH_PREFIXES[14:]:    # query-based patterns
        if qpat in query_lower:
            return True
    return False


# ---------------------------------------------------------------------------
# Token-bucket rate limiter
# ---------------------------------------------------------------------------

class _RateLimiter:
    """
    Classic token-bucket: refills `rate` tokens/second, capped at `rate`.
    wait_and_acquire() blocks until a token is available.
    """

    def __init__(self, rate: float):
        self._rate = rate
        self._tokens = float(rate)
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def _refill(self):
        now = time.monotonic()
        self._tokens = min(self._rate, self._tokens + (now - self._last) * self._rate)
        self._last = now

    def try_acquire(self) -> bool:
        with self._lock:
            self._refill()
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return True
            return False

    def wait_and_acquire(self):
        while not self.try_acquire():
            time.sleep(0.05)


# ---------------------------------------------------------------------------
# Thread-safe stats
# ---------------------------------------------------------------------------

class CrawlerStats:
    def __init__(self):
        self._lock = threading.Lock()
        self.urls_processed = 0
        self.urls_failed = 0
        self.urls_skipped = 0       # non-HTML by content-type or extension
        self.urls_dropped = 0
        self.queue_depth = 0
        self.throttled = False
        self.active = False
        self.start_time: Optional[float] = None
        self.finish_time: Optional[float] = None

    def snapshot(self) -> dict:
        with self._lock:
            elapsed = (
                (self.finish_time or time.time()) - self.start_time
                if self.start_time else 0.0
            )
            return {
                "active": self.active,
                "urls_processed": self.urls_processed,
                "urls_failed": self.urls_failed,
                "urls_skipped": self.urls_skipped,
                "urls_dropped_backpressure": self.urls_dropped,
                "queue_depth": self.queue_depth,
                "throttled": self.throttled,
                "elapsed_s": round(elapsed, 1),
            }

    def _set(self, **kwargs):
        with self._lock:
            for k, v in kwargs.items():
                setattr(self, k, v)

    def _inc(self, field: str, delta: int = 1):
        with self._lock:
            setattr(self, field, getattr(self, field) + delta)


# ---------------------------------------------------------------------------
# Crawler
# ---------------------------------------------------------------------------

class Crawler:
    """
    Parameters
    ----------
    index        : InvertedIndex — shared, thread-safe (SQLite-backed)
    max_workers  : concurrent fetch threads
    max_queue    : queue.Queue maxsize — back-pressure ceiling
    rate         : max HTTP fetches / second (token bucket)
    timeout      : per-request HTTP timeout in seconds
    same_domain  : if True (default) only follow links on the same hostname
    save_interval: (legacy, no-op; SQLite auto-commits every add_page)
    db_path      : path to the SQLite database for visited-URL tracking
    """

    _HEADERS = {
        "User-Agent": "MiniGoogle/1.0 (educational; github.com)",
        "Accept": "text/html,*/*;q=0.8",
        "Accept-Language": "en",
    }

    def __init__(
        self,
        index: InvertedIndex,
        max_workers: int = 8,
        max_queue: int = 500,
        rate: float = 10.0,
        timeout: float = 10.0,
        same_domain: bool = True,
        visited_path: Optional[str] = None,  # kept for API compat
        save_interval: int = 50,             # kept for API compat
        db_path: str = DB_PATH,
    ):
        self._index = index
        self._max_workers = max_workers
        self._timeout = timeout
        self._save_interval = save_interval
        self._max_queue = max_queue
        self._same_domain = same_domain

        self._rate_limiter = _RateLimiter(rate)
        self._work_q: queue.Queue = queue.Queue(maxsize=max_queue)

        # Visited URLs stored in SQLite — INSERT OR IGNORE is atomic
        self._visited_db = VisitedDB(path=db_path)
        self._session_db = SessionDB(path=db_path)
        self._failed_db = FailedURLDB(path=db_path)
        self._session_id: Optional[int] = None
        self._origin_host: str = ""

        self.stats = CrawlerStats()
        self._done_event = threading.Event()
        self._threads: List[threading.Thread] = []

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self, origin: str, max_depth: int):
        """
        Begin BFS crawl from *origin* to *max_depth*.
        Returns immediately; work runs on background daemon threads.

        Visited-URL semantics (post-fix)
        ---------------------------------
        URLs are marked visited in _worker at DEQUEUE time, not at enqueue time.
        This means:
          - A URL dropped due to back-pressure (queue full) is NOT permanently
            lost — it will be processed if rediscovered in a later session.
          - Two workers may race to mark the same URL; the second sees False
            and skips immediately, so no duplicate indexing occurs.
          - The origin is seeded unconditionally; if already visited the first
            worker dequeue skips it (mark_visited → False), the queue drains,
            and the monitor signals done within seconds.
        """
        self._done_event.clear()
        self.stats._set(active=True, start_time=time.time())
        self._origin_host = urllib.parse.urlparse(origin).netloc.lower()
        self._session_id = self._session_db.create_session(
            origin, max_depth, same_domain=self._same_domain
        )

        for _ in range(self._max_workers):
            t = threading.Thread(target=self._worker, daemon=True)
            t.start()
            self._threads.append(t)

        self._work_q.put((origin, origin, 0, max_depth))
        self.stats._set(queue_depth=1)

        threading.Thread(target=self._monitor, daemon=True).start()

    def wait(self, timeout: Optional[float] = None) -> bool:
        """Block until crawl finishes.  Returns True if finished."""
        return self._done_event.wait(timeout)

    def stop(self):
        """Drain queue and signal workers to exit."""
        while not self._work_q.empty():
            try:
                self._work_q.get_nowait()
                self._work_q.task_done()
            except queue.Empty:
                break
        self._work_q.join()

    def is_active(self) -> bool:
        return self.stats.active

    # ── Worker ───────────────────────────────────────────────────────────────

    def _worker(self):
        while True:
            try:
                item = self._work_q.get(timeout=2.0)
            except queue.Empty:
                if self._done_event.is_set():
                    break
                continue
            url = item[0]
            # Mark visited HERE (at dequeue time), not at enqueue time.
            # This ensures that a URL dropped due to back-pressure is NOT
            # permanently lost — it stays discoverable in future crawl runs.
            # If two workers race on the same URL (possible if it was enqueued
            # twice before either was dequeued), only the first proceeds.
            if not self._visited_db.mark_visited(url):
                self._work_q.task_done()
                continue
            try:
                self._process(*item)
            except Exception:
                self.stats._inc("urls_failed")
            finally:
                self._work_q.task_done()
                self.stats._set(queue_depth=self._work_q.qsize())

    def _process(self, url: str, origin: str, depth: int, max_depth: int):
        # Extension pre-filter: skip binary/static resources entirely.
        # These are NOT failures — we never intended to index them.
        if _should_skip_url(url):
            self.stats._inc("urls_skipped")
            return

        # Rate-limit (back-pressure #1)
        if not self._rate_limiter.try_acquire():
            self.stats._set(throttled=True)
            self._rate_limiter.wait_and_acquire()
        self.stats._set(throttled=False)

        html, error = self._fetch(url)

        if html is None:
            if error == "skip":
                # Non-HTML content (image served without extension, etc.)
                self.stats._inc("urls_skipped")
            else:
                # Real network / HTTP error
                self.stats._inc("urls_failed")
                if self._session_id is not None and error:
                    self._failed_db.add_failure(self._session_id, url, error)
            return

        # Parse text and index
        tp = TextParser()
        tp.feed(html)
        self._index.add_page(url, origin, depth, tp.word_counts(),
                             session_id=self._session_id)
        self.stats._inc("urls_processed")

        # Discover child links
        if depth < max_depth:
            lp = LinkParser(url)
            lp.feed(html)
            for link in lp.links:
                # Domain filter: skip links outside the origin host
                if self._same_domain:
                    link_host = urllib.parse.urlparse(link).netloc.lower()
                    if link_host != self._origin_host:
                        continue
                # Extension pre-filter: don't even enqueue binary URLs
                if _should_skip_url(link):
                    continue
                try:
                    self._work_q.put_nowait(
                        (link, origin, depth + 1, max_depth)
                    )
                except queue.Full:
                    # Back-pressure #2: queue at capacity — drop URL
                    self.stats._inc("urls_dropped")

    def _fetch(self, url: str):
        """
        HTTP GET using stdlib urllib.

        Returns
        -------
        (html_str, None)      — success
        (None,     "skip")    — non-HTML content (not an error)
        (None,     error_msg) — real HTTP/network error
        """
        try:
            # Percent-encode any non-ASCII characters in the URL path/query
            # (e.g. Cyrillic/Arabic Wikipedia URLs) so urllib can handle them.
            p = urllib.parse.urlparse(url)
            safe_url = p._replace(
                path=urllib.parse.quote(p.path, safe="/:@!$&'()*+,;="),
                query=urllib.parse.quote(p.query, safe="=&+"),
            ).geturl()
            req = urllib.request.Request(safe_url, headers=self._HEADERS)
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                ct = resp.headers.get("Content-Type", "")
                if "text/html" not in ct:
                    return None, "skip"
                charset = "utf-8"
                for part in ct.split(";"):
                    part = part.strip()
                    if part.lower().startswith("charset="):
                        charset = part.split("=", 1)[1].strip()
                        break
                return resp.read().decode(charset, errors="replace"), None
        except urllib.error.HTTPError as e:
            return None, f"HTTP {e.code}"
        except urllib.error.URLError as e:
            return None, f"URLError: {e.reason}"
        except Exception as e:
            return None, str(e)[:120]

    # ── Monitor ──────────────────────────────────────────────────────────────

    def _monitor(self):
        """Signal completion when queue fully drains."""
        self._work_q.join()
        self.stats._set(active=False, finish_time=time.time())
        self._done_event.set()
        if self._session_id is not None:
            s = self.stats.snapshot()
            self._session_db.finish_session(
                self._session_id,
                pages_indexed=self._index.page_count(),
                urls_processed=s["urls_processed"],
                urls_failed=s["urls_failed"],
                urls_skipped=s["urls_skipped"],
            )
