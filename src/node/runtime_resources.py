from __future__ import annotations

import os
from pathlib import Path
from typing import Tuple


def bootstrap_runtime_dirs(repo_root: Path, runtime_name: str = "graph-demo") -> Path:
    runtime_root = repo_root / ".runtime" / runtime_name
    (runtime_root / "logs").mkdir(parents=True, exist_ok=True)
    (runtime_root / "workflows").mkdir(parents=True, exist_ok=True)
    (runtime_root / "envs").mkdir(parents=True, exist_ok=True)

    os.environ.setdefault("ROOT_DIR", str(runtime_root))
    os.environ.setdefault("LOGS_DIR", str(runtime_root / "logs"))
    os.environ.setdefault("WORKFLOWS_DIR", str(runtime_root / "workflows"))
    os.environ.setdefault("ENVS_DIR", str(runtime_root / "envs"))
    return runtime_root


def load_dotenv_file(env_file: str | Path | None) -> None:
    if env_file is None:
        return
    path = Path(env_file)
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def register_runtime_models(
    *,
    runtime_root: Path,
    env_file: str | Path | None = None,
    intent_model_id: str = "deepseek-intent",
    generation_model_id: str = "deepseek-chat",
    rerank_model_id: str = "jina-reranker",
    qwen_model_id: str = "qwen3-chat",
) -> Tuple[str, str]:
    load_dotenv_file(env_file)

    chat_model_api_key = os.getenv("DEEPSEEK_API_KEY")
    jina_api_key = os.getenv("JINA_API_KEY")
    qwen_api_key = os.getenv("QWEN_API_KEY")

    if not chat_model_api_key:
        raise ValueError("Missing env: DEEPSEEK_API_KEY")
    if not jina_api_key:
        raise ValueError("Missing env: JINA_API_KEY")

    from alayaflow.api import Flow

    flow = Flow()
    flow.init(
        {
            "workflows_dir": str(runtime_root / "workflows"),
            "envs_dir": str(runtime_root / "envs"),
            "logs_dir": str(runtime_root / "logs"),
        }
    )
    flow.register_models(
        [
            {
                "name": "DeepSeek Intent",
                "model_id": intent_model_id,
                "provider_name": "DeepSeek",
                "model_name": "deepseek-chat",
                "base_url": os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
                "api_key": chat_model_api_key,
            },
            {
                "name": "DeepSeek Chat",
                "model_id": generation_model_id,
                "provider_name": "DeepSeek",
                "model_name": "deepseek-chat",
                "base_url": os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
                "api_key": chat_model_api_key,
            },
            {
                "name": "Jina Rerank",
                "model_id": rerank_model_id,
                "provider_name": "Jina",
                "model_type": "JinaRerank",
                "model_name": os.getenv("JINA_MODEL_NAME", "jina-reranker-v3"),
                "base_url": os.getenv("JINA_BASE_URL", "null"),
                "api_key": jina_api_key,
            },
            {
                "name": "Qwen3 Chat",
                "model_id": qwen_model_id,
                "provider_name": "OpenAI",
                "model_name": "qwen3",
                "base_url": os.getenv("QWEN_BASE_URL", "http://star.sustech.edu.cn/service/model/qwen35/v1"),
                "api_key": qwen_api_key or "placeholder",
            },
        ],
        overwrite=True,
    )
    return intent_model_id, generation_model_id
