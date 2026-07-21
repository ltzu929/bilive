const ICONS = {
  record: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="3"/></svg>',
  scissor: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="6" cy="7" r="3"/><circle cx="6" cy="17" r="3"/><path d="M8.5 8.5 20 20M8.5 15.5 20 4"/></svg>',
  upload: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 16V4"/><path d="m7 9 5-5 5 5"/><path d="M20 16v4H4v-4"/></svg>',
  setting: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1-2 2-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.6v.2h-3v-.2a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1-2-2 .1-.1A1.7 1.7 0 0 0 7.2 15a1.7 1.7 0 0 0-1.6-1H5.4v-3h.2a1.7 1.7 0 0 0 1.6-1 1.7 1.7 0 0 0-.3-1.9l-.1-.1 2-2 .1.1a1.7 1.7 0 0 0 1.9.3 1.7 1.7 0 0 0 1-1.6V4.6h3v.2a1.7 1.7 0 0 0 1 1.6 1.7 1.7 0 0 0 1.9-.3l.1-.1 2 2-.1.1a1.7 1.7 0 0 0-.3 1.9 1.7 1.7 0 0 0 1.6 1h.2v3H21a1.7 1.7 0 0 0-1.6 1Z"/></svg>',
  fold: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 4h12v16H6z"/><path d="M10 4v16"/></svg>',
  unfold: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 4h12v16H6z"/><path d="M14 4v16"/></svg>',
};

document.querySelectorAll(".nav-icon[data-icon]").forEach((element) => {
  element.innerHTML = ICONS[element.dataset.icon] || "";
});

const appShell = document.getElementById("app-shell");
const siderToggle = document.getElementById("sider-toggle");
const siderIcon = siderToggle?.querySelector(".nav-icon");

function applyCollapsed(collapsed) {
  appShell.classList.toggle("collapsed", collapsed);
  if (siderIcon) {
    siderIcon.dataset.icon = collapsed ? "unfold" : "fold";
    siderIcon.innerHTML = ICONS[siderIcon.dataset.icon] || "";
  }
  localStorage.setItem("sider-collapsed", collapsed ? "1" : "");
}

if (siderToggle) {
  siderToggle.addEventListener("click", () => {
    applyCollapsed(!appShell.classList.contains("collapsed"));
  });
  if (localStorage.getItem("sider-collapsed") === "1") applyCollapsed(true);
}

let sourceRecordingRequestId = 0;
// Guards refreshSourceDetail so a late-arriving response (e.g. from a 2s
// auto-refresh that raced with a user click) cannot overwrite a newer detail
// or reset the user's segment selection to the first segment.
let sourceDetailRequestId = 0;

const state = {
  slices: [],
  tasks: [],
  sourceRecordings: [],
  selectedSourceId: "",
  selectedSegmentId: "",
  sourceDetail: null,
  taskPanelCollapsed: false,
  selectedId: "",
  decision: "review",
  currentSliceProgress: null,
  collapsedSourceGroups: new Set(),
  draftRange: null,
  rangeDrag: null,
  failureInboxExpanded: false,
};

const elements = {
  roomFilter: document.querySelector("#room-filter"),
  statusFilter: document.querySelector("#status-filter"),
  startSliceButton: document.querySelector("#start-slice-button"),
  startSelectedSliceButton: document.querySelector("#start-selected-slice-button"),
  stopSliceButton: document.querySelector("#stop-slice-button"),
  refreshButton: document.querySelector("#refresh-button"),
  workerBadge: document.querySelector("#worker-badge"),
  sliceCount: document.querySelector("#slice-count"),
  sliceList: document.querySelector("#slice-list"),
  error: document.querySelector("#error"),
  previewVideo: document.querySelector("#preview-video"),
  sourceRecording: document.querySelector("#source-recording"),
  densityCore: document.querySelector("#density-core"),
  contextWindow: document.querySelector("#context-window"),
  danmakuCount: document.querySelector("#danmaku-count"),
  burstRank: document.querySelector("#burst-rank"),
  burstRatio: document.querySelector("#burst-ratio"),
  qualityScore: document.querySelector("#quality-score"),
  fileSize: document.querySelector("#file-size"),
  qualityReason: document.querySelector("#quality-reason"),
  manualStart: document.querySelector("#manual-start"),
  manualEnd: document.querySelector("#manual-end"),
  saveButton: document.querySelector("#save-button"),
  decisionButtons: Array.from(document.querySelectorAll("[data-decision]")),
  progressPanel: document.querySelector("#slice-progress-panel"),
  progressTitle: document.querySelector("#slice-progress-title"),
  progressMessage: document.querySelector("#slice-progress-message"),
  progressSource: document.querySelector("#slice-progress-source"),
  progressFile: document.querySelector("#slice-progress-file"),
  progressCount: document.querySelector("#slice-progress-count"),
  progressPercent: document.querySelector("#slice-progress-percent"),
  progressBar: document.querySelector("#slice-progress-bar"),
  progressOpenSourceButton: document.querySelector("#slice-progress-open-source"),
  sliceDiagnosticsList: document.querySelector("#slice-diagnostics-list"),
  sliceDiagnosticsSource: document.querySelector("#slice-diagnostics-source"),
  taskPanel: document.querySelector("#task-panel"),
  taskToggle: document.querySelector("#task-toggle"),
  taskList: document.querySelector("#task-list"),
  taskCount: document.querySelector("#task-count"),
  sourceRecordingList: document.querySelector("#source-recording-list"),
  sourceRecordingCount: document.querySelector("#source-recording-count"),
  sourcePreviewVideo: document.querySelector("#source-preview-video"),
  sourceFileSize: document.querySelector("#source-file-size"),
  sourceStatus: document.querySelector("#source-status"),
  sourceSummary: document.querySelector("#source-summary"),
  selectedSegmentRange: document.querySelector("#selected-segment-range"),
  densityChart: document.querySelector("#density-chart"),
  densitySegmentLayer: document.querySelector("#density-segment-layer"),
  segmentPanel: document.querySelector("#segment-panel"),
  segmentStatus: document.querySelector("#segment-status"),
  segmentTitle: document.querySelector("#segment-title"),
  segmentDescription: document.querySelector("#segment-description"),
  segmentTags: document.querySelector("#segment-tags"),
  segmentKeepButton: document.querySelector("#segment-keep-button"),
  segmentDropButton: document.querySelector("#segment-drop-button"),
  segmentRetryButton: document.querySelector("#segment-retry-button"),
  segmentRenderButton: document.querySelector("#segment-render-button"),
  subtitleFontSize: document.querySelector("#subtitle-font-size"),
  subtitleMarginV: document.querySelector("#subtitle-margin-v"),
  subtitleAlignment: document.querySelector("#subtitle-alignment"),
  subtitleOutline: document.querySelector("#subtitle-outline"),
  subtitleSaveButton: document.querySelector("#subtitle-save-button"),
  subtitleReburnButton: document.querySelector("#subtitle-reburn-button"),
  taskStatePill: document.querySelector("#task-state-pill"),
  taskStateLabel: document.querySelector("#task-state-label"),
  overviewSourceTotal: document.querySelector("#overview-source-total"),
  overviewTaskTotal: document.querySelector("#overview-task-total"),
  overviewReviewTotal: document.querySelector("#overview-review-total"),
  overviewKeepTotal: document.querySelector("#overview-keep-total"),
  failureInboxList: document.querySelector("#failure-inbox-list"),
  failureInboxCount: document.querySelector("#failure-inbox-count"),
  publishQueueList: document.querySelector("#publish-queue-list"),
  publishQueueCount: document.querySelector("#publish-queue-count"),
  publishRefreshButton: document.querySelector("#publish-refresh-button"),
  publishWakeButton: document.querySelector("#publish-wake-button"),
  performanceBody: document.querySelector("#performance-body"),
  performanceCount: document.querySelector("#performance-count"),
  performanceRefreshButton: document.querySelector("#performance-refresh-button"),
  rangeDraftStatus: document.querySelector("#range-draft-status"),
  segmentSaveRenderButton: document.querySelector("#segment-save-render-button"),
  segmentStrip: document.querySelector("#segment-strip"),
  segmentStripCount: document.querySelector("#segment-strip-count"),
};

function mediaUrl(item) {
  if (item.name.toLowerCase().endsWith(".flv")) {
    return `/api/preview/${encodeURIComponent(item.media_id)}`;
  }
  return `/api/media/${encodeURIComponent(item.media_id)}`;
}

async function request(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return response.json();
}

function showError(message) {
  elements.error.textContent = message;
  elements.error.classList.toggle("hidden", !message);
}

function formatBytes(value) {
  if (!value) return "-";
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

function formatRange(range) {
  if (!range) return "-";
  return `${Number(range.start).toFixed(1)}s - ${Number(range.end).toFixed(1)}s`;
}

function filteredSlices() {
  const status = elements.statusFilter.value;
  if (status === "all") return state.slices;
  return state.slices.filter((item) => item.decision === status);
}

function selectedSlice() {
  return filteredSlices().find((item) => item.id === state.selectedId) || null;
}

function ensureVisibleSelection() {
  const items = filteredSlices();
  if (!items.some((item) => item.id === state.selectedId)) {
    state.selectedId = items[0]?.id || "";
  }
}

const DECISION_TAG = {
  review: { cls: "tag-blue", label: "review" },
  keep: { cls: "tag-green", label: "keep" },
  drop: { cls: "tag-red", label: "drop" },
};

const TASK_STATUS_TAG = {
  ready: { cls: "tag-blue", label: "ready" },
  pending: { cls: "tag-orange", label: "pending" },
  processing: { cls: "tag-blue", label: "processing" },
  done: { cls: "tag-green", label: "done" },
  failed: { cls: "tag-red", label: "failed" },
  skipped: { cls: "tag-orange", label: "skipped" },
  stale: { cls: "tag-red", label: "stale" },
};

const SOURCE_STATUS_PRESENTATION = {
  ready: { label: "待处理", tone: "pending" },
  pending: { label: "待处理", tone: "pending" },
  processing: { label: "处理中", tone: "processing" },
  done: { label: "已完成", tone: "keep" },
  failed: { label: "失败", tone: "drop" },
  stale: { label: "待恢复", tone: "pending" },
  unknown: { label: "未知", tone: "neutral" },
};

const SEGMENT_STATUS_PRESENTATION = {
  review: { label: "待复核", tone: "review" },
  keep: { label: "保留", tone: "keep" },
  manual_keep: { label: "手动保留", tone: "keep" },
  judge_failed: { label: "判断失败", tone: "failed" },
  drop: { label: "已丢弃", tone: "drop" },
  not_queued: { label: "未入队", tone: "review" },
  queue_failed: { label: "入队失败", tone: "failed" },
};

function sourceStatusPresentation(status) {
  return SOURCE_STATUS_PRESENTATION[status] || SOURCE_STATUS_PRESENTATION.unknown;
}

function segmentStatusLabel(status) {
  return SEGMENT_STATUS_PRESENTATION[status] || {
    label: status || "待复核",
    tone: "review",
  };
}

function decisionTag(decision) {
  const config = DECISION_TAG[decision] || DECISION_TAG.review;
  const span = document.createElement("span");
  span.className = `tag ${config.cls}`;
  span.textContent = config.label;
  return span;
}

function taskStatusTag(status) {
  const config = TASK_STATUS_TAG[status] || { cls: "tag-blue", label: status || "unknown" };
  const span = document.createElement("span");
  span.className = `tag ${config.cls}`;
  span.textContent = config.label;
  return span;
}

function renderList() {
  if (!elements.sliceList || !elements.sliceCount) return;
  const items = filteredSlices();
  elements.sliceCount.textContent = `${items.length} items`;
  elements.sliceList.innerHTML = "";
  for (const item of items) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `slice-row${item.id === state.selectedId ? " active" : ""}`;

    const nameRow = document.createElement("span");
    nameRow.className = "slice-name";
    nameRow.textContent = item.name;
    if (item.refined) {
      const badge = document.createElement("span");
      badge.className = "refined-badge";
      badge.textContent = "refined";
      nameRow.appendChild(badge);
    }

    const metaRow = document.createElement("span");
    metaRow.className = "slice-meta";
    const room = document.createElement("span");
    room.textContent = item.room_id;
    const size = document.createElement("span");
    size.textContent = formatBytes(item.size_bytes);
    metaRow.append(room, document.createTextNode(" / "), size, decisionTag(item.decision));

    button.append(nameRow, metaRow);
    button.addEventListener("click", () => {
      state.selectedId = item.id;
      render();
    });
    elements.sliceList.appendChild(button);
  }
}

function syncDecisionButtons() {
  for (const button of elements.decisionButtons) {
    button.classList.toggle("active", button.dataset.decision === state.decision);
  }
}

function renderDetails() {
  if (!elements.previewVideo) return;
  const item = selectedSlice();
  elements.saveButton.disabled = !item;
  if (!item) {
    elements.previewVideo.removeAttribute("src");
    elements.sourceRecording.textContent = "-";
    elements.densityCore.textContent = "-";
    elements.contextWindow.textContent = "-";
    elements.danmakuCount.textContent = "-";
    elements.burstRank.textContent = "-";
    elements.burstRatio.textContent = "-";
    elements.qualityScore.textContent = "-";
    elements.fileSize.textContent = "-";
    elements.qualityReason.value = "";
    elements.manualStart.value = 0;
    elements.manualEnd.value = 0;
    state.decision = "review";
    syncDecisionButtons();
    return;
  }

  elements.previewVideo.src = mediaUrl(item);
  elements.sourceRecording.textContent = item.source_recording;
  elements.densityCore.textContent = formatRange(item.density_core);
  elements.contextWindow.textContent = formatRange(item.context_window);
  elements.danmakuCount.textContent = item.danmaku_count != null ? String(item.danmaku_count) : "-";
  elements.burstRank.textContent = item.burst_rank != null ? `#${item.burst_rank}` : "-";
  elements.burstRatio.textContent = item.burst_ratio != null ? `${item.burst_ratio}x` : "-";
  elements.qualityScore.textContent = item.quality_score != null ? `${Math.round(item.quality_score * 100)}%` : "-";
  elements.fileSize.textContent = formatBytes(item.size_bytes);
  elements.qualityReason.value = item.quality_reason || "";
  elements.manualStart.value = Number(item.manual_range?.start || 0);
  elements.manualEnd.value = Number(item.manual_range?.end || 0);
  state.decision = item.decision || "review";
  syncDecisionButtons();
}

function render() {
  ensureVisibleSelection();
  renderList();
  renderDetails();
}

function renderSliceProgress(progress) {
  state.currentSliceProgress = progress || null;
  const percent = Math.max(
    0,
    Math.min(100, Number(progress.current_slice_percent || 0)),
  );
  const status = progress.stale ? "stale" : (progress.status || "idle");
  const running = status === "running";
  const queued = status === "queued";
  const busy = running || queued;
  const stoppable = status === "running" || status === "stale";
  elements.progressPanel.dataset.status = status;
  elements.progressTitle.textContent = progress.phase_label || "空闲";
  elements.progressMessage.textContent = progress.stale
    ? "进度已过期，请检查切片进程"
    : (progress.error || progress.message || "暂无切片任务");
  elements.progressSource.textContent = progress.display_title || progress.source_name || "-";
  if (elements.progressFile) elements.progressFile.textContent = progress.source_file || progress.source_name || "-";
  elements.progressCount.textContent = `${Number(progress.current_slice || 0)}/${Number(progress.total_slices || 0)}`;
  elements.progressPercent.textContent = `${percent.toFixed(0)}%`;
  elements.progressBar.style.width = `${percent}%`;
  if (elements.progressOpenSourceButton) {
    elements.progressOpenSourceButton.disabled = !progress.source_task_id;
  }
  // Disable both start buttons while a slice is running OR queued, so neither
  // can re-submit a source that is already pending in the worker queue.
  elements.startSliceButton.disabled = busy;
  elements.startSliceButton.textContent = busy ? "切片中" : "启动切片";
  if (elements.stopSliceButton) elements.stopSliceButton.disabled = !stoppable;
  updateSelectedSliceButton();
  renderTaskState(status);
}

function renderTaskState(status) {
  if (!elements.taskStatePill || !elements.taskStateLabel) return;
  const presentation = {
    running: { tone: "running", label: "任务运行中" },
    queued: { tone: "running", label: "任务排队中" },
    complete: { tone: "complete", label: "本批已完成" },
    error: { tone: "error", label: "任务异常" },
    stale: { tone: "stale", label: "进度已过期" },
    idle: { tone: "idle", label: "等待任务" },
  }[status] || { tone: "idle", label: "等待任务" };
  elements.taskStatePill.className = `live-pill task-state-${presentation.tone}`;
  elements.taskStateLabel.textContent = presentation.label;
}

function renderSliceDiagnostics(payload) {
  const items = Array.isArray(payload.items) ? payload.items : [];
  elements.sliceDiagnosticsSource.textContent = payload.source_name || "-";
  elements.sliceDiagnosticsList.innerHTML = "";

  if (!items.length) {
    const empty = document.createElement("div");
    empty.className = "diagnostic-empty";
    empty.textContent = "暂无诊断信息";
    elements.sliceDiagnosticsList.appendChild(empty);
    return;
  }

  for (const item of items) {
    const row = document.createElement("article");
    row.className = `diagnostic-item diagnostic-${item.status || "info"}`;

    const marker = document.createElement("span");
    marker.className = "diagnostic-marker";

    const body = document.createElement("div");
    body.className = "diagnostic-body";

    const titleRow = document.createElement("div");
    titleRow.className = "diagnostic-title-row";
    const title = document.createElement("span");
    title.className = "diagnostic-item-title";
    title.textContent = item.title || "-";
    const message = document.createElement("span");
    message.className = "diagnostic-message";
    message.textContent = item.message || "";
    titleRow.append(title, message);

    const details = document.createElement("div");
    details.className = "diagnostic-details";
    for (const detail of item.details || []) {
      const pair = document.createElement("span");
      pair.className = "diagnostic-detail";
      const label = document.createElement("span");
      label.className = "diagnostic-detail-label";
      label.textContent = detail.label || "-";
      const value = document.createElement("span");
      value.className = "diagnostic-detail-value";
      value.textContent = detail.value || "-";
      pair.append(label, value);
      details.appendChild(pair);
    }

    body.append(titleRow, details);
    row.append(marker, body);
    elements.sliceDiagnosticsList.appendChild(row);
  }
}

function taskActions(task) {
  const status = task.status || "";
  const actions = [];
  if (status === "pending" || status === "stale") {
    actions.push({ action: "cancel-pending", label: "取消" });
  }
  if (status === "ready" || status === "done" || status === "failed") {
    actions.push({ action: "requeue", label: status === "done" ? "重跑" : "排队" });
  }
  if (status !== "done" && status !== "processing") {
    actions.push({ action: "mark-done", label: "标记完成" });
  }
  return actions;
}

function renderTaskList(tasks) {
  if (!elements.taskList || !elements.taskCount) return;
  elements.taskCount.textContent = `${tasks.length} items`;
  elements.taskList.innerHTML = "";
  updateOverviewStats();
  renderFailureInbox();

  if (!tasks.length) {
    const empty = document.createElement("div");
    empty.className = "task-empty";
    empty.textContent = "暂无任务";
    elements.taskList.appendChild(empty);
    return;
  }

  for (const task of tasks) {
    const row = document.createElement("article");
    row.className = `task-row task-${task.status || "unknown"}`;

    const main = document.createElement("div");
    main.className = "task-main";

    const title = document.createElement("div");
    title.className = "task-name";
    title.textContent = task.source_name || task.source_rel_path || "-";

    const meta = document.createElement("div");
    meta.className = "task-meta";
    const room = document.createElement("span");
    room.className = "task-room";
    room.textContent = task.room_name && task.room_name !== task.room_id
      ? `${task.room_name} (${task.room_id})`
      : task.room_id || "-";
    const size = document.createElement("span");
    size.className = "task-size";
    size.textContent = `${Number(task.source_size_mb || 0).toFixed(1)} MB`;
    meta.append(room);

    const statusCell = document.createElement("div");
    statusCell.className = "task-status-cell";
    statusCell.append(size, taskStatusTag(task.status));

    const message = document.createElement("div");
    message.className = "task-message";
    message.textContent = task.message || "";

    main.append(title, meta);

    const buttons = document.createElement("div");
    buttons.className = "task-actions";
    for (const config of taskActions(task)) {
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.taskAction = config.action;
      button.textContent = config.label;
      if (config.action === "cancel-pending") {
        button.className = "btn-danger";
      }
      button.addEventListener("click", () => runTaskAction(task, config.action));
      buttons.appendChild(button);
    }

    row.append(main, statusCell, message, buttons);
    elements.taskList.appendChild(row);
  }
}

function formatMegabytes(value) {
  const number = Number(value || 0);
  return number > 0 ? `${number.toFixed(1)} MB` : "-";
}

function sourceMediaUrl(detail) {
  if (!detail?.source_media_id) return "";
  return `/api/media/${encodeURIComponent(detail.source_media_id)}`;
}

function selectedSegment() {
  const segments = state.sourceDetail?.segments || [];
  return segments.find((segment) => segment.segment_id === state.selectedSegmentId) || null;
}

function segmentRangeLabel(segment) {
  if (!segment) return "-";
  const start = Number(segment.start_seconds || 0).toFixed(1);
  const end = Number(segment.end_seconds || 0).toFixed(1);
  return `${start}s - ${end}s`;
}

function renderSegmentStrip(segments = []) {
  if (!elements.segmentStrip || !elements.segmentStripCount) return;
  const items = Array.isArray(segments) ? segments : [];
  elements.segmentStripCount.textContent = `${items.length} 个候选`;
  elements.segmentStrip.innerHTML = "";

  if (!items.length) {
    const empty = document.createElement("div");
    empty.className = "segment-strip-empty";
    empty.textContent = "当前录播还没有候选片段";
    elements.segmentStrip.appendChild(empty);
    return;
  }

  for (const segment of items) {
    const status = segmentStatusLabel(segment.judge_status || "review");
    const button = document.createElement("button");
    button.type = "button";
    button.className = [
      "segment-chip",
      `segment-chip-${status.tone}`,
      segment.segment_id === state.selectedSegmentId ? "segment-chip-active" : "",
    ].filter(Boolean).join(" ");
    button.dataset.segmentId = segment.segment_id;

    const title = document.createElement("strong");
    title.textContent = segment.title
      || segment.quality_reason
      || segment.judge_error
      || "候选片段";

    const meta = document.createElement("span");
    meta.textContent = [
      segmentRangeLabel(segment),
      status.label,
      segment.quality_score != null ? `质量 ${Math.round(Number(segment.quality_score) * 100)}%` : "",
    ].filter(Boolean).join(" · ");

    button.append(title, meta);
    button.addEventListener("click", () => {
      if (elements.sourcePreviewVideo) {
        elements.sourcePreviewVideo.currentTime = Number(segment.start_seconds || 0);
        elements.sourcePreviewVideo.pause();
      }
      selectSegment(segment.segment_id);
    });
    elements.segmentStrip.appendChild(button);
  }
}

function sourceSummaryLabel(counts = {}) {
  return [
    `keep ${Number(counts.keep || 0) + Number(counts.manual_keep || 0)}`,
    `failed ${Number(counts.judge_failed || 0)}`,
    `drop ${Number(counts.drop || 0)}`,
  ].join(" / ");
}

function sourceReviewCount(counts = {}) {
  return Number(counts.review || 0) + Number(counts.judge_failed || 0);
}

function sourceKeepCount(counts = {}) {
  return Number(counts.keep || 0) + Number(counts.manual_keep || 0);
}

function sourceDateLabel(item) {
  const name = item.source_name || item.source_rel_path || "";
  const match = name.match(/(\d{8})-(\d{2})-(\d{2})-(\d{2})/);
  if (!match) return item.source_name || item.source_rel_path || "-";
  const [, yyyymmdd, hour, minute] = match;
  return `${yyyymmdd.slice(0, 4)}-${yyyymmdd.slice(4, 6)}-${yyyymmdd.slice(6, 8)} ${hour}:${minute} 直播`;
}

function sourceQueueSummary(item) {
  const counts = item.summary_counts || {};
  const candidates = Number(item.segment_count || 0);
  return [
    `${candidates} 个候选`,
    `待确认 ${sourceReviewCount(counts)}`,
    `保留 ${sourceKeepCount(counts)}`,
    `失败 ${Number(counts.judge_failed || 0)}`,
  ].join(" · ");
}

function summarizeSourceGroup(sources) {
  return sources.reduce(
    (summary, item) => {
      const counts = item.summary_counts || {};
      summary.sources += 1;
      summary.candidates += Number(item.segment_count || 0);
      summary.review += sourceReviewCount(counts);
      summary.keep += sourceKeepCount(counts);
      summary.failed += Number(counts.judge_failed || 0);
      return summary;
    },
    { sources: 0, candidates: 0, review: 0, keep: 0, failed: 0 },
  );
}

function sourceGroupForTask(taskId) {
  return state.sourceRecordings.find((item) => item.task_id === taskId)?.room_id || "";
}

function expandSourceGroupForTask(taskId) {
  const roomId = sourceGroupForTask(taskId);
  if (roomId) state.collapsedSourceGroups.delete(roomId);
}

function updateOverviewStats() {
  const sources = Array.isArray(state.sourceRecordings) ? state.sourceRecordings : [];
  const tasks = Array.isArray(state.tasks) ? state.tasks : [];
  const reviewCount = sources.reduce(
    (total, item) => total
      + sourceReviewCount(item.summary_counts),
    0,
  );
  const keepCount = sources.reduce(
    (total, item) => total
      + sourceKeepCount(item.summary_counts),
    0,
  );

  if (elements.overviewSourceTotal) elements.overviewSourceTotal.textContent = String(sources.length);
  if (elements.overviewTaskTotal) elements.overviewTaskTotal.textContent = String(tasks.length);
  if (elements.overviewReviewTotal) elements.overviewReviewTotal.textContent = String(reviewCount);
  if (elements.overviewKeepTotal) elements.overviewKeepTotal.textContent = String(keepCount);
}

function failureSeverity(item) {
  const values = {
    task_failed: 100,
    worker_failed: 90,
    render_failed: 70,
    judge_failed: 50,
    upload_failed: 20,
  };
  return values[item.kind] || 0;
}

function buildFailureInboxItems() {
  const items = [];
  for (const task of state.tasks || []) {
    if (task.status !== "failed") continue;
    items.push({
      kind: "task_failed",
      typeLabel: "任务失败",
      title: task.source_name || task.source_rel_path || "-",
      message: task.message || "整场切片任务失败，需要重新排队或标记完成。",
      actionLabel: "重新排队",
      sourceTaskId: task.task_id,
      roomId: task.room_id || "",
      task,
    });
  }

  for (const source of state.sourceRecordings || []) {
    const failed = Number(source.summary_counts?.judge_failed || 0);
    if (failed <= 0) continue;
    items.push({
      kind: "judge_failed",
      typeLabel: "判断失败",
      title: sourceDateLabel(source),
      message: `${failed} 个候选片段需要定位后重新分析或调整边界。`,
      actionLabel: "定位精修",
      sourceTaskId: source.task_id,
      roomId: source.room_id || "",
      segmentStatus: "judge_failed",
    });
  }

  for (const upload of uploadDashboardState.items || []) {
    if (upload.status !== "failed") continue;
    items.push({
      kind: "upload_failed",
      typeLabel: "投稿失败",
      title: upload.name || upload.video_path || "-",
      message: upload.last_error || "投稿队列失败，需要进入上传中心处理。",
      actionLabel: "查看投稿",
      upload,
    });
  }

  return items.sort((left, right) => (
    failureSeverity(right) - failureSeverity(left)
    || String(left.title).localeCompare(String(right.title), "zh-CN")
  ));
}

function renderFailureInbox() {
  if (!elements.failureInboxList || !elements.failureInboxCount) return;
  const items = buildFailureInboxItems();
  elements.failureInboxCount.textContent = `${items.length} 个待处理问题`;
  elements.failureInboxList.innerHTML = "";
  if (!items.length) {
    elements.failureInboxList.innerHTML = '<div class="task-empty">当前没有需要处理的失败项</div>';
    return;
  }

  // Avoid silently dropping low-severity failures: cap the collapsed view at 6
  // rows but surface a "+N 更多" affordance so the operator can reach the rest.
  const COLLAPSED_LIMIT = 6;
  const overLimit = items.length > COLLAPSED_LIMIT;
  const visible = overLimit && !state.failureInboxExpanded
    ? items.slice(0, COLLAPSED_LIMIT)
    : items;

  for (const item of visible) {
    const row = document.createElement("article");
    row.className = "failure-inbox-item";
    row.tabIndex = 0;
    row.dataset.failureKind = item.kind;

    const main = document.createElement("div");
    main.className = "failure-inbox-main";

    const type = document.createElement("span");
    type.className = "failure-inbox-type";
    type.textContent = item.typeLabel;

    const title = document.createElement("strong");
    title.className = "failure-inbox-title";
    title.textContent = item.title;

    const message = document.createElement("span");
    message.className = "failure-inbox-message";
    message.textContent = item.message;
    main.append(type, title, message);

    const action = document.createElement("button");
    action.type = "button";
    action.className = "failure-action-primary";
    action.textContent = item.actionLabel;
    action.addEventListener("click", (event) => {
      event.stopPropagation();
      executeFailureInboxAction(item).catch((error) => showError(error.message));
    });

    row.addEventListener("click", () => {
      focusFailureInboxItem(item).catch((error) => showError(error.message));
    });
    row.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      event.preventDefault();
      focusFailureInboxItem(item).catch((error) => showError(error.message));
    });

    row.append(main, action);
    elements.failureInboxList.appendChild(row);
  }

  if (overLimit) {
    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "failure-inbox-toggle";
    toggle.textContent = state.failureInboxExpanded
      ? "收起"
      : `+${items.length - COLLAPSED_LIMIT} 更多（共 ${items.length} 条）`;
    toggle.addEventListener("click", () => {
      state.failureInboxExpanded = !state.failureInboxExpanded;
      renderFailureInbox();
    });
    elements.failureInboxList.appendChild(toggle);
  }
}

async function focusFailureInboxItem(item) {
  if (item.kind === "upload_failed") {
    window.history.pushState({}, "", "/uploads");
    activateCurrentView();
    await refreshUploadDashboard();
    return;
  }
  if (!item.sourceTaskId) return;
  if (elements.statusFilter && elements.statusFilter.value !== "all") {
    elements.statusFilter.value = "all";
  }
  if (elements.roomFilter && item.roomId && elements.roomFilter.value !== item.roomId) {
    elements.roomFilter.value = item.roomId;
    await refreshSourceRecordings();
  }
  await selectSourceRecording(item.sourceTaskId);
  scrollSourceRecordingIntoView(item.sourceTaskId);
  if (item.segmentStatus) {
    const segment = (state.sourceDetail?.segments || []).find(
      (candidate) => candidate.judge_status === item.segmentStatus,
    );
    if (segment) {
      selectSegment(segment.segment_id);
      if (elements.sourcePreviewVideo) {
        elements.sourcePreviewVideo.currentTime = Number(segment.start_seconds || 0);
        elements.sourcePreviewVideo.pause();
      }
    }
  }
}

async function executeFailureInboxAction(item) {
  if (item.kind === "task_failed" && item.task) {
    await runTaskAction(item.task, "requeue");
    return;
  }
  await focusFailureInboxItem(item);
}

function sourceReviewPriority(item) {
  const counts = item.summary_counts || {};
  if (Number(counts.judge_failed || 0) > 0 || Number(counts.review || 0) > 0) return 3;
  if (Number(item.segment_count || 0) > 0) return 2;
  if (item.status === "processing" || item.status === "pending") return 1;
  return 0;
}


function sourceRecordingMatchesStatus(item, status) {
  if (!status || status === "all") return true;
  const counts = item.summary_counts || {};
  if (status === "todo") {
    return sourceReviewCount(counts) > 0
      || ["ready", "pending", "stale"].includes(item.status || "");
  }
  if (status === "processing") return item.status === "processing" || item.status === "running";
  if (status === "failed") return Number(counts.judge_failed || 0) > 0 || item.status === "failed";
  if (status === "done") return item.status === "done";
  if (status === "has_keep") {
    return Number(counts.keep || 0) + Number(counts.manual_keep || 0) > 0;
  }
  return true;
}

function filteredSourceRecordings() {
  const status = elements.statusFilter?.value || "all";
  return state.sourceRecordings.filter((item) => sourceRecordingMatchesStatus(item, status));
}

function sortedSourceRecordings() {
  return filteredSourceRecordings()
    .map((item, index) => ({ item, index }))
    .sort((left, right) => (
      sourceReviewPriority(right.item) - sourceReviewPriority(left.item)
      || left.index - right.index
    ))
    .map(({ item }) => item);
}

function ensureVisibleSourceSelection() {
  const items = sortedSourceRecordings();
  if (!items.some((item) => item.task_id === state.selectedSourceId)) {
    const preferredSource = items
      .filter((item) => Number(item.segment_count || 0) > 0)
      .sort((left, right) => sourceReviewPriority(right) - sourceReviewPriority(left))[0]
      || items[0];
    state.selectedSourceId = preferredSource?.task_id || "";
    state.selectedSegmentId = "";
    return true;
  }
  return false;
}

function updateSelectedSliceButton() {
  if (!elements.startSelectedSliceButton) return;
  const hasSelection = Boolean(state.selectedSourceId);
  const status = state.currentSliceProgress?.status;
  const busy = status === "running" || status === "queued";
  // Disable while a slice is running or queued so the "切当前录播" button
  // cannot be re-clicked (and re-submit the same source) before the worker
  // finishes. Called from renderSliceProgress and from startSlicing's finally.
  elements.startSelectedSliceButton.disabled = busy || !hasSelection;
  elements.startSelectedSliceButton.textContent = busy ? "切片中" : "切当前录播";
  elements.startSelectedSliceButton.title = hasSelection
    ? "只提交当前选中的录播"
    : "请先在 UP 主队列选择一场录播";
}

async function refreshSourceRecordings() {
  const requestId = ++sourceRecordingRequestId;
  const roomId = elements.roomFilter.value;
  const query = roomId ? `?room_id=${encodeURIComponent(roomId)}` : "";
  try {
    const sourceRecordings = await request(`/api/source-recordings${query}`);
    if (requestId !== sourceRecordingRequestId) return;
    state.sourceRecordings = sourceRecordings;
    ensureVisibleSourceSelection();
    renderSourceRecordings();
    if (state.selectedSourceId) {
      await refreshSourceDetail(state.selectedSourceId);
    } else {
      state.sourceDetail = null;
      renderSourceDetail();
    }
  } catch (error) {
    if (requestId !== sourceRecordingRequestId) return;
    showError(error.message);
  }
}

function renderSourceRow(item) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = `source-row up-source-row${item.task_id === state.selectedSourceId ? " active" : ""}`;
  button.dataset.taskId = item.task_id;

  const header = document.createElement("span");
  header.className = "source-row-header";

  const name = document.createElement("span");
  name.className = "source-name";
  name.textContent = sourceDateLabel(item);

  const status = sourceStatusPresentation(item.status);
  const statusBadge = document.createElement("span");
  statusBadge.className = `source-status-badge source-status-${status.tone}`;
  statusBadge.textContent = status.label;
  header.append(name, statusBadge);

  const meta = document.createElement("span");
  meta.className = "source-meta";
  meta.textContent = sourceQueueSummary(item);

  const summary = document.createElement("span");
  summary.className = "source-summary-line";
  summary.textContent = `${item.source_name || item.source_rel_path || "-"} / ${formatMegabytes(item.source_size_mb)}`;

  button.append(header, meta, summary);
  button.addEventListener("click", () => selectSourceRecording(item.task_id));
  return button;
}

function groupSourceRecordingsByRoom(items) {
  const groups = [];
  const byRoom = new Map();
  for (const item of items) {
    const roomId = item.room_id || "unknown";
    if (!byRoom.has(roomId)) {
      const group = {
        roomId,
        roomName: item.room_name || item.room_id || "-",
        sources: [],
      };
      byRoom.set(roomId, group);
      groups.push(group);
    }
    byRoom.get(roomId).sources.push(item);
  }
  return groups.map((group) => ({
    ...group,
    summary: summarizeSourceGroup(group.sources),
    collapsed: state.collapsedSourceGroups.has(group.roomId),
  }));
}

function renderSourceGroup(group) {
  const section = document.createElement("section");
  section.className = `source-group up-source-group${group.collapsed ? " collapsed" : ""}`;

  const header = document.createElement("button");
  header.type = "button";
  header.className = "source-group-header up-source-header";
  header.setAttribute("aria-expanded", group.collapsed ? "false" : "true");

  const main = document.createElement("span");
  main.className = "up-source-main";

  const chevron = document.createElement("span");
  chevron.className = "up-source-chevron";
  chevron.textContent = group.collapsed ? "›" : "⌄";

  const title = document.createElement("strong");
  title.textContent = group.roomName || group.roomId || "-";

  const meta = document.createElement("span");
  meta.className = "up-source-meta";
  meta.textContent = `待确认 ${group.summary.review} · 失败 ${group.summary.failed} · 已保留 ${group.summary.keep}`;
  main.append(chevron, title, meta);

  const count = document.createElement("span");
  count.className = "up-source-count";
  count.textContent = `${group.summary.candidates} 候选 / ${group.summary.sources} 场`;
  header.append(main, count);
  header.addEventListener("click", () => {
    if (state.collapsedSourceGroups.has(group.roomId)) {
      state.collapsedSourceGroups.delete(group.roomId);
    } else {
      state.collapsedSourceGroups.add(group.roomId);
    }
    renderSourceRecordings();
  });
  section.appendChild(header);

  if (!group.collapsed) {
    for (const item of group.sources) {
      section.appendChild(renderSourceRow(item));
    }
  }
  return section;
}

function renderSourceRecordings() {
  if (!elements.sourceRecordingList || !elements.sourceRecordingCount) return;
  const items = sortedSourceRecordings();
  elements.sourceRecordingCount.textContent = `${groupSourceRecordingsByRoom(items).length} 位 UP · ${items.length} 场录播`;
  elements.sourceRecordingList.innerHTML = "";
  updateOverviewStats();
  updateSelectedSliceButton();
  renderFailureInbox();

  if (!items.length) {
    const empty = document.createElement("div");
    empty.className = "task-empty";
    empty.textContent = "暂无录播";
    elements.sourceRecordingList.appendChild(empty);
    return;
  }

  for (const group of groupSourceRecordingsByRoom(items)) {
    elements.sourceRecordingList.appendChild(renderSourceGroup(group));
  }
}
function selectSourceRecording(taskId) {
  expandSourceGroupForTask(taskId);
  state.selectedSourceId = taskId;
  state.selectedSegmentId = "";
  state.draftRange = null;
  renderSourceRecordings();
  return refreshSourceDetail(taskId);
}

function scrollSourceRecordingIntoView(taskId) {
  expandSourceGroupForTask(taskId);
  renderSourceRecordings();
  const rows = elements.sourceRecordingList?.querySelectorAll("[data-task-id]") || [];
  for (const row of rows) {
    if (row.dataset.taskId !== taskId) continue;
    row.scrollIntoView({ block: "nearest", behavior: "smooth" });
    row.classList.add("source-row-locate");
    window.setTimeout(() => row.classList.remove("source-row-locate"), 1200);
    break;
  }
}

async function gotoCurrentSourceRecording() {
  const progress = state.currentSliceProgress || {};
  const taskId = progress.source_task_id || "";
  if (!taskId) return;

  if (elements.statusFilter && elements.statusFilter.value !== "all") {
    elements.statusFilter.value = "all";
  }
  if (elements.roomFilter && progress.room_id && elements.roomFilter.value !== progress.room_id) {
    elements.roomFilter.value = progress.room_id;
  }

  await refreshSourceRecordings();
  const target = state.sourceRecordings.find((item) => (
    item.task_id === taskId || item.source_rel_path === progress.source_rel_path
  ));
  if (!target) {
    showError("当前录播未出现在 UP 主队列");
    return;
  }
  await selectSourceRecording(target.task_id);
  scrollSourceRecordingIntoView(target.task_id);
}
async function refreshSourceDetail(taskId) {
  if (!taskId) return;
  const requestId = ++sourceDetailRequestId;
  const detail = await request(`/api/source-recordings/${encodeURIComponent(taskId)}`);
  if (requestId !== sourceDetailRequestId) return;
  state.sourceDetail = detail;
  if (!state.sourceDetail.segments?.some((segment) => segment.segment_id === state.selectedSegmentId)) {
    state.selectedSegmentId = state.sourceDetail.segments?.[0]?.segment_id || "";
  }
  renderSourceDetail();
}

function renderSourceDetail() {
  const detail = state.sourceDetail;
  if (!detail) {
    if (elements.sourcePreviewVideo) elements.sourcePreviewVideo.removeAttribute("src");
    if (elements.sourceRecording) elements.sourceRecording.textContent = "-";
    if (elements.sourceFileSize) elements.sourceFileSize.textContent = "-";
    renderSegmentStrip([]);
    renderSegmentPanel();
    renderDensityChart({ density_points: [], segments: [] });
    return;
  }

  const url = sourceMediaUrl(detail);
  if (url && elements.sourcePreviewVideo?.src !== new URL(url, window.location.href).href) {
    elements.sourcePreviewVideo.src = url;
  }
  if (elements.sourceRecording) elements.sourceRecording.textContent = detail.source_name || "-";
  if (elements.sourceFileSize) elements.sourceFileSize.textContent = formatMegabytes(detail.source_size_mb);
  if (elements.sourceStatus) elements.sourceStatus.textContent = detail.message || detail.status || "-";
  if (elements.sourceSummary) elements.sourceSummary.textContent = sourceSummaryLabel(detail.summary_counts);
  renderSegmentStrip(detail.segments || []);
  renderSegmentPanel();
  renderDensityChart(detail);
}

function renderDensityChart(detail) {
  if (!elements.densityChart || !elements.densitySegmentLayer) return;
  const points = Array.isArray(detail?.density_points) ? detail.density_points : [];
  const segments = Array.isArray(detail?.segments) ? detail.segments : [];
  const area = elements.densityChart.querySelector(".density-area");
  const maxEnd = Math.max(
    10,
    ...points.map((point) => Number(point.end_seconds || 0)),
    ...segments.map((segment) => Number(segment.end_seconds || 0)),
  );

  if (area) {
    if (!points.length) {
      area.setAttribute("d", "");
    } else {
      const top = points.map((point) => {
        const x = (Number(point.start_seconds || 0) / maxEnd) * 100;
        const y = 38 - Number(point.normalized || 0) * 34;
        return `${x.toFixed(2)} ${y.toFixed(2)}`;
      });
      const lastX = (Number(points[points.length - 1].end_seconds || maxEnd) / maxEnd) * 100;
      area.setAttribute("d", `M 0 38 L ${top.join(" L ")} L ${lastX.toFixed(2)} 38 Z`);
    }
  }

  elements.densitySegmentLayer.innerHTML = "";
  for (const segment of segments) {
    const status = segment.judge_status || "";
    const isKeep = status === "keep" || status === "manual_keep";
    const isFailed = status === "judge_failed";
    if (!isKeep && !isFailed) continue;

    const start = Number(segment.start_seconds || 0);
    const end = Number(segment.end_seconds || start);
    const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    rect.setAttribute("x", ((start / maxEnd) * 100).toFixed(2));
    rect.setAttribute("y", "3");
    rect.setAttribute("width", Math.max(((end - start) / maxEnd) * 100, 0.5).toFixed(2));
    rect.setAttribute("height", "34");
    rect.setAttribute("rx", "0");
    rect.classList.add(isKeep ? "segment-overlay-keep" : "segment-overlay-judge-failed");
    rect.addEventListener("click", () => {
      if (elements.sourcePreviewVideo) {
        elements.sourcePreviewVideo.currentTime = start;
        elements.sourcePreviewVideo.pause();
      }
      selectSegment(segment.segment_id);
    });
    elements.densitySegmentLayer.appendChild(rect);
  }
  renderEditableRangeOverlay(maxEnd);
}

function selectSegment(segmentId) {
  state.selectedSegmentId = segmentId;
  state.draftRange = null;
  renderSegmentStrip(state.sourceDetail?.segments || []);
  renderSegmentPanel();
  renderDensityChart(state.sourceDetail);
}

function ensureDraftRange(segment) {
  if (!segment) {
    state.draftRange = null;
    return null;
  }
  if (!state.draftRange || state.draftRange.segmentId !== segment.segment_id) {
    state.draftRange = {
      segmentId: segment.segment_id,
      start: Number(segment.start_seconds || 0),
      end: Number(segment.end_seconds || 0),
      dirty: false,
    };
  }
  return state.draftRange;
}

function selectedRangeDraft() {
  return ensureDraftRange(selectedSegment());
}

function updateRangeDraftStatus() {
  const draft = state.draftRange;
  if (!elements.rangeDraftStatus) return;
  const dirty = Boolean(draft?.dirty);
  elements.rangeDraftStatus.classList.toggle("range-draft-dirty", dirty);
  elements.rangeDraftStatus.textContent = dirty
    ? "区间有未保存修改。确认后请保存区间，或保存并重渲染。"
    : "区间未修改";
}

function updateRangeDraftControls({ seek = false, boundary = "start" } = {}) {
  const draft = state.draftRange;
  if (!draft) {
    if (elements.rangeDraftStatus) updateRangeDraftStatus();
    return;
  }
  if (elements.manualStart) elements.manualStart.value = Number(draft.start || 0).toFixed(1);
  if (elements.manualEnd) elements.manualEnd.value = Number(draft.end || 0).toFixed(1);
  if (elements.selectedSegmentRange) {
    elements.selectedSegmentRange.textContent = `${Number(draft.start || 0).toFixed(1)}s - ${Number(draft.end || 0).toFixed(1)}s`;
  }
  updateRangeDraftStatus();
  if (seek && elements.sourcePreviewVideo) {
    elements.sourcePreviewVideo.currentTime = boundary === "end" ? draft.end : draft.start;
    elements.sourcePreviewVideo.pause();
  }
}

function markRangeDraftDirty() {
  const segment = selectedSegment();
  const draft = selectedRangeDraft();
  if (!segment || !draft) return;
  const originalStart = Number(segment.start_seconds || 0);
  const originalEnd = Number(segment.end_seconds || 0);
  draft.dirty = Math.abs(draft.start - originalStart) > 0.05
    || Math.abs(draft.end - originalEnd) > 0.05;
}

function setDraftRangeBoundary(boundary, value, options = {}) {
  const draft = selectedRangeDraft();
  if (!draft) return;
  // If the selection changed under an in-flight drag (e.g. a 2s auto-refresh
  // swapped to another source recording), abort instead of writing the old
  // segment's captured maxEnd onto the new segment's draft.
  if (state.rangeDrag && draft.segmentId !== state.rangeDrag.segmentId) {
    return;
  }
  const number = Math.max(0, Number(value || 0));
  if (boundary === "start") {
    draft.start = Math.min(number, Math.max(0, draft.end - 0.1));
  } else {
    draft.end = Math.max(number, draft.start + 0.1);
  }
  markRangeDraftDirty();
  updateRangeDraftControls({ seek: Boolean(options.seek), boundary });
  if (state.rangeDrag) {
    // During a drag, update the overlay in place so we don't destroy the
    // handle element the pointer is dragging (which would drop the
    // .dragging fill and detach the pointerup target).
    updateRangeOverlayInPlace();
  } else {
    renderDensityChart(state.sourceDetail);
  }
}

function markRangeDraftFromInputs(event) {
  const draft = selectedRangeDraft();
  if (!draft) return;
  const start = Number(elements.manualStart?.value || 0);
  const end = Number(elements.manualEnd?.value || 0);
  draft.start = Math.max(0, Math.min(start, Math.max(0, end - 0.1)));
  draft.end = Math.max(end, draft.start + 0.1);
  markRangeDraftDirty();
  updateRangeDraftControls({
    seek: Boolean(event?.target),
    boundary: event?.target === elements.manualEnd ? "end" : "start",
  });
  renderDensityChart(state.sourceDetail);
}

function startRangeDrag(event, boundary, maxEnd) {
  event.preventDefault();
  const handle = event.currentTarget;
  const draft = selectedRangeDraft();
  if (!draft) return;
  // Capture the segment id and maxEnd at pointerdown; if the selection changes
  // before pointerup, setDraftRangeBoundary will refuse to keep writing.
  state.rangeDrag = {
    segmentId: draft.segmentId,
    boundary,
    maxEnd,
    handle,
  };
  handle.classList.add("dragging");
  const move = (pointerEvent) => {
    if (!state.rangeDrag) return;
    const box = elements.densityChart.getBoundingClientRect();
    const ratio = Math.min(1, Math.max(0, (pointerEvent.clientX - box.left) / Math.max(box.width, 1)));
    setDraftRangeBoundary(boundary, ratio * state.rangeDrag.maxEnd, { seek: true });
  };
  const stop = () => {
    if (state.rangeDrag?.handle) {
      state.rangeDrag.handle.classList.remove("dragging");
    }
    state.rangeDrag = null;
    document.removeEventListener("pointermove", move);
    document.removeEventListener("pointerup", stop);
    // Re-render once after the drag so the overlay binds fresh listeners and
    // reflects the final draft against the (possibly refreshed) chart.
    renderDensityChart(state.sourceDetail);
  };
  document.addEventListener("pointermove", move);
  document.addEventListener("pointerup", stop);
}

function updateRangeOverlayInPlace() {
  const draft = state.draftRange;
  const layer = elements.densitySegmentLayer?.querySelector(".editable-range-layer");
  if (!draft || !layer) return;
  const maxEnd = state.rangeDrag?.maxEnd;
  if (!maxEnd) return;
  const startX = (draft.start / maxEnd) * 100;
  const endX = (draft.end / maxEnd) * 100;
  const rect = layer.querySelector(".selected-range-overlay");
  if (rect) {
    rect.setAttribute("x", Math.min(startX, endX).toFixed(2));
    rect.setAttribute("width", Math.max(Math.abs(endX - startX), 0.5).toFixed(2));
  }
  const handles = layer.querySelectorAll(".range-handle");
  handles.forEach((handle) => {
    const boundary = handle.dataset.boundary;
    const x = boundary === "start" ? startX : endX;
    handle.setAttribute("x", (x - 0.45).toFixed(2));
  });
}

function renderEditableRangeOverlay(maxEnd) {
  const draft = selectedRangeDraft();
  if (!draft || !elements.densitySegmentLayer) return;
  // If a drag is in progress, keep the existing overlay (with its live
  // pointer listeners) rather than rebuilding it under the pointer.
  if (state.rangeDrag) return;
  const startX = (draft.start / maxEnd) * 100;
  const endX = (draft.end / maxEnd) * 100;
  const group = document.createElementNS("http://www.w3.org/2000/svg", "g");
  group.classList.add("editable-range-layer");

  const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
  rect.setAttribute("x", Math.min(startX, endX).toFixed(2));
  rect.setAttribute("y", "1.5");
  rect.setAttribute("width", Math.max(Math.abs(endX - startX), 0.5).toFixed(2));
  rect.setAttribute("height", "37");
  rect.setAttribute("rx", "0");
  rect.classList.add("selected-range-overlay");
  group.appendChild(rect);

  for (const [boundary, x] of [["start", startX], ["end", endX]]) {
    const handle = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    handle.setAttribute("x", (x - 0.45).toFixed(2));
    handle.setAttribute("y", "0.5");
    handle.setAttribute("width", "0.9");
    handle.setAttribute("height", "39");
    handle.setAttribute("rx", "0.45");
    handle.classList.add("range-handle");
    handle.dataset.boundary = boundary;
    handle.addEventListener("pointerdown", (event) => startRangeDrag(event, boundary, maxEnd));
    group.appendChild(handle);
  }
  elements.densitySegmentLayer.appendChild(group);
}

function renderSegmentPanel() {
  const segment = selectedSegment();
  const hasSegment = Boolean(segment);
  for (const element of [
    elements.segmentTitle,
    elements.segmentDescription,
    elements.segmentTags,
    elements.qualityReason,
    elements.manualStart,
    elements.manualEnd,
    elements.saveButton,
    elements.segmentKeepButton,
    elements.segmentDropButton,
    elements.segmentRetryButton,
    elements.segmentRenderButton,
    elements.segmentSaveRenderButton,
  ]) {
    if (element) element.disabled = !hasSegment;
  }

  if (!segment) {
    state.draftRange = null;
    if (elements.segmentStatus) {
      elements.segmentStatus.className = "panel-meta status-pill segment-status-review";
      elements.segmentStatus.textContent = "-";
    }
    if (elements.selectedSegmentRange) elements.selectedSegmentRange.textContent = "-";
    if (elements.segmentTitle) elements.segmentTitle.value = "";
    if (elements.segmentDescription) elements.segmentDescription.value = "";
    if (elements.segmentTags) elements.segmentTags.value = "";
    if (elements.qualityReason) elements.qualityReason.value = "";
    if (elements.manualStart) elements.manualStart.value = 0;
    if (elements.manualEnd) elements.manualEnd.value = 0;
    if (elements.danmakuCount) elements.danmakuCount.textContent = "-";
    if (elements.qualityScore) elements.qualityScore.textContent = "-";
    if (elements.burstRatio) elements.burstRatio.textContent = "-";
    updateRangeDraftStatus();
    return;
  }

  const draft = ensureDraftRange(segment);
  if (elements.segmentStatus) {
    const status = segment.judge_status || "review";
    const normalizedStatus = status === "manual_keep" ? "keep" : status.replaceAll("_", "-");
    elements.segmentStatus.className = `panel-meta status-pill segment-status-${normalizedStatus}`;
    elements.segmentStatus.textContent = status;
  }
  if (elements.segmentTitle) elements.segmentTitle.value = segment.title || "";
  if (elements.segmentDescription) elements.segmentDescription.value = segment.description || "";
  if (elements.segmentTags) elements.segmentTags.value = Array.isArray(segment.tags) ? segment.tags.join(", ") : "";
  // Surface upload-queue failures on the segment card. A manual_keep that
  // could not be inserted into upload_queue leaves upload_status="queue_failed"
  // and an upload_error reason; without this the operator sees a "kept"
  // segment that silently never publishes.
  const queueFailure = segment.upload_status === "queue_failed"
    ? `入队失败：${segment.upload_error || "未知原因"}`
    : "";
  if (elements.qualityReason) {
    const reason = segment.quality_reason || segment.judge_error || "";
    elements.qualityReason.value = queueFailure
      ? `${reason}${reason ? "\n" : ""}${queueFailure}`
      : reason;
  }
  if (draft) updateRangeDraftControls();
  if (elements.danmakuCount) elements.danmakuCount.textContent = segment.danmaku_count != null ? String(segment.danmaku_count) : "-";
  if (elements.qualityScore) {
    elements.qualityScore.textContent = segment.quality_score != null
      ? `${Math.round(Number(segment.quality_score) * 100)}%`
      : "-";
  }
  if (elements.burstRatio) elements.burstRatio.textContent = segment.burst_ratio != null ? `${segment.burst_ratio}x` : "-";
  populateSubtitleStyle(segment);
}

function populateSubtitleStyle(segment) {
  const style = (segment && segment.subtitle_style) || {};
  if (elements.subtitleFontSize) elements.subtitleFontSize.value = style.font_size != null ? String(style.font_size) : "";
  if (elements.subtitleMarginV) elements.subtitleMarginV.value = style.margin_v != null ? String(style.margin_v) : "";
  if (elements.subtitleAlignment) elements.subtitleAlignment.value = style.alignment != null ? String(style.alignment) : "";
  if (elements.subtitleOutline) elements.subtitleOutline.value = style.outline != null ? String(style.outline) : "";
}

function collectSubtitleStyle() {
  const payload = {};
  const fontSize = elements.subtitleFontSize?.value;
  const marginV = elements.subtitleMarginV?.value;
  const alignment = elements.subtitleAlignment?.value;
  const outline = elements.subtitleOutline?.value;
  if (fontSize !== undefined && fontSize !== "") payload.font_size = Number(fontSize);
  if (marginV !== undefined && marginV !== "") payload.margin_v = Number(marginV);
  if (alignment !== undefined && alignment !== "") payload.alignment = Number(alignment);
  if (outline !== undefined && outline !== "") payload.outline = Number(outline);
  return payload;
}

async function saveSubtitleStyle() {
  await runSegmentAction("subtitle-style", collectSubtitleStyle());
}

async function reburnCurrentSubtitles() {
  await saveSubtitleStyle();
  await runSegmentAction("reburn");
}

async function runSegmentAction(action, payload = null) {
  const segment = selectedSegment();
  if (!segment) return;
  const options = { method: "POST" };
  if (payload) options.body = JSON.stringify(payload);
  const updated = await request(`/api/segments/${encodeURIComponent(segment.segment_id)}/${action}`, options);
  if (updated.status_url) {
    if (elements.segmentStatus) elements.segmentStatus.textContent = "queued";
    const worker = describeWorkerTrigger(updated.worker_trigger);
    if (worker.message) showError(worker.message);
    await pollActionJob(updated.status_url);
    await refreshSourceDetail(state.selectedSourceId);
    return;
  }
  const segments = state.sourceDetail?.segments || [];
  const index = segments.findIndex((item) => item.segment_id === updated.segment_id);
  if (index >= 0) segments[index] = updated;
  state.selectedSegmentId = updated.segment_id;
  renderSourceDetail();
}

async function pollActionJob(statusUrl) {
  for (let attempt = 0; attempt < 120; attempt += 1) {
    const job = await request(statusUrl);
    if (elements.segmentStatus) elements.segmentStatus.textContent = job.status || "pending";
    if (job.status === "done") return job.result || {};
    if (job.status === "failed") {
      throw new Error(`动作执行失败：${job.error || "未知错误"}`);
    }
    await new Promise((resolve) => setTimeout(resolve, 2000));
  }
  throw new Error("动作执行超时，请检查 Windows Worker 状态");
}

async function saveSegmentRange() {
  const draft = selectedRangeDraft();
  await runSegmentAction("range", {
    start_seconds: Number(draft?.start ?? elements.manualStart?.value ?? 0),
    end_seconds: Number(draft?.end ?? elements.manualEnd?.value ?? 0),
  });
  state.draftRange = null;
  renderSegmentPanel();
  renderDensityChart(state.sourceDetail);
}

async function saveAndRenderCurrentSegment() {
  await saveSegmentRange();
  await renderCurrentSegment();
}

function parseTags(value) {
  return String(value || "")
    .split(/[,，\s]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

async function manualKeepCurrentSegment() {
  const draft = selectedRangeDraft();
  await runSegmentAction("manual-keep", {
    title: elements.segmentTitle?.value || "",
    description: elements.segmentDescription?.value || "",
    tags: parseTags(elements.segmentTags?.value || ""),
    start_seconds: Number(draft?.start ?? elements.manualStart?.value ?? 0),
    end_seconds: Number(draft?.end ?? elements.manualEnd?.value ?? 0),
  });
}

async function dropCurrentSegment() {
  await runSegmentAction("drop", {
    reason: elements.qualityReason?.value || "",
  });
}

async function retryCurrentSegmentJudge() {
  await runSegmentAction("retry-judge");
}

async function renderCurrentSegment() {
  await runSegmentAction("render");
}

function toggleTaskPanel() {
  state.taskPanelCollapsed = !state.taskPanelCollapsed;
  elements.taskPanel?.classList.toggle("task-collapsed", state.taskPanelCollapsed);
  if (elements.taskToggle) {
    elements.taskToggle.setAttribute("aria-expanded", state.taskPanelCollapsed ? "false" : "true");
    elements.taskToggle.textContent = state.taskPanelCollapsed ? "展开" : "折叠";
  }
}

async function refreshSliceProgress() {
  try {
    renderSliceProgress(await request("/api/slice-progress"));
  } catch (error) {
    renderSliceProgress({
      status: "error",
      phase_label: "进度不可用",
      message: error.message,
      current_slice_percent: 0,
    });
  }
}

async function refreshSliceDiagnostics() {
  try {
    renderSliceDiagnostics(await request("/api/slice-diagnostics"));
  } catch (error) {
    renderSliceDiagnostics({
      source_name: "-",
      items: [
        {
          id: "diagnostics-error",
          title: "诊断不可用",
          status: "error",
          message: error.message,
          details: [],
        },
      ],
    });
  }
}

async function refreshTasks() {
  const roomId = elements.roomFilter.value;
  const query = roomId ? `?room_id=${encodeURIComponent(roomId)}` : "";
  try {
    state.tasks = await request(`/api/tasks${query}`);
    renderTaskList(state.tasks);
  } catch (error) {
    if (!elements.taskList || !elements.taskCount) return;
    elements.taskCount.textContent = "error";
    elements.taskList.innerHTML = "";
    const row = document.createElement("div");
    row.className = "task-empty";
    row.textContent = `任务状态不可用：${error.message}`;
    elements.taskList.appendChild(row);
  }
}

async function refresh() {
  showError("");
  const roomId = elements.roomFilter.value;
  const query = roomId ? `?room_id=${encodeURIComponent(roomId)}` : "";
  try {
    state.slices = await request(`/api/slices${query}`);
    if (!state.slices.some((item) => item.id === state.selectedId)) {
      state.selectedId = state.slices[0]?.id || "";
    }
    render();
  } catch (error) {
    showError(error.message);
  }
}

async function refreshRooms() {
  try {
    state.rooms = await request("/api/rooms");
    renderRoomOptions(state.rooms);
  } catch (err) {
    console.error("Failed to load room list:", err);
    // Fallback: show room IDs from slices as plain options
    if (!state.rooms || !state.rooms.length) {
      const seen = new Set();
      const fallback = [];
      for (const item of state.slices) {
        if (!seen.has(item.room_id)) {
          seen.add(item.room_id);
          fallback.push({ room_id: item.room_id, name: item.room_id });
        }
      }
      if (fallback.length) renderRoomOptions(fallback);
    }
  }
}

function renderRoomOptions(rooms) {
  const selected = elements.roomFilter.value;
  elements.roomFilter.innerHTML = '<option value="">全部 UP</option>';
  for (const room of rooms) {
    const opt = document.createElement("option");
    opt.value = room.room_id;
    opt.textContent = room.name || room.room_id;
    opt.title = opt.textContent === room.room_id ? room.room_id : `${opt.textContent} (${room.room_id})`;
    elements.roomFilter.appendChild(opt);
  }
  if (rooms.some((r) => r.room_id === selected)) {
    elements.roomFilter.value = selected;
  }
}

function describeWorkerTrigger(trigger) {
  if (!trigger || trigger.status === "disabled" || trigger.status === "skipped") {
    return {
      handled: true,
      message: trigger?.message || "remote worker trigger is disabled",
    };
  }
  if (trigger.status === "accepted") {
    return {
      handled: true,
      message: "Windows Worker API 已接受任务",
    };
  }
  if (trigger.status === "already_running") {
    return { handled: true, message: "Windows Worker 正在处理现有任务" };
  }
  if (trigger.status === "no_pending") {
    return { handled: true, message: "没有待处理任务" };
  }
  if (trigger.status === "dependency_unavailable") {
    const missing = trigger.dependencies?.unavailable?.join(", ") || "未知依赖";
    return {
      handled: true,
      message: `任务已保留，Windows 依赖不可用：${missing}。请运行 .\\start_pipeline.ps1 检查状态`,
    };
  }
  if (trigger.status === "failed") {
    const detail = trigger.stderr || trigger.message || "未知错误";
    return {
      handled: true,
      message: `任务已保留，但 Windows Worker 调用失败：${detail}`,
    };
  }
  return {
    handled: true,
    message: `远程 worker 状态：${trigger.status}`,
  };
}

async function runTaskAction(task, action) {
  showError("");
  try {
    const result = await request(`/api/tasks/${encodeURIComponent(task.task_id)}/${action}`, {
      method: "POST",
    });
    if (action === "requeue") {
      const worker = describeWorkerTrigger(result.worker_trigger);
      if (worker.message) {
        showError(worker.message);
      }
    }
    await refreshTasks();
    await refresh();
    await refreshSliceProgress();
    await refreshSliceDiagnostics();
    await refreshWorkerStatus();
  } catch (error) {
    showError(error.message);
  }
}


function assertStopSucceeded(result) {
  const status = String(result?.status || "");
  if (status === "stopped" || status === "idle") return "success";
  if (status === "partial") return "partial";
  const message = result?.message || result?.detail || result?.stderr || result?.stdout || `停止 Windows 重任务节点失败：${status || "未知状态"}`;
  throw new Error(message);
}

async function stopSlicing() {
  showError("");
  if (!elements.stopSliceButton) return;
  elements.stopSliceButton.disabled = true;
  elements.stopSliceButton.textContent = "停止中";
  try {
    const result = await request("/api/worker-trigger/stop", {
      method: "POST",
    });
    const outcome = assertStopSucceeded(result);
    const recovered = Number(result.recovered || 0);
    const recoveredSources = Number(result.recovered_sources || 0);
    const recoveredActions = Number(result.recovered_actions || 0);
    const pending = Number(result.pending_tasks || 0);
    const partialDetail = Array.isArray(result.errors) && result.errors.length
      ? ` 未终止：${result.errors.join("；")}`
      : "";
    renderSliceProgress({
      status: outcome === "partial" ? "error" : "idle",
      phase_label: outcome === "partial" ? "部分停止" : "已停止",
      message: outcome === "partial"
        ? `已恢复 ${recovered} 个处理中任务（录播 ${recoveredSources}，动作 ${recoveredActions}），待处理 ${pending} 个。${partialDetail}`
        : `已停止 Windows 重任务节点，恢复 ${recovered} 个处理中任务（录播 ${recoveredSources}，动作 ${recoveredActions}），待处理 ${pending} 个。`,
      current_slice_percent: 0,
    });
    await refreshWorkerStatus();
    await refreshSliceProgress();
    await refreshSliceDiagnostics();
    await refreshTasks();
    await refreshSourceRecordings();
  } catch (error) {
    showError(error.message);
  } finally {
    elements.stopSliceButton.textContent = "停止";
  }
}

async function startSlicing({ selectedOnly = false } = {}) {
  showError("");
  const button = selectedOnly ? elements.startSelectedSliceButton : elements.startSliceButton;
  if (selectedOnly && !state.selectedSourceId) {
    showError("请先选择一场录播");
    updateSelectedSliceButton();
    return;
  }
  if (button) {
    button.disabled = true;
    button.textContent = "启动中";
  }
  try {
    const requestOptions = { method: "POST" };
    if (selectedOnly) {
      requestOptions.body = JSON.stringify({ task_id: state.selectedSourceId });
    }
    const result = await request("/api/slice/start", {
      ...requestOptions,
    });
    const queued = Number(result.queued || 0);
    const pendingTasks = Number(result.pending_tasks || queued);
    let workerMessage = "";
    if (pendingTasks > 0) {
      const remoteWorker = describeWorkerTrigger(result.worker_trigger);
      workerMessage = remoteWorker.message;
    }
    renderSliceProgress({
      status: pendingTasks > 0 ? "queued" : "idle",
      phase_label: pendingTasks > 0
        ? (selectedOnly ? "已提交当前录播" : "已提交切片任务")
        : "没有可提交录像",
      message: pendingTasks > 0
        ? `待处理 ${pendingTasks} 个任务，本次新增 ${queued} 个。${workerMessage}`
        : (selectedOnly ? "当前录播不可提交或已处理" : "没有找到新的整场 mp4+xml 录像"),
      current_slice_percent: 0,
    });
    setTimeout(refreshSliceProgress, 1000);
    setTimeout(refreshSliceDiagnostics, 1000);
    setTimeout(refreshTasks, 1000);
    setTimeout(refreshSourceRecordings, 1000);
  } catch (error) {
    showError(error.message);
  } finally {
    // Do not unconditionally re-enable the button: the worker may already be
    // running or the task queued (status set by renderSliceProgress above or
    // by a concurrent refreshSliceProgress poll). Re-enabling here would let
    // the same source be submitted again before the worker finishes.
    const status = state.currentSliceProgress?.status;
    const busy = status === "running" || status === "queued";
    if (button) {
      button.disabled = busy || (selectedOnly && !state.selectedSourceId);
      button.textContent = busy
        ? "切片中"
        : (selectedOnly ? "切当前录播" : "启动切片");
    }
    updateSelectedSliceButton();
  }
}

async function saveFeedback() {
  if (state.sourceDetail && state.selectedSegmentId) {
    showError("");
    elements.saveButton.disabled = true;
    try {
      await saveSegmentRange();
    } catch (error) {
      showError(error.message);
    } finally {
      elements.saveButton.disabled = false;
    }
    return;
  }
  const item = selectedSlice();
  if (!item) return;
  showError("");
  elements.saveButton.disabled = true;
  try {
    const feedback = await request(`/api/slices/${encodeURIComponent(item.id)}/feedback`, {
      method: "PATCH",
      body: JSON.stringify({
        decision: state.decision,
        quality_reason: elements.qualityReason.value,
        manual_range: {
          start: Number(elements.manualStart.value || 0),
          end: Number(elements.manualEnd.value || 0),
          relative_to: "slice",
        },
      }),
    });
    Object.assign(item, {
      decision: feedback.decision,
      quality_reason: feedback.quality_reason,
      manual_range: feedback.manual_range,
      reviewed_at: feedback.reviewed_at,
      review_source: feedback.review_source,
    });
    render();
  } catch (error) {
    showError(error.message);
  } finally {
    elements.saveButton.disabled = false;
  }
}

function setDecisionAndSave(decision) {
  state.decision = decision;
  syncDecisionButtons();
  saveFeedback();
}

function selectNextCandidate() {
  const items = filteredSlices();
  if (!items.length) return;
  const currentIdx = items.findIndex((item) => item.id === state.selectedId);
  const nextIndex = currentIdx < items.length - 1 ? currentIdx + 1 : 0;
  state.selectedId = items[nextIndex].id;
  render();
}

function replayPreview() {
  const video = elements.previewVideo;
  if (video && video.src) {
    video.load();
  }
}


let uploadDashboardState = { items: [], queue_counts: {}, worker: {} };

function currentViewName() {
  if (window.location.pathname.startsWith("/uploads")) return "uploads";
  if (window.location.pathname.startsWith("/settings")) return "settings";
  return "tasks";
}

function activateCurrentView() {
  const view = currentViewName();
  document.querySelectorAll(".app-view").forEach((element) => {
    element.classList.toggle("hidden", element.id !== `${view}-view`);
  });
  document.querySelectorAll(".nav-item[data-view]").forEach((element) => {
    element.classList.toggle("active", element.dataset.view === view);
  });
  document.body.dataset.view = view;
  return view;
}

function uploadStatusPresentation(status) {
  const values = {
    queued: ["等待上传", "queued"],
    uploading: ["上传中", "active"],
    uploaded: ["等待投稿", "active"],
    publishing: ["投稿中", "active"],
    published: ["已发布", "published"],
    failed: ["失败", "failed"],
  };
  const [label, tone] = values[status] || [status || "未知", "neutral"];
  return { label, tone };
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatTimestamp(value) {
  const timestamp = Number(value || 0);
  if (!timestamp) return "-";
  return new Date(timestamp * 1000).toLocaleString("zh-CN", { hour12: false });
}

async function refreshUploadDashboard() {
  const error = document.querySelector("#upload-error");
  try {
    uploadDashboardState = await request("/api/upload-dashboard");
    if (error) error.classList.add("hidden");
    renderUploadQueue();
  } catch (reason) {
    if (error) {
      error.textContent = reason.message;
      error.classList.remove("hidden");
    }
  }
}

function updateUploadMetrics(prefix, counts = uploadDashboardState.queue_counts || {}) {
  const active = Number(counts.uploading || 0) + Number(counts.uploaded || 0) + Number(counts.publishing || 0);
  const values = {
    [`${prefix}-count-queued`]: counts.queued || 0,
    [`${prefix}-count-active`]: active,
    [`${prefix}-count-published`]: counts.published || 0,
    [`${prefix}-count-failed`]: counts.failed || 0,
  };
  Object.entries(values).forEach(([id, value]) => {
    const element = document.getElementById(id);
    if (element) element.textContent = String(value);
  });
}

function filteredUploadItems(filter) {
  return (uploadDashboardState.items || []).filter((item) => {
    if (filter === "all") return true;
    if (filter === "active") return ["uploading", "uploaded", "publishing"].includes(item.status);
    return item.status === filter;
  });
}

function createUploadRow(item, compact = false) {
  const row = document.createElement("article");
  const status = uploadStatusPresentation(item.status);
  row.className = compact ? "upload-row publish-row" : "upload-row";
  row.innerHTML = `
    <div class="upload-row-main">
      <strong title="${escapeHtml(item.name || "-")}">${escapeHtml(item.name || "-")}</strong>
      <span>${escapeHtml(item.room || "-")} / 更新于 ${formatTimestamp(item.updated_at)}</span>
    </div>
    <span class="upload-status upload-status-${status.tone}">${status.label}</span>
    <div class="upload-row-meta"><span>尝试 ${Number(item.attempts || 0)} 次</span><span>${item.bvid ? escapeHtml(item.bvid) : "暂无 BV 号"}</span></div>
    <div class="upload-row-error">${item.last_error ? escapeHtml(item.last_error) : "-"}</div>`;
  return row;
}

function renderPublishQueue() {
  updateUploadMetrics("publish");
  if (!elements.publishQueueList) return;
  const items = filteredUploadItems("all").slice(0, 6);
  if (elements.publishQueueCount) elements.publishQueueCount.textContent = `${items.length} 个项目`;
  elements.publishQueueList.innerHTML = "";
  if (!items.length) {
    elements.publishQueueList.innerHTML = '<div class="task-empty">当前没有投稿任务</div>';
    return;
  }
  for (const item of items) {
    elements.publishQueueList.appendChild(createUploadRow(item, true));
  }
}

function formatPerformanceNumber(value) {
  const num = Number(value);
  if (!Number.isFinite(num)) return "-";
  if (num >= 10000) return `${(num / 10000).toFixed(1)}万`;
  return String(num);
}

async function refreshPerformancePanel() {
  if (!elements.performanceBody) return;
  let payload;
  try {
    payload = await request("/api/slice-performance");
  } catch (reason) {
    elements.performanceBody.innerHTML = `<div class="task-empty">读取失败：${escapeHtml(reason.message)}</div>`;
    return;
  }
  if (payload.status === "unavailable") {
    if (elements.performanceCount) elements.performanceCount.textContent = "暂无数据";
    elements.performanceBody.innerHTML = '<div class="task-empty">尚无发布表现数据（需先在 Windows 端采集）</div>';
    return;
  }
  const items = payload.items || [];
  if (elements.performanceCount) elements.performanceCount.textContent = `${items.length} 个切片`;
  if (!items.length) {
    elements.performanceBody.innerHTML = '<div class="task-empty">暂无已发布切片</div>';
    return;
  }
  const rows = items
    .map(
      (item) => `
        <tr>
          <td class="performance-title" title="${escapeHtml(item.title || item.bvid || "-")}">${escapeHtml(item.title || item.bvid || "-")}</td>
          <td>${formatPerformanceNumber(item.view)}</td>
          <td>${formatPerformanceNumber(item.likes)}</td>
          <td>${formatPerformanceNumber(item.coin)}</td>
          <td>${formatPerformanceNumber(item.favorite)}</td>
          <td>${formatPerformanceNumber(item.danmaku)}</td>
          <td>${item.quality_score != null ? Number(item.quality_score).toFixed(2) : "-"}</td>
        </tr>`
    )
    .join("");
  elements.performanceBody.innerHTML = `
    <table class="performance-table">
      <thead>
        <tr><th>切片</th><th>播放</th><th>点赞</th><th>投币</th><th>收藏</th><th>弹幕</th><th>质量分</th></tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>`;
}

function renderUploadQueue() {
  const counts = uploadDashboardState.queue_counts || {};
  updateUploadMetrics("upload", counts);
  updateUploadMetrics("publish", counts);

  const worker = uploadDashboardState.worker || {};
  const pill = document.querySelector("#upload-worker-pill");
  if (pill) {
    const running = worker.process_status === "running";
    pill.className = `live-pill ${running ? "task-state-running" : "task-state-idle"}`;
    pill.querySelector("span:last-child").textContent = running ? "上传节点运行中" : "上传节点空闲";
  }

  const filter = document.querySelector("#upload-status-filter")?.value || "all";
  const items = filteredUploadItems(filter);
  const count = document.querySelector("#upload-queue-count");
  const list = document.querySelector("#upload-queue-list");
  if (count) count.textContent = `${items.length} 个项目`;
  if (list) {
    list.innerHTML = "";
    if (!items.length) {
      list.innerHTML = '<div class="task-empty">当前筛选条件下没有投稿任务</div>';
    } else {
      for (const item of items) {
        list.appendChild(createUploadRow(item));
      }
    }
  }
  renderPublishQueue();
  renderFailureInbox();
}
async function wakeUploadWorker() {
  const button = document.querySelector("#upload-wake-button");
  if (button) button.disabled = true;
  try {
    await request("/api/worker-trigger/wake", { method: "POST" });
    await refreshUploadDashboard();
  } catch (error) {
    const box = document.querySelector("#upload-error");
    if (box) {
      box.textContent = error.message;
      box.classList.remove("hidden");
    }
  } finally {
    if (button) button.disabled = false;
  }
}

async function loadDashboardSettings() {
  const data = await request("/api/dashboard-settings");
  const setValue = (id, value) => {
    const element = document.getElementById(id);
    if (element) element.value = value;
  };
  setValue("setting-burst-ratio", `${data.slice.burst_ratio}x`);
  setValue("setting-burst-context", `±${data.slice.burst_context} 秒`);
  setValue("setting-burst-top-n", data.slice.burst_top_n);
  setValue("setting-min-video-size", `${data.slice.min_video_size_mb} MB`);
  setValue("setting-mimo-model", data.mimo.model);
  setValue("setting-mimo-fps", `${data.mimo.fps} FPS · ${data.mimo.media_resolution}`);
  setValue(
    "setting-mimo-key",
    data.mimo.configured ? "已配置" : "由 Windows 环境管理",
  );
  setValue("setting-whisper", `${data.whisper.model} · ${data.whisper.device} ${data.whisper.compute_type}`);

  const preferences = JSON.parse(localStorage.getItem("dashboard-preferences") || "{}");
  const interval = document.querySelector("#pref-refresh-interval");
  const compact = document.querySelector("#pref-compact-queue");
  const collapse = document.querySelector("#pref-collapse-sidebar");
  if (interval) interval.value = String(preferences.refreshInterval || 30);
  if (compact) compact.checked = Boolean(preferences.compactQueue);
  if (collapse) collapse.checked = localStorage.getItem("sider-collapsed") === "1";
  document.body.classList.toggle("compact-queue", Boolean(preferences.compactQueue));
}

function saveDashboardPreferences(event) {
  event?.preventDefault();
  const preferences = {
    refreshInterval: Number(document.querySelector("#pref-refresh-interval")?.value || 30),
    compactQueue: Boolean(document.querySelector("#pref-compact-queue")?.checked),
  };
  localStorage.setItem("dashboard-preferences", JSON.stringify(preferences));
  const collapse = Boolean(document.querySelector("#pref-collapse-sidebar")?.checked);
  applyCollapsed(collapse);
  document.body.classList.toggle("compact-queue", preferences.compactQueue);
  const message = document.querySelector("#settings-message");
  if (message) {
    message.textContent = "界面偏好已保存在当前浏览器。生产参数仍由 bilive-server.toml 管理。";
    message.classList.remove("hidden");
  }
}

document.addEventListener("keydown", (event) => {
  const tag = document.activeElement?.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;

  const key = event.key.toLowerCase();
  if (key === "k") {
    setDecisionAndSave("keep");
  } else if (key === "d") {
    setDecisionAndSave("drop");
  } else if (key === "r") {
    setDecisionAndSave("review");
  } else if (key === "j") {
    selectNextCandidate();
  } else if (key === "l") {
    replayPreview();
  }
});

elements.startSliceButton.addEventListener("click", () => startSlicing());
elements.startSelectedSliceButton?.addEventListener("click", () => startSlicing({ selectedOnly: true }));
elements.stopSliceButton?.addEventListener("click", stopSlicing);
elements.progressOpenSourceButton?.addEventListener("click", () => {
  gotoCurrentSourceRecording().catch((error) => showError(error.message));
});
elements.refreshButton.addEventListener("click", () => {
  refresh();
  refreshSourceRecordings();
});
elements.statusFilter.addEventListener("change", () => {
  const changed = ensureVisibleSourceSelection();
  renderSourceRecordings();
  if (changed && state.selectedSourceId) {
    refreshSourceDetail(state.selectedSourceId).catch((error) => showError(error.message));
  } else if (!state.selectedSourceId) {
    state.sourceDetail = null;
    renderSourceDetail();
  }
});
elements.roomFilter.addEventListener("change", () => {
  refresh();
  refreshTasks();
  refreshSourceRecordings();
});
elements.saveButton.addEventListener("click", saveFeedback);
elements.manualStart?.addEventListener("input", markRangeDraftFromInputs);
elements.manualEnd?.addEventListener("input", markRangeDraftFromInputs);
elements.taskToggle?.addEventListener("click", toggleTaskPanel);
document.querySelector("#upload-refresh-button")?.addEventListener("click", refreshUploadDashboard);
elements.publishRefreshButton?.addEventListener("click", refreshUploadDashboard);
elements.performanceRefreshButton?.addEventListener("click", refreshPerformancePanel);
document.querySelector("#upload-wake-button")?.addEventListener("click", wakeUploadWorker);
elements.publishWakeButton?.addEventListener("click", wakeUploadWorker);
document.querySelector("#upload-status-filter")?.addEventListener("change", renderUploadQueue);
document.querySelector("#settings-form")?.addEventListener("submit", saveDashboardPreferences);
document.querySelector("#settings-save-button")?.addEventListener("click", saveDashboardPreferences);
elements.segmentKeepButton?.addEventListener("click", () => manualKeepCurrentSegment().catch((error) => showError(error.message)));
elements.segmentDropButton?.addEventListener("click", () => dropCurrentSegment().catch((error) => showError(error.message)));
elements.segmentRetryButton?.addEventListener("click", () => retryCurrentSegmentJudge().catch((error) => showError(error.message)));
elements.segmentRenderButton?.addEventListener("click", () => renderCurrentSegment().catch((error) => showError(error.message)));
elements.subtitleSaveButton?.addEventListener("click", () => saveSubtitleStyle().catch((error) => showError(error.message)));
elements.subtitleReburnButton?.addEventListener("click", () => reburnCurrentSubtitles().catch((error) => showError(error.message)));
elements.segmentSaveRenderButton?.addEventListener("click", () => saveAndRenderCurrentSegment().catch((error) => showError(error.message)));
for (const button of elements.decisionButtons) {
  button.addEventListener("click", () => {
    state.decision = button.dataset.decision;
    syncDecisionButtons();
  });
}

function renderRemoteWorkerStatus(data) {
  const badge = elements.workerBadge;
  if (!badge) return false;
  if (data?.mode !== "remote" || !data.enabled) return false;
  const running = data.status === "running";
  badge.className = `worker-badge ${running ? "worker-running" : "worker-idle"}`;
  if (running) {
    const pid = data.watcher?.pid || data.lock?.pid || "";
    badge.textContent = `Windows 重任务节点：处理中${pid ? ` PID ${pid}` : ""}`;
  } else if (data.status === "unavailable") {
    badge.textContent = "Windows 重任务节点：离线";
  } else {
    badge.textContent = `Windows 重任务节点：空闲，待处理 ${Number(data.pending_tasks || 0)}`;
  }
  badge.title = data.message || "Windows Worker API";
  return true;
}

async function refreshWorkerStatus() {
  try {
    const remoteStatus = await request("/api/worker-trigger/status");
    if (renderRemoteWorkerStatus(remoteStatus)) return;
  } catch {
    // The badge below reports the unavailable Windows worker.
  }
  if (elements.workerBadge) {
    elements.workerBadge.className = "worker-badge worker-idle";
    elements.workerBadge.textContent = "Windows 重任务节点：离线";
  }
}

async function wakeWorkerOnPageLoad() {
  if (!elements.workerBadge) return;
  elements.workerBadge.className = "worker-badge worker-running";
  elements.workerBadge.textContent = "Windows 重任务节点：启动中";
  try {
    const status = await request("/api/worker-trigger/wake", {
      method: "POST",
    });
    renderRemoteWorkerStatus(status);
  } catch {
    elements.workerBadge.className = "worker-badge worker-idle";
    elements.workerBadge.textContent = "Windows 重任务节点：离线";
  }
}

const activeView = activateCurrentView();
if (activeView === "tasks") {
  refresh();
  refreshRooms();
  refreshSourceRecordings();
  refreshSliceProgress();
  refreshSliceDiagnostics();
  refreshTasks();
  refreshUploadDashboard();
  refreshPerformancePanel();
  wakeWorkerOnPageLoad();
} else if (activeView === "uploads") {
  refreshUploadDashboard();
  refreshWorkerStatus();
} else {
  loadDashboardSettings().catch((error) => {
    const message = document.querySelector("#settings-message");
    if (message) {
      message.textContent = error.message;
      message.classList.remove("hidden");
    }
  });
}

setInterval(() => {
  if (document.visibilityState !== "visible") return;
  const view = currentViewName();
  if (view === "tasks") {
    refresh();
    refreshSourceRecordings();
    refreshTasks();
    refreshWorkerStatus();
    refreshUploadDashboard();
  } else if (view === "uploads") {
    refreshUploadDashboard();
  }
}, Number(JSON.parse(localStorage.getItem("dashboard-preferences") || "{}").refreshInterval || 30) * 1000);

setInterval(() => {
  if (document.visibilityState === "visible" && currentViewName() === "tasks") {
    refreshSliceProgress();
    refreshSliceDiagnostics();
  }
}, 2000);

setInterval(() => {
  if (document.visibilityState === "visible" && currentViewName() === "tasks") {
    refreshWorkerStatus();
  }
}, 5000);

document.addEventListener("visibilitychange", () => {
  if (document.visibilityState !== "visible") return;
  const view = currentViewName();
  if (view === "tasks") {
    refreshRooms();
    refresh();
    refreshSourceRecordings();
    refreshTasks();
    refreshSliceProgress();
    refreshSliceDiagnostics();
    refreshWorkerStatus();
    refreshUploadDashboard();
    refreshPerformancePanel();
  } else if (view === "uploads") {
    refreshUploadDashboard();
  }
});
