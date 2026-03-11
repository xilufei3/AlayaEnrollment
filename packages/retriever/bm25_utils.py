"""
BM25 稀疏向量编码：用于混合检索（向量 + 关键词）。
fit(corpus) 后 encode_doc / encode_query 得到 dict[int, float] 稀疏向量，可持久化供检索时使用。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# 可选 jieba，若无则用字符级分词
try:
    import jieba
    def _tokenize(s: str) -> list[str]:
        return list(jieba.cut_for_search(s))
except ImportError:
    def _tokenize(s: str) -> list[str]:
        s = (s or "").strip()
        if not s:
            return []
        import re
        return re.findall(r"[a-zA-Z0-9]+|[^\s]", s)


def _default_tokenizer(doc: str) -> list[str]:
    return [t for t in _tokenize(doc) if t.strip()]


class BM25SparseEncoder:
    """基于 rank_bm25 的 BM25 编码器，可 fit 后 save/load 状态，用于写入与检索。"""

    def __init__(self, tokenizer: Any = None) -> None:
        self._tokenizer = tokenizer or _default_tokenizer
        self._bm25: Any = None
        self._vocab: dict[str, int] = {}
        self._idf: list[float] = []

    def fit(self, corpus: list[str]) -> None:
        from rank_bm25 import BM25Okapi
        tokenized = [self._tokenizer(d) for d in corpus]
        self._bm25 = BM25Okapi(tokenized)
        vocab: set[str] = set()
        for toks in tokenized:
            vocab.update(toks)
        self._vocab = {t: i for i, t in enumerate(sorted(vocab))}
        import math
        N = len(tokenized)
        self._idf = []
        for t in sorted(self._vocab.keys()):
            df = sum(1 for toks in tokenized if t in toks)
            idf = math.log((N - df + 0.5) / (df + 0.5) + 1.0)
            self._idf.append(idf)

    def encode_doc(self, doc: str) -> dict[int, float]:
        if self._bm25 is None or not self._vocab:
            return {}
        toks = self._tokenizer(doc)
        if not toks:
            return {}
        from collections import Counter
        cnt = Counter(toks)
        out: dict[int, float] = {}
        for t, tf in cnt.items():
            if t in self._vocab:
                idx = self._vocab[t]
                idf = self._idf[idx] if idx < len(self._idf) else 0.0
                out[idx] = float(tf * idf)
        return out

    def encode_query(self, query: str) -> dict[int, float]:
        return self.encode_doc(query)

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {"vocab": self._vocab, "idf": self._idf}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)

    @classmethod
    def load(cls, path: Path, tokenizer: Any = None) -> "BM25SparseEncoder":
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        enc = cls(tokenizer=tokenizer)
        enc._vocab = data["vocab"]
        enc._idf = data["idf"]
        enc._bm25 = None
        return enc

    @property
    def is_fitted(self) -> bool:
        return bool(self._vocab)
