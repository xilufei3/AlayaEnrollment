# Structured Retrieval (SQL) Design

Date: 2026-03-12  
Status: Draft (for review)

## 1. Context

Current retrieval flow is `search_planner -> retrieval -> rerank -> sufficiency_eval` under `src/agentic_rag`.

Observed gaps:
- `SearchPlan.strategy` is fixed to `vector_keyword_hybrid`.
- `retrieval` currently only performs vector search and always returns empty `structured_results`.
- There is no SQL execution path yet, so "structured retrieval" is not truly implemented.

## 2. Goals

- Add reliable structured retrieval for fact-style questions (province/year/policy timeline/major constraints).
- Keep semantic retrieval (vector/hybrid) for open-text questions.
- Support hybrid fusion of SQL + vector evidence in one answer.
- Avoid unsafe free-form SQL generation and reduce hallucinated filters.

## 3. Options

## Option A: Milvus metadata filter only
- Use Milvus `filter_expression` (`province == "Zhejiang" AND year == "2025"`).
- Pros: smallest change, no new storage dependency.
- Cons: weak relational capability (joins, aggregations, sorted business tables, analytics-style queries).

## Option B (Recommended): PostgreSQL for structured facts + Milvus for semantic retrieval
- Keep Milvus for vector/hybrid recall.
- Add PostgreSQL as structured source of truth for facts and constraints.
- Planner routes to `vector_only`, `sql_only`, or `hybrid`.
- Pros: strong SQL expressiveness, predictable filters, scalable and maintainable.
- Cons: requires schema migration and ingestion dual-write.

## Option C: All-in PostgreSQL (`pgvector` + SQL)
- Migrate both vector and structured search to PostgreSQL.
- Pros: one engine, simpler infra long-term.
- Cons: larger migration risk and performance uncertainty vs current Milvus pipeline.

Recommendation: Option B.

## 4. Recommended Architecture (Option B)

Flow:
1. `intent_classify` extracts `intent + slots` (`province`, `year`, ...).
2. `search_planner` outputs:
   - `strategy`: `vector_only | sql_only | hybrid`
   - `vector_query`
   - `structured_query` (canonical DSL, not raw SQL)
3. `structured_search_sql` compiles DSL to parameterized SQL and executes in read-only mode.
4. `retrieval` performs vector/hybrid recall (Milvus).
5. `rerank` merges SQL docs + vector docs via weighted RRF and source priors.
6. `sufficiency_eval` decides `sufficient | missing_slots | insufficient_docs`.

## 5. Data Model (PostgreSQL)

Minimal tables for first phase:

```sql
CREATE TABLE fact_admission_policy (
  id BIGSERIAL PRIMARY KEY,
  source_doc_id TEXT NOT NULL,
  source_chunk_id TEXT NOT NULL,
  province TEXT NOT NULL,
  year INT NOT NULL,
  batch TEXT,
  admission_type TEXT,
  major_group TEXT,
  score_min NUMERIC,
  rank_min INT,
  policy_text TEXT NOT NULL,
  source_url TEXT,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_policy_province_year
  ON fact_admission_policy (province, year);

CREATE INDEX idx_policy_year
  ON fact_admission_policy (year);
```

Optional generic mapping table (for traceability):

```sql
CREATE TABLE retrieval_chunk_mapping (
  chunk_id TEXT PRIMARY KEY,
  collection TEXT NOT NULL,
  source_doc_id TEXT NOT NULL,
  intent TEXT NOT NULL,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

## 6. Query Planning and SQL Safety

Do not let LLM emit raw SQL. Use a constrained DSL:

```json
{
  "domain": "admission_policy",
  "filters": { "province": "浙江", "year": 2025 },
  "select": ["policy_text", "score_min", "rank_min"],
  "sort": [{"field": "score_min", "order": "asc"}],
  "limit": 20
}
```

Compiler rules:
- allowlist columns/operators only.
- parameterized SQL only (`$1, $2...`), no string interpolation.
- hard limit row count (e.g., `limit <= 50`).
- read-only connection + statement timeout.

## 7. Fusion Strategy

Convert SQL rows to pseudo-documents:
- `page_content`: normalized textual summary from SQL row.
- `metadata`: `source=sql`, `table`, `province`, `year`, `source_doc_id`, confidence prior.

Merge with vector docs by weighted RRF:
- SQL prior weight: 1.2
- Vector prior weight: 1.0
- If user asks exact fact question with complete slots, boost SQL path.

## 8. Code Changes (Planned)

- `src/agentic_rag/schemas.py`
  - extend `SearchPlan.strategy` and add `structured_query`.
- `src/agentic_rag/node/search_planner.py`
  - produce constrained structured DSL.
- `src/agentic_rag/node/structured_search_sql.py` (new)
  - DSL -> SQL compiler + executor.
- `src/agentic_rag/graph.py`
  - include structured node and hybrid branching.
- `src/agentic_rag/node/rerank.py`
  - fuse SQL docs + vector docs.
- `src/runtime/graph_runtime.py` / startup wiring
  - inject SQL client/pool.

## 9. Rollout Plan

Phase 1 (MVP):
- Admission policy domain only (`province`, `year`).
- Add one SQL table + one structured node + fusion.

Phase 2:
- Add major/training structured facts.
- Add aggregation queries (counts, ranges, latest policy by year).

Phase 3:
- Planner quality tuning + offline eval set.
- Query cache and latency optimization.

## 10. Acceptance Criteria

- For fact questions with complete slots, top answer includes SQL-backed evidence.
- `missing_slots` prompts are triggered correctly when key filters are absent.
- Structured query execution has zero SQL-injection risk (compiler + parameterization).
- P95 added latency from SQL path <= 150ms in internal environment.
- Trace logs include: chosen strategy, DSL, SQL latency, returned row count.

## 11. Open Decisions

- Database choice confirmation: PostgreSQL assumed.
- Ingestion mode: ETL dual-write directly to SQL vs async sync job from Milvus metadata.
- Priority domains after `admission_policy`: `major_and_training` or `campus_life`.
