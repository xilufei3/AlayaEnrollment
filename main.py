from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import uvicorn
from dotenv import load_dotenv


DEFAULT_APP_IMPORT = "src.api.chat_app:app"
DEFAULT_API_HOST = "0.0.0.0"
DEFAULT_API_PORT = 8008
DEFAULT_MILVUS_PORT = 19530
DEFAULT_WAIT_TIMEOUT = 60.0


def _repo_root() -> Path:
    return Path(__file__).resolve().parent


def _load_env(repo_root: Path) -> None:
    env_file = repo_root / ".env"
    if env_file.exists():
        load_dotenv(env_file, override=False)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Start the AlayaEnrollment backend services")
    parser.add_argument("--host", default=DEFAULT_API_HOST, help="FastAPI bind host")
    parser.add_argument("--port", type=int, default=DEFAULT_API_PORT, help="FastAPI bind port")
    parser.add_argument("--reload", action="store_true", help="Enable uvicorn auto-reload")
    parser.add_argument(
        "--skip-infra",
        action="store_true",
        help="Skip docker compose startup and only run the API service",
    )
    parser.add_argument(
        "--compose-file",
        default=str(Path("infra") / "docker" / "milvus-compose.yml"),
        help="Docker compose file used for backend infra startup",
    )
    parser.add_argument(
        "--app",
        default=DEFAULT_APP_IMPORT,
        help="ASGI app import string passed to uvicorn",
    )
    parser.add_argument(
        "--wait-timeout",
        type=float,
        default=DEFAULT_WAIT_TIMEOUT,
        help="Seconds to wait for the Milvus TCP port after compose startup",
    )
    return parser


def _run_compose(repo_root: Path, compose_file: Path) -> None:
    if not compose_file.exists():
        raise FileNotFoundError(f"Compose file not found: {compose_file}")

    command = ["docker", "compose", "-f", str(compose_file), "up", "-d"]
    print(f"[main] Starting backend infra: {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=repo_root, check=True)


def _milvus_endpoint_from_env() -> tuple[str, int]:
    raw_uri = os.getenv("MILVUS_URI", f"http://localhost:{DEFAULT_MILVUS_PORT}").strip()
    if "://" not in raw_uri:
        raw_uri = f"http://{raw_uri}"
    parsed = urlparse(raw_uri)
    host = parsed.hostname or "localhost"
    port = parsed.port or DEFAULT_MILVUS_PORT
    return host, port


def _wait_for_tcp(host: str, port: int, timeout: float) -> None:
    deadline = time.time() + max(1.0, timeout)
    last_error: Exception | None = None

    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=3):
                print(f"[main] Milvus is ready at {host}:{port}", flush=True)
                return
        except OSError as exc:
            last_error = exc
            time.sleep(1.0)

    detail = f"{type(last_error).__name__}: {last_error}" if last_error else "unknown error"
    raise TimeoutError(f"Timed out waiting for Milvus at {host}:{port}. Last error: {detail}")


def main() -> int:
    repo_root = _repo_root()
    _load_env(repo_root)
    args = _build_parser().parse_args()

    compose_file = Path(args.compose_file)
    if not compose_file.is_absolute():
        compose_file = repo_root / compose_file

    if not args.skip_infra:
        _run_compose(repo_root, compose_file)
        milvus_host, milvus_port = _milvus_endpoint_from_env()
        print(f"[main] Waiting for Milvus at {milvus_host}:{milvus_port} ...", flush=True)
        _wait_for_tcp(milvus_host, milvus_port, args.wait_timeout)

    reload_dirs = [str(repo_root / "src")] if args.reload else None
    print(f"[main] Starting API: {args.app} on {args.host}:{args.port}", flush=True)
    uvicorn.run(
        args.app,
        host=args.host,
        port=args.port,
        reload=args.reload,
        reload_dirs=reload_dirs,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
