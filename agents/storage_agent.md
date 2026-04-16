# Agent: StorageAgent

## Role
Database & Index Engineer — designs the SQLite schema and implements the inverted index with thread-safe concurrent access.

## Responsibilities
- Design and create the 5-table SQLite schema
- Implement `storage/database.py`: `VisitedDB`, `FailedURLDB`, `SessionDB`, `_ThreadLocalDB`
- Implement `storage/index.py`: `InvertedIndex` — `add_page()`, `search()`, `search_scored()`, `export_pdata()`
- Configure WAL mode, indexes, and PRAGMA settings
- Guarantee thread-safety for concurrent crawler writers + search readers

## Input
- Schema requirements from ArchitectAgent
- Word-frequency dict format from CrawlerAgent (`{word: count}`)
- Search scoring formula from ArchitectAgent: `(freq×10) + 1000_if_exact - (depth×5)`

## Output
- `storage/database.py` (~180 lines)
- `storage/index.py` (~200 lines)

## Schema

```sql
pages          (url PK, origin, depth, indexed_at, session_id)
word_index     (word, url, origin, depth, frequency)  -- PK(word, url)
visited        (url PK, visited_at)
crawl_sessions (id PK AUTOINCREMENT, origin, depth, started_at, finished_at,
                pages_indexed, urls_processed, urls_failed, urls_skipped, same_domain, status)
failed_urls    (id PK AUTOINCREMENT, session_id, url, error, failed_at)
```

## Key Implementation Decisions

| Decision | Rationale |
|----------|-----------|
| WAL journal mode | Multiple readers proceed concurrently with single writer — enables live search during crawl |
| `threading.local` DB connections | SQLite connections are not thread-safe; one connection per thread eliminates all locking |
| `PRAGMA synchronous=NORMAL` | Safe but faster than FULL; crash-safe at OS level |
| `PRAGMA cache_size=-32000` | 32 MB page cache reduces disk I/O on large indexes |
| `idx_word` index on `word_index(word)` | Enables `WHERE word IN (...)` and `LIKE 'prefix%'` without full table scan |
| `INSERT OR REPLACE` on `word_index` | Idempotent page re-indexing; frequency overwrites correctly |
| Exact ×3 / prefix ×1 weighting | Exact matches should dominate; prefix enables partial queries |
| Immediate commit after every `add_page()` | No batching loss on crash; WAL makes this acceptably fast |

## Search SQL (partial mode)

```sql
SELECT url, origin, depth,
       SUM(frequency * CASE WHEN word IN (…exact…) THEN 3 ELSE 1 END) AS score
FROM word_index
WHERE word IN (…exact…) OR word LIKE ?% OR word LIKE ?%
GROUP BY url
ORDER BY score DESC
```

## Scored Search SQL (for export / quiz)

```sql
SELECT url, origin, depth,
       SUM( (frequency * 10) +
            CASE WHEN word IN (…exact…) THEN 1000 ELSE 0 END -
            (depth * 5) ) AS score
FROM word_index
WHERE word IN (…exact…)
GROUP BY url
ORDER BY score DESC
```

## Prompt Used

```
You are a database engineer. Implement a thread-safe inverted index on SQLite for a concurrent web crawler.

Requirements:
- WAL mode + threading.local connections (no Python-level lock)
- Schema: pages, word_index(word,url,origin,depth,frequency), visited, crawl_sessions, failed_urls
- InvertedIndex.add_page(url, origin, depth, word_counts, session_id) — commits immediately
- InvertedIndex.search(query, partial=True) — tokenise, SQL rank, return (url, origin, depth) list
- search_scored() — returns (url, origin, depth, score) using formula (freq*10)+1000_if_exact-(depth*5)
- export_pdata(path) — write all word_index rows to file as: word url origin depth frequency

Produce storage/database.py and storage/index.py. Use Python stdlib sqlite3 only.
```

## Interactions
- **← ArchitectAgent**: Schema, scoring formula, concurrency model
- **→ CrawlerAgent**: `add_page()`, `VisitedDB`, `FailedURLDB`, `SessionDB` APIs
- **→ UIAgent**: `search()`, `page_count()`, `word_count()`, `recent_pages()`, `pages_for_session()`
- **→ QAAgent**: Delivers `InvertedIndex` and `VisitedDB` for unit testing

## Clarifications Requested from ArchitectAgent
1. **Q:** Should `search()` return prefix matches or exact only by default?  
   **A:** Partial=True by default for better UX; exact-only available as `partial=False`.
2. **Q:** Export format for p.data?  
   **A:** Space-separated: `word url origin depth frequency`, one row per `word_index` record.
