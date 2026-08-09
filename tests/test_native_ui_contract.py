from pathlib import Path


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
