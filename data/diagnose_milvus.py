"""
诊断脚本：检查 Milvus 集合的实际状态（是否有索引、是否已加载、是否能搜索）。
用法：python -m data.diagnose_milvus
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# 加载 .env
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
env_file = ROOT / ".env"
if env_file.exists():
    from dotenv import load_dotenv
    load_dotenv(env_file)

from pymilvus import MilvusClient

MILVUS_URI   = os.getenv("MILVUS_URI", "http://localhost:19530")
MILVUS_TOKEN = os.getenv("MILVUS_TOKEN", "")
MILVUS_DB    = os.getenv("MILVUS_DB_NAME", "")

COLLECTIONS_TO_CHECK = ["admission_policy", "school_overview", "majors_and_training"]

def sep(title: str = "") -> None:
    print("=" * 60)
    if title:
        print(f"  {title}")
        print("=" * 60)

def main() -> None:
    print(f"连接 Milvus: {MILVUS_URI}")
    kwargs: dict = {"uri": MILVUS_URI}
    if MILVUS_TOKEN:
        kwargs["token"] = MILVUS_TOKEN
    if MILVUS_DB:
        kwargs["db_name"] = MILVUS_DB
    client = MilvusClient(**kwargs)

    all_collections = client.list_collections()
    sep("Milvus 中所有 collection")
    print(all_collections)

    for col in COLLECTIONS_TO_CHECK:
        sep(f"Collection: {col}")
        if col not in all_collections:
            print(f"  [!] 不存在")
            continue

        # 1. describe
        try:
            desc = client.describe_collection(collection_name=col)
            fields = [f.get("name") for f in (desc.get("fields") or [])]
            print(f"  字段: {fields}")
            num_entities = desc.get("num_entities", "unknown")
            print(f"  行数(num_entities): {num_entities}")
        except Exception as e:
            print(f"  [!] describe_collection 出错: {e}")

        # 2. 统计行数
        try:
            stats = client.get_collection_stats(collection_name=col)
            print(f"  stats: {stats}")
        except Exception as e:
            print(f"  [!] get_collection_stats 出错: {e}")

        # 3. 索引
        try:
            indexes = client.list_indexes(collection_name=col)
            print(f"  list_indexes 返回: {indexes}")
            for idx_name in (indexes or []):
                try:
                    idx_desc = client.describe_index(collection_name=col, index_name=idx_name)
                    print(f"    索引[{idx_name}]: {idx_desc}")
                except Exception as ie:
                    print(f"    [!] describe_index({idx_name}) 出错: {ie}")
        except Exception as e:
            print(f"  [!] list_indexes 出错: {e}")

        # 4. 加载状态
        try:
            state = client.get_load_state(collection_name=col)
            print(f"  get_load_state 原始返回: {state!r}")
        except Exception as e:
            print(f"  [!] get_load_state 出错: {e}")

        # 5. 尝试加载
        try:
            client.load_collection(collection_name=col)
            print(f"  load_collection: 成功（之前未加载）")
        except Exception as e:
            print(f"  load_collection: {e}")

        # 6. 尝试简单查询（query，不需要索引）
        try:
            rows = client.query(
                collection_name=col,
                filter="",
                output_fields=["id"],
                limit=3,
            )
            print(f"  query(前3行 id): {[r.get('id') for r in rows]}")
        except Exception as e:
            print(f"  [!] query 出错: {e}")

        # 7. 尝试搜索（用零向量）
        try:
            desc2 = client.describe_collection(collection_name=col)
            dim = None
            for f in (desc2.get("fields") or []):
                if f.get("name") == "vector":
                    dim = int((f.get("params") or {}).get("dim", 0))
                    break
            if dim:
                dummy_vec = [0.0] * dim
                results = client.search(
                    collection_name=col,
                    data=[dummy_vec],
                    anns_field="vector",
                    limit=3,
                    output_fields=["id"],
                )
                hits = results[0] if results else []
                print(f"  search(零向量, top3): {[h.get('id') for h in hits]}")
            else:
                print(f"  [!] 无法获取向量维度，跳过 search 测试")
        except Exception as e:
            print(f"  [!] search 出错: {e}")

        # 8. 尝试带 output_fields=["*"] 的搜索（测试 sparse_vector 是否报错）
        try:
            desc3 = client.describe_collection(collection_name=col)
            dim = None
            for f in (desc3.get("fields") or []):
                if f.get("name") == "vector":
                    dim = int((f.get("params") or {}).get("dim", 0))
                    break
            if dim:
                dummy_vec = [0.0] * dim
                results = client.search(
                    collection_name=col,
                    data=[dummy_vec],
                    anns_field="vector",
                    limit=2,
                    output_fields=["*"],
                )
                hits = results[0] if results else []
                first = hits[0] if hits else {}
                entity = first.get("entity", {})
                print(f"  search(output=['*'], top1) entity keys: {list(entity.keys())}")
                # 打印 content 或 text 字段
                for key in ["content", "text", "page_content"]:
                    val = entity.get(key)
                    if val:
                        print(f"    {key}[:80]: {str(val)[:80]}")
                        break
        except Exception as e:
            print(f"  [!] search with output_fields=['*'] 出错: {e}")

    sep("诊断完成")

if __name__ == "__main__":
    main()
