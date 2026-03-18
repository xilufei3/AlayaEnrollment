from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.knowledge.manage import ingest_vector


VECTOR_CATEGORIES: tuple[str, ...] = (
    "school_info",
    "admissions",
    "major",
    "career",
    "campus",
)


def parse_category(value: str) -> str | None:
    normalized = value.strip()
    if not normalized:
        return None
    if normalized not in VECTOR_CATEGORIES:
        choices = ", ".join(VECTOR_CATEGORIES)
        raise argparse.ArgumentTypeError(f"category must be one of: {choices}")
    return normalized


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="导入单个向量文件")
    parser.add_argument("--file", required=True, help="待导入文件路径")
    parser.add_argument(
        "--category",
        type=parse_category,
        help="导入分类，可选；留空则不写入分类标签",
    )
    parser.add_argument("--chunk-size", type=int, default=512, help="分块大小")
    parser.add_argument("--chunk-overlap", type=int, default=64, help="分块重叠大小")
    parser.add_argument("--query", help="导入后用于验证检索的查询语句")
    parser.add_argument("--top-k", type=int, default=3, help="验证检索返回条数")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    path = Path(args.file)
    logging.info("开始导入：%s", path)
    ingest_vector(
        file_path=str(path),
        category=args.category,
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
    )

    if args.query:
        from src.knowledge.vector_manager import VectorManager

        hits = VectorManager().search(args.query, top_k=args.top_k)
        print(json.dumps(hits, ensure_ascii=False, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
