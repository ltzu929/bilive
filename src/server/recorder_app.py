"""Load blrec's ASGI app after installing the in-memory Cookie override."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from src.server.recorder_navigation import patch_installed_blrec_navigation
from src.server.recorder_server import install_secret_cookie, read_secret_cookie


cookie_path = Path(os.environ.get("BILIVE_RECORDER_COOKIE_FILE", ""))
cookie = read_secret_cookie(cookie_path) if str(cookie_path) else ""
if install_secret_cookie(cookie):
    logging.getLogger(__name__).info(
        "Loaded the ignored Bilibili Cookie into recorder memory"
    )

try:
    navigation_updated = patch_installed_blrec_navigation()
except Exception:
    logging.getLogger(__name__).exception(
        "Could not add the optional Bilive Studio recorder navigation"
    )
else:
    if navigation_updated:
        logging.getLogger(__name__).info(
            "Added the Bilive Studio workbench entry to the recorder sidebar"
        )

from blrec.web import app  # noqa: E402


__all__ = ("app",)
