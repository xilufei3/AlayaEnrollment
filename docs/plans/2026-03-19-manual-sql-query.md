# Manual SQL Query Flow Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the heavier structured-SQL automation with a lightweight manual-table workflow where YAML describes query contracts, handwritten Python functions run handwritten SQL, and `manage.py` only supports query and validation operations.

**Architecture:** Keep SQLite tables and imported data fully manual. Simplify `table_registry.yaml` into a metadata contract that tells the upper layer which business keys to extract and which query function to call. Keep `SQLManager` as a small database-access layer and move handwritten business queries into a new `sql_queries.py` module.

**Tech Stack:** Python, SQLite, SQLAlchemy, PyYAML, pytest

---

### Task 1: Simplify Registry Metadata To Query Contracts

**Files:**
- Modify: `src/config/table_registry.yaml`
- Create: `tests/config/test_manual_sql_registry.py`

**Step 1: Write the failing test**

```python
from src.knowledge.sql_manager import SQLManager


def test_admission_scores_registry_uses_manual_query_contract():
    meta = SQLManager().get_table_meta("admission_scores")

    assert meta["physical_name"] == "admission_scores"
    assert meta["query_key"] == ["province", "year"]
    assert meta["tool_name"] == "query_admission_scores"
    assert "primary_key" not in meta
    assert "indexes" not in meta
```

**Step 2: Run test to verify it fails**

Run:

```bash
python -m pytest tests/config/test_manual_sql_registry.py -q
```

Expected:

- FAIL because the registry still uses the previous heavier schema-management shape

**Step 3: Write minimal implementation**

Update `src/config/table_registry.yaml` so `admission_scores` uses the lighter contract:

```yaml
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
    columns:
      province: "省份名称"
      year: "年份"
      max_score: "最高分原文"
```

Remove heavy schema-only fields such as `primary_key`, `unique_key`, and `indexes`.

**Step 4: Run test to verify it passes**

Run:

```bash
python -m pytest tests/config/test_manual_sql_registry.py -q
```

Expected:

- PASS

**Step 5: Commit**

```bash
git add src/config/table_registry.yaml tests/config/test_manual_sql_registry.py
git commit -m "refactor: simplify SQL registry to manual query contracts"
```

### Task 2: Slim SQLManager To Query And Lightweight Validation Only

**Files:**
- Modify: `src/knowledge/sql_manager.py`
- Replace: `tests/knowledge/test_sql_manager.py`

**Step 1: Write the failing test**

```python
import sqlite3

from src.knowledge.sql_manager import SQLManager


def test_validate_registered_tables_checks_table_and_query_key_presence(tmp_path, monkeypatch):
    # point registry to temp db
    # manually create admission_scores with province/year columns
    # reset SQLManager singleton
    sm = SQLManager()

    report = sm.validate_registered_tables()

    assert report["admission_scores"]["table_exists"] is True
    assert report["admission_scores"]["missing_query_key_columns"] == []
```

**Step 2: Run test to verify it fails**

Run:

```bash
python -m pytest tests/knowledge/test_sql_manager.py -q
```

Expected:

- FAIL because `SQLManager` still contains heavy schema-management helpers rather than the new lightweight validation contract

**Step 3: Write minimal implementation**

Refactor `src/knowledge/sql_manager.py` to keep only:

- `get_all_table_meta()`
- `get_table_meta(table_name)`
- `get_registered_table_names()`
- `get_physical_table_name(table_name)`
- `get_query_key(table_name)`
- `get_tool_name(table_name)`
- `get_engine(db_id)`
- `execute(sql, db_id="main_db", params=None)`
- `list_tables(db_id="main_db")`
- `table_exists(table_name, db_id="main_db")`
- `get_table_columns(table_name, db_id="main_db")`
- `validate_registered_tables()`

Suggested validation shape:

```python
{
    "admission_scores": {
        "table_exists": True,
        "physical_name": "admission_scores",
        "query_key": ["province", "year"],
        "missing_query_key_columns": [],
    }
}
```

Remove or stop exposing automatic DDL and ingestion-oriented helpers.

**Step 4: Run test to verify it passes**

Run:

```bash
python -m pytest tests/knowledge/test_sql_manager.py -q
```

Expected:

- PASS

**Step 5: Commit**

```bash
git add src/knowledge/sql_manager.py tests/knowledge/test_sql_manager.py
git commit -m "refactor: slim SQL manager to query operations"
```

### Task 3: Add Handwritten Query Functions

**Files:**
- Create: `src/knowledge/sql_queries.py`
- Modify: `src/knowledge/__init__.py`
- Create: `tests/knowledge/test_sql_queries.py`

**Step 1: Write the failing test**

```python
import sqlite3

from src.knowledge.sql_queries import query_admission_scores


def test_query_admission_scores_returns_full_row(tmp_path, monkeypatch):
    # point registry to temp db and manually create table
    # insert one row manually
    rows = query_admission_scores(province="安徽", year=2024)

    assert rows[0]["province"] == "安徽"
    assert rows[0]["year"] == 2024
    assert rows[0]["min_score"] == "641（生物奥赛银牌）"
```

**Step 2: Run test to verify it fails**

Run:

```bash
python -m pytest tests/knowledge/test_sql_queries.py -q
```

Expected:

- FAIL because `sql_queries.py` and `query_admission_scores(...)` do not exist yet

**Step 3: Write minimal implementation**

Create `src/knowledge/sql_queries.py` with:

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

Export the function from `src/knowledge/__init__.py`.

**Step 4: Run test to verify it passes**

Run:

```bash
python -m pytest tests/knowledge/test_sql_queries.py -q
```

Expected:

- PASS

**Step 5: Commit**

```bash
git add src/knowledge/sql_queries.py src/knowledge/__init__.py tests/knowledge/test_sql_queries.py
git commit -m "feat: add handwritten SQL query functions"
```

### Task 4: Refactor Manage To Query And Validation Only

**Files:**
- Modify: `src/knowledge/manage.py`
- Create: `tests/knowledge/test_manage_sql.py`

**Step 1: Write the failing test**

```python
from src.knowledge.manage import validate_sql_registry


def test_validate_sql_registry_reports_registered_table_status(tmp_path, monkeypatch):
    report = validate_sql_registry()

    assert "admission_scores" in report
    assert "table_exists" in report["admission_scores"]
```

**Step 2: Run test to verify it fails**

Run:

```bash
python -m pytest tests/knowledge/test_manage_sql.py -q
```

Expected:

- FAIL because `manage.py` still contains structured ingestion responsibilities instead of a query/validation-only surface

**Step 3: Write minimal implementation**

Refactor `src/knowledge/manage.py` so it keeps only query/validation concerns.

Add:

```python
def validate_sql_registry() -> dict:
    return SQLManager().validate_registered_tables()
```

Optional debug helper:

```python
def run_query_admission_scores(province: str, year: int) -> list[dict]:
    return query_admission_scores(province=province, year=year)
```

Remove or deprecate:

- `ingest_sql(...)`
- `ingest-sql` CLI subcommand
- automatic structured-data import workflow

Keep:

- `health_check()`
- SQL validation CLI
- optional debug query CLI

**Step 4: Run test to verify it passes**

Run:

```bash
python -m pytest tests/knowledge/test_manage_sql.py -q
```

Then run:

```bash
python -m pytest tests/config/test_manual_sql_registry.py tests/knowledge/test_sql_manager.py tests/knowledge/test_sql_queries.py tests/knowledge/test_manage_sql.py -q
```

Expected:

- PASS

**Step 5: Commit**

```bash
git add src/knowledge/manage.py tests/knowledge/test_manage_sql.py
git commit -m "refactor: keep manage focused on SQL query and validation"
```

### Task 5: Update Documentation For Manual DB Workflow

**Files:**
- Modify: `README.md`

**Step 1: Write the failing test**

Use a documentation checklist instead of an automated test:

- README must no longer imply automatic structured SQL import
- README must describe manual table creation and manual data import
- README must mention query validation entrypoints

**Step 2: Run the check to verify it fails**

Open `README.md` and confirm the old ingestion wording is still present.

Expected:

- FAIL because the documentation still reflects the earlier automated SQL direction

**Step 3: Write minimal implementation**

Update `README.md` to document:

- manual creation of `data/db/admissions.db`,
- manual execution of table-creation SQL,
- manual import of structured data,
- use of `table_registry.yaml` as query metadata only,
- how to run SQL validation or debug queries through `manage.py`.

**Step 4: Run the check to verify it passes**

Re-read the relevant `README.md` section and confirm all checklist items are satisfied.

Expected:

- PASS

**Step 5: Commit**

```bash
git add README.md
git commit -m "docs: describe manual SQL query workflow"
```
