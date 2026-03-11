"""
一次导入一个子目录到对应 collection，使用 CollectionService。

用法（在仓库根目录执行）:
  python -m data.ingest_vectors --dir admission_policy
  python -m data.ingest_vectors --dir majors_and_training
  python -m data.ingest_vectors --dir school_overview
  python -m data.ingest_vectors --dir admission_policy --collection my_admission
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import (
    DATA_DIR,
    DEFAULT_BATCH_SIZE,
    DEFAULT_CHUNK_OVERLAP,
    DEFAULT_CHUNK_SIZE,
    DEFAULT_ETL_TIMEOUT,
    ENV_FILE,
    SUPPORTED_DIRS,
    get_collection_for_dir,
    get_etl_url,
    get_milvus_token,
    get_milvus_uri,
    load_dotenv,
)

# 仓库根目录加入 path（便于作为脚本直接运行时导入 packages）
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _gather_files(data_root: Path, dir_name: str) -> list[Path]:
    """收集指定子目录下所有文件。"""
    d = data_root / dir_name
    if not d.is_dir():
        return []
    return sorted(p for p in d.rglob("*") if p.is_file())


def main() -> int:
    parser = argparse.ArgumentParser(
        description="将 data 下指定子目录的文件导入向量库（一个目录对应一个 collection）"
    )
    parser.add_argument(
        "--dir",
        required=True,
        choices=SUPPORTED_DIRS,
        help="要导入的子目录名",
    )
    parser.add_argument(
        "--collection",
        default=None,
        help="目标 collection 名称（默认使用 config 中该目录对应的 collection）",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DATA_DIR,
        help="data 目录路径",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=DEFAULT_CHUNK_SIZE,
        help="分片大小",
    )
    parser.add_argument(
        "--chunk-overlap",
        type=int,
        default=DEFAULT_CHUNK_OVERLAP,
        help="分片重叠",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help="写入批大小",
    )
    parser.add_argument(
        "--no-ocr",
        action="store_true",
        help="关闭 OCR",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=ENV_FILE,
        help=".env 文件路径",
    )
    parser.add_argument(
        "--drop",
        action="store_true",
        help="导入前先删除已存在的同名 collection（必须与 --hybrid 配合使用，否则 schema 不匹配会报错）",
    )
    parser.add_argument(
        "--hybrid",
        action="store_true",
        help="启用混合检索：写入 content + BM25 稀疏向量，并保存 BM25 状态（需 store 支持 create_hybrid_collection）",
    )
    parser.add_argument(
        "--bm25-state-dir",
        type=Path,
        default=None,
        help="BM25 状态保存目录（默认 data/bm25_state 或环境变量 BM25_STATE_DIR）",
    )
    args = parser.parse_args()

    load_dotenv(args.env_file)

    data_root = args.data_dir.resolve()
    if not data_root.is_dir():
        print(f"data 目录不存在: {data_root}", file=sys.stderr)
        return 1

    dir_name = args.dir
    collection_name = args.collection or get_collection_for_dir(dir_name)
    file_paths = _gather_files(data_root, dir_name)

    if not file_paths:
        print(f"子目录下未找到文件: {data_root / dir_name}", file=sys.stderr)
        return 1

    print(f"子目录: {dir_name}")
    print(f"目标 collection: {collection_name}")
    print(f"待导入文件数: {len(file_paths)}")
    for p in file_paths:
        print(f"  - {p.relative_to(data_root)}")

    try:
        from pymilvus import MilvusClient
        from packages.vector_store.milvus_store import MilvusVectorStore
        from packages.alayadata.client import AlayaDataClient
        from packages.collection.service import CollectionService, InsertFilesResult
    except ImportError as e:
        print(f"导入失败: {e}", file=sys.stderr)
        return 1

    uri = get_milvus_uri()
    token = get_milvus_token()
    try:
        client = MilvusClient(uri=uri, token=token if token else None)
    except Exception as e:
        print(f"Milvus 连接失败: {e}", file=sys.stderr)
        return 1

    store = MilvusVectorStore(client)
    alaya_client = AlayaDataClient(base_url=get_etl_url(), timeout=DEFAULT_ETL_TIMEOUT)
    service = CollectionService(store=store, alaya_client=alaya_client)

    if args.drop:
        existing = service.collection_exists(collection_name)
        if existing.exists:
            print(f"删除旧 collection: {collection_name}")
            service.drop_collection(collection_name)
        else:
            print(f"collection 不存在，跳过删除: {collection_name}")

    try:
        result: InsertFilesResult = service.insert_files(
            collection_name,
            file_paths,
            chunk_size=args.chunk_size,
            chunk_overlap=args.chunk_overlap,
            enable_ocr=not args.no_ocr,
            batch_size=args.batch_size,
            enable_hybrid=args.hybrid,
            bm25_state_dir=args.bm25_state_dir,
        )
    except KeyboardInterrupt:
        print("\n已中断", file=sys.stderr)
        return 130
    except Exception as e:
        print(f"导入失败: {e}", file=sys.stderr)
        raise
    finally:
        alaya_client.close()

    print(f"\n完成: 已处理 {result.files_processed} 个文件, 写入 {result.chunks_written} 条 chunk")
    if result.skipped_files:
        print(f"跳过 {len(result.skipped_files)} 个文件:")
        for p in result.skipped_files:
            print(f"  - {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
