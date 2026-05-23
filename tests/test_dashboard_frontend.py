from pathlib import Path


FRONTEND_HTML = Path("frontend/index.html")
FRONTEND_JS = Path("frontend/app.js")
FRONTEND_CSS = Path("frontend/styles.css")


def test_mp4_media_uses_original_media_endpoint():
    text = FRONTEND_JS.read_text(encoding="utf-8")
    assert 'item.name.toLowerCase().endsWith(".flv")' in text
    assert "return `/api/media/${encodeURIComponent(item.media_id)}`;" in text


def test_flv_media_uses_preview_endpoint():
    text = FRONTEND_JS.read_text(encoding="utf-8")
    assert "return `/api/preview/${encodeURIComponent(item.media_id)}`;" in text


def test_render_details_passes_item_to_media_url():
    text = FRONTEND_JS.read_text(encoding="utf-8")
    assert "elements.previewVideo.src = mediaUrl(item);" in text


def test_navigation_does_not_map_multiple_items_to_blrec_tasks():
    text = FRONTEND_HTML.read_text(encoding="utf-8")
    assert text.count('href="http://127.0.0.1:2234/tasks"') == 0
    assert 'href="/tasks"' in text
    assert 'aria-disabled="true"' in text


def test_slice_link_remains_active_and_unimplemented_items_are_disabled():
    text = FRONTEND_HTML.read_text(encoding="utf-8")
    assert '<a class="nav-item active" href="/tasks">' in text
    assert text.count('class="nav-item disabled" aria-disabled="true"') >= 2


def test_frontend_contains_slice_progress_panel():
    text = FRONTEND_HTML.read_text(encoding="utf-8")
    assert 'id="slice-progress-panel"' in text
    assert 'id="slice-progress-bar"' in text
    assert 'id="slice-progress-percent"' in text


def test_frontend_polls_slice_progress_endpoint():
    text = FRONTEND_JS.read_text(encoding="utf-8")
    assert 'request("/api/slice-progress")' in text
    assert "renderSliceProgress" in text
    assert "setInterval" in text


def test_frontend_styles_slice_progress_panel():
    text = FRONTEND_CSS.read_text(encoding="utf-8")
    assert ".progress-panel" in text
    assert ".progress-fill" in text
