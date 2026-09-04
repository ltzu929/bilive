import hashlib
import json
import zipfile
from pathlib import Path


WHEEL = Path("wheel/blrec-2.0.0b4+bilive.8-py3-none-any.whl")


def test_dashboard_service_is_api_only():
    app_source = Path("src/dashboard/app.py").read_text(encoding="utf-8")

    assert "api = create_app()" in app_source
    assert "BILIVE_DASHBOARD_STATIC" not in app_source
    assert not any(Path("frontend").glob("index.html"))
    assert not any(Path("frontend").glob("app.js"))
    assert not any(Path("frontend").glob("styles.css"))


def test_recorder_surface_has_no_legacy_navigation_injection():
    recorder_app = Path("src/server/recorder_app.py").read_text(encoding="utf-8")

    assert "StudioApiMiddleware" in recorder_app
    assert "recorder_navigation" not in recorder_app
    assert not Path("src/server/recorder_navigation.py").exists()
    assert not Path("src/server/recorder_studio_bridge.html").exists()


def test_native_gateway_namespace_is_explicit():
    gateway = Path("src/server/studio_proxy.py").read_text(encoding="utf-8")

    assert "StudioApiMiddleware" in gateway
    assert 'or "/studio-api"' in gateway
    assert "/studio-proxy" not in gateway
    assert "get(\"referer\")" not in gateway


def test_native_source_video_only_loads_on_demand():
    template = Path(
        "frontend/src/app/studio/studio-slices.component.html"
    ).read_text(encoding="utf-8")
    with zipfile.ZipFile(WHEEL) as archive:
        javascript = b"\n".join(
            archive.read(name)
            for name in archive.namelist()
            if name.startswith("blrec/data/webapp/") and name.endswith(".js")
        )

    assert 'preload="none"' in template
    assert 'preload="metadata"' not in template
    assert b'"preload","none"' in javascript


def test_native_source_queue_tracks_stable_group_and_recording_ids():
    template = Path(
        "frontend/src/app/studio/studio-slices.component.html"
    ).read_text(encoding="utf-8")
    component = Path(
        "frontend/src/app/studio/studio-slices.component.ts"
    ).read_text(encoding="utf-8")
    with zipfile.ZipFile(WHEEL) as archive:
        javascript = b"\n".join(
            archive.read(name)
            for name in archive.namelist()
            if name.startswith("blrec/data/webapp/") and name.endswith(".js")
        )

    assert "trackBy: trackByGroup" in template
    assert "trackBy: trackByRecording" in template
    assert "trackByGroup(_index: number, group: { room: string }): string" in component
    assert "return group.room || 'all';" in component
    assert "trackByRecording(_index: number, item: StudioSourceRecording): string" in component
    assert "return item.task_id;" in component
    assert b"trackByGroup" in javascript
    assert b"trackByRecording" in javascript
    assert b"24px 0" in javascript


def test_native_wheel_uses_studio_api_namespace():
    with zipfile.ZipFile(WHEEL) as archive:
        javascript = b"\n".join(
            archive.read(name)
            for name in archive.namelist()
            if name.startswith("blrec/data/webapp/") and name.endswith(".js")
        )

    assert b"/studio-api" in javascript
    assert b"/api/source-recordings" not in javascript
    assert b"/api/slice/start" not in javascript
    assert b"/api/worker-trigger/" not in javascript


def test_native_wheel_allows_workspace_and_queue_to_scroll():
    with zipfile.ZipFile(WHEEL) as archive:
        compiled_styles = b"\n".join(
            archive.read(name)
            for name in archive.namelist()
            if name.startswith("blrec/data/webapp/")
            and name.endswith((".css", ".js"))
        )

    assert compiled_styles.count(
        b"overflow-x:hidden!important;overflow-y:auto!important"
    ) >= 2


def test_native_wheel_includes_source_built_queue_sorting():
    with zipfile.ZipFile(WHEEL) as archive:
        javascript = b"\n".join(
            archive.read(name)
            for name in archive.namelist()
            if name.startswith("blrec/data/webapp/") and name.endswith(".js")
        )
        index = archive.read("blrec/data/webapp/index.html")

    assert b"bilive-studio-queue-sort.js" not in index
    assert rb"\u6700\u65b0\u5f55\u64ad\u4f18\u5148" in javascript
    assert rb"\u6700\u65e9\u5f55\u64ad\u4f18\u5148" in javascript
    assert rb"\u6309 UP \u4e3b\u5206\u7ec4" in javascript


def test_native_wheel_includes_streamer_subtitle_preview():
    with zipfile.ZipFile(WHEEL) as archive:
        javascript = b"\n".join(
            archive.read(name)
            for name in archive.namelist()
            if name.startswith("blrec/data/webapp/") and name.endswith(".js")
        )

    assert (
        rb"\u793a\u4f8b\u5b57\u5e55\uff1a\u8fd9\u662f\u4e00\u6761"
        rb"\u4e3b\u64ad\u4e13\u5c5e\u5b57\u5e55"
    ) in javascript
    assert rb"\u6d4f\u89c8\u5668\u5185\u5373\u65f6\u9884\u89c8" in javascript


def test_native_wheel_service_worker_tracks_patched_assets():
    with zipfile.ZipFile(WHEEL) as archive:
        stylesheet_name = next(
            name
            for name in archive.namelist()
            if name.startswith("blrec/data/webapp/styles.") and name.endswith(".css")
        )
        manifest = json.loads(archive.read("blrec/data/webapp/ngsw.json"))

        assets = {
            f"/{Path(stylesheet_name).name}": archive.read(stylesheet_name),
            "/index.html": archive.read("blrec/data/webapp/index.html"),
        }

    app_urls = next(
        group["urls"] for group in manifest["assetGroups"] if group["name"] == "app"
    )
    for public_path, contents in assets.items():
        assert public_path in app_urls
        assert manifest["hashTable"][public_path] == hashlib.sha1(contents).hexdigest()
