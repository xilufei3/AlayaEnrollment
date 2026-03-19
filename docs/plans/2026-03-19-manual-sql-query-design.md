# Manual SQL Query Design

## Goal

Switch the structured-data approach from registry-driven schema creation and ingestion to a lighter manual workflow:

- database tables are created manually,
- data import is done manually,
- YAML only describes tables and query contracts,
- handwritten query functions execute handwritten SQL,
- `manage.py` only exposes query and validation helpers.

This design supersedes the earlier automation-heavy structured-SQL approach for implementation scope.

## Why This Design

The previous direction added automatic table creation, registry-driven schema validation, and structured ingestion helpers. That is more infrastructure than the current use case needs.

The current use case is simpler:

- one or a few manually maintained SQLite tables,
- stable query patterns,
- a future LLM layer that extracts business query keys,
- code-controlled SQL execution.

Given that scope, the safest and lowest-maintenance design is:

- manual schema,
- manual import,
- YAML for metadata only,
- Python functions for SQL.

## Core Decisions

### 1. Do not let the LLM generate raw SQL

The LLM should produce query-key values, not SQL text.

For `admission_scores`, the LLM should generate:

```json
{
  "tool_name": "query_admission_scores",
  "arguments": {
    "province": "安徽",
    "year": 2024
  }
}
```

The SQL remains handwritten in code.

### 2. Use business query keys, not physical database IDs

Do not expose database `id` values to the model.

For `admission_scores`, the meaningful query key is:

- `province`
- `year`

This is the business key used to locate a row.

### 3. YAML becomes a query contract, not a schema engine

`src/config/table_registry.yaml` should only describe:

- which database a table belongs to,
- the physical table name,
- what the table is for,
- which business query keys the LLM should extract,
- which query function the LLM or upper layer should call,
- what columns exist for explanation and prompting.

It should not drive:

- table creation,
- migrations,
- indexes,
- column types,
- ingestion.

### 4. SQL lives in handwritten query functions

Add a dedicated query-function layer, for example:

- `src/knowledge/sql_queries.py`

Example:

```python
from .sql_manager import SQLManager


def query_admission_scores(province: str, year: int) -> list[dict]:
    sql = """
    SELECT *
    FROM admission_scores
    WHERE province = :province AND year = :year
    """
    return SQLManager().execute(
        sql,
        params={"province": province, "year": year},
    )
```

This keeps SQL explicit, auditable, and easy to debug.

### 5. `manage.py` only handles query/validation concerns

`manage.py` should no longer own structured ingestion.

It should keep only lightweight operational helpers such as:

- health checks,
- registered-table validation,
- optional debug query entrypoints.

It should not do:

- CSV ingestion,
- Excel ingestion,
- schema creation,
- schema migration.

## Proposed YAML Shape

```yaml
databases:
  main_db:
    type: sqlite
    path: "./data/db/admissions.db"

tables:
  admission_scores:
    db_id: "main_db"
    physical_name: "admission_scores"
    description: "各省各年份录取数据宽表，按 province + year 查询整行"
    query_key:
      - province
      - year
    tool_name: "query_admission_scores"
    use_when:
      - "用户查询某省某年的录取数据"
      - "用户查询最高分、平均分、最低分、位次"
      - "用户查询某省近几年录取情况"
    columns:
      province: "省份名称"
      year: "年份"
      admission_count: "总录取人数"
      regular_batch_count: "普通批次录取人数"
      joint_program_count: "联合培养录取人数"
      physics_review_count: "物理学综评人数"
      kcl_count: "KCL联合医学院人数"
      max_score: "最高分原文"
      max_rank: "最高分位次原文"
      avg_score: "平均分原文"
      avg_rank: "平均分位次原文"
      min_score: "最低分原文"
      min_rank: "最低分位次原文"
      note: "备注"
```

## Proposed Code Responsibilities

### `src/config/table_registry.yaml`

Owns:

- database ID mapping,
- physical table names,
- descriptions,
- `query_key`,
- `tool_name`,
- column descriptions.

Does not own:

- DDL,
- schema enforcement,
- SQL templates,
- ingestion config.

### `src/knowledge/sql_manager.py`

Owns:

- loading YAML metadata,
- opening database connections,
- executing parameterized SQL,
- basic metadata access,
- lightweight validation that registered physical tables and query-key columns exist.

Does not own:

- handwritten business queries,
- LLM routing,
- schema creation,
- ingestion.

### `src/knowledge/sql_queries.py`

Owns:

- handwritten query functions per table,
- stable SQL text,
- optional lightweight dispatcher by `tool_name`.

### `src/knowledge/manage.py`

Owns:

- health check,
- SQL registry validation,
- optional debug query command.

Does not own:

- import workflows,
- schema creation,
- auto-generated SQL.

## Validation Scope

Validation should be intentionally lightweight.

Good enough for this phase:

- confirm registered databases can connect,
- confirm registered physical tables exist,
- confirm all `query_key` columns exist on those tables.

Do not rebuild the previous heavy registry-vs-schema engine unless requirements grow.

## Query Flow

1. The upper layer reads table metadata from YAML.
2. The upper layer gives the model the table description, `query_key`, and `tool_name`.
3. The model returns a tool call with query-key values.
4. The application calls the corresponding Python query function.
5. The query function executes handwritten SQL through `SQLManager`.
6. The full row is returned.

## Non-Goals

Out of scope for this design:

- automatic table creation,
- automatic index creation,
- automatic CSV/Excel import,
- letting the model generate SQL,
- registry-driven migration management.

## Risks And Mitigations

### Risk: metadata drifts from the manually managed database

Mitigation:

- keep validation lightweight but explicit,
- document the manual schema,
- run `manage.py` validation after manual changes.

### Risk: adding more tables increases handwritten query code

Mitigation:

- accept this tradeoff for now,
- each table gets one small query function,
- revisit abstraction only when multiple tables prove the pattern repetitive.

### Risk: future teams reintroduce dynamic SQL too early

Mitigation:

- keep SQL in explicit query functions,
- keep the LLM contract limited to `tool_name + query_key values`.
