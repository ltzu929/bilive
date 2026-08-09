"""Integrate Bilive Studio into blrec's packaged web UI."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any


INJECTION_START = "<!-- bilive-studio-navigation:start -->"
INJECTION_END = "<!-- bilive-studio-navigation:end -->"
LEGACY_LINK_ID = "slice-dashboard-link"
DEFAULT_REPOSITORY_URL = "https://github.com/ltzu929/bilive"

_LEGACY_LINK_RE = re.compile(
    rf"\s*<a\b(?=[^>]*\bid=[\"']{LEGACY_LINK_ID}[\"'])[^>]*>.*?</a>\s*",
    flags=re.IGNORECASE | re.DOTALL,
)
_TEMPLATE_PATH = Path(__file__).with_name("recorder_studio_bridge.html")
_ICON_DIR = Path(__file__).with_name("recorder_navigation_icons")
_ICON_NAMES = ("scissor", "upload", "setting")


def build_navigation_injection(
    dashboard_port: int = 2234,
    repository_url: str = DEFAULT_REPOSITORY_URL,
) -> str:
    normalized_port = int(dashboard_port)
    if not 1 <= normalized_port <= 65535:
        raise ValueError("dashboard_port must be between 1 and 65535")
    normalized_repository_url = repository_url.strip().removesuffix(".git")
    if not normalized_repository_url.startswith(("https://", "http://")):
        raise ValueError("repository_url must be an absolute HTTP(S) URL")
    template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    return (
        template.replace("__DASHBOARD_PORT__", str(normalized_port))
        .replace("__PROJECT_REPOSITORY_URL__", normalized_repository_url)
        .strip()
    )


def inject_studio_navigation(
    html: str,
    dashboard_port: int = 2234,
    repository_url: str = DEFAULT_REPOSITORY_URL,
) -> str:
    """Return a normalized blrec index with one project-owned nav injection."""
    normalized = html.replace("\r\n", "\n").replace("\r", "\n")
    normalized = _LEGACY_LINK_RE.sub("\n", normalized)
    while (start := normalized.find(INJECTION_START)) >= 0:
        end = normalized.find(INJECTION_END, start)
        if end < 0:
            raise ValueError("incomplete Bilive Studio navigation injection")
        end += len(INJECTION_END)
        normalized = (
            normalized[:start].rstrip("\n")
            + "\n"
            + normalized[end:].lstrip("\n")
        )

    if "</body>" not in normalized:
        raise ValueError("blrec webapp index has no closing body tag")

    injection = build_navigation_injection(dashboard_port, repository_url)
    return normalized.replace("</body>", f"{injection}\n\n</body>", 1)


def _manifest_bytes(manifest: dict[str, Any]) -> bytes:
    return (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def patch_blrec_webapp_navigation(
    webapp_dir: str | Path,
    *,
    dashboard_port: int = 2234,
    repository_url: str = DEFAULT_REPOSITORY_URL,
) -> bool:
    """Patch blrec's installed webapp and its Angular service-worker hash."""
    directory = Path(webapp_dir)
    index_path = directory / "index.html"
    manifest_path = directory / "ngsw.json"

    original_index = index_path.read_text(encoding="utf-8-sig")
    patched_index = inject_studio_navigation(
        original_index,
        dashboard_port,
        repository_url,
    )
    patched_bytes = patched_index.encode("utf-8")
    index_changed = index_path.read_bytes() != patched_bytes

    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    hash_table = manifest.setdefault("hashTable", {})
    index_hash = hashlib.sha1(patched_bytes).hexdigest()
    manifest_changed = hash_table.get("/index.html") != index_hash
    if manifest_changed:
        hash_table["/index.html"] = index_hash
        manifest["timestamp"] = int(time.time() * 1000)

    if index_changed:
        index_path.write_bytes(patched_bytes)
    asset_changed = False
    for icon_name in _ICON_NAMES:
        target = directory / f"bilive-{icon_name}.svg"
        source_bytes = (_ICON_DIR / f"{icon_name}.svg").read_bytes()
        if not target.is_file() or target.read_bytes() != source_bytes:
            target.write_bytes(source_bytes)
            asset_changed = True
    if manifest_changed:
        manifest_path.write_bytes(_manifest_bytes(manifest))

    return index_changed or manifest_changed or asset_changed


def patch_installed_blrec_navigation(
    *,
    dashboard_port: int = 2234,
    repository_url: str = DEFAULT_REPOSITORY_URL,
) -> bool:
    import blrec

    package_dir = Path(blrec.__file__).resolve().parent
    return patch_blrec_webapp_navigation(
        package_dir / "data" / "webapp",
        dashboard_port=dashboard_port,
        repository_url=repository_url,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--webapp-dir")
    parser.add_argument("--dashboard-port", type=int, default=2234)
    parser.add_argument("--repository-url", default=DEFAULT_REPOSITORY_URL)
    args = parser.parse_args(argv)

    if args.webapp_dir:
        changed = patch_blrec_webapp_navigation(
            args.webapp_dir,
            dashboard_port=args.dashboard_port,
            repository_url=args.repository_url,
        )
    else:
        changed = patch_installed_blrec_navigation(
            dashboard_port=args.dashboard_port,
            repository_url=args.repository_url,
        )
    print("updated" if changed else "unchanged")
    return 0


__all__ = (
    "DEFAULT_REPOSITORY_URL",
    "INJECTION_END",
    "INJECTION_START",
    "LEGACY_LINK_ID",
    "build_navigation_injection",
    "inject_studio_navigation",
    "main",
    "patch_blrec_webapp_navigation",
    "patch_installed_blrec_navigation",
)


if __name__ == "__main__":
    raise SystemExit(main())
