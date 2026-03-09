# AlayaData Sync Ingestion Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 实现最小同步管道：调用 AlayaData ETL，标准化结果，优先复用 ETL embedding，缺失补齐后写入 Milvus，并返回标准化 DTO。

**Architecture:** 三层最小实现：`AlayaDataClient`（纯 HTTP）+ `IngestionService`（业务编排）+ `MilvusStoreService`（向量写入）；CLI 作为薄入口。所有对外返回值使用 dataclass DTO。

**Tech Stack:** Python 3.13, requests, dataclasses, pytest, packages.vector_store (Milvus), OpenAI-compatible embedding API

---

### Task 1: 定义 DTO 契约（types.py）

**Files:**
- Create: `app/services/types.py`
- Test: `tests/app/services/test_types.py`

**Step 1: Write the failing test**

```python
from app.services.types import SliceDTO

def test_slice_content_fallback_order():
    row = {"content": "B", "text": "C"}
    dto = SliceDTO.from_raw(row)
    assert dto.content_md == "B"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/app/services/test_types.py::test_slice_content_fallback_order -v`
Expected: FAIL with `ModuleNotFoundError` or `AttributeError`.

**Step 3: Write minimal implementation**

```python
@dataclass(slots=True)
class SliceDTO:
    content_md: str
    @classmethod
    def from_raw(cls, row: dict) -> "SliceDTO":
        for key in ("content_md", "content", "text", "chunk_text", "page_content"):
            value = row.get(key)
            if isinstance(value, str) and value.strip():
                return cls(content_md=value.strip())
        return cls(content_md="")
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/app/services/test_types.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add app/services/types.py tests/app/services/test_types.py
git commit -m "feat: add ingestion dto contracts"
```

### Task 2: 实现 AlayaDataClient（DTO 返回）

**Files:**
- Create: `app/services/alayadata_client.py`
- Test: `tests/app/services/test_alayadata_client.py`

**Step 1: Write the failing test**

```python
def test_create_job_returns_dto(requests_mock):
    requests_mock.post("http://etl/v1/etl/jobs", json={"job_id": "job_1", "status": "queued"})
    client = AlayaDataClient(server_url="http://etl")
    result = client.create_job(upload_ref="up_1", dataset=None, doc_id=None, chunk_size=800, chunk_overlap=120, enable_ocr=True, parser_preference=["builtin"])
    assert result.job_id == "job_1"
    assert result.status == "queued"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/app/services/test_alayadata_client.py::test_create_job_returns_dto -v`
Expected: FAIL with missing class/module.

**Step 3: Write minimal implementation**

```python
class AlayaDataClient:
    def create_job(...)->CreateJobResultDTO:
        resp = self._session.post(...)
        payload = resp.json()
        return CreateJobResultDTO(job_id=str(payload["job_id"]), status=str(payload.get("status", "queued")))
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/app/services/test_alayadata_client.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add app/services/alayadata_client.py tests/app/services/test_alayadata_client.py
git commit -m "feat: add alayadata client dto interface"
```

### Task 3: 实现 MilvusStoreService 封装

**Files:**
- Create: `app/services/milvus_store.py`
- Test: `tests/app/services/test_milvus_store.py`

**Step 1: Write the failing test**

```python
def test_upsert_batches_and_returns_total_upserted():
    store = FakeStore()
    svc = MilvusStoreService(store=store)
    total = svc.upsert("idx", items=[...], batch_size=2)
    assert total == 3
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/app/services/test_milvus_store.py::test_upsert_batches_and_returns_total_upserted -v`
Expected: FAIL with missing service.

**Step 3: Write minimal implementation**

```python
class MilvusStoreService:
    def upsert(self, index_name: str, items: list[VectorItem], batch_size: int = 64) -> int:
        total = 0
        for i in range(0, len(items), batch_size):
            result = self._store.upsert(UpsertRequest(index=index_name, items=items[i:i+batch_size]))
            total += result.upserted
        return total
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/app/services/test_milvus_store.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add app/services/milvus_store.py tests/app/services/test_milvus_store.py
git commit -m "feat: add milvus store service wrapper"
```

### Task 4: 实现 IngestionService 编排

**Files:**
- Create: `app/services/ingestion_service.py`
- Test: `tests/app/services/test_ingestion_service.py`

**Step 1: Write the failing test**

```python
def test_ingest_prefers_etl_embeddings_and_fallbacks_when_missing():
    summary = svc.ingest_file(Path("a.md"), index_name="idx")
    assert summary.used_etl_embeddings == 2
    assert summary.fallback_embedded == 1
    assert summary.status == "succeeded_with_warnings"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/app/services/test_ingestion_service.py::test_ingest_prefers_etl_embeddings_and_fallbacks_when_missing -v`
Expected: FAIL with missing logic.

**Step 3: Write minimal implementation**

```python
class IngestionService:
    def ingest_file(...)->IngestSummaryDTO:
        # ETL result -> chunks
        # embedding_vector present: reuse
        # missing: call embedding client
        # write to milvus service
        # build warnings + summary
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/app/services/test_ingestion_service.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add app/services/ingestion_service.py tests/app/services/test_ingestion_service.py
git commit -m "feat: add synchronous ingestion orchestration"
```

### Task 5: 实现 CLI 薄入口

**Files:**
- Create: `app/scripts/ingest_file.py`
- Test: `tests/app/scripts/test_ingest_file.py`

**Step 1: Write the failing test**

```python
def test_cli_parses_args_and_prints_summary(capsys, monkeypatch):
    code = main(["--file", "a.md", "--index", "idx"])
    assert code == 0
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/app/scripts/test_ingest_file.py::test_cli_parses_args_and_prints_summary -v`
Expected: FAIL with missing CLI.

**Step 3: Write minimal implementation**

```python
def main(argv=None)->int:
    args = parser.parse_args(argv)
    summary = ingestion_service.ingest_file(...)
    print(summary)
    return 0
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/app/scripts/test_ingest_file.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add app/scripts/ingest_file.py tests/app/scripts/test_ingest_file.py
git commit -m "feat: add ingestion cli entrypoint"
```

### Task 6: 全量验证与文档补充

**Files:**
- Modify: `README.md`
- Modify: `docs/plans/2026-03-08-alayadata-sync-ingestion-design.md`
- Test: `tests/app/services/test_types.py`
- Test: `tests/app/services/test_alayadata_client.py`
- Test: `tests/app/services/test_milvus_store.py`
- Test: `tests/app/services/test_ingestion_service.py`
- Test: `tests/app/scripts/test_ingest_file.py`

**Step 1: Write failing doc/test assertion (if missing command sample)**

```python
def test_readme_has_ingest_cli_example():
    assert "python -m app.scripts.ingest_file" in Path("README.md").read_text(encoding="utf-8")
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/app/scripts/test_readme_ingest_example.py -v`
Expected: FAIL without CLI usage docs.

**Step 3: Write minimal implementation**

```markdown
python -m app.scripts.ingest_file --file ./a.pdf --index admission_index --server http://100.64.0.30:6000
```

**Step 4: Run test suites**

Run: `pytest tests/app/services tests/app/scripts -v`
Expected: All PASS.

**Step 5: Commit**

```bash
git add README.md docs/plans/2026-03-08-alayadata-sync-ingestion-design.md tests/app/services tests/app/scripts app/services app/scripts
git commit -m "docs: add sync etl ingestion usage and verification"
```
