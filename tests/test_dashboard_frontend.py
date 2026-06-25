from pathlib import Path


FRONTEND_HTML = Path("frontend/index.html")
FRONTEND_JS = Path("frontend/app.js")
FRONTEND_CSS = Path("frontend/styles.css")


def _frontend_texts():
    return {
        "html": FRONTEND_HTML.read_text(encoding="utf-8"),
        "js": FRONTEND_JS.read_text(encoding="utf-8"),
        "css": FRONTEND_CSS.read_text(encoding="utf-8"),
    }


def test_frontend_media_url_contract():
    text = FRONTEND_JS.read_text(encoding="utf-8")

    assert 'item.name.toLowerCase().endsWith(".flv")' in text
    assert "return `/api/preview/${encodeURIComponent(item.media_id)}`;" in text
    assert "return `/api/media/${encodeURIComponent(item.media_id)}`;" in text
    assert "elements.previewVideo.src = mediaUrl(item);" in text


def test_frontend_navigation_contract():
    text = FRONTEND_HTML.read_text(encoding="utf-8")

    assert text.count('href="http://127.0.0.1:2234/tasks"') == 0
    assert 'href="/tasks" data-view="tasks" aria-label="切片工作台"' in text
    assert 'href="/uploads"' in text
    assert 'href="/settings"' in text
    assert 'class="nav-item disabled"' not in text


def test_frontend_secondary_pages_and_scrollable_review_queue_contract():
    texts = _frontend_texts()

    for element_id in [
        "tasks-view",
        "uploads-view",
        "settings-view",
        "upload-queue-list",
        "upload-status-filter",
        "upload-refresh-button",
        "upload-wake-button",
        "settings-form",
        "settings-save-button",
    ]:
        assert f'id="{element_id}"' in texts["html"]

    assert "function escapeHtml" in texts["js"]
    assert "由 Windows 环境管理" in texts["js"]
    assert 'aria-label="切片工作台"' in texts["html"]
    assert "?????" not in texts["html"]
    assert 'src="/app.js?v=20260625-1"' in texts["html"]

    for contract in [
        "activateCurrentView",
        "refreshUploadDashboard",
        "renderUploadQueue",
        "loadDashboardSettings",
        "saveDashboardPreferences",
    ]:
        assert contract in texts["js"]

    assert ".source-list-panel" in texts["css"]
    assert "overflow-y: auto;" in texts["css"]
    assert "scrollbar-gutter: stable;" in texts["css"]


def test_frontend_dashboard_dom_contract():
    texts = _frontend_texts()

    for element_id in [
        "slice-progress-panel",
        "slice-progress-bar",
        "slice-progress-percent",
        "slice-diagnostics-panel",
        "slice-diagnostics-list",
        "task-panel",
        "task-list",
        "task-toggle",
        "source-recording-list",
        "source-preview-video",
        "density-chart",
        "segment-panel",
        "quality-score",
        "burst-ratio",
        "start-slice-button",
        "stop-slice-button",
    ]:
        assert f'id="{element_id}"' in texts["html"]

    for function_name in [
        "refreshSourceRecordings",
        "renderSourceRecordings",
        "selectSourceRecording",
        "renderDensityChart",
        "toggleTaskPanel",
    ]:
        assert function_name in texts["js"]


def test_frontend_modern_review_workspace_contract():
    texts = _frontend_texts()
    text = texts["html"]

    for class_name in [
        "studio-topbar",
        "overview-card",
        "review-workspace",
        "review-queue",
        "preview-stage",
        "density-card",
        "review-panel",
        "review-summary",
    ]:
        assert f'class="{class_name}' in text

    assert 'id="density-chart"' in text
    assert 'id="density-segment-layer"' in text
    assert "弹幕密度与候选区间" in text
    for element_id in [
        "task-state-pill",
        "task-state-label",
        "overview-source-total",
        "overview-task-total",
        "overview-review-total",
        "overview-keep-total",
    ]:
        assert f'id="{element_id}"' in text

    for presentation_contract in [
        "SOURCE_STATUS_PRESENTATION",
        "sourceStatusPresentation",
        "updateOverviewStats",
        "source-status-badge",
        "segment-status-",
        "renderTaskState",
        "segment_count || 0",
        "sourceReviewPriority",
    ]:
        assert presentation_contract in texts["js"]


def test_source_recording_refresh_ignores_stale_responses():
    text = FRONTEND_JS.read_text(encoding="utf-8")

    assert "let sourceRecordingRequestId = 0;" in text
    assert "const requestId = ++sourceRecordingRequestId;" in text
    assert "if (requestId !== sourceRecordingRequestId) return;" in text


def test_frontend_source_recording_status_filter_contract():
    texts = _frontend_texts()

    for option in [
        '<option value="todo">待处理</option>',
        '<option value="processing">处理中</option>',
        '<option value="failed">失败</option>',
        '<option value="done">已完成</option>',
        '<option value="has_keep">有保留片段</option>',
    ]:
        assert option in texts["html"]

    assert "function sourceRecordingMatchesStatus" in texts["js"]
    assert "filteredSourceRecordings" in texts["js"]
    assert "renderSourceRecordings();" in texts["js"]
    assert "stopSlicing" in texts["js"]
    assert "progress.display_title" in texts["js"]
    assert "progress.source_file" in texts["js"]
    assert "stopSliceButton.disabled = !running" in texts["js"]

def test_frontend_api_endpoint_contract():
    text = FRONTEND_JS.read_text(encoding="utf-8")

    for endpoint in [
        'request(`/api/tasks${query}`)',
        '`/api/tasks/${encodeURIComponent(task.task_id)}/${action}`',
        'request("/api/slice-progress")',
        'request("/api/slice-diagnostics")',
        'request("/api/slice/start", {',
        'request("/api/worker-trigger/status")',
        'request("/api/worker-trigger/stop", {',
    ]:
        assert endpoint in text

    for action in ["cancel-pending", "mark-done", "requeue"]:
        assert action in text


def test_frontend_worker_trigger_contract():
    texts = _frontend_texts()
    text = texts["js"]

    assert "PC_WORKER_RUN_ONCE_URL" not in text
    assert "PC_WORKER_STATUS_URL" not in text
    assert "http://127.0.0.1:2235" not in text
    assert "startPcWorkerOnce" not in text
    assert "pendingTasks" in text
    assert "worker_trigger" in text
    assert "describeWorkerTrigger" in text
    assert "dependency_unavailable" in text
    assert "start_pipeline.ps1" in text
    assert "pollActionJob" in text
    assert "status_url" in text
    assert "动作执行失败" in text
    assert "Windows 重任务节点" in texts["html"]
    assert "Windows 重任务节点" in text
    assert "PC worker" not in texts["html"]
    assert "PC Worker" not in texts["html"]
    assert "PC worker" not in text
    assert 'request("/api/worker-trigger/wake", {' in text
    assert "wakeWorkerOnPageLoad();" in text
    assert text.count('request("/api/worker-trigger/wake", {') == 2
    assert "Windows 重任务节点：启动中" in text


def test_frontend_style_contract_for_slice_panels_and_rows():
    text = FRONTEND_CSS.read_text(encoding="utf-8")

    for selector in [
        ".progress-panel",
        ".progress-fill",
        ".diagnostics-panel",
        ".diagnostic-item",
        ".diagnostic-details",
        ".slice-list .slice-row",
        ".density-area",
        ".segment-overlay-keep",
        ".segment-overlay-judge-failed",
    ]:
        assert selector in text

    assert "height: auto;" in text
    assert "align-items: stretch;" in text


def test_frontend_keyboard_shortcuts_contract():
    text = FRONTEND_JS.read_text(encoding="utf-8")

    assert 'document.addEventListener("keydown"' in text
    for key in ['"k"', '"d"', '"r"', '"j"', '"l"']:
        assert key in text
    for guard in ["activeElement", "INPUT", "TEXTAREA"]:
        assert guard in text
    assert "saveFeedback" in text
    assert "filteredSlices" in text
    assert "previewVideo" in text
