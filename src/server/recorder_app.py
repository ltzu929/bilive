"""Load the native Angular blrec ASGI app after installing the Cookie override."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from src.server.recorder_server import install_secret_cookie, read_secret_cookie
from src.server.studio_proxy import StudioProxyMiddleware


cookie_path = Path(os.environ.get("BILIVE_RECORDER_COOKIE_FILE", ""))
cookie = read_secret_cookie(cookie_path) if str(cookie_path) else ""
if install_secret_cookie(cookie):
    logging.getLogger(__name__).info(
        "Loaded the ignored Bilibili Cookie into recorder memory"
    )

from blrec.web import app as blrec_app  # noqa: E402

# Keep the dashboard workbench reachable through the same recorder origin
# while its UI is being migrated into the native Angular application.
app = StudioProxyMiddleware(blrec_app)


__all__ = ("app",)
