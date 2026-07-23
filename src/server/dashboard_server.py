"""Run the Windows Bilive dashboard as a consoleless background service."""

from __future__ import annotations

import argparse
import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

import uvicorn

from src.server.worker_server import configure_worker_environment


def configure_dashboard_environment(
    project_root: str | Path,
    *,
    videos_dir: str | Path | None = None,
) -> None:
    root = Path(project_root).expanduser().resolve()
    if videos_dir is not None:
        os.environ["BILIVE_VIDEOS_DIR"] = str(Path(videos_dir).expanduser().resolve())
    configure_worker_environment(root, auto_upload=False)
    os.environ["BILIVE_REMOTE_WORKER_ENABLED"] = "1"


def _configure_logging(project_root: Path, *, console: bool) -> Path:
    log_dir = project_root / "logs" / "runtime"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "dashboard.log"
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2234)
    parser.add_argument("--videos-dir")
    parser.add_argument("--console", action="store_true")
    args = parser.parse_args(argv)

    project_root = Path(__file__).resolve().parents[2]
    configure_dashboard_environment(project_root, videos_dir=args.videos_dir)
    log_path = _configure_logging(project_root, console=args.console)
    logger = logging.getLogger(__name__)

    try:
        from src.db.conn import migrate_upload_queue
        from src.dashboard.app import api

        migrate_upload_queue()
        logger.info(
            "Starting Bilive Dashboard on %s:%s; log=%s",
            args.host,
            args.port,
            log_path,
        )
        config = uvicorn.Config(
            api,
            host=args.host,
            port=args.port,
            log_config=None,
            access_log=False,
        )
        uvicorn.Server(config).run()
        return 0
    except Exception:
        logger.exception("Bilive Dashboard failed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
