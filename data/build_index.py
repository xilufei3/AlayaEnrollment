"""
为已有数据但未建索引的 Milvus collection 建索引并 load，解决「index not found」报错。

用法（在仓库根目录执行）:
  python -m data.build_index --collection admission_policy --collection school_overview
  python -m data.build_index --all
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import (
    DIR_TO_COLLECTION,
    ENV_FILE,
    get_milvus_token,
    get_milvus_uri,
    load_dotenv,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="为指定 collection 创建索引并 load（已有数据但未建索引时使用）"
    )
    parser.add_argument(
        "--collection",
        action="append",
        default=[],
        dest="collections",
        help="collection 名称，可多次指定",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="对所有 data config 中的 collection 执行",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=ENV_FILE,
        help=".env 路径",
    )
    args = parser.parse_args()

    load_dotenv(args.env_file)

    if args.all:
        collections = list(DIR_TO_COLLECTION.values())
    elif args.collections:
        collections = list(dict.fromkeys(args.collections))
    else:
        print("请指定 --collection <name> 或 --all", file=sys.stderr)
        return 1

    try:
        from pymilvus import MilvusClient
        from packages.vector_store.milvus_store import MilvusVectorStore
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
    if not hasattr(store, "ensure_index_and_load_auto"):
        print("当前 store 不支持 ensure_index_and_load_auto", file=sys.stderr)
        return 1

    for name in collections:
        if not client.has_collection(collection_name=name):
            print(f"跳过（不存在）: {name}")
            continue
        try:
            print(f"建索引并 load: {name} ...")
            store.ensure_index_and_load_auto(name)
            print(f"  完成: {name}")
        except Exception as e:
            print(f"  失败: {name} -> {e}", file=sys.stderr)
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
