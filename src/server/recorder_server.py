"""Run the Windows blrec service without persisting recorder credentials."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any


def _load_project_env_file(env_path: Path) -> None:
    if not env_path.is_file():
        return
    lines = env_path.read_text(encoding="utf-8-sig").splitlines()
    existing_names = set(os.environ)
    loaded: dict[str, str] = {}
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        if not name:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        loaded[name] = value
    for name, value in loaded.items():
        if name not in existing_names:
            os.environ[name] = value


def configure_recorder_environment(
    project_root: str | Path,
    *,
    videos_dir: str | Path | None = None,
) -> tuple[Path, Path, Path]:
    root = Path(project_root).expanduser().resolve()
    _load_project_env_file(root / ".secrets" / "env")
    record_key = os.environ.pop("RECORD_KEY", "").strip()
    if not record_key:
        raise RuntimeError("RECORD_KEY is missing from .secrets/env")

    settings_path = (root / "settings.toml").resolve()
    output_path = Path(videos_dir or root / "Videos").expanduser().resolve()
    log_dir = (root / "logs" / "record").resolve()
    output_path.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)

    os.environ["PYTHONPATH"] = str(root)
    os.environ["PYTHONUTF8"] = "1"
    os.environ["PYTHONIOENCODING"] = "utf-8"
    os.environ["NO_PROXY"] = "127.0.0.1,localhost"
    os.environ["no_proxy"] = os.environ["NO_PROXY"]
    os.environ["BLREC_API_KEY"] = record_key
    os.environ["BLREC_CONFIG"] = str(settings_path)
    os.environ["BLREC_OUT_DIR"] = str(output_path)
    os.environ["BLREC_LOG_DIR"] = str(log_dir)
    os.environ["BLREC_PROGRESS"] = ""
    os.environ["BILIVE_RECORDER_COOKIE_FILE"] = str(
        (root / ".secrets" / "bilibili.cookie").resolve()
    )
    return settings_path, output_path, log_dir


def read_secret_cookie(cookie_path: str | Path) -> str:
    path = Path(cookie_path)
    if not path.is_file():
        return ""
    cookie = path.read_text(encoding="utf-8-sig").strip()
    if "\n" in cookie or "\r" in cookie:
        raise ValueError("bilibili.cookie must contain one HTTP Cookie header line")
    if cookie and "=" not in cookie:
        raise ValueError("bilibili.cookie is not a valid HTTP Cookie header")
    return cookie


def persistent_settings_payload(settings: Any) -> dict[str, Any]:
    """Build the TOML payload while excluding the in-memory secret Cookie."""
    payload = settings.dict(exclude_none=True)
    payload.setdefault("header", {})["cookie"] = ""
    return payload


def install_secret_cookie(settings_cookie: str) -> bool:
    """Inject Cookie into blrec's Settings.load and strip it from every dump."""
    if not settings_cookie:
        return False

    import toml
    from blrec.setting import Settings

    original_load = Settings.load.__func__

    @classmethod
    def load_with_secret(cls: type[Any], path: str) -> Any:
        settings = original_load(cls, path)
        settings.header.cookie = settings_cookie
        return settings

    def dump_without_secret(settings: Any) -> None:
        with open(settings._path, "wt", encoding="utf8") as file:
            toml.dump(persistent_settings_payload(settings), file)

    Settings.load = load_with_secret
    Settings.dump = dump_without_secret
    return True


def _configure_runtime_logging(project_root: Path, *, console: bool) -> Path:
    log_dir = project_root / "logs" / "runtime"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "recorder-service.log"
    handler = RotatingFileHandler(
        log_path,
        maxBytes=5 * 1024 * 1024,
        backupCount=2,
        encoding="utf-8",
    )
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[handler],
        force=True,
    )
    if not console:
        sink = open(os.devnull, "w", encoding="utf-8")
        sys.stdout = sink
        sys.stderr = sink
    return log_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2233)
    parser.add_argument("--videos-dir")
    parser.add_argument("--console", action="store_true")
    args = parser.parse_args(argv)

    project_root = Path(__file__).resolve().parents[2]
    log_path = _configure_runtime_logging(project_root, console=args.console)
    logger = logging.getLogger(__name__)

    try:
        settings_path, output_path, _ = configure_recorder_environment(
            project_root,
            videos_dir=args.videos_dir,
        )

        from src import blrec_patch, blrec_settings

        if blrec_patch.main([]) != 0:
            raise RuntimeError("failed to verify the blrec FPS guard")
        if blrec_settings.main([str(settings_path)]) != 0:
            raise RuntimeError("failed to validate blrec settings")

        cookie = read_secret_cookie(project_root / ".secrets" / "bilibili.cookie")
        if cookie:
            logger.info("Recorder will load the ignored Bilibili Cookie in memory")
        else:
            logger.warning(
                "No .secrets/bilibili.cookie found; paid/login-only stream qualities "
                "may be unavailable"
            )

        import uvicorn

        config = uvicorn.Config(
            "src.server.recorder_app:app",
            host=args.host,
            port=args.port,
            log_config=None,
            access_log=False,
        )
        logger.info(
            "Starting Bilive Recorder on %s:%s; videos=%s; log=%s",
            args.host,
            args.port,
            output_path,
            log_path,
        )
        uvicorn.Server(config).run()
        return 0
    except Exception:
        logger.exception("Bilive Recorder failed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
