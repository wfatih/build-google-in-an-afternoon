# Agent: QAAgent

## Role
Quality Assurance Engineer — writes comprehensive unit and integration tests, validates each component against acceptance criteria, and flags regressions.

## Responsibilities
- Write 140+ unit tests across all modules using stdlib `unittest` only
- Validate every acceptance criterion (AC1–AC11) from the PRD
- Test thread-safety of `CrawlerStats`, `_RateLimiter`, `VisitedDB`
- Test search scoring correctness (exact vs. prefix weighting)
- Test HTTP endpoints via `http.client` (no requests library)
- Report failures to the responsible agent for fix

## Input
- Component APIs from CrawlerAgent, StorageAgent, UIAgent
- Acceptance criteria AC1–AC11 from ArchitectAgent

## Output
- `tests/test_tokenize.py` — 18 tests
- `tests/test_parser.py` — 22 tests
- `tests/test_database.py` — 19 tests
- `tests/test_index.py` — 28 tests
- `tests/test_engine.py` — 15 tests
- `tests/test_search_scored.py` — 12 tests
- `tests/test_server.py` — 14 tests
- `tests/test_failed_urls.py` — 12 tests

**Total: 140 tests, 0 failures**

## Test Coverage by Area

| Module | What Is Tested |
|--------|---------------|
| `tokenize` | Case normalisation, punctuation stripping, min-length filter, alpha-only, empty input |
| `parser` | Link resolution (relative, absolute, fragment), URL normalisation, script/style skip, word counts |
| `database` | `VisitedDB` atomic dedup under concurrent threads, `SessionDB` lifecycle (start→finish→query), ordering |
| `index` | `add_page()` idempotency, exact search ranking, partial search prefix matching, score formula, pagination, export |
| `engine` | `_RateLimiter` token refill (thread-safe), `CrawlerStats` atomic increments, pause state |
| `search_scored` | Score formula `(freq*10)+1000-(depth*5)`, exact-only mode, multi-token query aggregation |
| `server` | All 9 REST endpoints return correct HTTP status + JSON shape; search returns `relevance_score` |
| `failed_urls` | Persist on HTTP error, per-session query, multiple sessions isolation |

## Key Test Cases

```python
# Score formula verification
def test_score_exact_match(self):
    # freq=542, depth=0: (542*10)+1000-(0*5) = 6420
    self.idx.add_page("http://a.com", "http://a.com", 0, {"python": 542})
    results = self.idx.search_scored("python")
    self.assertEqual(results[0][3], 6420)

# Prefix match is lower than exact
def test_partial_beats_nothing_but_loses_to_exact(self):
    self.idx.add_page("http://a.com", "http://a.com", 0, {"python": 10})
    self.idx.add_page("http://b.com", "http://b.com", 0, {"pythonic": 100})
    results = self.idx.search("python", partial=True)
    self.assertEqual(results[0][0], "http://a.com")  # exact wins

# Rate limiter thread safety
def test_rate_limiter_concurrent(self):
    rl = _RateLimiter(rate=100)
    acquired = []
    def worker():
        rl.wait_and_acquire()
        acquired.append(1)
    threads = [threading.Thread(target=worker) for _ in range(10)]
    [t.start() for t in threads]; [t.join() for t in threads]
    self.assertEqual(len(acquired), 10)
```

## Prompt Used

```
You are a QA engineer. Write comprehensive unit tests for the following Python modules using stdlib unittest only (no pytest).

For each module, test:
1. Happy-path correctness
2. Edge cases (empty input, single word, duplicate URLs)
3. Thread-safety (concurrent add_page, concurrent search+index, rate limiter under load)
4. The exact scoring formula: score = (freq*10) + 1000_if_exact - (depth*5)

Modules to test:
- crawler/parser.py: tokenize(), LinkParser, TextParser
- crawler/engine.py: _RateLimiter, CrawlerStats
- storage/database.py: VisitedDB (atomic dedup), SessionDB
- storage/index.py: InvertedIndex (add_page, search, search_scored, export_pdata)
- ui/server.py: all REST endpoints via http.client

No external test runner. Run with: python -m unittest discover -s tests -v
```

## Interactions
- **← CrawlerAgent**: Receives `_RateLimiter`, `CrawlerStats` for testing
- **← StorageAgent**: Receives `InvertedIndex`, `VisitedDB`, `SessionDB` for testing
- **← UIAgent**: Receives server for HTTP integration tests
- **→ ArchitectAgent**: Reports AC violations for design review
- **→ All agents**: Files bug reports when tests fail; agents fix and resubmit

## Bugs Found & Fixed

| Bug | Detected By | Fixed By |
|-----|-------------|----------|
| `recent_pages()` ordered oldest-first | `test_recent_pages_newest_first` | StorageAgent — added `ORDER BY indexed_at DESC` |
| `search_scored()` missing from `InvertedIndex` | `test_search_scored.py` | StorageAgent — added method |
| Server returned 500 on unknown session ID | `test_server_session_not_found` | UIAgent — added 404 guard |
