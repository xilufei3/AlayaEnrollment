"""
manage.py
─────────
知识库管理，对外提供：
  warmup()       应用启动时预热单例（FastAPI lifespan 调用）
  health_check() 连通性检查（监控接口调用）
  ingest_vector() 文件 → ETL → Milvus（运维/后台页面调用）
  ingest_sql()    CSV/Excel → SQLite（运维/后台页面调用）

CLI 用法：
  python -m knowledge.manage warmup
  python -m knowledge.manage ingest-vector --file ./data/school_info.pdf --category school_info
  python -m knowledge.manage ingest-sql    --file ./data/scores.csv --table admission_scores
  python -m knowledge.manage health
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .sql_manager import SQLManager
from .system_db import SystemDB
from .vector_manager import VectorManager

logger = logging.getLogger(__name__)

VECTOR_CATEGORIES: tuple[str, ...] = (
    "school_info",
    "admissions",
    "major",
    "career",
    "campus",
)


# ════════════════════════════════════════════════════════════
# 预热：FastAPI lifespan 的 startup 阶段调用
# ════════════════════════════════════════════════════════════

def warmup() -> None:
    logger.info("知识库预热开始 ...")

    vm = VectorManager()
    vm.ensure_collection()      # ← 新增：建表（已存在则跳过）
    SQLManager()
    SystemDB()

    _probe_milvus()
    _probe_sqlite()
    _probe_embedder()

    logger.info("知识库预热完成")


def _probe_milvus() -> None:
    try:
        from .vector_manager import VectorManager
        VectorManager().search("连通测试", top_k=1)     # ← 改为新的统一入口
        logger.info("✅ Milvus 连通正常")
    except Exception as e:
        logger.warning("⚠️  Milvus 连通异常：%s", e)

def _probe_sqlite() -> None:
    try:
        from .sql_manager import SQLManager
        from sqlalchemy import text
        sm = SQLManager()
        for db_id, engine in sm._engines.items():
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        logger.info("✅ SQLite 连通正常")
    except Exception as e:
        logger.warning("⚠️  SQLite 连通异常：%s", e)


def _probe_embedder() -> None:
    try:
        from .alaya_embedder import AlayaEmbedder
        vec = AlayaEmbedder().embed("连通测试")
        if not vec:
            raise ValueError("返回向量为空")
        logger.info("✅ Embedder 连通正常（dim=%d）", len(vec))
    except Exception as e:
        logger.warning("⚠️  Embedder 连通异常：%s", e)


# ════════════════════════════════════════════════════════════
# 健康检查：监控接口调用
# ════════════════════════════════════════════════════════════

def health_check() -> dict:
    """返回各组件连通状态"""
    from .alaya_embedder import AlayaEmbedder
    from .sql_manager import SQLManager
    from .vector_manager import VectorManager
    from sqlalchemy import text

    status: dict = {
        "milvus":   False,
        "embedder": False,
        "sqlite":   {},
    }

    try:
        VectorManager().search("health", top_k=1)
        status["milvus"] = True
    except Exception as e:
        status["milvus_error"] = str(e)

    try:
        vec = AlayaEmbedder().embed("health")
        status["embedder"] = bool(vec)
        status["embedder_dim"] = len(vec)
    except Exception as e:
        status["embedder_error"] = str(e)

    try:
        sm = SQLManager()
        for db_id, engine in sm._engines.items():
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            status["sqlite"][db_id] = True
    except Exception as e:
        status["sqlite_error"] = str(e)

    return status


# ════════════════════════════════════════════════════════════
# 向量数据导入：运维操作，按需调用
# ════════════════════════════════════════════════════════════

def ingest_vector(
    file_path: str,
    category: str | None = None,
    chunk_size: int = 512,
    chunk_overlap: int = 64,
    *,
    flush: bool = True,
) -> None:
    """
    文件 → AlayaETL（分块 + embedding） → VectorManager.insert_chunks() → Milvus

    批量导入时传 flush=False，由调用方在全部文件写入后统一 flush。
    """
    from .alaya_etl import AlayaETL
    from .vector_manager import VectorManager

    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"文件不存在：{file_path}")

    # 1. ETL：分块 + embedding（按需创建，非单例）
    etl = AlayaETL()
    chunks = etl.process_file(path, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    logger.info("ETL 完成，共 %d 个 chunks", len(chunks))

    # 2. 注入业务元数据
    for c in chunks:
        metadata = c.setdefault("metadata", {})
        metadata["source_file"] = path.name
        if category:
            metadata["category"] = category

    # 3. 写入 Milvus
    vm = VectorManager()
    vm.ensure_collection()
    inserted = vm.insert_chunks(chunks, flush=flush)
    if category:
        logger.info("✅ 向量导入完成：%d chunks → category='%s'", inserted, category)
    else:
        logger.info("✅ 向量导入完成：%d chunks", inserted)


# ════════════════════════════════════════════════════════════
# 结构化数据导入：运维操作，按需调用
# ════════════════════════════════════════════════════════════

def ingest_sql(
    file_path: str,
    table_name: str,
    if_exists: str = "append",
) -> None:
    """
    CSV / Excel → SQLite
    if_exists: 'append' | 'replace' | 'fail'
    """
    import pandas as pd
    from .sql_manager import SQLManager

    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"文件不存在：{file_path}")

    sm = SQLManager()
    meta = sm.get_table_meta(table_name)
    if meta is None:
        raise ValueError(f"表 '{table_name}' 未在 table_registry.yaml 中注册")

    # 读取文件
    df = pd.read_csv(path, dtype=str) if path.suffix.lower() == ".csv" \
        else pd.read_excel(path, dtype=str)

    # 只保留 registry 声明的列，缺失列补 None
    declared_cols = list(meta["columns"].keys())
    for col in declared_cols:
        if col not in df.columns:
            df[col] = None
    df = df[declared_cols]

    logger.info("读取数据：%d 行，%d 列", len(df), len(df.columns))

    engine = sm._engines[meta["db_id"]]
    df.to_sql(table_name, con=engine, if_exists=if_exists, index=False)
    logger.info("✅ SQL 导入完成：%d 行 → 表 '%s'（if_exists=%s）", len(df), table_name, if_exists)


# ════════════════════════════════════════════════════════════
# CLI 入口
# ════════════════════════════════════════════════════════════

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

    parser = argparse.ArgumentParser(description="知识库管理工具")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("warmup", help="预热单例连接")

    p_vec = sub.add_parser("ingest-vector", help="导入向量数据")
    p_vec.add_argument("--file",          required=True)
    p_vec.add_argument("--category",      type=parse_category,
                       help="导入分类，可选；留空则不写入分类标签")
    p_vec.add_argument("--chunk-size",    type=int, default=512)
    p_vec.add_argument("--chunk-overlap", type=int, default=64)

    p_sql = sub.add_parser("ingest-sql", help="导入结构化数据")
    p_sql.add_argument("--file",      required=True)
    p_sql.add_argument("--table",     required=True)
    p_sql.add_argument("--if-exists", default="append",
                       choices=["append", "replace", "fail"])

    sub.add_parser("health", help="健康检查")

    args = parser.parse_args()

    if args.cmd == "warmup":
        warmup()
    elif args.cmd == "ingest-vector":
        ingest_vector(args.file, args.category, args.chunk_size, args.chunk_overlap)
    elif args.cmd == "ingest-sql":
        ingest_sql(args.file, args.table, args.if_exists)
    elif args.cmd == "health":
        import json
        print(json.dumps(health_check(), ensure_ascii=False, indent=2))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
