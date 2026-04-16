# Agent: UIAgent

## Role
Frontend & API Engineer — builds the web server, single-page dashboard, and all REST endpoints using Python stdlib only.

## Responsibilities
- Implement `ui/server.py`: `ThreadingHTTPServer`, `_Handler`, all 9 REST endpoints
- Embed the full HTML/CSS/JS single-page app as a string literal (no template files)
- Wire live stats polling (1 s), recent pages (3 s), session list (5 s)
- Implement Pause / Resume / Stop controls
- Implement `GET /search?query=<word>&sortBy=relevance` endpoint with `relevance_score`
- Implement `GET /api/export` for p.data download
- Render crawl history table with per-session drill-down (indexed pages + failed URLs)

## Input
- REST API surface from ArchitectAgent (9 endpoints)
- `CrawlerStats` shape from CrawlerAgent
- `InvertedIndex` API from StorageAgent
- `SessionDB` / `FailedURLDB` API from StorageAgent

## Output
- `ui/server.py` (~900 lines, includes embedded HTML/CSS/JS)

## REST Endpoints Implemented

| Method | Path | Handler |
|--------|------|---------|
| GET | `/` | Embedded SPA HTML |
| GET | `/api/stats` | Live crawler + index counters |
| GET | `/api/recent` | 10 most recently indexed pages |
| GET | `/api/sessions` | All crawl session records |
| GET | `/api/sessions/<id>` | Session detail: pages + failures |
| GET | `/search` | `?query=<word>&sortBy=relevance` → results with `relevance_score` |
| GET | `/api/export` | Stream p.data file as download |
| POST | `/api/index` | Start crawl `{url, depth, workers, rate, max_queue, same_domain}` |
| POST | `/api/search` | Search `{query, limit, offset}` → paginated results |
| POST | `/api/pause` \| `/api/resume` \| `/api/stop` | Crawl control |

## Key Implementation Decisions

| Decision | Rationale |
|----------|-----------|
| Embedded SPA (no template files) | Zero extra files; server is a single self-contained module |
| `ThreadingHTTPServer` | Each request handled in a separate thread; search doesn't block while crawl is writing |
| JS `setInterval` polling (not WebSocket) | Simpler, stdlib-compatible; polling every 1–5 s is sufficient for live dashboard |
| Back-pressure queue bar in UI | Visual indicator of queue fill % gives operator instant insight into load |
| `GET /search` (query param) alongside `POST /api/search` | Enables direct browser URL and `curl` testing without JSON body |

## Prompt Used

```
You are a Python web developer. Implement a single-page web dashboard for a web crawler system.

Requirements:
- Python stdlib only: http.server.ThreadingHTTPServer, json, threading
- No Flask, no Jinja2, no external JS libraries
- Embed full HTML/CSS/JS as a string literal inside server.py
- REST endpoints: GET /api/stats, /api/recent, /api/sessions, /api/sessions/<id>,
                  GET /search?query=&sortBy=relevance,
                  GET /api/export,
                  POST /api/index, /api/search, /api/pause, /api/resume, /api/stop
- Dashboard panels:
    1. Crawler control (URL input, depth, workers, rate, queue size, same-domain toggle, Start/Pause/Resume/Stop)
    2. Live stats (processed, indexed, words, queue depth, failed, skipped, dropped, back-pressure bar)
    3. Search (query box, results table with relevance_score, Load More pagination)
    4. Crawl History (session table; click row → drill-down with indexed pages + failed URLs tabs)
    5. Recently Indexed (live 10-row table)

Stats auto-refresh: 1s. Recent pages: 3s. Session list: 5s.
```

## Interactions
- **← ArchitectAgent**: REST API surface, stats payload shape
- **← CrawlerAgent**: `CrawlerStats` counters, `pause()`/`resume()`/`stop()` methods
- **← StorageAgent**: `search()`, `search_scored()`, `recent_pages()`, `pages_for_session()`, `export_pdata()`
- **→ QAAgent**: Delivers server for HTTP integration tests

## Clarifications Requested
1. **Q (to ArchitectAgent):** Port — 8080 or 3600?  
   **A:** Default 3600; configurable via `--port` flag.
2. **Q (to StorageAgent):** Does `export_pdata()` write to disk or stream?  
   **A:** Write to disk at `data/storage/p.data`; endpoint streams the file.
