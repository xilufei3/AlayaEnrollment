# SQLite Structured Retrieval Design

Date: 2026-03-13
Status: Approved for planning

## 1. Context

Current retrieval flow is:

`intent_classify -> search_planner -> retrieval -> rerank -> sufficiency_eval -> generate`

under `src/agentic_rag`.

Current constraints and decisions:

- Vector or hybrid semantic retrieval remains mandatory for every eligible retrieval turn.
- Structured retrieval is supplemental evidence, not a replacement path.
- Structured data volume is small, so SQLite is sufficient for the first implementation.
- The design must support a future management API for imports and operational visibility.

## 2. Goals

- Keep the existing vector retrieval path as the primary retrieval mechanism.
- Add optional SQLite-backed structured retrieval for fact-like questions.
- Support both exact lookup and simple filtering/sorting for table-like data.
- Keep the query interface stable even when different domains use different table schemas.
- Design import and query interfaces that can later be exposed as admin APIs.

## 3. Non-Goals

- Replacing Milvus or semantic retrieval with SQL-only retrieval.
- Letting the LLM emit raw executable SQL as the primary production path.
- Building a generic BI or analytics layer.
- Supporting arbitrary joins and unrestricted aggregation in phase 1.

## 4. Recommended Architecture

The final retrieval flow becomes:

`intent_classify -> search_planner -> retrieval -> structured_search(optional) -> rerank/fuse -> sufficiency_eval -> generate`

Behavior:

- `retrieval` always runs for retrieval-eligible questions.
- `structured_search` runs only when the planner decides structured evidence is likely useful.
- If structured search returns no rows, the pipeline continues with semantic evidence only.
- SQL-backed rows are converted into pseudo-documents so downstream nodes can remain mostly unchanged.

This keeps the current agent shape intact while allowing structured evidence to improve fact precision.

## 5. Query Responsibility

Raw SQL should not be produced directly by the LLM in the main implementation.

Instead, responsibilities are split:

- The LLM or planner may produce query intent.
- The backend validates that intent against domain rules.
- A compiler generates parameterized SQLite SQL.
- The repository executes the SQL and returns rows.

Target flow:

`user question -> slots/query intent -> structured query request -> domain registry -> SQL compiler -> sqlite execute`

## 6. Why Not LLM-Generated Raw SQL

Putting schema in the prompt and asking the model to produce SQL is acceptable only as a prototype shortcut.

It is not the recommended production design because it is weak on:

- stability across schema changes
- safety and allowlisting
- observability and deterministic replay
- testability
- handling many domains with heterogeneous tables

For this project, the better long-term design is:

- prompt/schema can help the model understand what to query
- the model outputs constrained query intent
- the backend generates the final SQL

## 7. Structured Query Model

The core internal query contract should be source-agnostic and API-friendly.

```python
class StructuredSearchRequest(TypedDict, total=False):
    domain: str
    filters: dict[str, Any]
    select: list[str]
    sort: list[dict[str, str]]
    limit: int
```

Example:

```json
{
  "domain": "admission_policy",
  "filters": {
    "province": "浙江",
    "year": 2025,
    "admission_type": "综合评价"
  },
  "select": ["score_min", "rank_min", "source_ref"],
  "sort": [{"field": "score_min", "order": "asc"}],
  "limit": 10
}
```

This request is the contract between planner-level intent and the SQLite execution layer.

## 8. Domain Registry

Different domains may have different physical tables or column names. That difference should be hidden behind a registry.

Each domain definition should include:

- target table
- allowed filter fields
- allowed sort fields
- allowed select fields
- field name mapping from semantic field to physical column
- default select fields
- formatter metadata for turning rows into pseudo-documents

Example shape:

```python
DOMAIN_REGISTRY = {
    "admission_policy": {
        "table": "admission_policy_records",
        "filterable_fields": {
            "province": "province",
            "year": "year",
            "admission_type": "admission_type",
            "batch": "batch",
        },
        "sortable_fields": {
            "year": "year",
            "score_min": "score_min",
            "rank_min": "rank_min",
        },
        "selectable_fields": {
            "province": "province",
            "year": "year",
            "score_min": "score_min",
            "rank_min": "rank_min",
            "policy_text": "policy_text",
            "source_ref": "source_ref",
        },
        "default_select": [
            "province",
            "year",
            "admission_type",
            "score_min",
            "rank_min",
            "source_ref",
        ],
    }
}
```

This registry is how the system handles heterogeneous table schemas without exposing that complexity upstream.

## 9. SQL Compiler Rules

The SQL compiler owns final SQL generation.

Rules:

- `domain` must exist in the registry.
- `filters`, `select`, and `sort` fields must be allowlisted.
- only parameterized SQL is allowed
- only `SELECT` queries are generated
- enforce a hard `LIMIT`
- phase 1 supports simple equality filters plus ordered result sets

Example compiled SQL:

```sql
SELECT score_min, rank_min, source_ref
FROM admission_policy_records
WHERE province = ? AND year = ? AND admission_type = ?
ORDER BY score_min ASC
LIMIT ?
```

Params:

```python
["浙江", 2025, "综合评价", 10]
```

## 10. Query Execution Service

Recommended internal boundary:

```python
class StructuredSearchService(Protocol):
    def search(self, req: StructuredSearchRequest) -> list[StructuredRow]: ...
```

And a normalized row model:

```python
class StructuredRow(TypedDict, total=False):
    row_id: str
    content: str
    metadata: dict[str, Any]
```

Implementation responsibilities:

- validate request
- compile SQL
- execute SQLite query
- normalize rows
- convert rows to pseudo-documents for downstream fusion

## 11. Import Model

Import should not be source-driven such as `import_excel(path)` as the core contract.

Instead, source-specific adapters should produce a normalized import request:

```python
class StructuredImportRow(TypedDict, total=False):
    record_id: str
    domain: str
    data: dict[str, Any]
    source: dict[str, Any]

class StructuredImportRequest(TypedDict, total=False):
    domain: str
    schema_version: str
    mode: Literal["append", "replace", "upsert"]
    rows: list[StructuredImportRow]
    idempotency_key: str
```

Core service:

```python
class StructuredImportService(Protocol):
    def preview(self, req: StructuredImportRequest) -> dict[str, Any]: ...
    def execute(self, req: StructuredImportRequest) -> StructuredImportResult: ...
```

This lets file adapters, future upload APIs, and batch jobs all reuse the same import service.

## 12. SQLite Table Strategy

SQLite should contain both management tables and domain fact tables.

Management tables:

- `structured_import_jobs`
- `structured_import_job_items`

Purpose:

- track import status
- support preview and execute flows
- expose operational state in future admin APIs
- preserve row-level validation failures

Fact tables:

- phase 1 should start with `admission_policy_records`
- future domains can add separate fact tables rather than one generic mega-table

Required common audit fields per fact table:

- `record_id`
- `source_type`
- `source_ref`
- `schema_version`
- `import_job_id`
- `created_at`
- `updated_at`

Suggested phase-1 fact table fields for `admission_policy_records`:

- `record_id`
- `province`
- `year`
- `admission_type`
- `batch`
- `score_min`
- `rank_min`
- `policy_text`
- `source_type`
- `source_ref`
- `schema_version`
- `import_job_id`
- `created_at`
- `updated_at`

## 13. Integration with Agentic RAG

Required graph-level changes:

- extend `SearchPlan` with optional structured query fields and a boolean or signal indicating whether structured search should run
- add a `structured_search` node after `retrieval`
- update rerank or fusion logic to merge SQLite-derived pseudo-documents with vector documents

Important invariant:

- semantic retrieval is still required
- structured retrieval only adds evidence and never removes the primary retrieval step

## 14. Result Formatting

Structured rows should be turned into pseudo-documents before fusion.

Example content:

`2025年浙江省综合评价招生最低录取分为 XXX，最低位次为 XXX，来源：2025 年招生简章。`

Recommended metadata:

- `source = "sqlite"`
- `domain`
- `table`
- `record_id`
- `province`
- `year`
- `source_ref`

This keeps downstream handling consistent with the existing document-based pipeline.

## 15. Future Admin API Shape

The design should be compatible with endpoints such as:

- `POST /admin/structured-imports/preview`
- `POST /admin/structured-imports`
- `GET /admin/structured-imports/{import_id}`
- `POST /admin/structured-queries/preview`

This is one reason import and query contracts should be request/response based rather than file-path based.

## 16. Rollout Plan

Phase 1:

- add SQLite storage and repository layer
- implement import management tables
- implement `admission_policy_records`
- add structured query request/registry/compiler/repository
- add optional `structured_search` node
- fuse SQLite rows into downstream chunks

Phase 2:

- add more domains
- add richer filters and result formatting
- add admin API endpoints

Phase 3:

- add offline evals for structured retrieval usefulness
- decide whether prompt-assisted query intent is needed beyond rules/slots

## 17. Open Decisions

- whether phase-1 query intent should be rule-based only or allow LLM-generated constrained requests
- whether `replace` mode should be table-wide or domain-partition scoped
- whether preview should persist a draft import job or stay fully ephemeral

## 18. Final Recommendation

Use SQLite as a small structured fact store that supplements, but never replaces, semantic retrieval.

Do not let the LLM write raw SQL in the production path.

Use:

- normalized import requests
- domain-specific fact tables
- a domain registry
- a SQL compiler that generates parameterized SQLite queries

This gives the project a stable path from prototype to production without overbuilding.
