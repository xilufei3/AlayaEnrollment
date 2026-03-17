from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
ALAYAFLOW_SRC = ROOT / "AlayaFlow" / "src"
if str(ALAYAFLOW_SRC) not in sys.path:
    sys.path.insert(0, str(ALAYAFLOW_SRC))

from src.node import model_provider


class FakeChatOpenAI:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.extra_body = kwargs.get("extra_body")


class FakeJinaRerank:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.top_n = kwargs.get("top_n")


def test_get_model_returns_same_instance_for_same_kind(monkeypatch) -> None:
    model_provider.reset_model_cache()
    monkeypatch.setattr(model_provider, "ChatOpenAI", FakeChatOpenAI)

    first = model_provider.get_model("generation")
    second = model_provider.get_model("generation")

    assert first is second


def test_get_model_returns_different_instances_for_different_kinds(monkeypatch) -> None:
    model_provider.reset_model_cache()
    monkeypatch.setattr(model_provider, "ChatOpenAI", FakeChatOpenAI)

    intent_model = model_provider.get_model("intent")
    generation_model = model_provider.get_model("generation")

    assert intent_model is not generation_model


def test_generation_model_disables_qwen_thinking(monkeypatch) -> None:
    model_provider.reset_model_cache()
    monkeypatch.setattr(model_provider, "ChatOpenAI", FakeChatOpenAI)

    model = model_provider.get_model("generation")

    assert model.extra_body == {"chat_template_kwargs": {"enable_thinking": False}}


def test_rerank_model_supports_top_n_override(monkeypatch) -> None:
    model_provider.reset_model_cache()
    monkeypatch.setattr(model_provider, "JinaRerank", FakeJinaRerank)

    reranker = model_provider.get_model("rerank", top_n=3)

    assert reranker.top_n == 3
