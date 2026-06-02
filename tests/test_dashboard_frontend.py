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


def test_frontend_contains_slice_diagnostics_panel():
    text = FRONTEND_HTML.read_text(encoding="utf-8")
    assert 'id="slice-diagnostics-panel"' in text
    assert 'id="slice-diagnostics-list"' in text
    assert "正在加载诊断信息" in text
    assert "/app.js?v=" in text
    assert "/styles.css?v=" in text


def test_frontend_contains_task_recovery_panel():
    text = FRONTEND_HTML.read_text(encoding="utf-8")
    assert 'id="task-panel"' in text
    assert 'id="task-list"' in text
    assert "任务队列" in text


def test_frontend_fetches_tasks_and_calls_recovery_endpoints():
    text = FRONTEND_JS.read_text(encoding="utf-8")
    assert 'request(`/api/tasks${query}`)' in text
    assert 'renderTaskList' in text
    assert '`/api/tasks/${encodeURIComponent(task.task_id)}/${action}`' in text
    assert "workerError" in text
    assert "cancel-pending" in text
    assert "mark-done" in text
    assert "requeue" in text


def test_frontend_contains_quality_metadata_fields():
    html = FRONTEND_HTML.read_text(encoding="utf-8")
    js = FRONTEND_JS.read_text(encoding="utf-8")
    assert 'id="quality-score"' in html
    assert 'id="burst-ratio"' in html
    assert "quality_score" in js
    assert "burst_ratio" in js


def test_frontend_contains_start_slice_button():
    text = FRONTEND_HTML.read_text(encoding="utf-8")
    assert 'id="start-slice-button"' in text
    assert "启动切片" in text


def test_frontend_polls_slice_progress_endpoint():
    text = FRONTEND_JS.read_text(encoding="utf-8")
    assert 'request("/api/slice-progress")' in text
    assert "renderSliceProgress" in text
    assert "setInterval" in text
    assert "进度已过期，请检查切片进程" in text
    assert "进度不可用" in text
    assert "暂无切片任务" in text


def test_frontend_polls_slice_diagnostics_endpoint():
    text = FRONTEND_JS.read_text(encoding="utf-8")
    assert 'request("/api/slice-diagnostics")' in text
    assert "renderSliceDiagnostics" in text
    assert "sliceDiagnosticsList" in text


def test_frontend_posts_start_slice_request():
    text = FRONTEND_JS.read_text(encoding="utf-8")
    assert 'request("/api/slice/start", {' in text
    assert 'method: "POST"' in text
    assert "startSlicing" in text


def test_frontend_triggers_local_pc_worker_once():
    text = FRONTEND_JS.read_text(encoding="utf-8")
    assert "PC_WORKER_RUN_ONCE_URL" in text
    assert "http://127.0.0.1:2235/api/worker/run-once" in text
    assert "startPcWorkerOnce" in text
    assert "pendingTasks" in text
    assert "start_pc_worker_api.ps1" in text
    assert "start_pipeline.ps1" not in text


def test_frontend_styles_slice_progress_panel():
    text = FRONTEND_CSS.read_text(encoding="utf-8")
    assert ".progress-panel" in text
    assert ".progress-fill" in text


def test_frontend_styles_slice_diagnostics_panel():
    text = FRONTEND_CSS.read_text(encoding="utf-8")
    assert ".diagnostics-panel" in text
    assert ".diagnostic-item" in text
    assert ".diagnostic-details" in text


def test_frontend_keeps_slice_rows_from_inheriting_global_button_height():
    text = FRONTEND_CSS.read_text(encoding="utf-8")
    assert ".slice-list .slice-row" in text
    assert "height: auto;" in text
    assert "align-items: stretch;" in text


# --- Keyboard shortcuts (Milestone 6) ---


def test_frontend_registers_keydown_event_listener():
    text = FRONTEND_JS.read_text(encoding="utf-8")
    assert 'document.addEventListener("keydown"' in text


def test_frontend_keyboard_shortcuts_map_k_d_r_j_l():
    text = FRONTEND_JS.read_text(encoding="utf-8")
    assert '"k"' in text or "'k'" in text
    assert '"d"' in text or "'d'" in text
    assert '"r"' in text or "'r'" in text
    assert '"j"' in text or "'j'" in text
    assert '"l"' in text or "'l'" in text


def test_frontend_keyboard_shortcuts_skip_input_and_textarea():
    text = FRONTEND_JS.read_text(encoding="utf-8")
    assert "activeElement" in text
    assert "INPUT" in text
    assert "TEXTAREA" in text


def test_frontend_j_key_selects_next_candidate():
    text = FRONTEND_JS.read_text(encoding="utf-8")
    assert "filteredSlices" in text
    assert "nextIndex" in text or "nextIdx" in text or "next_index" in text


def test_frontend_l_key_reloads_preview():
    text = FRONTEND_JS.read_text(encoding="utf-8")
    assert "previewVideo" in text
    assert "load()" in text or ".src" in text


def test_frontend_k_d_r_set_decision_and_save():
    text = FRONTEND_JS.read_text(encoding="utf-8")
    assert "saveFeedback" in text
    assert "keep" in text
    assert "drop" in text
    assert "review" in text
