# Copyright (c) 2024 bilive.

import logging
import time
import os
from typing import Optional
from functools import partial
from src.config import LOG_DIR


# Process-wide guard so importing this module (and callers that wire logging
# at startup) never installs duplicate handlers across reloads/test runs.
_default_logging_configured = False


def configure_default_logging(*, console: bool = True) -> None:
    """Install a single file+console handler on the ``bilive`` logger namespace.

    Idempotent: safe to call from every entry point (worker server, dashboard
    module load, tests). The ``bilive.*`` loggers (bilive.db, bilive.config,
    bilive.scan, ...) propagate to this one handler instead of relying on each
    process happening to call ``logging.basicConfig`` — the Pi dashboard, which
    uvicorn launches without any Python logging setup, otherwise drops
    sub-WARNING db/config diagnostics to stderr-only lastResort.
    """
    global _default_logging_configured
    root_logger = logging.getLogger("bilive")
    if _default_logging_configured and root_logger.handlers:
        return
    # Clear any stale handlers so a reconfigure (e.g. test reload) is clean.
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)
        handler.close()

    formatter = logging.Formatter(
        "[%(levelname)s] - [%(asctime)s %(name)s] - %(message)s"
    )
    log_folder = f"{LOG_DIR}/runtime"
    try:
        os.makedirs(log_folder, exist_ok=True)
    except OSError:
        # If LOG_DIR is not writable (e.g. read-only test cwd), fall back to
        # console-only so logging never breaks the process.
        log_folder = None
    if log_folder:
        now = time.strftime("%Y%m%d", time.localtime(time.time()))
        try:
            file_handler = logging.FileHandler(
                f"{log_folder}/bilive-{now}.log", encoding="UTF-8"
            )
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(formatter)
            root_logger.addHandler(file_handler)
        except OSError:
            pass
    if console:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

    root_logger.setLevel(logging.DEBUG)
    # Stop propagation so we don't double-log through the root/basicConfig chain.
    root_logger.propagate = False
    _default_logging_configured = True


class Logger:
    def __init__(self, log_file_prefix: Optional[str] = None):
        self.log_file_prefix = log_file_prefix
        self._logger = None

    def __get__(self, instance, owner):
        if self._logger is None:
            self._logger = self._create_logger()
        return self._logger

    def _create_logger(self):
        logger = logging.getLogger(f"bilive {self.log_file_prefix}")
        if not logger.handlers:
            logger.setLevel("DEBUG")
            formatter = logging.Formatter(
                "[%(levelname)s] - [%(asctime)s %(name)s] - %(message)s"
            )

            # console output
            console_handler = logging.StreamHandler()
            console_handler.setLevel("INFO")
            console_handler.setFormatter(formatter)
            logger.addHandler(console_handler)

            # file output
            now = time.strftime("%Y%m%d", time.localtime(time.time()))
            log_folder = f"{LOG_DIR}/{self.log_file_prefix}"
            if not os.path.exists(log_folder):
                os.makedirs(log_folder)
            path = f"{log_folder}/{self.log_file_prefix}-{now}.log"
            file_handler = logging.FileHandler(path, encoding="UTF-8")
            file_handler.setLevel("DEBUG")
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)

        return logger


class Log:
    def __init__(self, log_file_prefix: Optional[str] = None):
        self.logger = Logger(log_file_prefix)

    @property
    def debug(self):
        return partial(self.logger.__get__(None, None).debug)

    @property
    def info(self):
        return partial(self.logger.__get__(None, None).info)

    @property
    def warning(self):
        return partial(self.logger.__get__(None, None).warning)

    @property
    def error(self):
        return partial(self.logger.__get__(None, None).error)

    @property
    def critical(self):
        return partial(self.logger.__get__(None, None).critical)


scan_log = Log("scan")
upload_log = Log("upload")

if __name__ == "__main__":
    for i in range(1000):
        scan_log.info(f"Starting scan module... {i}")
        time.sleep(0.1)
        scan_log.debug(f"Debug information in scan module {i}")

        upload_log.info(f"Starting upload module... {i}")
        time.sleep(0.1)
        upload_log.error(f"Upload failed! {i}")
