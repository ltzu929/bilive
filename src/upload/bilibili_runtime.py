# Copyright (c) 2024 bilive.
"""Bilibili runtime client: cookie-authed HTTP session + bilitool upload bridge.

Owns the ``requests.Session`` used for both the nav/login check and the actual
UPOS upload (which delegates into the bilitool submodule with a runtime-patched
``Model`` pointing at a per-process config file), then the web publish step via
``BilibiliWebClient``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import requests

from src.upload.bilibili_web import BilibiliWebClient
from src.upload.cookie import parse_cookie_file
from src.upload.models import UploadSettings


class BilibiliRuntimeClient:
    def __init__(
        self,
        *,
        cookies: dict[str, str],
        upload_line: str = "auto",
        session: requests.Session | None = None,
    ) -> None:
        self.cookies = dict(cookies)
        self.upload_line = upload_line
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/143.0.0.0 Safari/537.36"
                ),
                "Referer": "https://member.bilibili.com/",
            }
        )
        self.session.cookies.update(self.cookies)
        self.web = BilibiliWebClient(
            session=self.session,
            csrf=self.cookies["bili_jct"],
        )

    def check_login(self) -> dict[str, Any] | None:
        response = self.session.get(
            "https://api.bilibili.com/x/web-interface/nav",
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict) or data.get("isLogin") is not True:
            return None
        return {
            "isLogin": True,
            "uname": str(data.get("uname") or ""),
            "mid": data.get("mid"),
        }

    def upload_file(
        self,
        video_path: str,
        metadata: dict[str, Any],
    ) -> str:
        previous_config_path = os.environ.get("BILITOOL_CONFIG_PATH")
        config_path = Path(previous_config_path or self._bilitool_config_path())
        config_path.parent.mkdir(parents=True, exist_ok=True)
        os.environ["BILITOOL_CONFIG_PATH"] = str(config_path)
        try:
            from src.upload.bilitool.bilitool.controller import upload_controller
            from src.upload.bilitool.bilitool.model import model as bilitool_model
            from src.upload.bilitool.bilitool.upload import bili_upload

            base_model = bilitool_model.Model

            class RuntimeModel(base_model):
                def __init__(self, path=None) -> None:
                    super().__init__(path or config_path)

            previous_models = (
                bilitool_model.Model,
                bili_upload.Model,
                upload_controller.Model,
            )
            bilitool_model.Model = RuntimeModel
            bili_upload.Model = RuntimeModel
            upload_controller.Model = RuntimeModel
            try:
                controller = upload_controller.UploadController()
                controller.bili_uploader.session = self.session
                headers = dict(self.session.headers)
                headers["Cookie"] = "; ".join(
                    f"{key}={value}" for key, value in self.cookies.items()
                )
                controller.bili_uploader.headers = headers
                remote_filename = controller.upload_video(
                    video_path,
                    cdn=self.upload_line,
                )
            finally:
                (
                    bilitool_model.Model,
                    bili_upload.Model,
                    upload_controller.Model,
                ) = previous_models
        finally:
            if previous_config_path is None:
                os.environ.pop("BILITOOL_CONFIG_PATH", None)
            else:
                os.environ["BILITOOL_CONFIG_PATH"] = previous_config_path
        if not remote_filename:
            raise RuntimeError("UPOS upload did not return a remote filename")
        return str(remote_filename)

    def _bilitool_config_path(self) -> Path:
        project_root = Path(
            os.environ.get("BILIVE_DIR", Path(__file__).resolve().parents[2])
        )
        runtime_dir = Path(os.environ.get("BILIVE_LOG_DIR", project_root / "logs"))
        runtime_dir = runtime_dir / "runtime"
        runtime_dir.mkdir(parents=True, exist_ok=True)
        return runtime_dir / "bilitool-config.json"

    def submit_uploaded_video(
        self,
        remote_filename: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        return self.web.submit_uploaded_video(remote_filename, metadata)


def build_runtime_client(settings: UploadSettings) -> BilibiliRuntimeClient:
    cookies = parse_cookie_file(settings.cookie_file)
    return BilibiliRuntimeClient(
        cookies=cookies,
        upload_line=settings.upload_line,
    )