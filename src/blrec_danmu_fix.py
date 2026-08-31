"""Runtime compatibility patch for Bilibili's signed danmu-info API."""

from __future__ import annotations

import asyncio
import hashlib
import re
import time
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlencode, urlparse


_MIXIN_KEY_ENC_TAB = [
    46,
    47,
    18,
    2,
    53,
    8,
    23,
    32,
    15,
    50,
    10,
    31,
    58,
    3,
    45,
    35,
    27,
    43,
    5,
    49,
    33,
    9,
    42,
    19,
    29,
    28,
    14,
    39,
    12,
    38,
    41,
    13,
    37,
    48,
    7,
    16,
    24,
    55,
    40,
    61,
    26,
    17,
    0,
    1,
    60,
    51,
    30,
    4,
    22,
    25,
    54,
    21,
    56,
    59,
    6,
    63,
    57,
    62,
    11,
    36,
    20,
    34,
    44,
    52,
]
_WBI_KEY_TTL_SECONDS = 6 * 60 * 60
_WBI_KEYS: tuple[str, str] | None = None
_WBI_KEYS_MTIME = 0.0
_WBI_KEYS_LOCK = asyncio.Lock()
_CURRENT_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/136.0.0.0 Safari/537.36"
)
_COOKIE_FIELD_PATTERN = r"(?:^|; *){} *="


def _extract_wbi_key(url: str) -> str:
    return urlparse(url).path.rsplit("/", 1)[-1].split(".", 1)[0]


def _mixin_key(img_key: str, sub_key: str) -> str:
    raw = img_key + sub_key
    return "".join(raw[index] for index in _MIXIN_KEY_ENC_TAB)[:32]


def sign_wbi_params(
    params: Mapping[str, Any],
    img_key: str,
    sub_key: str,
    *,
    now: int | None = None,
) -> dict[str, str]:
    """Return Bilibili WBI parameters without exposing cookie values."""
    values = dict(params)
    values["wts"] = int(time.time()) if now is None else int(now)
    signed = {
        str(key): "".join(
            character for character in str(value) if character not in "!'()*"
        )
        for key, value in sorted(values.items())
    }
    query = urlencode(signed)
    signed["w_rid"] = hashlib.md5(
        (query + _mixin_key(img_key, sub_key)).encode("utf-8")
    ).hexdigest()
    return signed


def _has_cookie_field(cookie: str, field: str) -> bool:
    pattern = _COOKIE_FIELD_PATTERN.format(re.escape(field))
    return bool(re.search(pattern, cookie, re.IGNORECASE))


async def _fetch_wbi_keys(api: Any) -> tuple[str, str]:
    response = await api._get_json(
        api.base_api_urls,
        "/x/web-interface/nav",
        check_response=False,
    )
    image_data = (response.get("data") or {}).get("wbi_img") or {}
    img_url = image_data.get("img_url")
    sub_url = image_data.get("sub_url")
    if not img_url or not sub_url:
        raise RuntimeError("Bilibili nav response did not contain WBI keys")
    return _extract_wbi_key(img_url), _extract_wbi_key(sub_url)


async def _get_wbi_keys(api: Any, *, force: bool = False) -> tuple[str, str]:
    global _WBI_KEYS, _WBI_KEYS_MTIME
    now = time.monotonic()
    if not force and _WBI_KEYS and now - _WBI_KEYS_MTIME < _WBI_KEY_TTL_SECONDS:
        return _WBI_KEYS

    async with _WBI_KEYS_LOCK:
        now = time.monotonic()
        if not force and _WBI_KEYS and now - _WBI_KEYS_MTIME < _WBI_KEY_TTL_SECONDS:
            return _WBI_KEYS
        _WBI_KEYS = await _fetch_wbi_keys(api)
        _WBI_KEYS_MTIME = time.monotonic()
        return _WBI_KEYS


async def _ensure_buvid(api: Any) -> None:
    cookie = api.headers.get("Cookie", "")
    if not cookie or _has_cookie_field(cookie, "buvid3"):
        return

    response = await api._get_json(
        api.base_api_urls,
        "/x/frontend/finger/spi",
    )
    data = response.get("data") or {}
    buvid3 = data.get("b_3") or data.get("buvid3")
    buvid4 = data.get("b_4") or data.get("buvid4")
    if not buvid3:
        raise RuntimeError("Bilibili fingerprint response did not contain buvid3")

    extra = f"buvid3={buvid3}"
    if buvid4:
        extra += f"; buvid4={buvid4}"
    api.headers["Cookie"] = f"{cookie}; {extra}"


async def _get_signed_danmu_info(api: Any, room_id: int) -> Any:
    img_key, sub_key = await _get_wbi_keys(api)
    params = sign_wbi_params(
        {"id": room_id, "type": 0},
        img_key,
        sub_key,
    )
    response = await api._get_json(
        api.base_live_api_urls,
        "/xlive/web-room/v1/index/getDanmuInfo",
        params=params,
    )
    return response["data"]


async def _get_app_danmu_info(api: Any, room_id: int) -> Any:
    # beta.4 already ships the signed AppApi implementation. Use a fresh
    # facade over the existing session so the WebApi object keeps its normal
    # headers and the app request gets its mobile User-Agent.
    from blrec.bili.api import AppApi

    app_api = AppApi(
        api._session,
        headers={"Cookie": api.headers.get("Cookie", "")},
        room_id=room_id,
    )
    return await app_api.get_danmu_info(room_id)


def install_danmu_api_fix() -> bool:
    """Patch the installed beta.4 WebApi once for the recorder process."""
    from blrec.bili.api import WebApi
    from blrec.bili.exceptions import ApiRequestError

    if getattr(WebApi, "_bilive_danmu_api_fix", False):
        return False

    async def get_danmu_info(self: Any, room_id: int) -> Any:
        self.headers.setdefault("Referer", "https://live.bilibili.com/")
        self.headers["User-Agent"] = _CURRENT_BROWSER_UA
        await _ensure_buvid(self)
        try:
            return await _get_app_danmu_info(self, room_id)
        except Exception as app_exc:
            try:
                return await _get_signed_danmu_info(self, room_id)
            except ApiRequestError as exc:
                if exc.code != -352:
                    raise
                # Bilibili rotates WBI keys. Refresh once before allowing
                # blrec's normal fallback/reconnect path to handle a
                # persistent challenge.
                await _get_wbi_keys(self, force=True)
                try:
                    return await _get_signed_danmu_info(self, room_id)
                except Exception:
                    raise app_exc
            except Exception:
                raise app_exc

    WebApi.get_danmu_info = get_danmu_info
    WebApi._bilive_danmu_api_fix = True
    return True


__all__ = ("install_danmu_api_fix", "sign_wbi_params")
