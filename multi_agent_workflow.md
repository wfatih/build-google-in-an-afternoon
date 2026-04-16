# Multi-Agent Workflow

**Project:** build-google-in-an-afternoon — Web Crawler & Search Engine  
**Course:** AI Aided Computer Engineering — Istanbul Technical University  
**Student:** Fatih Çakır, 150220086

---

## Overview

This project was built using a structured multi-agent AI workflow. Rather than issuing a single prompt to generate the full system, the development process was divided among six specialized agents. Each agent owned a distinct component, received a focused prompt, produced concrete output, and communicated with other agents through well-defined interfaces. I acted as the human orchestrator: reviewing each agent's output, resolving conflicts, and making all final architectural decisions.

The final system is a single-machine Python web crawler and search engine built entirely with the standard library. The multi-agent approach is a description of the **development process**, not the runtime architecture.

---

## Agent Roster

| Agent | Component Owned | Primary Output |
|-------|----------------|----------------|
| **ArchitectAgent** | System design, PRD | `product_prd.md`, interface contracts |
| **CrawlerAgent** | BFS engine, rate limiter | `crawler/engine.py`, `crawler/parser.py` |
| **StorageAgent** | SQLite schema, inverted index | `storage/database.py`, `storage/index.py` |
| **UIAgent** | Web dashboard, REST API | `ui/server.py` |
| **QAAgent** | Unit & integration tests | `tests/*.py` (140 tests) |
| **ReviewAgent** | Code review, docs | `readme.md`, `recommendation.md`, this file |

Individual agent specifications are in the [`agents/`](agents/) directory.

---

## Workflow Diagram

```
                         ┌─────────────────────┐
                         │   Human Orchestrator │
                         │   (Fatih Çakır)      │
                         │  review · arbitrate  │
                         │  approve · deploy    │
                         └──────────┬──────────┘
                                    │
                         ┌──────────▼──────────┐
                         │   ArchitectAgent     │
                         │  PRD · schema ·      │
                         │  interface contracts │
                         └──┬───┬───┬───┬──────┘
                            │   │   │   │
               ┌────────────┘   │   │   └────────────┐
               ▼                ▼   ▼                 ▼
     ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
     │ CrawlerAgent │  │ StorageAgent │  │   UIAgent    │
     │ engine.py    │  │ database.py  │  │  server.py   │
     │ parser.py    │  │ index.py     │  │  REST + SPA  │
     └──────┬───────┘  └──────┬───────┘  └──────┬───────┘
            │                 │                  │
            └────────┬────────┘                  │
                     ▼                           │
           ┌─────────────────┐                  │
           │    QAAgent      │◄─────────────────┘
           │  140 unit tests │
           └────────┬────────┘
                    │  bug reports
                    ▼
           ┌─────────────────┐
           │  ReviewAgent    │
           │  audit · docs   │
           └─────────────────┘
```

---

## Phase-by-Phase Execution

### Phase 1 — Architecture (ArchitectAgent)

**Input:** Raw assignment spec  
**Duration:** Single session

The ArchitectAgent analysed the requirements and produced the full `product_prd.md` before any code was written. Key decisions at this phase:

- **SQLite + WAL** for concurrent read-while-write (enables live search during crawl)
- **Bounded `queue.Queue`** for back-pressure (drop, never block workers)
- **Token-bucket rate limiter** for polite, smooth crawling
- **`threading.local` DB connections** to sidestep SQLite thread restrictions
- **Same-domain crawling default** to prevent queue explosion on Wikipedia

These decisions were documented in the PRD and communicated as interface contracts to all downstream agents.

**Human decision:** Approved WAL + threading.local over a mutex-based alternative proposed by ArchitectAgent's second draft. The lock-free approach scales better with 8+ worker threads.

---

### Phase 2 — Core Components (CrawlerAgent + StorageAgent, parallel)

**Input:** Interface contracts from ArchitectAgent  
**Duration:** Two parallel sessions

CrawlerAgent and StorageAgent worked concurrently because their interfaces were fully defined upfront.

**CrawlerAgent produced:**
- BFS queue loop with N worker threads
- `_RateLimiter` (token bucket, thread-safe)
- `LinkParser` + `TextParser` + `tokenize()`
- URL pre-filter (40+ extensions, MediaWiki namespaces)
- Pause/Resume/Stop via `threading.Event`

**StorageAgent produced:**
- 5-table SQLite schema with WAL + indexes
- `InvertedIndex.add_page()` — immediate commit, idempotent
- `InvertedIndex.search()` — exact ×3 / prefix ×1 SQL scoring
- `InvertedIndex.search_scored()` — `(freq×10)+1000−(depth×5)` for export
- `VisitedDB`, `FailedURLDB`, `SessionDB`

**Conflict resolved by human:** StorageAgent initially proposed batching 50 pages per commit for performance. CrawlerAgent objected that crashes would lose batched data. Human decision: immediate commit per page (PRD requirement F-P2), with a note in `recommendation.md` about batching for production.

---

### Phase 3 — UI & API (UIAgent)

**Input:** CrawlerStats shape, InvertedIndex API, REST surface from ArchitectAgent  
**Duration:** Single session

UIAgent built the entire `ui/server.py` as a self-contained module — no template files, no external frameworks. The full HTML/CSS/JS single-page app is embedded as a string literal.

Key additions beyond the PRD baseline:
- Back-pressure queue bar (visual % fill)
- `GET /search?query=&sortBy=relevance` (curl-friendly endpoint)
- `GET /api/export` for p.data download
- Per-session drill-down with Indexed Pages / Failed URLs tabs

**Human decision:** Added `GET /search` query-param endpoint (not in original PRD) after UIAgent noted it simplifies manual testing and quiz verification.

---

### Phase 4 — Testing (QAAgent)

**Input:** All source files from Phases 2–3, acceptance criteria AC1–AC11  
**Duration:** Single session

QAAgent wrote 140 unit and integration tests. Three bugs were found and sent back to the responsible agent:

| Bug | Found by | Fixed by |
|-----|----------|----------|
| `recent_pages()` returned oldest-first | `test_recent_pages_newest_first` | StorageAgent added `ORDER BY indexed_at DESC` |
| `search_scored()` method missing | `test_search_scored.py` | StorageAgent added method |
| Server returned 500 on unknown session ID | `test_server_session_not_found` | UIAgent added 404 guard |

All 140 tests pass after fixes.

---

### Phase 5 — Review & Documentation (ReviewAgent)

**Input:** All source files + test results  
**Duration:** Single session

ReviewAgent performed:
- Security audit (SQL injection, XSS, path traversal) — all clear
- Stdlib-only verification — confirmed zero external imports
- Performance analysis — noted two optimisations for production
- Wrote `readme.md`, `recommendation.md`, and this document

---

## Agent Interaction Log (Key Exchanges)

### Exchange 1: StorageAgent ↔ ArchitectAgent
**StorageAgent:** "Should `search()` return prefix matches by default or exact only?"  
**ArchitectAgent:** "Partial=True by default — better UX. Exact-only available as parameter."  
**Human:** Approved.

### Exchange 2: CrawlerAgent ↔ StorageAgent
**CrawlerAgent:** "What happens to dropped URLs — mark visited or not?"  
**ArchitectAgent (arbitrating):** "Do NOT mark visited. Dropped URLs must be recoverable in a future session."  
**Human:** Approved — this was the correct design for resumability.

### Exchange 3: QAAgent → StorageAgent (Bug Report)
**QAAgent:** "test_recent_pages_newest_first FAIL — `recent_pages()` returns rows in insertion order, not recency order."  
**StorageAgent:** Fixed — added `ORDER BY indexed_at DESC LIMIT ?`.  
**Human:** Verified fix, merged.

### Exchange 4: UIAgent → ArchitectAgent (Scope Extension)
**UIAgent:** "Proposes adding `GET /search?query=&sortBy=relevance` for direct browser/curl access."  
**Human decision:** Approved — adds significant usability for manual verification and quiz.

---

## Prompting Strategy

Each agent received a **role-specific system prompt** followed by a **task prompt** containing:
1. The exact interface contract (function signatures, data shapes)
2. Hard constraints (stdlib-only, no external libs)
3. Explicit acceptance criteria to satisfy
4. Output format (file name + structure)

This approach prevented agents from making assumptions about other components and kept each session focused and short enough to avoid context drift.

**What worked well:**
- Parallel execution of CrawlerAgent + StorageAgent (no dependencies)
- Giving QAAgent the acceptance criteria directly — it generated targeted tests
- ReviewAgent as a final gate — caught the three bugs QAAgent found

**What required human judgment:**
- Commit-per-page vs. batching (performance vs. durability trade-off)
- Same-domain default (usability vs. scope)
- Adding the `GET /search` endpoint (scope extension)
- Resolving the "drop vs. block" back-pressure decision

---

## Evaluation Against Project Criteria

| Criterion | Evidence |
|-----------|----------|
| Agents defined with clear responsibilities | 6 agents, each with `agents/*.md` spec |
| Agents assigned distinct responsibilities | No overlap: each owns one layer |
| Agent interactions documented | Exchange log above; each agent's `Interactions` section |
| Human manages and evaluates outputs | All decisions logged; 3 bugs triaged; 2 scope decisions made |
| Final system is functional | 140 tests pass; server runs; crawl + search verified |
| Scalability | WAL, bounded queue, token bucket, per-thread connections |
| Architectural sensibility | Single-machine, stdlib-only, resumable, concurrent search |
