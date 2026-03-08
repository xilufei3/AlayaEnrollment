from __future__ import annotations

import os
import uuid

from .client_factory import create_store_from_env
from .models import CreateIndexRequest, SearchRequest, UpsertRequest, VectorItem


def main() -> None:
    store = create_store_from_env()
    index_name = f"sustech_demo_{uuid.uuid4().hex[:8]}"

    store.create_index(CreateIndexRequest(index=index_name, dimension=4, metric="COSINE"))
    try:
        store.upsert(
            UpsertRequest(
                index=index_name,
                items=[
                    VectorItem(
                        id="chunk_1",
                        vector=[0.10, 0.20, 0.30, 0.40],
                        payload={"title": "2026招生简章", "text": "综合评价招生说明"},
                    ),
                    VectorItem(
                        id="chunk_2",
                        vector=[0.12, 0.22, 0.31, 0.39],
                        payload={"title": "2026招生简章", "text": "报名时间安排"},
                    ),
                ],
            )
        )

        result = store.search(
            SearchRequest(
                index=index_name,
                query_vector=[0.11, 0.21, 0.30, 0.40],
                top_k=2,
            )
        )
        print(f"Search hits: {len(result.hits)}")
        for i, hit in enumerate(result.hits, 1):
            print(f"{i}. id={hit.id}, score={hit.score:.4f}, title={hit.payload.get('title')}")
    finally:
        if os.getenv("KEEP_COLLECTION", "0") != "1":
            store.drop_index(index_name)
        store.close()


if __name__ == "__main__":
    main()

