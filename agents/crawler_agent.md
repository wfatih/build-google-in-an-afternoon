# Agent: CrawlerAgent

## Role
Crawler Engineer — implements the BFS web crawler with concurrent workers, rate limiting, and back-pressure.

## Responsibilities
- Implement `crawler/engine.py`: `Crawler`, `CrawlerStats`, `_RateLimiter`
- Implement `crawler/parser.py`: `LinkParser`, `TextParser`, `tokenize()`
- Implement pause / resume / stop via `threading.Event`
- Pre-filter URLs (40+ binary extensions, MediaWiki namespaces)
- Enforce same-domain constraint

## Input
- Component interface contract from ArchitectAgent
- `InvertedIndex.add_page()` signature from StorageAgent
- DB handles: `VisitedDB`, `FailedURLDB`, `SessionDB` from StorageAgent

## Output
- `crawler/engine.py` (~350 lines)
- `crawler/parser.py` (~150 lines)

## Key Implementation Decisions

| Decision | Rationale |
|----------|-----------|
| Worker threads (not asyncio) | Simpler mental model; SQLite WAL handles writer contention; `urllib.request` is blocking |
| `queue.Queue(maxsize)` drop strategy | When full, child URLs are discarded but NOT marked visited — recoverable in later sessions |
| Token bucket refills via `time.monotonic()` | Monotonic clock prevents backward jumps on NTP sync |
| `INSERT OR IGNORE` on `visited` table | Atomic dedup — no Python lock needed between workers |
| URL pre-filter before HTTP request | Avoids spending a rate-limiter token on a resource that will be rejected by Content-Type |
| `_SKIP_PATH_PREFIXES` for MediaWiki | `Talk:`, `Special:`, `User:` pages are noise; filtering keeps index content-focused |

## Prompt Used

```
You are a Python systems engineer. Implement a concurrent BFS web crawler with these exact specs:
- stdlib only: urllib.request, html.parser, queue, threading
- N worker threads, token-bucket rate limiter (rate req/sec)
- Bounded queue (maxsize) for back-pressure: drop child URLs when full
- Visited-URL dedup via SQLite INSERT OR IGNORE (atomic, no Python lock)
- Pre-filter: skip URLs with extensions in [.jpg, .pdf, .css, .js, ...]
- Pause/resume/stop via threading.Event
- Session tracking: record pages_indexed, urls_failed, urls_skipped, urls_dropped

Interface contract:
  Crawler.start(origin: str, k: int, workers: int, rate: float, max_queue: int, same_domain: bool)
  Crawler.pause() / resume() / stop()
  CrawlerStats: dataclass with all live counters

Produce crawler/engine.py and crawler/parser.py.
```

## Interactions
- **← ArchitectAgent**: Interface contract, design decisions
- **← StorageAgent**: `add_page()`, `VisitedDB`, `FailedURLDB`, `SessionDB` APIs
- **→ QAAgent**: Delivers `_RateLimiter` and `CrawlerStats` for unit testing
- **→ UIAgent**: Exposes `CrawlerStats` counters for live dashboard polling

## Clarifications Requested from ArchitectAgent
1. **Q:** What happens to dropped URLs — mark visited or not?  
   **A:** Do NOT mark visited; allows rediscovery in a future session.
2. **Q:** Should stop() wait for in-flight pages to finish?  
   **A:** Yes — drain queue, call `Queue.join()`, then record session stats.
