# Product Requirements Document — Mini-Google

**Project:** Web Crawler & Search Engine
**Version:** 2.0
**Date:** 2026-03-18
**Course:** AI Aided Computer Engineering — Istanbul Technical University

---

## 1. Overview

Mini-Google is a single-machine, concurrent web crawler and real-time search engine built entirely with Python's standard library. It serves as a demonstration of concurrent system design, back-pressure management, and thread-safe data structures in the context of large-scale information retrieval. Version 2.0 adds a browser-based web UI served by Python's built-in `http.server`.

---

## 2. Goals

| # | Goal |
|---|---|
| G1 | Crawl a website starting from a given URL to a configurable depth `k`. |
| G2 | Guarantee that no URL is fetched more than once per crawl session. |
| G3 | Support concurrent search while the indexer is still running. |
| G4 | Implement back-pressure so the system cannot exhaust memory or overwhelm remote servers. |
| G5 | Provide real-time visibility into crawl progress via a CLI dashboard. |
| G6 | Support resuming a crawl after interruption without restarting from scratch. |
| G7 | Provide a browser-based web UI for crawling and searching (no external web framework). |

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
| F-I7 | Store indexed data as `(word → [{url, origin, depth, frequency}])` in SQLite. |
| F-I8 | Run on a configurable number of concurrent worker threads. |
| F-I9 | Apply a token-bucket rate limiter (configurable fetches/second). |
| F-I10 | Apply queue-depth back-pressure: drop child URLs when queue is at capacity. |

### 4.2 Searcher (`search` command)

| ID | Requirement |
|---|---|
| F-S1 | Accept a free-text `query` string. |
| F-S2 | Tokenise query and look up each token in the inverted index. |
| F-S3 | Return a ranked list of `(relevant_url, origin_url, depth)` triples. |
| F-S4 | Relevancy score = sum of per-token frequency counts across all query terms. |
| F-S5 | Search must be thread-safe and may execute concurrently with indexing. |
| F-S6 | Search reflects the most recently indexed pages (live index). |

### 4.3 Dashboard (`--dashboard` flag)

| ID | Requirement |
|---|---|
| F-D1 | Display: URLs processed, URLs failed, queue depth, back-pressure/throttle status, elapsed time, pages indexed, unique words. |
| F-D2 | Refresh at least every 500 ms while crawl is active. |
| F-D3 | Work on Windows and Unix without external terminal libraries. |

### 4.4 Web UI (`server` command)

| ID | Requirement |
|---|---|
| F-W1 | Serve a single-page HTML dashboard on `localhost:8080` (configurable port). |
| F-W2 | Use Python's built-in `http.server.ThreadingHTTPServer` — no Flask/Django/FastAPI. |
| F-W3 | Expose REST endpoints: `GET /api/stats`, `GET /api/recent`, `POST /api/index`, `POST /api/search`. |
| F-W4 | Auto-refresh stats every 1 second and recently-indexed table every 3 seconds via JS `fetch`. |
| F-W5 | Allow starting a crawl from the browser with configurable URL, depth, workers, rate, max-queue. |
| F-W6 | Show back-pressure queue bar and throttle badge in real time. |

### 4.5 Persistence (Resume)

| ID | Requirement |
|---|---|
| F-P1 | Persist all state to `data/mini_google.db` (SQLite). |
| F-P2 | Every `add_page()` commits immediately — no batching loss on crash. |
| F-P3 | On startup, load existing state and skip already-visited URLs. |
| F-P4 | `INSERT OR IGNORE` on `visited` table provides atomic deduplication. |

---

## 5. Non-Functional Requirements

| ID | Requirement |
|---|---|
| NF1 | The system must handle a crawl of thousands of URLs on a single laptop without OOM errors (back-pressure). |
| NF2 | No URL may be processed more than once per crawl session. |
| NF3 | Search response time < 1 second for indexes up to 10,000 pages. |
| NF4 | No external third-party libraries. Only Python stdlib. |
| NF5 | Code must be readable and each major component documented. |

---

## 6. System Architecture

```
mini-google/
├── crawler/
│   ├── __init__.py
│   ├── engine.py     ← Crawler, CrawlerStats, _RateLimiter
│   └── parser.py     ← LinkParser, TextParser, tokenize
├── storage/
│   ├── __init__.py
│   ├── database.py   ← SQLite init, DB_PATH, VisitedDB, _ThreadLocalDB
│   └── index.py      ← InvertedIndex (add_page, search, recent_pages)
├── ui/
│   ├── __init__.py
│   └── server.py     ← WebServer, _Handler (ThreadingHTTPServer)
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
   │  ├─ Worker Threads   │    │  thread-safe WAL mode     │
   │  ├─ _RateLimiter     │    └──────────────────────────┘
   │  ├─ VisitedDB        │
   │  └─ Monitor Thread   │    ┌──────────────────────────┐
   └──────────────────────┘    │  ui/server.py             │
                               │  ThreadingHTTPServer      │
                               │  Single-page dashboard    │
                               └──────────────────────────┘
```

### Key Design Decisions

**Why a bounded `queue.Queue` for back-pressure?**
A bounded queue is the simplest correct way to prevent a wide crawl from allocating unbounded memory. When it fills, we drop URLs rather than blocking workers (which would deadlock) or growing without limit.

**Why a token-bucket rate limiter?**
Token-bucket smooths the request rate in bursts while respecting a sustained cap. It is more polite to remote servers than a fixed-delay approach and decouples request rate from thread count.

**Why SQLite with WAL mode instead of in-memory data structures?**
SQLite WAL mode allows multiple reader threads to proceed concurrently with a single active writer. Per-thread connections (`threading.local`) avoid SQLite's thread-safety restrictions. `INSERT OR IGNORE` on the `visited` table makes visited-URL deduplication atomic without any Python-level mutex.

**Why does search work while indexing is active?**
SQLite WAL mode + per-thread connections = no Python-level lock is required between crawler writer threads and search reader threads. The search SQL query uses the `idx_word` index so it never does a full table scan in Python.

**Why `http.server.ThreadingHTTPServer` for the web UI?**
No external dependencies. Each HTTP request is handled in a separate thread, so the dashboard's 1-second polling never blocks active crawl workers.

---

## 7. Acceptance Criteria

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

---

## 8. Out-of-Scope (Future Work)

See `recommendation.md` for production deployment recommendations.
