from __future__ import annotations

import argparse
import json
import logging

from src.knowledge.vector_manager import (
    SEARCH_HYBRID,
    SEARCH_SPARSE,
    SEARCH_VECTOR,
    VectorManager,
)

SEARCH_MODES: tuple[str, ...] = (
    SEARCH_VECTOR,
    SEARCH_SPARSE,
    SEARCH_HYBRID,
)

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="向量检索 demo：依次测试 vector / sparse / hybrid 三种检索模式")
    parser.add_argument("--query", required=True, help="检索查询语句")
    parser.add_argument("--top-k", type=int, default=3, help="每种检索模式返回的结果条数")
    parser.add_argument(
        "--filter",
        dest="filter_expr",
        help='Milvus 过滤表达式，例如：category == "major"',
    )
    return parser


def run_demo(query: str, top_k: int, filter_expr: str | None = None) -> dict[str, object]:
    vm = VectorManager()
    results: dict[str, object] = {
        "query": query,
        "top_k": top_k,
        "filter": filter_expr,
        "results": {},
    }

    for mode in SEARCH_MODES:
        hits = vm.search(
            query=query,
            top_k=top_k,
            filter_expr=filter_expr,
            mode=mode,
        )
        results["results"][mode] = {
            "count": len(hits),
            "hits": hits,
        }

    return results


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    payload = run_demo(args.query, args.top_k, args.filter_expr)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
