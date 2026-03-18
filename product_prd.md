# Product Requirements Document — Web Crawler & Search Engine

**Project:** Web Crawler & Search Engine
**Version:** 3.0
**Date:** 2026-03-18
**Course:** AI Aided Computer Engineering — Istanbul Technical University

---

## 1. Overview

A single-machine, concurrent web crawler and real-time search engine built entirely with Python's standard library. The system demonstrates concurrent system design, back-pressure management, and thread-safe data structures in the context of large-scale information retrieval. The web UI is served by Python's built-in `http.server` with no external web framework.

---

## 2. Goals

| # | Goal |
|---|---|
| G1 | Crawl a website starting from a given URL to a configurable depth `k`. |
| G2 | Guarantee that no URL is fetched more than once per crawl session. |
| G3 | Support concurrent search while the indexer is still running. |
| G4 | Implement back-pressure so the system cannot exhaust memory or overwhelm remote servers. |
| G5 | Provide real-time visibility into crawl progress via a CLI dashboard and web UI. |
| G6 | Support resuming a crawl after interruption without restarting from scratch. |
| G7 | Provide a browser-based web UI for crawling, searching, and inspecting crawl history. |
| G8 | Allow pausing and resuming an active crawl without losing queue state. |

---

## 3. Non-Goals

- Multi-machine distributed crawling.
- Compliance with `robots.txt` (noted but not implemented).
- Full-text ranking algorithms (PageRank, BM25, TF-IDF).
- Authentication or crawling behind login pages.
- External third-party libraries (Flask, Django, BeautifulSoup, requests, etc.).

---

## 4. Functional Requirements

### 4.1 Indexer (`index` command)

| ID | Requirement |
|---|---|
| F-I1 | Accept `origin` (URL) and `k` (integer depth) as inputs. |
| F-I2 | Perform BFS traversal; enqueue all `<a href>` links found on each page. |
| F-I3 | Never fetch the same URL twice within a session (visited set). |
| F-I4 | Stop following links once depth `k` is reached relative to the origin. |
| F-I5 | Use only `urllib.request` for HTTP and `html.parser` for HTML parsing. |
| F-I6 | Extract word-frequency counts from page text (excluding script/style). |
| F-I7 | Store indexed data in SQLite as `(word, url, origin, depth, frequency)`. |
| F-I8 | Run on a configurable number of concurrent worker threads. |
| F-I9 | Apply a token-bucket rate limiter (configurable fetches/second). |
| F-I10 | Apply queue-depth back-pressure: drop child URLs when queue is at capacity. |
| F-I11 | Pre-filter URLs by file extension before fetching (images, PDFs, scripts, etc.). |
| F-I12 | Support same-domain-only crawling to prevent unbounded cross-site traversal. |
| F-I13 | Skip MediaWiki non-content namespaces (Talk:, Special:, User:, Template:, …). |
| F-I14 | Record every crawl as a session in the database (start time, end time, outcome). |
| F-I15 | Persist failed URLs (with error reason) per session for later inspection. |

### 4.2 Crawl Control

| ID | Requirement |
|---|---|
| F-C1 | Support pausing an active crawl; workers finish their current page then wait. |
| F-C2 | Support resuming a paused crawl; queue and visited-URL state are preserved. |
| F-C3 | Support stopping a crawl; queue is drained and workers exit cleanly. |

### 4.3 Searcher (`search` command)

| ID | Requirement |
|---|---|
| F-S1 | Accept a free-text `query` string. |
| F-S2 | Tokenise query and look up each token in the inverted index. |
| F-S3 | Return a ranked list of `(relevant_url, origin_url, depth)` triples. |
| F-S4 | Relevancy: exact token matches weighted ×3, prefix matches weighted ×1. |
| F-S5 | Support partial (prefix) word matching: `"artif"` matches `"artificial"`. |
| F-S6 | Support paginated results via `limit` and `offset` parameters. |
| F-S7 | Search must be thread-safe and may execute concurrently with indexing. |
| F-S8 | Search reflects the most recently indexed pages (live index). |

### 4.4 Dashboard (`--dashboard` flag)

| ID | Requirement |
|---|---|
| F-D1 | Display: URLs processed, failed, skipped, dropped, queue depth, throttle status, elapsed time, pages indexed, unique words. |
| F-D2 | Refresh at least every 500 ms while crawl is active. |
| F-D3 | Work on Windows and Unix without external terminal libraries. |

### 4.5 Web UI (`server` command)

| ID | Requirement |
|---|---|
| F-W1 | Serve a single-page HTML dashboard on `localhost:8080` (configurable port). |
| F-W2 | Use Python's built-in `http.server.ThreadingHTTPServer` — no Flask/Django/FastAPI. |
| F-W3 | Expose REST endpoints (see §7). |
| F-W4 | Auto-refresh stats every 1 s, recent pages every 3 s, session list every 5 s. |
| F-W5 | Allow starting a crawl from the browser with configurable URL, depth, workers, rate, max-queue, same-domain toggle. |
| F-W6 | Show back-pressure queue bar, throttle badge, and paused badge in real time. |
| F-W7 | Expose Pause / Resume / Stop controls for the active crawl. |
| F-W8 | Show crawl history table; clicking a row reveals indexed pages and failed URLs for that session. |
| F-W9 | Search results support "Load more" pagination without re-running the query. |

### 4.6 Persistence (Resume)

| ID | Requirement |
|---|---|
| F-P1 | Persist all state to `data/mini_google.db` (SQLite). |
| F-P2 | Every `add_page()` commits immediately — no batching loss on crash. |
| F-P3 | On startup, load existing state and skip already-visited URLs. |
| F-P4 | `INSERT OR IGNORE` on `visited` table provides atomic deduplication. |
| F-P5 | Every crawl session recorded in `crawl_sessions` table with full outcome stats. |
| F-P6 | Failed URLs stored per-session in `failed_urls` table for UI drill-down. |

---

## 5. Non-Functional Requirements

| ID | Requirement |
|---|---|
| NF1 | The system must handle thousands of URLs on a single laptop without OOM errors (back-pressure). |
| NF2 | No URL may be processed more than once per crawl session. |
| NF3 | Search response time < 1 second for indexes up to 10,000 pages. |
| NF4 | No external third-party libraries. Only Python stdlib. |
| NF5 | Code must be readable and each major component documented. |
| NF6 | Test coverage via stdlib `unittest` — no external test runner required. |

---

## 6. System Architecture

```
project/
├── crawler/
│   ├── engine.py     ← Crawler, CrawlerStats, _RateLimiter
│   └── parser.py     ← LinkParser, TextParser, tokenize
├── storage/
│   ├── database.py   ← SQLite schema, VisitedDB, FailedURLDB, SessionDB
│   └── index.py      ← InvertedIndex (add_page, search, pages_for_session)
├── ui/
│   └── server.py     ← WebServer, _Handler (ThreadingHTTPServer)
├── tests/            ← 65 unit tests (stdlib unittest)
├── main.py           ← CLI entry point (argparse)
└── data/
    └── mini_google.db
```

```
┌──────────────────────────────────────────────────────────┐
│                 main.py (CLI / server)                   │
│     server | index | search | status                     │
└──────────────┬───────────────────────────────────────────┘
               │
   ┌───────────▼──────────┐    ┌──────────────────────────┐
   │  crawler/engine.py   │    │  storage/index.py         │
   │                      │───▶│  InvertedIndex (SQLite)   │
   │  BFS Queue           │    │                           │
   │  ├─ Worker Threads   │    │  WAL mode, idx_word index │
   │  ├─ _RateLimiter     │    └──────────────────────────┘
   │  ├─ _pause_event     │
   │  ├─ _stop_event      │    ┌──────────────────────────┐
   │  ├─ VisitedDB        │    │  storage/database.py      │
   │  ├─ FailedURLDB      │    │  VisitedDB, FailedURLDB   │
   │  ├─ SessionDB        │    │  SessionDB                │
   │  └─ Monitor Thread   │    └──────────────────────────┘
   └──────────────────────┘
                               ┌──────────────────────────┐
                               │  ui/server.py             │
                               │  ThreadingHTTPServer      │
                               │  Single-page dashboard    │
                               └──────────────────────────┘
```

### Key Design Decisions

**Why a bounded `queue.Queue` for back-pressure?**
A bounded queue is the simplest correct way to prevent a wide crawl from allocating unbounded memory. When it fills, we drop URLs rather than blocking workers (which would deadlock) or growing without limit. Dropped URLs are not marked visited, so they can be rediscovered in a later session.

**Why a token-bucket rate limiter?**
Token-bucket smooths the request rate in bursts while respecting a sustained cap. It is more polite to remote servers than a fixed-delay approach and decouples request rate from thread count.

**Why SQLite with WAL mode instead of in-memory data structures?**
SQLite WAL mode allows multiple reader threads to proceed concurrently with a single active writer. Per-thread connections (`threading.local`) avoid SQLite's thread-safety restrictions. `INSERT OR IGNORE` on the `visited` table makes visited-URL deduplication atomic without any Python-level mutex.

**Why does search work while indexing is active?**
SQLite WAL mode + per-thread connections = no Python-level lock is required between crawler writer threads and search reader threads. The `idx_word` index means search never does a full table scan.

**Why URL pre-filtering?**
Fetching a binary resource (image, PDF) only to reject it on Content-Type wastes bandwidth and a rate-limiter token. Pre-filtering by extension removes the HTTP round-trip entirely and keeps the "failed" counter meaningful (real errors only).

**Why same-domain-only crawling?**
Wikipedia articles link to thousands of external sites. Without domain scoping, a depth-2 crawl from a single article can discover millions of URLs across the entire web, causing unbounded queue growth and meaningless back-pressure drops. Same-domain mode keeps the crawl focused and the queue manageable.

**Why pause/resume via `threading.Event`?**
`Event.wait()` is a zero-busy-wait blocking call. Workers call it immediately after dequeuing, so they block at the earliest safe point without holding any lock. This means the queue and all in-flight state are preserved exactly, and resuming is instantaneous.

---

## 7. REST API

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Single-page web UI |
| `GET` | `/api/stats` | Live crawler + index statistics |
| `GET` | `/api/recent` | Last 10 indexed pages |
| `GET` | `/api/sessions` | All crawl session records |
| `GET` | `/api/sessions/<id>` | Session detail: indexed pages + failed URLs |
| `POST` | `/api/index` | Start crawl `{url, depth, workers, rate, max_queue, same_domain}` |
| `POST` | `/api/search` | Search `{query, limit, offset}` → `{total, has_more, results}` |
| `POST` | `/api/pause` | Pause the active crawl |
| `POST` | `/api/resume` | Resume a paused crawl |
| `POST` | `/api/stop` | Stop the active crawl |

---

## 8. Acceptance Criteria

| Criterion | Pass condition |
|---|---|
| AC1 | `python main.py index https://example.com 2` indexes >= 1 page without error. |
| AC2 | `python main.py search "example"` returns `(url, origin, depth)` triples. |
| AC3 | Running search in a separate thread while indexing returns growing result sets. |
| AC4 | Queue does not grow beyond `max_queue` during a wide crawl. |
| AC5 | Interrupting with Ctrl+C and restarting resumes without re-fetching visited URLs. |
| AC6 | Dashboard shows queue depth, throttle status, and elapsed time updating live. |
| AC7 | `python main.py server` starts HTTP server; browser at localhost:8080 shows the dashboard. |
| AC8 | Starting a crawl from the web UI and searching returns results in the browser. |
| AC9 | Pause/Resume buttons appear during an active crawl; queue depth is preserved across pause. |
| AC10 | Searching `"artif"` returns pages containing `"artificial"`. |
| AC11 | Clicking a crawl history row shows the pages indexed and failures for that session. |

---

## 9. Out-of-Scope (Future Work)

See `recommendation.md` for production deployment recommendations.
