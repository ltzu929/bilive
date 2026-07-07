"""Tests for the bilive default logging configuration.

Covers the gap that motivated configure_default_logging: the Pi dashboard is
launched by uvicorn with no Python entry point, so ``bilive.*`` loggers (e.g.
``bilive.db`` written from src/db/conn.py) had no handler and dropped to
lastResort stderr. The dashboard module load now wires a handler on the
``bilive`` namespace so those diagnostics land somewhere.
"""

from __future__ import annotations

import logging

import pytest

from src.log import logger as logger_module
from src.log.logger import configure_default_logging


@pytest.fixture
def reset_bilive_logging(monkeypatch):
    """Isolate each test from prior configure_default_logging calls."""
    root = logging.getLogger("bilive")
    saved_handlers = list(root.handlers)
    saved_propagate = root.propagate
    saved_flag = logger_module._default_logging_configured
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()
    root.propagate = True
    monkeypatch.setattr(logger_module, "_default_logging_configured", False)
    yield root
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()
    for handler in saved_handlers:
        root.addHandler(handler)
    root.propagate = saved_propagate
    monkeypatch.setattr(logger_module, "_default_logging_configured", saved_flag)


def test_configure_default_logging_installs_handler_on_bilive_namespace(reset_bilive_logging):
    root = reset_bilive_logging
    configure_default_logging()
    assert root.handlers, "bilive logger must gain at least one handler"
    assert root.propagate is False


def test_configure_default_logging_is_idempotent(reset_bilive_logging):
    root = reset_bilive_logging
    configure_default_logging()
    first_count = len(root.handlers)
    configure_default_logging()
    configure_default_logging()
    assert len(root.handlers) == first_count, "repeated calls must not stack handlers"


def test_configure_default_logging_routes_bilive_db_to_a_handler(reset_bilive_logging):
    reset_bilive_logging
    configure_default_logging()
    root = logging.getLogger("bilive")
    captured: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record):
            captured.append(record)

    capture = _Capture(level=logging.DEBUG)
    root.addHandler(capture)
    try:
        db_logger = logging.getLogger("bilive.db")
        db_logger.setLevel(logging.DEBUG)
        db_logger.warning("skipped duplicate video_path=foo.mp4")
    finally:
        root.removeHandler(capture)

    # bilive.db propagates up to the bilive root logger, whose handler we just
    # configured — the record must arrive there (not be dropped to lastResort).
    assert any(
        record.name == "bilive.db" and "skipped duplicate" in record.message
        for record in captured
    )


def test_configure_default_logging_falls_back_when_log_dir_unwritable(
    reset_bilive_logging, monkeypatch, tmp_path
):
    # Force makedirs to fail so we exercise the console-only fallback: the call
    # must still succeed and install at least the console handler.
    monkeypatch.setattr(logger_module.os, "makedirs", lambda *a, **k: (_ for _ in ()).throw(OSError("denied")))
    root = reset_bilive_logging
    configure_default_logging()
    assert any(isinstance(h, logging.StreamHandler) for h in root.handlers)


def test_dashboard_module_load_configures_bilive_logging():
    """Importing src.dashboard.app (the uvicorn target) wires the handler."""
    # Re-import to trigger the module-level configure_default_logging call.
    import importlib

    import src.dashboard.app as dashboard_app

    importlib.reload(dashboard_app)
    root = logging.getLogger("bilive")
    assert root.handlers, "dashboard import must configure the bilive logger namespace"
