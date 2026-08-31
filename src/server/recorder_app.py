"""Load the native Angular blrec ASGI app after installing the Cookie override."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from src.blrec_danmu_fix import install_danmu_api_fix
from src.server.recorder_server import install_secret_cookie, read_secret_cookie
from src.server.studio_proxy import StudioApiMiddleware


cookie_path = Path(os.environ.get("BILIVE_RECORDER_COOKIE_FILE", ""))
cookie = read_secret_cookie(cookie_path) if str(cookie_path) else ""
if install_secret_cookie(cookie):
    logging.getLogger(__name__).info(
        "Loaded the ignored Bilibili Cookie into recorder memory"
    )
if install_danmu_api_fix():
    logging.getLogger(__name__).info(
        "Installed the Bilibili danmu API compatibility fix"
    )

from blrec.web import app as blrec_app  # noqa: E402

# Keep only the Studio API and media routes reachable through the recorder
# origin.  The page itself is always the native Angular application shipped by
# blrec; the Windows dashboard no longer contributes an iframe or static UI.
app = StudioApiMiddleware(blrec_app)


__all__ = ("app",)
