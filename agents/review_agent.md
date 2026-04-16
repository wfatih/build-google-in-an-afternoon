# Agent: ReviewAgent

## Role
Code Reviewer & Technical Writer — performs final code review, security audit, performance analysis, and produces all documentation.

## Responsibilities
- Review each agent's output for correctness, security, and style
- Identify and flag security vulnerabilities (command injection, path traversal, XSS)
- Validate that no external libraries were used
- Write `readme.md` (user-facing), `recommendation.md` (production deployment)
- Verify the final system satisfies all 11 acceptance criteria
- Produce `multi_agent_workflow.md`

## Input
- All source files from CrawlerAgent, StorageAgent, UIAgent
- Test results from QAAgent
- PRD from ArchitectAgent

## Output
- `readme.md`
- `recommendation.md`
- `multi_agent_workflow.md`
- Inline code review comments (resolved before final commit)

## Security Review Findings

| Finding | Severity | Resolution |
|---------|----------|------------|
| URL parameter in `/search?query=` passed to SQL | Medium | Confirmed: parameterised via `?` placeholder — no injection possible |
| `urllib.request` follows redirects by default | Low | Acceptable for crawler; infinite loops capped by visited-set dedup |
| SQLite DB file world-readable | Low | Localhost-only; noted in recommendation for prod |
| No Content-Security-Policy header | Info | Added `Content-Security-Policy: default-src 'self' 'unsafe-inline'` |

## Performance Review Findings

| Finding | Impact | Resolution |
|---------|--------|------------|
| `add_page()` commits after every page | High write latency at scale | Acceptable for dev; batched WAL commits noted in recommendation |
| No `idx_origin` index on `word_index` | Slow origin-filter queries | Added `CREATE INDEX idx_origin ON word_index(origin)` |
| `export_pdata()` loads all rows into memory | OOM risk on 10M+ entries | Streaming cursor approach described in recommendation |

## Stdlib-Only Verification

```bash
grep -r "^import\|^from" crawler/ storage/ ui/ main.py \
  | grep -Ev "(sqlite3|urllib|html|http|threading|queue|json|
               time|os|re|pathlib|collections|io|sys|argparse|
               dataclasses|typing|unittest|contextlib|functools)"
# Result: (empty — all imports are stdlib)
```

## Acceptance Criteria Verification

| AC | Criterion | Status |
|----|-----------|--------|
| AC1 | `python main.py index https://example.com 2` indexes ≥1 page | Pass |
| AC2 | `python main.py search "example"` returns `(url, origin, depth)` | Pass |
| AC3 | Concurrent search returns growing result sets | Pass (WAL mode) |
| AC4 | Queue never exceeds `max_queue` | Pass (bounded Queue) |
| AC5 | Ctrl+C + restart resumes without re-fetching | Pass (visited table) |
| AC6 | Dashboard shows queue, throttle, elapsed updating live | Pass |
| AC7 | `python main.py server` — browser at localhost:3600 shows dashboard | Pass |
| AC8 | Start crawl from UI + search returns results | Pass |
| AC9 | Pause/Resume preserves queue depth | Pass (threading.Event) |
| AC10 | `"artif"` returns pages containing `"artificial"` | Pass (LIKE prefix) |
| AC11 | Crawl history row drill-down shows pages + failures | Pass |

## Prompt Used

```
You are a senior engineer doing final code review. For each file:
1. Check for security issues (SQL injection, XSS, path traversal, command injection)
2. Verify stdlib-only (no pip packages)
3. Check thread safety (shared mutable state, missing locks)
4. Check for resource leaks (unclosed connections, files, threads)
5. Flag any deviation from the PRD

Then write:
- readme.md: quick-start, architecture diagram, API reference, test instructions
- recommendation.md: 2 paragraphs on production deployment

Files to review: crawler/engine.py, crawler/parser.py, storage/database.py,
                 storage/index.py, ui/server.py, main.py
```

## Interactions
- **← All agents**: Receives completed source files for review
- **→ CrawlerAgent / StorageAgent / UIAgent**: Returns review comments for fixes
- **→ ArchitectAgent**: Escalates design-level issues
- **← QAAgent**: Uses test results as evidence in review
