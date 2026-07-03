from pathlib import Path
import pytest


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
    assert 'src="/app.js?v=20260627-4"' in texts["html"]
    assert 'href="/styles.css?v=20260627-4"' in texts["html"]

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
        "start-selected-slice-button",
        "stop-slice-button",
        "slice-progress-open-source",
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

def test_frontend_unified_publish_workbench_contract():
    texts = _frontend_texts()

    for element_id in [
        "publish-panel",
        "publish-queue-list",
        "publish-queue-count",
        "publish-refresh-button",
        "publish-wake-button",
        "publish-count-queued",
        "publish-count-active",
        "publish-count-published",
        "publish-count-failed",
        "segment-tags",
    ]:
        assert f'id="{element_id}"' in texts["html"]

    for js_contract in [
        "groupSourceRecordingsByRoom",
        "renderSourceGroup",
        "renderPublishQueue",
        "updateUploadMetrics",
        "parseTags",
        "segmentTags",
        "publishWakeButton",
        "publishRefreshButton",
        "refreshUploadDashboard();",
    ]:
        assert js_contract in texts["js"]

    for css_contract in [
        ".source-group",
        ".source-group-header",
        ".publish-panel",
        ".publish-overview",
        ".publish-queue-compact",
        ".tag-input",
    ]:
        assert css_contract in texts["css"]


def test_frontend_failure_inbox_contract():
    texts = _frontend_texts()

    for element_id in [
        "failure-inbox-panel",
        "failure-inbox-count",
        "failure-inbox-list",
    ]:
        assert f'id="{element_id}"' in texts["html"]

    for js_contract in [
        "buildFailureInboxItems",
        "failureSeverity",
        "renderFailureInbox",
        "focusFailureInboxItem",
        "failure-inbox-item",
        "failure-action-primary",
    ]:
        assert js_contract in texts["js"]

    for css_contract in [
        ".failure-inbox-panel",
        ".failure-inbox-list",
        ".failure-inbox-item",
        ".failure-action-primary",
    ]:
        assert css_contract in texts["css"]


def test_frontend_editable_density_range_contract():
    texts = _frontend_texts()

    for element_id in [
        "range-draft-status",
        "segment-save-render-button",
    ]:
        assert f'id="{element_id}"' in texts["html"]

    for js_contract in [
        "draftRange",
        "renderEditableRangeOverlay",
        "startRangeDrag",
        "setDraftRangeBoundary",
        "markRangeDraftFromInputs",
        "saveAndRenderCurrentSegment",
        "range-handle",
    ]:
        assert js_contract in texts["js"]

    for css_contract in [
        ".selected-range-overlay",
        ".range-handle",
        ".range-draft-status",
        ".range-draft-dirty",
    ]:
        assert css_contract in texts["css"]


def test_frontend_left_queue_is_up_owner_queue_contract():
    texts = _frontend_texts()

    assert "UP 主队列" in texts["html"]
    assert "审核队列" not in texts["html"]
    assert "定位到 UP 主队列" in texts["html"]
    assert "全部 UP 主" in texts["html"]
    assert "当前录播未出现在 UP 主队列" in texts["js"]
    for js_contract in [
        "sourceReviewCount",
        "sourceKeepCount",
        "sourceQueueSummary",
        "summarizeSourceGroup",
        "collapsedSourceGroups",
        "expandSourceGroupForTask",
        "aria-expanded",
    ]:
        assert js_contract in texts["js"]

    for css_contract in [
        ".up-source-main",
        ".up-source-meta",
        ".up-source-count",
        ".up-source-row",
        "width: calc(100% - 38px);",
        "box-sizing: border-box;",
        ".up-source-group.collapsed",
    ]:
        assert css_contract in texts["css"]


def test_frontend_review_workspace_expands_instead_of_first_screen_clamp():
    text = FRONTEND_CSS.read_text(encoding="utf-8")

    assert "Desktop review workbench should expand" in text
    assert "height: 540px;" not in text
    assert "height: 132px;" not in text
    assert "max-height: 330px;" not in text
    assert "grid-template-columns: 280px minmax(560px, 1fr) 320px;" in text
    assert "min-height: 680px;" in text
    assert "height: 108px;" in text


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
    assert "progress.source_task_id" in texts["js"]
    assert "gotoCurrentSourceRecording" in texts["js"]
    assert "scrollIntoView" in texts["js"]
    assert "progressOpenSourceButton.disabled = !progress.source_task_id" in texts["js"]
    assert "button.dataset.taskId = item.task_id" in texts["js"]
    assert "startSelectedSliceButton" in texts["js"]
    assert "selectedOnly = false" in texts["js"]
    assert "task_id: state.selectedSourceId" in texts["js"]
    assert "startSlicing({ selectedOnly: true })" in texts["js"]
    assert "progressOpenSourceButton?.addEventListener" in texts["js"]
    assert "const stoppable = status === \"running\" || status === \"stale\"" in texts["js"]
    assert "stopSliceButton.disabled = !stoppable" in texts["js"]
    assert "stopSliceButton.disabled = !running" not in texts["js"]
    assert "function assertStopSucceeded" in texts["js"]
    assert "status === \"stopped\" || status === \"idle\"" in texts["js"]
    assert "status === \"partial\"" in texts["js"]
    assert "throw new Error" in texts["js"]

def test_frontend_status_filter_matches_segment_review_counts():
    import shutil
    import subprocess
    import textwrap

    if shutil.which("node") is None:
        pytest.skip("node is required for frontend behavior test")

    script = textwrap.dedent(
        """
        const fs = require('fs');
        const source = fs.readFileSync('frontend/app.js', 'utf8');
        const names = ['sourceReviewCount', 'sourceKeepCount', 'sourceRecordingMatchesStatus'];
        for (const name of names) {
          const match = source.match(new RegExp(`function ${name}\\\\([^]*?\\\\n}`));
          if (!match) throw new Error(`missing ${name}`);
          eval(match[0]);
        }
        const doneWithReview = { status: 'done', summary_counts: { review: 1, judge_failed: 0 } };
        const doneWithJudgeFailure = { status: 'done', summary_counts: { review: 0, judge_failed: 1 } };
        const readyWithoutReview = { status: 'ready', summary_counts: {} };
        const failedRecording = { status: 'failed', summary_counts: {} };
        if (!sourceRecordingMatchesStatus(doneWithReview, 'todo')) throw new Error('review segment hidden from todo');
        if (!sourceRecordingMatchesStatus(doneWithJudgeFailure, 'todo')) throw new Error('judge_failed segment hidden from todo');
        if (!sourceRecordingMatchesStatus(doneWithJudgeFailure, 'failed')) throw new Error('judge_failed segment hidden from failed');
        if (!sourceRecordingMatchesStatus(readyWithoutReview, 'todo')) throw new Error('ready source hidden from todo');
        if (!sourceRecordingMatchesStatus(failedRecording, 'failed')) throw new Error('failed source hidden from failed');
        """
    )
    subprocess.run(["node", "-e", script], check=True)


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
