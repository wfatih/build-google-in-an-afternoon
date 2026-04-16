# Agent: ArchitectAgent

## Role
System Architect — translates product requirements into a concrete, component-level design before any code is written.

## Responsibilities
- Parse and clarify the raw assignment requirements
- Define the system's module boundaries and data flow
- Decide technology constraints (stdlib-only, SQLite, WAL mode)
- Produce the authoritative `product_prd.md` as the shared contract for all downstream agents
- Resolve design conflicts raised by other agents (e.g., StorageAgent vs. CrawlerAgent on concurrency model)

## Input
- Raw assignment text (Project 1 spec)
- Constraints: single machine, Python stdlib only, no external libraries

## Output
- `product_prd.md` — full PRD with goals, functional requirements, schema, REST API surface, acceptance criteria
- Architecture diagram (ASCII, embedded in PRD)
- Component boundary decisions communicated to all agents

## Key Decisions Made

| Decision | Rationale |
|----------|-----------|
| SQLite with WAL mode (not in-memory dict) | WAL allows concurrent readers (search) during writes (crawler) without Python-level locks |
| Bounded `queue.Queue(maxsize)` for back-pressure | Simplest correct mechanism to cap memory; drop rather than block to prevent deadlock |
| Token-bucket rate limiter | Smooths bursts while respecting sustained cap; decouples rate from thread count |
| `threading.local` for DB connections | Avoids SQLite thread-safety restriction without a global mutex |
| Same-domain crawling as default | Prevents unbounded queue growth from Wikipedia's millions of external links |
| BFS over DFS | Depth limit `k` maps naturally to BFS level; DFS risks deep paths before shallow ones |

## Prompt Used

```
You are a senior software architect. Given the following assignment, produce:
1. A full PRD (goals, non-goals, functional requirements, schema, REST API, acceptance criteria)
2. A component diagram showing data flow between crawler, storage, and UI layers
3. Key design decision justifications

Constraints:
- Single machine, Python stdlib only (no Flask, requests, BeautifulSoup)
- Must support concurrent search while crawling
- Must handle very large crawls without OOM

Assignment: [raw spec text]
```

## Interactions
- **→ CrawlerAgent**: Hands off engine interface contract (`start(origin, k, workers, rate, max_queue)`)
- **→ StorageAgent**: Hands off SQLite schema and `InvertedIndex` API (`add_page`, `search`)
- **→ UIAgent**: Hands off REST API surface (9 endpoints) and stats payload shape
- **→ QAAgent**: Hands off acceptance criteria (AC1–AC11) as test targets
- **← All agents**: Receives clarification requests; arbitrates conflicts
