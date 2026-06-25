from __future__ import annotations

import argparse
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

import uvicorn


def _load_project_env_file(env_path: Path) -> None:
    if not env_path.is_file():
        return
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        if not name or name in os.environ:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        os.environ[name] = value


def configure_worker_environment(
    project_root: str | Path,
    *,
    auto_upload: bool,
) -> None:
    root = Path(project_root).expanduser().resolve()
    _load_project_env_file(root / ".secrets" / "env")
    os.environ["PYTHONPATH"] = str(root)
    os.environ["PYTHONUTF8"] = "1"
    os.environ["PYTHONIOENCODING"] = "utf-8"
    os.environ["NO_PROXY"] = "127.0.0.1,localhost"
    os.environ["no_proxy"] = os.environ["NO_PROXY"]
    os.environ["BILIVE_DIR"] = str(root)
    os.environ["BILIVE_CONFIG"] = str(root / "bilive-server.toml")
    os.environ["BILIVE_VIDEOS_DIR"] = str(root / "Videos")
    os.environ["BILIVE_DB_PATH"] = str(root / "src" / "db" / "data.db")
    os.environ["BILIVE_COOKIE_FILE"] = str(
        root / ".secrets" / "bilibili.cookie"
    )
    os.environ["BILIVE_AUTO_UPLOAD"] = "1" if auto_upload else "0"


def request_server_shutdown(holder: dict[str, Any]) -> None:
    server = holder.get("server")
    if server is not None:
        server.should_exit = True


def _configure_logging(project_root: Path, *, console: bool) -> Path:
    log_dir = project_root / "logs" / "runtime"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "worker-api.log"
    handlers: list[logging.Handler] = [
        RotatingFileHandler(
            log_path,
            maxBytes=5 * 1024 * 1024,
            backupCount=2,
            encoding="utf-8",
        )
    ]
    if console:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )
    return log_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the bilive Windows Worker API")
    parser.add_argument("--no-upload", action="store_true")
    parser.add_argument("--console", action="store_true")
    args = parser.parse_args(argv)

    project_root = Path(__file__).resolve().parents[2]
    configure_worker_environment(
        project_root,
        auto_upload=not args.no_upload,
    )
    log_path = _configure_logging(project_root, console=args.console)
    logger = logging.getLogger(__name__)

    try:
        from src.db.conn import migrate_upload_queue
        from src.server.worker_api import create_app

        migrate_upload_queue()
        holder: dict[str, Any] = {}
        app = create_app(
            shutdown_requester=lambda: request_server_shutdown(holder),
            auto_upload=not args.no_upload,
        )
        config = uvicorn.Config(
            app,
            host="127.0.0.1",
            port=2235,
            log_config=None,
            access_log=args.console,
        )
        server = uvicorn.Server(config)
        holder["server"] = server
        logger.info(
            "Starting bilive Worker API on 127.0.0.1:2235; log=%s",
            log_path,
        )
        server.run()
        return 0
    except Exception:
        logger.exception("Bilive Worker API failed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
