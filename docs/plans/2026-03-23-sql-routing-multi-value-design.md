# SQL Routing And Multi-Value Query Planning Design

**Date:** 2026-03-23

**Status:** Approved design

## Goal

Refine the admissions RAG SQL branch so that:

- `search_planner` can see registered SQL table capabilities from `src/config/table_registry.yaml`
- SQL is enabled only for data-style questions that actually match a registered table
- a new `sql_plan_builder` node converts the selected table metadata into a lightweight query-key plan
- the plan supports multiple provinces and multiple years without turning the system into generic text-to-SQL

## Current Problems

The current SQL branch is too broad.

- `src/graph/agentic_rag/node/search_planner.py` enables SQL for every `admission_policy` intent
- `src/graph/agentic_rag/node/sql_query.py` immediately calls `query_admission_scores(...)`
- rule questions such as “631 是什么意思” or “综评规则是什么” can be polluted by `admission_scores` rows
- the planner LLM cannot currently see SQL table metadata, so it cannot distinguish “rule explanation” from “score table lookup” using registered table capabilities
- the current SQL helper only supports a single `province` and a single `year`

## Scope

This design intentionally stays small.

### In Scope

- expose SQL table capability summaries to `search_planner`
- let `search_planner` decide whether SQL should run, and which table or tables are candidates
- add `sql_plan_builder` between planner and executor
- support multi-value query keys for:
  - `province`
  - `year`
- treat vague time expressions such as “近几年” or omitted years as “no explicit year filter”

### Out Of Scope

- raw SQL generation by the LLM
- generic text-to-SQL
- aggregation, joins, group by, ranking DSL, or arbitrary operators
- exposing table registry metadata to generation or sufficiency-eval nodes
- changing the global `slots` contract used by intent classification

## Proposed Architecture

### 1. `search_planner` becomes metadata-aware

`search_planner` should load SQL table summaries from `table_registry.yaml` through `SQLManager`, then include a compact summary in the planner prompt.

For each registered table, the summary should include:

- table name
- description
- `use_when`
- `query_key`
- `columns`

The planner output should no longer directly contain a final execution plan. Instead, it should produce:

- the existing `search_plan`
- a lightweight `sql_candidate`

Suggested contract:

```json
{
  "enabled": true,
  "selected_tables": ["admission_scores"],
  "reason": "问题在查询录取分数或位次数据"
}
```

For rule questions, the planner should return:

```json
{
  "enabled": false,
  "selected_tables": [],
  "reason": "问题是规则解释，不对应分数表"
}
```

This keeps routing responsibility in one place: the planner decides whether SQL should run at all.

### 2. Add a dedicated `sql_plan_builder` node

Insert a new node after `search_planner` and before `sql_query`.

Responsibilities:

- read `query`, `intent`, simple `slots`, and the selected SQL tables
- look only at the chosen table metadata, not the whole registry
- extract only fixed query-key values, not arbitrary SQL clauses

For the current scope, the plan builder only needs to produce multi-value key lists.

Suggested contract:

```json
{
  "enabled": true,
  "table_plans": [
    {
      "table": "admission_scores",
      "key_values": {
        "province": ["广东", "浙江"],
        "year": ["2022", "2023", "2024"]
      },
      "reason": "用户在比较多个省份多个年份的录取情况"
    }
  ],
  "limit": 6
}
```

Interpretation rules:

- a single province still uses a one-element list
- a single year still uses a one-element list
- multiple explicit provinces use a multi-element list
- multiple explicit years use a multi-element list
- “近几年”, “历年”, or omitted year means `year: []`
- omitted province means `province: []`

This keeps the representation simple:

- list present with values = explicit filter
- empty list = no explicit filter

No `eq`, `in`, `between`, or raw SQL text is needed in the first version.

### 3. Keep SQL execution deterministic

`sql_query` should continue to be a deterministic node. It should not ask the model to write SQL.

Instead, it should:

- read the finalized `sql_plan`
- dispatch each `table_plan` to a whitelisted query helper
- normalize returned rows into `structured_results` and `structured_chunks`

For `admission_scores`, the executor should call a widened helper such as:

```python
query_admission_scores(
    provinces=["广东", "浙江"],
    years=["2022", "2023", "2024"],
    limit=6,
)
```

When a key list is empty, the helper should skip that filter.

### 4. Extend the query helper for list filters

`src/knowledge/sql_queries.py` should be upgraded from single-value arguments to list-aware arguments.

Recommended signature:

```python
def query_admission_scores(
    *,
    provinces: list[str] | None = None,
    years: list[int | str] | None = None,
    limit: int = 20,
) -> list[dict]:
```

Execution behavior:

- `provinces=None` or `[]` means no province filter
- `years=None` or `[]` means no year filter
- non-empty lists compile into deterministic `IN (...)` predicates using parameter binding

This is sufficient for:

- one province + one year
- multiple provinces + one year
- one province + multiple years
- multiple provinces + multiple years
- omitted province and/or omitted year

## State Changes

The RAG state should distinguish routing intent from executable SQL plan.

Recommended additions:

```python
class SQLCandidate(TypedDict, total=False):
    enabled: bool
    selected_tables: list[str]
    reason: str

class TablePlan(TypedDict, total=False):
    table: str
    key_values: dict[str, list[str]]
    reason: str

class SQLPlan(TypedDict, total=False):
    enabled: bool
    table_plans: list[TablePlan]
    limit: int
    reason: str
```

Why split them:

- `sql_candidate` belongs to routing
- `sql_plan` belongs to execution

This avoids overloading one structure with two different responsibilities.

## Graph Changes

Current subgraph:

`search_planner -> retrieval/sql_query -> merge_context -> rerank -> eval`

Proposed subgraph:

`search_planner -> retrieval/sql_plan_builder`

`sql_plan_builder -> sql_query`

`retrieval/sql_query -> merge_context -> rerank -> eval`

This preserves the current parallel retrieval + structured lookup pattern while separating SQL routing from SQL planning.

## Prompting Strategy

### Planner prompt

The planner prompt should receive:

- `query`
- `intent`
- `slots`
- `iteration`
- `eval_reason`
- previous `chunks` text when available
- SQL table capability summary generated from `table_registry.yaml`

The prompt should explicitly instruct:

- only enable SQL when the question matches a registered table’s `use_when`
- rule interpretation questions should keep SQL disabled
- output only `rewritten_query`, `reason`, and the SQL candidate payload

### SQL plan builder prompt

The plan builder prompt should receive:

- original user query
- intent
- simple slots
- selected table metadata only

The prompt should explicitly instruct:

- extract only registered query keys
- each key maps to a list of values
- when the user does not specify a key, output an empty list
- do not invent keys not present in the table metadata
- do not generate SQL text

## Retry / Eval Loop Impact

The eval loop still retries the RAG subgraph on `insufficient_docs`.

This design improves behavior because:

- rule questions should stop enabling SQL at the planner stage
- data questions can still retry retrieval while preserving structured lookup behavior

Deliberately deferred:

- skipping repeated identical SQL plans across retries

That can be added later if repeated SQL calls become a performance concern, but it is not required for the first version.

## Testing Strategy

### Planner tests

Add or update tests to verify:

- planner prompt includes SQL registry context
- rule-style `admission_policy` questions disable SQL
- score-style questions select `admission_scores`

### Plan-builder tests

Add tests to verify:

- single province + single year -> one-element lists
- multiple provinces -> multi-value `province`
- multiple years -> multi-value `year`
- “近几年” or omitted year -> empty `year` list

### Executor tests

Add tests to verify:

- `sql_query` calls the helper with province and year lists
- empty lists do not apply filters
- structured results still become `Document` rows for downstream nodes

### Query helper tests

Add tests to verify:

- list-aware SQL filter compilation works for provinces
- list-aware SQL filter compilation works for years
- empty list means no filter

## Migration Notes

- `table_registry.yaml` already contains enough metadata for the first version
- no registry schema change is required to start
- future tables can follow the same pattern if they declare `description`, `use_when`, `query_key`, and `columns`

## Recommendation

Proceed with the minimal version first:

- metadata-aware `search_planner`
- new `sql_plan_builder`
- multi-value `province` and `year` support in deterministic execution

This resolves the current “all `admission_policy` questions trigger score-table SQL” issue while keeping the system explainable and easy to extend.
