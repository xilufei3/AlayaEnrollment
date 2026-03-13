"""
全量重建脚本：删除旧 collection，将所有子目录数据一次性写入 sustc_enrollment。

用法（在仓库根目录执行）:
  # 标准向量导入
  python -m data.ingest_all

  # 混合检索（向量 + BM25 稀疏）
  python -m data.ingest_all --hybrid

  # 仅删除旧 collection，不导入（用于手动清理）
  python -m data.ingest_all --drop-only

  # 跳过旧 collection 的删除（直接追加写入）
  python -m data.ingest_all --no-drop-old
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import (
    COLLECTION_NAME,
    DATA_DIR,
    DEFAULT_BATCH_SIZE,
    DEFAULT_CHUNK_OVERLAP,
    DEFAULT_CHUNK_SIZE,
    DEFAULT_ETL_TIMEOUT,
    ENV_FILE,
    SUPPORTED_DIRS,
    get_etl_url,
    get_milvus_token,
    get_milvus_uri,
    load_dotenv,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# 旧 collection 名称列表（迁移前的三个独立 collection）
LEGACY_COLLECTIONS: list[str] = [
    "school_overview",
    "admission_policy",
    "majors_and_training",
]

# 图片等二进制文件后缀，导入时跳过
SKIP_SUFFIXES: set[str] = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico", ".bmp"}


def _gather_all_files(data_root: Path) -> list[Path]:
    """收集所有支持子目录下的文档文件（跳过图片等二进制文件）。"""
    files: list[Path] = []
    for dir_name in SUPPORTED_DIRS:
        d = data_root / dir_name
        if not d.is_dir():
            print(f"  [跳过] 目录不存在: {d}")
            continue
        dir_files = sorted(
            p for p in d.rglob("*")
            if p.is_file() and p.suffix.lower() not in SKIP_SUFFIXES
        )
        print(f"  {dir_name}: {len(dir_files)} 个文件")
        files.extend(dir_files)
    return files


def main() -> int:
    parser = argparse.ArgumentParser(
        description="删除旧 collection，将所有数据全量导入 sustc_enrollment"
    )
    parser.add_argument(
        "--drop-only",
        action="store_true",
        help="仅删除旧 collection 和目标 collection，不执行导入",
    )
    parser.add_argument(
        "--no-drop-old",
        action="store_true",
        help="跳过旧 collection 的删除步骤（追加模式）",
    )
    parser.add_argument(
        "--keep-target",
        action="store_true",
        help="跳过对目标 collection（sustc_enrollment）的删除，直接追加写入",
    )
    parser.add_argument(
        "--hybrid",
        action="store_true",
        help="启用混合检索：写入向量 + BM25 稀疏向量",
    )
    parser.add_argument(
        "--bm25-state-dir",
        type=Path,
        default=None,
        help="BM25 状态保存目录（默认 data/bm25_state）",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=DEFAULT_CHUNK_SIZE,
        help=f"分片大小（默认 {DEFAULT_CHUNK_SIZE}）",
    )
    parser.add_argument(
        "--chunk-overlap",
        type=int,
        default=DEFAULT_CHUNK_OVERLAP,
        help=f"分片重叠（默认 {DEFAULT_CHUNK_OVERLAP}）",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"写入批大小（默认 {DEFAULT_BATCH_SIZE}）",
    )
    parser.add_argument(
        "--no-ocr",
        action="store_true",
        help="关闭 OCR",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DATA_DIR,
        help="data 目录路径",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=ENV_FILE,
        help=".env 文件路径",
    )
    args = parser.parse_args()

    load_dotenv(args.env_file)

    data_root = args.data_dir.resolve()
    if not data_root.is_dir():
        print(f"data 目录不存在: {data_root}", file=sys.stderr)
        return 1

    try:
        from pymilvus import MilvusClient
        from packages.vector_store.milvus_store import MilvusVectorStore
        from packages.alayadata.client import AlayaDataClient
        from packages.collection.service import CollectionService, InsertFilesResult
    except ImportError as e:
        print(f"导入依赖失败: {e}", file=sys.stderr)
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

    from pymilvus.exceptions import MilvusException

    def _safe_drop(col_name: str) -> None:
        """删除 collection，忽略 Milvus 集群缓存刷新失败（InvalidateCollectionMetaCache）。
        该错误发生时 collection 已在服务端删除，仅缓存同步失败，可安全忽略。
        """
        try:
            service.drop_collection(col_name)
            print(f"  已删除: {col_name}")
        except MilvusException as e:
            if "InvalidateCollectionMetaCache" in str(e) or "node not match" in str(e):
                print(f"  已删除（缓存刷新警告，可忽略）: {col_name}")
            else:
                raise

    # ── 1. 删除旧 collection ──────────────────────────────────────────────────
    if not args.no_drop_old:
        print("\n[1/3] 删除旧 collection...")
        for old_col in LEGACY_COLLECTIONS:
            result = service.collection_exists(old_col)
            if result.exists:
                _safe_drop(old_col)
            else:
                print(f"  不存在，跳过: {old_col}")
    else:
        print("\n[1/3] 跳过旧 collection 删除（--no-drop-old）")

    # ── 2. 删除目标 collection ────────────────────────────────────────────────
    if not args.keep_target:
        print(f"\n[2/3] 删除目标 collection: {COLLECTION_NAME}")
        result = service.collection_exists(COLLECTION_NAME)
        if result.exists:
            _safe_drop(COLLECTION_NAME)
        else:
            print(f"  不存在，跳过: {COLLECTION_NAME}")
    else:
        print(f"\n[2/3] 跳过目标 collection 删除（--keep-target），将追加写入")

    if args.drop_only:
        print("\n--drop-only 模式，已完成删除，退出。")
        alaya_client.close()
        return 0

    # ── 3. 收集并导入所有文件 ──────────────────────────────────────────────────
    print(f"\n[3/3] 收集文件...")
    file_paths = _gather_all_files(data_root)
    if not file_paths:
        print("未找到任何文件，退出。", file=sys.stderr)
        alaya_client.close()
        return 1

    print(f"\n目标 collection : {COLLECTION_NAME}")
    print(f"待导入文件总数  : {len(file_paths)}")
    print(f"混合检索模式    : {'开启' if args.hybrid else '关闭'}")

    try:
        ingest_result: InsertFilesResult = service.insert_files(
            COLLECTION_NAME,
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

    print(f"\n✓ 完成: 已处理 {ingest_result.files_processed} 个文件，写入 {ingest_result.chunks_written} 条 chunk")
    if ingest_result.skipped_files:
        print(f"  跳过 {len(ingest_result.skipped_files)} 个文件:")
        for p in ingest_result.skipped_files:
            print(f"    - {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
