from pathlib import Path


FRONTEND_HTML = Path("frontend/index.html")
FRONTEND_JS = Path("frontend/app.js")


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
    assert 'href="http://127.0.0.1:2234/"' in text
    assert 'href="/tasks"' in text
    assert 'aria-disabled="true"' in text


def test_slice_link_remains_active_and_unimplemented_items_are_disabled():
    text = FRONTEND_HTML.read_text(encoding="utf-8")
    assert '<a class="nav-item active" href="/tasks">切片</a>' in text
    assert '<span class="nav-item disabled" aria-disabled="true">上传</span>' in text
    assert '<span class="nav-item disabled" aria-disabled="true">设置</span>' in text
