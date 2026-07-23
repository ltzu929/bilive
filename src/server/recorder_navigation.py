"""Add the Bilive Studio workbench entry to blrec's packaged web UI."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any


INJECTION_START = "<!-- bilive-studio-navigation:start -->"
INJECTION_END = "<!-- bilive-studio-navigation:end -->"

_INJECTION_TEMPLATE = r"""
<!-- bilive-studio-navigation:start -->
<style id="bilive-studio-navigation-style">
  #bilive-studio-nav > .anticon {
    font-size: 16px;
    line-height: 0;
    vertical-align: -0.125em;
  }
  #bilive-studio-nav a {
    color: inherit;
  }
</style>
<script id="bilive-studio-navigation-script">
(() => {
  const navId = "bilive-studio-nav";
  const dashboardPort = __DASHBOARD_PORT__;

  function copyAngularScope(source, target) {
    if (!source) return;
    for (const name of source.getAttributeNames()) {
      if (name.startsWith("_ngcontent-")) {
        target.setAttribute(name, "");
      }
    }
  }

  function mountNavigation() {
    if (document.getElementById(navId)) return;

    const menu = document.querySelector("nav.sidebar-menu ul.ant-menu");
    const firstItem = menu && menu.querySelector("li.ant-menu-item");
    if (!menu || !firstItem) return;

    const item = document.createElement("li");
    item.id = navId;
    item.className = "ant-menu-item";
    item.style.paddingLeft = firstItem.style.paddingLeft || "24px";
    item.title = "切片工作台";
    copyAngularScope(firstItem, item);

    const icon = document.createElement("i");
    icon.className = "anticon anticon-scissor";
    icon.setAttribute("aria-hidden", "true");
    icon.innerHTML = '<svg viewBox="64 64 896 896" focusable="false" fill="currentColor" width="1em" height="1em"><path d="M567.1 512l318.5-319.3c5-5 1.5-13.7-5.6-13.7h-90.5c-2.1 0-4.2.8-5.6 2.3l-273.3 274-90.2-90.5c12.5-22.1 19.7-47.6 19.7-74.8 0-83.9-68.1-152-152-152S136 206.1 136 290s68.1 152 152 152c27.7 0 53.6-7.4 75.9-20.3l90 90.3-90.1 90.3A151.04 151.04 0 00288 582c-83.9 0-152 68.1-152 152s68.1 152 152 152 152-68.1 152-152c0-27.2-7.2-52.7-19.7-74.8l90.2-90.5 273.3 274c1.5 1.5 3.5 2.3 5.6 2.3H880c7.1 0 10.7-8.6 5.6-13.7L567.1 512zM288 370c-44.1 0-80-35.9-80-80s35.9-80 80-80 80 35.9 80 80-35.9 80-80 80zm0 444c-44.1 0-80-35.9-80-80s35.9-80 80-80 80 35.9 80 80-35.9 80-80 80z"></path></svg>';
    copyAngularScope(firstItem.querySelector("i"), icon);

    const label = document.createElement("span");
    copyAngularScope(firstItem.querySelector("span"), label);

    const link = document.createElement("a");
    link.href = `${location.protocol}//${location.hostname}:${dashboardPort}/tasks`;
    link.textContent = "切片";
    link.title = "切片工作台";
    link.setAttribute("aria-label", "切片工作台");
    link.addEventListener("click", (event) => event.stopPropagation());
    copyAngularScope(firstItem.querySelector("a"), link);

    label.appendChild(link);
    item.append(icon, label);
    firstItem.insertAdjacentElement("afterend", item);
  }

  mountNavigation();
  new MutationObserver(mountNavigation).observe(document.documentElement, {
    childList: true,
    subtree: true,
  });
})();
</script>
<!-- bilive-studio-navigation:end -->
""".strip()


def build_navigation_injection(dashboard_port: int = 2234) -> str:
    normalized_port = int(dashboard_port)
    if not 1 <= normalized_port <= 65535:
        raise ValueError("dashboard_port must be between 1 and 65535")
    return _INJECTION_TEMPLATE.replace("__DASHBOARD_PORT__", str(normalized_port))


def inject_studio_navigation(html: str, dashboard_port: int = 2234) -> str:
    """Return a normalized blrec index with one project-owned nav injection."""
    normalized = html.replace("\r\n", "\n").replace("\r", "\n")
    start = normalized.find(INJECTION_START)
    if start >= 0:
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

    injection = build_navigation_injection(dashboard_port)
    return normalized.replace("</body>", f"{injection}\n\n</body>", 1)


def _manifest_bytes(manifest: dict[str, Any]) -> bytes:
    return (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def patch_blrec_webapp_navigation(
    webapp_dir: str | Path,
    *,
    dashboard_port: int = 2234,
) -> bool:
    """Patch blrec's installed webapp and its Angular service-worker hash."""
    directory = Path(webapp_dir)
    index_path = directory / "index.html"
    manifest_path = directory / "ngsw.json"

    original_index = index_path.read_text(encoding="utf-8-sig")
    patched_index = inject_studio_navigation(original_index, dashboard_port)
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
    if manifest_changed:
        manifest_path.write_bytes(_manifest_bytes(manifest))

    return index_changed or manifest_changed


def patch_installed_blrec_navigation(*, dashboard_port: int = 2234) -> bool:
    import blrec

    package_dir = Path(blrec.__file__).resolve().parent
    return patch_blrec_webapp_navigation(
        package_dir / "data" / "webapp",
        dashboard_port=dashboard_port,
    )


__all__ = (
    "INJECTION_END",
    "INJECTION_START",
    "build_navigation_injection",
    "inject_studio_navigation",
    "patch_blrec_webapp_navigation",
    "patch_installed_blrec_navigation",
)
