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
from src.knowledge.vector_manager import VectorManager


VECTOR_CATEGORIES: tuple[str, ...] = (
    "school_info",
    "admissions",
    "major",
    "career",
    "campus",
)
SUPPORTED_EXTENSIONS: tuple[str, ...] = (".md", ".txt", ".doc", ".docx", ".pdf")
DEFAULT_INPUT_DIR = REPO_ROOT / "data" / "raw" / "unstructured"


def parse_category(value: str) -> str | None:
    normalized = value.strip()
    if not normalized:
        return None
    if normalized not in VECTOR_CATEGORIES:
        choices = ", ".join(VECTOR_CATEGORIES)
        raise argparse.ArgumentTypeError(f"category must be one of: {choices}")
    return normalized


def collect_ingest_files(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="批量导入目录下所有向量文件")
    parser.add_argument(
        "--dir",
        default=str(DEFAULT_INPUT_DIR),
        help=f"待递归导入的目录路径，默认：{DEFAULT_INPUT_DIR}",
    )
    parser.add_argument(
        "--category",
        type=parse_category,
        help="导入分类，可选；留空则不写入分类标签",
    )
    parser.add_argument("--chunk-size", type=int, default=1200, help="分块大小")
    parser.add_argument("--chunk-overlap", type=int, default=200, help="分块重叠大小")
    parser.add_argument("--query", help="导入后用于验证检索的查询语句")
    parser.add_argument("--top-k", type=int, default=3, help="验证检索返回条数")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    root_dir = Path(args.dir)
    if not root_dir.exists():
        raise FileNotFoundError(f"目录不存在：{root_dir}")
    if not root_dir.is_dir():
        raise NotADirectoryError(f"不是目录：{root_dir}")

    paths = collect_ingest_files(root_dir)
    if not paths:
        raise FileNotFoundError(
            f"目录下没有可导入文件（支持：{', '.join(SUPPORTED_EXTENSIONS)}）：{root_dir}"
        )

    vm = VectorManager()
    if vm._client.has_collection(vm._collection):
        logging.info("批量导入前清空 collection：%s", vm._collection)
        vm.drop_collection()
    else:
        logging.info("collection 不存在，跳过清空：%s", vm._collection)

    logging.info("递归发现 %d 个可导入文件", len(paths))
    for path in paths:
        logging.info("开始导入：%s", path)
        ingest_vector(
            file_path=str(path),
            category=args.category,
            chunk_size=args.chunk_size,
            chunk_overlap=args.chunk_overlap,
            flush=False,
        )

    logging.info("全部文件写入完成，统一 flush ...")
    vm.flush()

    if args.query:
        hits = VectorManager().search(args.query, top_k=args.top_k)
        print(json.dumps(hits, ensure_ascii=False, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
