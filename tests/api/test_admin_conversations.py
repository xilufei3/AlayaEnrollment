from __future__ import annotations

from src.api.chat_app import (
    _build_admin_conversation_detail,
    _build_admin_conversation_overview,
)


def test_build_admin_conversation_overview_groups_threads_by_device_id() -> None:
    payload = _build_admin_conversation_overview(
        [
            {
                "thread_id": "thread-1",
                "created_at": "2026-04-09T07:00:00+00:00",
                "updated_at": "2026-04-09T07:05:00+00:00",
                "metadata": {"device_id": "user-a", "graph_id": "agent"},
                "values": {
                    "messages": [
                        {"id": "m1", "type": "human", "content": "广东本科招生政策"},
                        {"id": "m2", "type": "ai", "content": "这里是回答"},
                    ]
                },
            },
            {
                "thread_id": "thread-2",
                "created_at": "2026-04-09T08:00:00+00:00",
                "updated_at": "2026-04-09T08:05:00+00:00",
                "metadata": {"device_id": "user-b", "graph_id": "agent"},
                "values": {
                    "messages": [
                        {"id": "m3", "type": "human", "content": "宿舍条件如何"},
                    ]
                },
            },
        ],
        total_threads=12,
        total_users=9,
        limit=2,
        offset=0,
    )

    assert payload["stats"] == {
        "user_count": 2,
        "thread_count": 2,
        "message_count": 3,
    }
    assert payload["totals"] == {
        "user_count": 9,
        "thread_count": 12,
    }
    assert payload["pagination"] == {
        "limit": 2,
        "offset": 0,
        "page": 1,
        "page_count": 6,
        "has_prev": False,
        "has_next": True,
    }
    assert payload["users"][0]["user_id"] == "user-b"
    assert payload["users"][0]["threads"][0]["title"] == "宿舍条件如何"
    assert payload["users"][1]["threads"][0]["preview"] == "这里是回答"


def test_build_admin_conversation_detail_normalizes_message_roles_and_text() -> None:
    payload = _build_admin_conversation_detail(
        thread_id="thread-9",
        thread={
            "thread_id": "thread-9",
            "created_at": "2026-04-09T07:00:00+00:00",
            "updated_at": "2026-04-09T07:05:00+00:00",
            "metadata": {"device_id": "user-a", "graph_id": "agent"},
            "values": {
                "messages": [
                    {
                        "id": "m1",
                        "type": "human",
                        "content": [
                            {"type": "text", "text": "请介绍一下"},
                            {"type": "text", "text": "南科大的专业设置"},
                        ],
                    },
                    {
                        "id": "m2",
                        "type": "ai",
                        "content": "南科大采用书院制培养。",
                    },
                ]
            },
        },
    )

    assert payload["user_id"] == "user-a"
    assert payload["title"] == "请介绍一下 南科大的专业设置"
    assert payload["message_count"] == 2
    assert payload["messages"][0]["role"] == "user"
    assert payload["messages"][0]["text"] == "请介绍一下 南科大的专业设置"
    assert payload["messages"][1]["role"] == "assistant"
