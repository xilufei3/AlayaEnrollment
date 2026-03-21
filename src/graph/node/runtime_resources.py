from __future__ import annotations

import os
from pathlib import Path


def bootstrap_runtime_dirs(repo_root: Path, runtime_name: str = "graph-demo") -> Path:
    runtime_base = os.getenv("RUNTIME_ROOT", "").strip()
    if runtime_base:
        runtime_root = Path(runtime_base).expanduser()
        if not runtime_root.is_absolute():
            runtime_root = repo_root / runtime_root
        runtime_root = runtime_root / runtime_name
    else:
        runtime_root = repo_root / ".runtime" / runtime_name

    (runtime_root / "logs").mkdir(parents=True, exist_ok=True)
    (runtime_root / "workflows").mkdir(parents=True, exist_ok=True)
    (runtime_root / "envs").mkdir(parents=True, exist_ok=True)

    os.environ["ROOT_DIR"] = str(runtime_root)
    os.environ["LOGS_DIR"] = str(runtime_root / "logs")
    os.environ["WORKFLOWS_DIR"] = str(runtime_root / "workflows")
    os.environ["ENVS_DIR"] = str(runtime_root / "envs")
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
