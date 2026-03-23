from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from sqlalchemy import text

from ..config.settings import config
from .sql_manager import SQLManager

logger = logging.getLogger(__name__)

VECTOR_CATEGORIES: tuple[str, ...] = config.ingest.vector.categories


def warmup() -> None:
    logger.info("knowledge warmup started")

    from .system_db import SystemDB
    from .vector_manager import VectorManager

    vm = VectorManager()
    vm.ensure_collection()
    SQLManager()
    SystemDB()

    _probe_milvus()
    _probe_sqlite()
    _probe_embedder()

    logger.info("knowledge warmup finished")


def _probe_milvus() -> None:
    try:
        from .vector_manager import VectorManager

        VectorManager().search("health", top_k=1)
        logger.info("milvus is reachable")
    except Exception as exc:
        logger.warning("milvus probe failed: %s", exc)


def _probe_sqlite() -> None:
    try:
        for db_id, engine in SQLManager()._engines.items():
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            logger.info("sqlite is reachable: %s", db_id)
    except Exception as exc:
        logger.warning("sqlite probe failed: %s", exc)


def _probe_embedder() -> None:
    try:
        from .embedder import get_embedder

        vector = get_embedder().embed("health")
        if not vector:
            raise ValueError("empty embedding result")
        logger.info("embedder is reachable: provider=%s", config.embedding.provider_name)
    except Exception as exc:
        logger.warning("embedder probe failed: %s", exc)


def health_check() -> dict:
    from .embedder import get_embedder
    from .vector_manager import VectorManager
    from sqlalchemy import text

    status: dict[str, object] = {
        "milvus": False,
        "embedder": False,
        "embedding_provider": config.embedding.provider_name,
        "sqlite": {},
    }

    try:
        VectorManager().search("health", top_k=1)
        status["milvus"] = True
    except Exception as exc:
        status["milvus_error"] = str(exc)

    try:
        vector = get_embedder().embed("health")
        status["embedder"] = bool(vector)
        status["embedder_dim"] = len(vector)
    except Exception as exc:
        status["embedder_error"] = str(exc)

    try:
        sm = SQLManager()
        for db_id, engine in sm._engines.items():
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            status["sqlite"][db_id] = True
    except Exception as exc:
        status["sqlite_error"] = str(exc)

    return status


def ingest_vector(
    file_path: str,
    category: str | None = None,
    chunk_size: int = config.ingest.vector.chunk_size,
    chunk_overlap: int = config.ingest.vector.chunk_overlap,
    *,
    flush: bool = True,
) -> int:
    """Ingest a file into the vector store. Returns number of chunks inserted."""
    from .alaya_etl import AlayaETL
    from .vector_manager import VectorManager

    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"file not found: {file_path}")

    etl = AlayaETL()
    chunks = etl.process_file(path, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    logger.info("etl finished with %d chunks", len(chunks))

    for chunk in chunks:
        metadata = chunk.setdefault("metadata", {})
        metadata["source_file"] = path.name
        if category:
            metadata["category"] = category

    vm = VectorManager()
    vm.ensure_collection()
    inserted = vm.insert_chunks(chunks, flush=flush)
    logger.info("vector ingest finished: %d chunks", inserted)
    return inserted


def validate_sql_registry() -> dict[str, dict]:
    return SQLManager().validate_registered_tables()


def run_query_admission_scores(
    province: str | None = None,
    year: int | str | None = None,
    limit: int = 20,
) -> list[dict]:
    from .sql_queries import query_admission_scores

    provinces = [province] if province else []
    years = [year] if year is not None else []
    return query_admission_scores(provinces=provinces, years=years, limit=limit)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    def parse_category(value: str) -> str | None:
        normalized = value.strip()
        if not normalized:
            return None
        if normalized not in VECTOR_CATEGORIES:
            choices = ", ".join(VECTOR_CATEGORIES)
            raise argparse.ArgumentTypeError(f"category must be one of: {choices}")
        return normalized

    parser = argparse.ArgumentParser(description="knowledge management tools")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("warmup", help="warm up shared dependencies")

    p_vec = sub.add_parser("ingest-vector", help="ingest vector documents")
    p_vec.add_argument("--file", required=True)
    p_vec.add_argument("--category", type=parse_category)
    p_vec.add_argument("--chunk-size", type=int, default=config.ingest.vector.chunk_size)
    p_vec.add_argument("--chunk-overlap", type=int, default=config.ingest.vector.chunk_overlap)

    sub.add_parser("health", help="run dependency health checks")
    sub.add_parser("validate-sql", help="validate registered SQL tables")

    p_query = sub.add_parser(
        "query-admission-scores",
        help="run the handwritten admission_scores query",
    )
    p_query.add_argument("--province")
    p_query.add_argument("--year", type=int)
    p_query.add_argument("--limit", type=int, default=20)

    args = parser.parse_args()

    if args.cmd == "warmup":
        warmup()
    elif args.cmd == "ingest-vector":
        ingest_vector(args.file, args.category, args.chunk_size, args.chunk_overlap)
    elif args.cmd == "health":
        print(json.dumps(health_check(), ensure_ascii=False, indent=2))
    elif args.cmd == "validate-sql":
        print(json.dumps(validate_sql_registry(), ensure_ascii=False, indent=2))
    elif args.cmd == "query-admission-scores":
        rows = run_query_admission_scores(
            province=args.province,
            year=args.year,
            limit=args.limit,
        )
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
