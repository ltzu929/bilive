from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from typing import Any


WEB_SUBMIT_URL = "https://member.bilibili.com/x/vu/web/add/v3"


class BilibiliWebClient:
    def __init__(
        self,
        *,
        session,
        csrf: str,
        now_ms: Callable[[], int] | None = None,
    ) -> None:
        if not csrf:
            raise ValueError("bili_jct is required for Bilibili submission")
        self.session = session
        self.csrf = csrf
        self.now_ms = now_ms or (lambda: int(time.time() * 1000))

    def submit_uploaded_video(
        self,
        remote_filename: str,
        metadata: Mapping[str, Any],
    ) -> dict[str, Any]:
        title = str(metadata.get("title") or "").strip()
        if not title:
            raise ValueError("upload title is required")
        if not remote_filename:
            raise ValueError("remote filename is required")

        desc = str(metadata.get("desc") or "")
        payload = {
            "copyright": int(metadata.get("copyright", 2)),
            "source": str(metadata.get("source") or ""),
            "tid": int(metadata.get("tid") or 0),
            "cover": str(metadata.get("cover") or ""),
            "title": title,
            "desc_format_id": 0,
            "desc": desc,
            "dynamic": str(metadata.get("dynamic") or ""),
            "subtitle": {"open": 0, "lan": ""},
            "tag": str(metadata.get("tag") or ""),
            "videos": [
                {
                    "filename": remote_filename,
                    "title": title,
                    "desc": desc,
                }
            ],
        }
        response = self.session.post(
            WEB_SUBMIT_URL,
            params={
                "t": str(self.now_ms()),
                "csrf": self.csrf,
            },
            json=payload,
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Bilibili submission returned a non-object response")
        return data
