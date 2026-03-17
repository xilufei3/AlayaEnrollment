# Project Model Provider Design

**Goal:** Replace AlayaFlow model registration usage in this project with a project-local model provider that returns per-kind singleton model instances.

**Architecture:** The project will own model construction and caching inside a dedicated provider module. Callers will request models by stable kinds such as `intent`, `generation`, `planner`, `eval`, and `rerank`, and the provider will return a singleton instance per kind with kind-specific configuration.

**Key Decisions:**
- Stop relying on `register_runtime_models()` and `ModelManager.get_model()` in project code.
- Introduce a local provider that constructs `ChatOpenAI` and `JinaRerank` directly.
- Cache instances per model kind so repeated calls reuse the same instance, while different kinds can keep different parameters.
- Keep Qwen non-thinking mode centralized in provider configuration via `extra_body={"chat_template_kwargs": {"enable_thinking": False}}`.
- Preserve existing node behavior by changing model lookup only, not prompt or graph logic.

**Components:**
- New model config module describing per-kind provider settings.
- New model provider module exposing a small lookup API.
- Node migrations for intent classification, generation, search planning, sufficiency evaluation, and rerank.
- Runtime cleanup so startup no longer depends on model registration.

**Error Handling:**
- Missing API keys should raise clear configuration errors when a model is first requested.
- Unknown model kinds should raise a `KeyError` with the supported kinds.

**Testing:**
- Verify same kind returns the same instance.
- Verify different kinds return different instances.
- Verify Qwen chat kinds include disable-thinking `extra_body`.
- Verify rerank kind preserves `top_n` support without AlayaFlow model registration.
