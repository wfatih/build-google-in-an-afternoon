# Mini-Google Quiz 1 — Answers

---

## Question 1 — Raw Storage File

**File:** `data/storage/p.data`

The file is generated from the SQLite database (`data/mini_google.db`) by calling:

```
GET http://localhost:3600/api/export
```

**Format** (one entry per line, space-separated):

```
word  url  origin  depth  frequency
```

**Statistics at time of submission:**
- Total indexed pages  : 708
- Total unique words   : 86,571
- Total p.data entries : 470,579

---

## Question 2 — Chosen Word

**Word:** `python`

This word appears on **246 different URLs** in the index.  The crawl was
seeded from `https://en.wikipedia.org/wiki/Python_(programming_language)`,
so "python" is the single most content-rich term in the index.

---

## Question 3 — Three Entries Copied from p.data

> Format: `word  url  origin  depth  frequency`

**Entry 1:**
```
python https://en.wikipedia.org/wiki/Python_(programming_language) https://en.wikipedia.org/wiki/Python_(programming_language) 0 542
```

**Entry 2:**
```
python https://en.wikipedia.org/wiki/History_of_Python https://en.wikipedia.org/wiki/Python_(programming_language) 1 234
```

**Entry 3:**
```
python https://en.wikipedia.org/wiki/List_of_Python_software https://en.wikipedia.org/wiki/Python_(programming_language) 1 187
```

---

## Question 4 — API Search

```
GET http://localhost:3600/search?query=python&sortBy=relevance
```

**Response (top 5):**
```json
{
  "query": "python",
  "total": 246,
  "results": [
    { "url": "https://en.wikipedia.org/wiki/Python_(programming_language)",         "depth": 0, "relevance_score": 6420 },
    { "url": "https://en.wikipedia.org/wiki/History_of_Python",                    "depth": 1, "relevance_score": 3335 },
    { "url": "https://en.wikipedia.org/wiki/List_of_Python_software",              "depth": 1, "relevance_score": 2865 },
    { "url": "https://en.wikipedia.org/wiki/Python_syntax_and_semantics",          "depth": 1, "relevance_score": 2845 },
    { "url": "https://en.wikipedia.org/wiki/Outline_of_the_Python_programming_language", "depth": 1, "relevance_score": 2195 }
  ]
}
```

---

## Question 5 — #1 Result

| Field               | Value |
|---------------------|-------|
| **URL**             | `https://en.wikipedia.org/wiki/Python_(programming_language)` |
| **relevance_score** | **6420** |

---

## Question 6 — Manual Score Calculation

**Formula:** `score = (frequency × 10) + 1000 − (depth × 5)`

The `+1000` bonus applies only for **exact matches** (indexed word = query token).

| Entry | frequency | depth | Calculation | Score |
|-------|-----------|-------|-------------|-------|
| **1** | 542 | 0 | (542 × 10) + 1000 − (0 × 5) = 5420 + 1000 − 0 | **6420** |
| **2** | 234 | 1 | (234 × 10) + 1000 − (1 × 5) = 2340 + 1000 − 5 | **3335** |
| **3** | 187 | 1 | (187 × 10) + 1000 − (1 × 5) = 1870 + 1000 − 5 | **2865** |

**Highest manually calculated score: Entry 1 = 6420**

---

## Question 7 — Does the Highest Score Match the API's #1 Result?

**Yes.**

| | Manual | API |
|---|---|---|
| **#1 URL** | `…/Python_(programming_language)` | `…/Python_(programming_language)` |
| **Score** | **6420** | **6420** |

Both the URL and the exact numeric score match perfectly.

The API endpoint `GET /search?query=<word>&sortBy=relevance` uses the same
formula implemented in SQL:

```sql
SELECT url, origin, depth,
       SUM( (frequency * 10) + 1000 - (depth * 5) ) AS score
FROM word_index
WHERE word IN ('python')
GROUP BY url
ORDER BY score DESC
```

---

## Question 8 — Chain-of-Thought Enhancement

### Current Approach: Single-Stage Lookup

The current search pipeline is a **one-shot SQL query**:

1. Tokenise the query string into lowercase alphabetic tokens
2. Run a single SQL `SELECT` on the `word_index` table
3. Score each URL as `SUM( (freq×10) + 1000 − (depth×5) )` and sort descending
4. Return the paginated result list

This is fast and correct but it treats every query identically — it has no
understanding of **intent**, **context beyond word frequency**, or **document
quality signals** like link authority or title prominence.

---

### Chain-of-Thought (CoT) Enhancement

A Chain-of-Thought approach breaks the search into a series of **explicit
reasoning steps**, each refining the previous result before returning it
to the user.  Below is the full pipeline:

```
User query
    │
    ▼
Step 1 — QUERY UNDERSTANDING
   • Normalise and spell-check the query
   • Detect named entities (e.g. "Python" → programming language, not the snake)
   • Expand synonyms / abbreviations (e.g. "ML" → also search "machine learning")
   • Detect query type: navigational (find a specific site) vs. informational
    │
    ▼
Step 2 — CANDIDATE RETRIEVAL   ← current system lives here
   • Execute the inverted-index SQL to retrieve the top-N candidate URLs
   • Apply formula: score = (freq×10) + 1000 − (depth×5) per exact match
    │
    ▼
Step 3 — DOCUMENT ENRICHMENT
   • For each candidate, fetch additional signals from the database:
     - Title / H1 heading match  (+500 bonus if title contains query token)
     - Inbound link count: how many other indexed pages link to this URL
     - Recency: indexed_at timestamp (newer pages get a small freshness boost)
     - Domain authority: origin pages (depth=0) treated as anchor documents
    │
    ▼
Step 4 — CONTEXTUAL RE-RANKING
   • Combine base score with enrichment signals:
     final_score = base_score
                 + (title_match  × 500)
                 + (inbound_links × 20)
                 + (1 / (days_since_indexed + 1) × 50)
   • Re-sort all candidates by final_score descending
    │
    ▼
Step 5 — DIVERSITY FILTER
   • If the top-10 results are dominated by a single origin domain,
     inject the highest-scoring result from each other available domain
     to ensure breadth across sources
    │
    ▼
Step 6 — EXPLANATION GENERATION
   • For each returned URL, attach a human-readable reason string, e.g.:
     "Ranked #1: 'python' appears 542 times (exact match), depth=0 (seed
      page of the crawl), highest inbound link count among 246 matches."
    │
    ▼
Final ranked results + per-result explanations
```

---

### Worked Example for Query `"python"`

| Step | What Happens | Result |
|------|-------------|--------|
| **1. Query Understanding** | "python" is a single unambiguous token; crawl origin is a Python (language) Wikipedia article, so language sense is confirmed | Token: `python`, type: informational |
| **2. Candidate Retrieval** | SQL returns 246 URLs; top URL has base score 6420 (freq=542, depth=0) | 246 candidates |
| **3. Enrichment** | Main Python article title is "Python (programming language)" — contains the query → title bonus +500; it is the origin page (depth=0) and has the most inbound links | Enriched score: 6420 + 500 + (links × 20) |
| **4. Re-ranking** | Title bonus and link authority widen the gap over #2 (History_of_Python, which scores 3335 base + smaller bonuses) | Same #1, stronger confidence |
| **5. Diversity** | All top results are from `en.wikipedia.org`; the filter injects the top result from any other domain if available | No change for this index |
| **6. Explanation** | `"#1: 'python' appears 542 times (exact, highest frequency), depth=0 (crawl root), title contains query, most inbound links"` | Explanation returned with result |

---

### Why CoT Improves Search Quality

| Dimension | Single-Stage (current) | Chain-of-Thought |
|-----------|----------------------|------------------|
| Synonym / abbreviation handling | ✗ | ✓ Step 1 expands query |
| Title / heading signals | ✗ | ✓ Step 3 enriches |
| Link authority (PageRank-like) | ✗ | ✓ Step 3 counts inbound links |
| Freshness | ✗ | ✓ Step 3 uses `indexed_at` |
| Result diversity | ✗ | ✓ Step 5 cross-origin injection |
| Explainability | ✗ | ✓ Step 6 per-result reasoning |
| Computational cost | Very low (1 SQL query) | Moderate (multi-step, but all steps cacheable) |

The Chain-of-Thought approach mirrors how production search engines work:
a fast, broad **retrieval** stage is followed by multiple **re-ranking**
passes that apply progressively richer signals, surfacing the most relevant
and trustworthy results rather than just the most frequent ones.
