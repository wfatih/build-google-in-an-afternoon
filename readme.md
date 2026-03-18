# Mini-Google — Web Crawler & Search Engine

A concurrent web crawler and inverted-index search engine built with **Python's standard library only** — no Scrapy, BeautifulSoup, Flask, or requests.

---

## Quick Start

```bash
# 1. Start the web UI (recommended)
python main.py server
# Open http://localhost:8080 in your browser

# 2. Or use the CLI
python main.py index https://wikipedia.org 2 --dashboard
python main.py search "free encyclopedia"
python main.py status
```

No pip install needed. Python 3.10+ required.

---

## Web UI

Start with `python main.py server` and open **http://localhost:8080**.

| Panel | What it does |
|---|---|
| Crawler | Enter a URL + depth, configure workers/rate/queue, hit Start |
| Live stats | Auto-refreshes every second: processed, indexed, queue depth, back-pressure bar |
| Search | Type a query, get ranked `(url, origin, depth)` triples instantly |
| Recently Indexed | Live table of the last 10 indexed pages |

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

### `search <query>`

```bash
python main.py search "artificial intelligence"
```

Returns ranked `(relevant_url, origin_url, depth)` triples.

### `status`

```bash
python main.py status
```

Prints page count, word count, visited URL count, and recent pages.

---

## Architecture

```
mini-google/
├── crawler/
│   ├── engine.py     BFS crawler, token-bucket rate limiter, CrawlerStats
│   └── parser.py     LinkParser, TextParser, tokenize (stdlib html.parser)
├── storage/
│   ├── database.py   SQLite schema, VisitedDB, per-thread connections
│   └── index.py      InvertedIndex — add_page() + search()
├── ui/
│   └── server.py     ThreadingHTTPServer web UI (stdlib http.server)
├── main.py           CLI entry point (argparse)
└── data/
    └── mini_google.db  SQLite database (auto-created)
```

### How it works

**Indexer (BFS Crawler)**

1. `start(origin, k)` spawns N worker threads and seeds the queue with `(origin, depth=0)`.
2. Each worker: rate-limit → HTTP GET (`urllib.request`) → parse HTML (`html.parser`) → write to SQLite → enqueue child links.
3. Back-pressure is applied at two levels:
   - **Queue ceiling**: `queue.Queue(maxsize=N)` drops child URLs when full.
   - **Token bucket**: workers sleep when the rate limit is hit, capping sustained throughput.
4. Visited-URL deduplication uses `INSERT OR IGNORE` in SQLite — atomic, no Python lock needed.
5. A monitor thread calls `queue.Queue.join()` and fires a `threading.Event` when all work is done.

**Inverted Index (SQLite)**

```sql
-- Relevancy query: SUM(frequency) per URL across all query terms
SELECT url, origin, depth, SUM(frequency) AS score
FROM word_index
WHERE word IN (?, ?, ...)
GROUP BY url ORDER BY score DESC
```

Scoring runs inside the SQLite engine using the `idx_word` index — no full table scan in Python.

**Concurrent Search While Indexing**

SQLite WAL mode allows readers to proceed while a writer is active. Each thread uses its own connection (`threading.local`), so there is no Python-level lock between crawl workers and search queries. Results reflect newly indexed pages with zero additional code.

**Persistence / Resume**

All state lives in `data/mini_google.db`. Every `add_page()` commits immediately. On the next `index` run, the `visited` table skips already-crawled URLs automatically.

---

## Database Schema

```sql
pages      (url PK, origin, depth, indexed_at)
word_index (word, url PK, origin, depth, frequency)   -- 81K+ rows typical
visited    (url PK, visited_at)                        -- dedup, atomic
```

---

## Concurrent search while indexing active

SQLite WAL mode + per-thread connections = no explicit synchronization needed between the crawler's writer threads and search queries. The web UI polls `/api/stats` every second and search results reflect the live index state.
