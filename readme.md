# Web Crawler & Search Engine

A concurrent web crawler and inverted-index search engine built with **Python's standard library only** — no Scrapy, BeautifulSoup, Flask, or requests.

---

## Quick Start

```bash
# 1. Start the web UI (recommended)
python main.py server
# Open http://localhost:3600

# 2. Or use the CLI
python main.py index https://en.wikipedia.org/wiki/Python 2 --dashboard
python main.py search "programming language"
python main.py status
```

No `pip install` needed. Python 3.10+ required.

---

## Web UI

Start with `python main.py server` and open **http://localhost:3600**.

### Crawler panel

- Enter an origin URL and depth `k`
- Configure workers, rate limit, and queue size
- Toggle **Same domain only** to stay within the origin hostname (recommended)
- **Start** — begins BFS crawl in the background
- **Pause / Resume** — workers finish their current page then wait; queue is preserved
- **Stop** — drains the queue and shuts workers down cleanly

### Live stats (auto-refreshes every second)

| Stat | Meaning |
|---|---|
| Processed | Pages successfully fetched and indexed |
| Indexed | Total pages in the database (all sessions) |
| Words | Unique words in the inverted index |
| Queue | Current work-queue depth |
| Failed | Real HTTP/network errors (4xx, 5xx, timeouts) |
| Skipped | Non-HTML URLs skipped without fetching (images, PDFs, scripts…) |
| Dropped (BP) | URLs discarded by back-pressure when queue was full |

### Search panel

- Supports **partial word matching** — `"artif"` matches `"artificial"`, `"python"` matches `"python"`
- Exact matches rank higher (weight ×3) than prefix matches (weight ×1)
- **Load more** button pages through all results without re-running the query

### Crawl History

- Every crawl session is recorded with its start time, duration, and outcome
- Click any row to open a **detail panel** with two tabs:
  - **Indexed Pages** — every URL indexed in that session
  - **Failed URLs** — every real error with its HTTP status or error message

### Recently Indexed

Live table of the 10 most recently indexed pages across all sessions.

---

## CLI Commands

### `index <url> <depth>`

```bash
python main.py index https://example.com 2 --dashboard
```

| Flag | Default | Description |
|---|---|---|
| `--workers` | 8 | Concurrent fetch threads |
| `--rate` | 10 | Max HTTP req/sec (token bucket) |
| `--max-queue` | 500 | Back-pressure queue ceiling |
| `--timeout` | 10 | Per-request timeout (seconds) |
| `--dashboard` | off | Live terminal dashboard |
| `--all-domains` | off | Follow links to any domain (default: same domain only) |

### `search <query>`

```bash
python main.py search "artificial intelligence"
```

Returns ranked `(relevant_url, origin_url, depth)` triples. Partial word matching is active by default.

### `status`

```bash
python main.py status
```

Prints page count, word count, visited URL count, and the 5 most recently indexed pages.

---

## Architecture

```
project/
├── crawler/
│   ├── engine.py     Crawler, CrawlerStats, _RateLimiter
│   └── parser.py     LinkParser, TextParser, tokenize
├── storage/
│   ├── database.py   SQLite schema, VisitedDB, FailedURLDB, SessionDB
│   └── index.py      InvertedIndex — add_page(), search(), pages_for_session()
├── ui/
│   └── server.py     ThreadingHTTPServer single-page web app
├── tests/            65 unit tests (stdlib unittest)
├── main.py           CLI entry point (argparse)
└── data/
    └── mini_google.db  SQLite database (auto-created on first run)
```

---

## How it works

### Indexer — BFS crawler

1. `start(origin, k)` spawns N worker threads and seeds the queue with `(origin, depth=0)`.
2. Each worker follows this pipeline:

   ```
   URL pre-filter  →  rate limiter  →  HTTP GET  →  parse HTML  →  write index  →  enqueue children
   ```

3. **URL pre-filter** (before any HTTP request):
   - 40+ binary extensions (`.jpg`, `.png`, `.pdf`, `.css`, `.js`, …) skipped immediately
   - MediaWiki namespaces (`Talk:`, `Special:`, `User:`, `Template:`, …) skipped
   - Query parameters (`action=edit`, `oldid=`, `diff=`) skipped
   - If `same_domain=True`, links outside the origin hostname are dropped

4. **Back-pressure** at two levels:
   - **Queue ceiling** — `queue.Queue(maxsize)` drops child URLs when full; dropped URLs are not marked visited so they can be rediscovered later
   - **Token bucket** — workers sleep when the rate limit is exhausted

5. Visited-URL deduplication uses `INSERT OR IGNORE` in SQLite — atomic, no Python-level lock needed.

6. A monitor thread calls `queue.Queue.join()` and fires a `threading.Event` when all work completes, recording final stats in the `crawl_sessions` table.

### Pause / Resume / Stop

- **Pause** clears `_pause_event`; workers call `_pause_event.wait()` after dequeuing, blocking until resumed. The queue and visited-URL state are fully preserved.
- **Resume** sets `_pause_event`; workers unblock and continue.
- **Stop** sets `_stop_event`, unblocks any paused workers, drains the queue, and calls `Queue.join()`.

### Inverted Index — relevancy scoring

```sql
-- Partial search: exact hits weighted ×3, prefix hits ×1
SELECT url, origin, depth,
       SUM(frequency * CASE WHEN word IN (?, …) THEN 3 ELSE 1 END) AS score
FROM word_index
WHERE word IN (?, …) OR word LIKE ?% OR word LIKE ?%
GROUP BY url
ORDER BY score DESC
```

Scoring runs entirely inside the SQLite engine using the `idx_word` index — no full table scan in Python.

### Concurrent search while indexing

SQLite WAL mode allows reader threads to proceed concurrently with the single active writer. Each thread has its own connection (`threading.local`), so there is no Python-level lock between crawler workers and search queries. Search results reflect newly indexed pages immediately.

### Persistence and resume

All state lives in `data/mini_google.db`. Every `add_page()` commits immediately. On the next `index` run the `visited` table causes already-crawled URLs to be skipped automatically. Failed URLs are persisted in `failed_urls` keyed by session, so the UI drill-down works across restarts.

---

## Database Schema

```sql
pages          (url PK, origin, depth, indexed_at, session_id)
word_index     (word, url PK, origin, depth, frequency)
visited        (url PK, visited_at)
crawl_sessions (id PK, origin, depth, started_at, finished_at,
                pages_indexed, urls_processed, urls_failed,
                urls_skipped, same_domain, status)
failed_urls    (id PK, session_id, url, error, failed_at)
```

---

## REST API

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Single-page web UI |
| `GET` | `/search?query=X&sortBy=relevance` | Scored search — returns `relevance_score` per result |
| `GET` | `/api/stats` | Live crawler + index statistics |
| `GET` | `/api/recent` | Last 10 indexed pages |
| `GET` | `/api/export` | Export word index to `data/storage/p.data` (plaintext) |
| `GET` | `/api/sessions` | All crawl session records |
| `GET` | `/api/sessions/<id>` | Session detail: indexed pages + failed URLs |
| `POST` | `/api/index` | Start a crawl `{url, depth, workers, rate, max_queue, same_domain}` |
| `POST` | `/api/search` | Search `{query, limit, offset}` → `{total, has_more, results}` |
| `POST` | `/api/pause` | Pause the active crawl |
| `POST` | `/api/resume` | Resume a paused crawl |
| `POST` | `/api/stop` | Stop the active crawl |

---

## Tests

```bash
python -m unittest discover -s tests -v
```

65 unit tests across five modules — no external test runner required.

| Module | What it covers |
|---|---|
| `test_tokenize` | `tokenize()` — case, punctuation, length, alpha-only |
| `test_parser` | `LinkParser` (resolution, normalisation), `TextParser` (skip script/style) |
| `test_database` | `VisitedDB` (atomic dedup), `SessionDB` (lifecycle, ordering) |
| `test_index` | `InvertedIndex` (add, search exact + partial, ranking, pagination) |
| `test_engine` | `_RateLimiter` (thread safety, refill), `CrawlerStats` (thread safety, pause) |
