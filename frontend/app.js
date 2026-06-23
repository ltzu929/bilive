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
};

const elements = {
  roomFilter: document.querySelector("#room-filter"),
  statusFilter: document.querySelector("#status-filter"),
  startSliceButton: document.querySelector("#start-slice-button"),
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
  progressCount: document.querySelector("#slice-progress-count"),
  progressPercent: document.querySelector("#slice-progress-percent"),
  progressBar: document.querySelector("#slice-progress-bar"),
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
  segmentKeepButton: document.querySelector("#segment-keep-button"),
  segmentDropButton: document.querySelector("#segment-drop-button"),
  segmentRetryButton: document.querySelector("#segment-retry-button"),
  segmentRenderButton: document.querySelector("#segment-render-button"),
  taskStatePill: document.querySelector("#task-state-pill"),
  taskStateLabel: document.querySelector("#task-state-label"),
  overviewSourceTotal: document.querySelector("#overview-source-total"),
  overviewTaskTotal: document.querySelector("#overview-task-total"),
  overviewReviewTotal: document.querySelector("#overview-review-total"),
  overviewKeepTotal: document.querySelector("#overview-keep-total"),
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

function sourceStatusPresentation(status) {
  return SOURCE_STATUS_PRESENTATION[status] || SOURCE_STATUS_PRESENTATION.unknown;
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
  const percent = Math.max(
    0,
    Math.min(100, Number(progress.current_slice_percent || 0)),
  );
  const status = progress.stale ? "stale" : (progress.status || "idle");
  elements.progressPanel.dataset.status = status;
  elements.progressTitle.textContent = progress.phase_label || "空闲";
  elements.progressMessage.textContent = progress.stale
    ? "进度已过期，请检查切片进程"
    : (progress.error || progress.message || "暂无切片任务");
  elements.progressSource.textContent = progress.source_name || "-";
  elements.progressCount.textContent = `${Number(progress.current_slice || 0)}/${Number(progress.total_slices || 0)}`;
  elements.progressPercent.textContent = `${percent.toFixed(0)}%`;
  elements.progressBar.style.width = `${percent}%`;
  elements.startSliceButton.disabled = status === "running";
  elements.startSliceButton.textContent = status === "running" ? "切片中" : "启动切片";
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

function sourceSummaryLabel(counts = {}) {
  return [
    `keep ${Number(counts.keep || 0) + Number(counts.manual_keep || 0)}`,
    `failed ${Number(counts.judge_failed || 0)}`,
    `drop ${Number(counts.drop || 0)}`,
  ].join(" / ");
}

function updateOverviewStats() {
  const sources = Array.isArray(state.sourceRecordings) ? state.sourceRecordings : [];
  const tasks = Array.isArray(state.tasks) ? state.tasks : [];
  const reviewCount = sources.reduce(
    (total, item) => total
      + Number(item.summary_counts?.review || 0)
      + Number(item.summary_counts?.judge_failed || 0),
    0,
  );
  const keepCount = sources.reduce(
    (total, item) => total
      + Number(item.summary_counts?.keep || 0)
      + Number(item.summary_counts?.manual_keep || 0),
    0,
  );

  if (elements.overviewSourceTotal) elements.overviewSourceTotal.textContent = String(sources.length);
  if (elements.overviewTaskTotal) elements.overviewTaskTotal.textContent = String(tasks.length);
  if (elements.overviewReviewTotal) elements.overviewReviewTotal.textContent = String(reviewCount);
  if (elements.overviewKeepTotal) elements.overviewKeepTotal.textContent = String(keepCount);
}

function sourceReviewPriority(item) {
  const counts = item.summary_counts || {};
  if (Number(counts.judge_failed || 0) > 0 || Number(counts.review || 0) > 0) return 3;
  if (Number(item.segment_count || 0) > 0) return 2;
  if (item.status === "processing" || item.status === "pending") return 1;
  return 0;
}

async function refreshSourceRecordings() {
  const requestId = ++sourceRecordingRequestId;
  const roomId = elements.roomFilter.value;
  const query = roomId ? `?room_id=${encodeURIComponent(roomId)}` : "";
  try {
    const sourceRecordings = await request(`/api/source-recordings${query}`);
    if (requestId !== sourceRecordingRequestId) return;
    state.sourceRecordings = sourceRecordings;
    if (!state.sourceRecordings.some((item) => item.task_id === state.selectedSourceId)) {
      const preferredSource = [...state.sourceRecordings]
        .filter((item) => Number(item.segment_count || 0) > 0)
        .sort((left, right) => sourceReviewPriority(right) - sourceReviewPriority(left))[0]
        || state.sourceRecordings[0];
      state.selectedSourceId = preferredSource?.task_id || "";
      state.selectedSegmentId = "";
    }
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

function renderSourceRecordings() {
  if (!elements.sourceRecordingList || !elements.sourceRecordingCount) return;
  const items = state.sourceRecordings
    .map((item, index) => ({ item, index }))
    .sort((left, right) => (
      sourceReviewPriority(right.item) - sourceReviewPriority(left.item)
      || left.index - right.index
    ))
    .map(({ item }) => item);
  elements.sourceRecordingCount.textContent = `${items.length} 条录播`;
  elements.sourceRecordingList.innerHTML = "";
  updateOverviewStats();

  if (!items.length) {
    const empty = document.createElement("div");
    empty.className = "task-empty";
    empty.textContent = "暂无录播";
    elements.sourceRecordingList.appendChild(empty);
    return;
  }

  for (const item of items) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `source-row${item.task_id === state.selectedSourceId ? " active" : ""}`;

    const header = document.createElement("span");
    header.className = "source-row-header";

    const name = document.createElement("span");
    name.className = "source-name";
    name.textContent = item.source_name || item.source_rel_path || "-";

    const status = sourceStatusPresentation(item.status);
    const statusBadge = document.createElement("span");
    statusBadge.className = `source-status-badge source-status-${status.tone}`;
    statusBadge.textContent = status.label;
    header.append(name, statusBadge);

    const meta = document.createElement("span");
    meta.className = "source-meta";
    meta.textContent = `${item.room_name || item.room_id || "-"} · ${formatMegabytes(item.source_size_mb)}`;

    const summary = document.createElement("span");
    summary.className = "source-summary-line";
    summary.textContent = sourceSummaryLabel(item.summary_counts);

    button.append(header, meta, summary);
    button.addEventListener("click", () => selectSourceRecording(item.task_id));
    elements.sourceRecordingList.appendChild(button);
  }
}

function selectSourceRecording(taskId) {
  state.selectedSourceId = taskId;
  state.selectedSegmentId = "";
  renderSourceRecordings();
  refreshSourceDetail(taskId);
}

async function refreshSourceDetail(taskId) {
  if (!taskId) return;
  state.sourceDetail = await request(`/api/source-recordings/${encodeURIComponent(taskId)}`);
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
    renderDensityChart({ density_points: [], segments: [] });
    renderSegmentPanel();
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
  renderDensityChart(detail);
  renderSegmentPanel();
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
}

function selectSegment(segmentId) {
  state.selectedSegmentId = segmentId;
  renderDensityChart(state.sourceDetail);
  renderSegmentPanel();
}

function renderSegmentPanel() {
  const segment = selectedSegment();
  const hasSegment = Boolean(segment);
  for (const element of [
    elements.segmentTitle,
    elements.segmentDescription,
    elements.qualityReason,
    elements.manualStart,
    elements.manualEnd,
    elements.saveButton,
    elements.segmentKeepButton,
    elements.segmentDropButton,
    elements.segmentRetryButton,
    elements.segmentRenderButton,
  ]) {
    if (element) element.disabled = !hasSegment;
  }

  if (!segment) {
    if (elements.segmentStatus) {
      elements.segmentStatus.className = "panel-meta status-pill segment-status-review";
      elements.segmentStatus.textContent = "-";
    }
    if (elements.selectedSegmentRange) elements.selectedSegmentRange.textContent = "-";
    if (elements.segmentTitle) elements.segmentTitle.value = "";
    if (elements.segmentDescription) elements.segmentDescription.value = "";
    if (elements.qualityReason) elements.qualityReason.value = "";
    if (elements.manualStart) elements.manualStart.value = 0;
    if (elements.manualEnd) elements.manualEnd.value = 0;
    if (elements.danmakuCount) elements.danmakuCount.textContent = "-";
    if (elements.qualityScore) elements.qualityScore.textContent = "-";
    if (elements.burstRatio) elements.burstRatio.textContent = "-";
    return;
  }

  if (elements.segmentStatus) {
    const status = segment.judge_status || "review";
    const normalizedStatus = status === "manual_keep" ? "keep" : status.replaceAll("_", "-");
    elements.segmentStatus.className = `panel-meta status-pill segment-status-${normalizedStatus}`;
    elements.segmentStatus.textContent = status;
  }
  if (elements.selectedSegmentRange) elements.selectedSegmentRange.textContent = segmentRangeLabel(segment);
  if (elements.segmentTitle) elements.segmentTitle.value = segment.title || "";
  if (elements.segmentDescription) elements.segmentDescription.value = segment.description || "";
  if (elements.qualityReason) elements.qualityReason.value = segment.quality_reason || segment.judge_error || "";
  if (elements.manualStart) elements.manualStart.value = Number(segment.start_seconds || 0);
  if (elements.manualEnd) elements.manualEnd.value = Number(segment.end_seconds || 0);
  if (elements.danmakuCount) elements.danmakuCount.textContent = segment.danmaku_count != null ? String(segment.danmaku_count) : "-";
  if (elements.qualityScore) {
    elements.qualityScore.textContent = segment.quality_score != null
      ? `${Math.round(Number(segment.quality_score) * 100)}%`
      : "-";
  }
  if (elements.burstRatio) elements.burstRatio.textContent = segment.burst_ratio != null ? `${segment.burst_ratio}x` : "-";
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
  await runSegmentAction("range", {
    start_seconds: Number(elements.manualStart?.value || 0),
    end_seconds: Number(elements.manualEnd?.value || 0),
  });
}

async function manualKeepCurrentSegment() {
  await runSegmentAction("manual-keep", {
    title: elements.segmentTitle?.value || "",
    description: elements.segmentDescription?.value || "",
    tags: [],
    start_seconds: Number(elements.manualStart?.value || 0),
    end_seconds: Number(elements.manualEnd?.value || 0),
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

async function startSlicing() {
  showError("");
  elements.startSliceButton.disabled = true;
  elements.startSliceButton.textContent = "启动中";
  try {
    const result = await request("/api/slice/start", {
      method: "POST",
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
      phase_label: pendingTasks > 0 ? "已提交切片任务" : "没有可提交录像",
      message: pendingTasks > 0
        ? `待处理 ${pendingTasks} 个任务，本次新增 ${queued} 个。${workerMessage}`
        : "没有找到新的整场 mp4+xml 录像",
      current_slice_percent: 0,
    });
    setTimeout(refreshSliceProgress, 1000);
    setTimeout(refreshSliceDiagnostics, 1000);
    setTimeout(refreshTasks, 1000);
    setTimeout(refreshSourceRecordings, 1000);
    elements.startSliceButton.disabled = false;
    elements.startSliceButton.textContent = "启动切片";
  } catch (error) {
    showError(error.message);
    elements.startSliceButton.disabled = false;
    elements.startSliceButton.textContent = "启动切片";
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

function renderUploadQueue() {
  const counts = uploadDashboardState.queue_counts || {};
  const active = Number(counts.uploading || 0) + Number(counts.uploaded || 0) + Number(counts.publishing || 0);
  const values = {
    "upload-count-queued": counts.queued || 0,
    "upload-count-active": active,
    "upload-count-published": counts.published || 0,
    "upload-count-failed": counts.failed || 0,
  };
  Object.entries(values).forEach(([id, value]) => {
    const element = document.getElementById(id);
    if (element) element.textContent = String(value);
  });

  const worker = uploadDashboardState.worker || {};
  const pill = document.querySelector("#upload-worker-pill");
  if (pill) {
    const running = worker.process_status === "running";
    pill.className = `live-pill ${running ? "task-state-running" : "task-state-idle"}`;
    pill.querySelector("span:last-child").textContent = running ? "上传节点运行中" : "上传节点空闲";
  }

  const filter = document.querySelector("#upload-status-filter")?.value || "all";
  const items = (uploadDashboardState.items || []).filter((item) => {
    if (filter === "all") return true;
    if (filter === "active") return ["uploading", "uploaded", "publishing"].includes(item.status);
    return item.status === filter;
  });
  const count = document.querySelector("#upload-queue-count");
  const list = document.querySelector("#upload-queue-list");
  if (count) count.textContent = `${items.length} 个项目`;
  if (!list) return;
  list.innerHTML = "";
  if (!items.length) {
    list.innerHTML = '<div class="task-empty">当前筛选条件下没有投稿任务</div>';
    return;
  }
  for (const item of items) {
    const row = document.createElement("article");
    const status = uploadStatusPresentation(item.status);
    row.className = "upload-row";
    row.innerHTML = `
      <div class="upload-row-main">
        <strong title="${escapeHtml(item.name || "-")}">${escapeHtml(item.name || "-")}</strong>
        <span>${escapeHtml(item.room || "-")} · 更新于 ${formatTimestamp(item.updated_at)}</span>
      </div>
      <span class="upload-status upload-status-${status.tone}">${status.label}</span>
      <div class="upload-row-meta"><span>尝试 ${Number(item.attempts || 0)} 次</span><span>${item.bvid ? escapeHtml(item.bvid) : "暂无 BV 号"}</span></div>
      <div class="upload-row-error">${item.last_error ? escapeHtml(item.last_error) : "-"}</div>`;
    list.appendChild(row);
  }
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

elements.startSliceButton.addEventListener("click", startSlicing);
elements.refreshButton.addEventListener("click", () => {
  refresh();
  refreshSourceRecordings();
});
elements.statusFilter.addEventListener("change", render);
elements.roomFilter.addEventListener("change", () => {
  refresh();
  refreshTasks();
  refreshSourceRecordings();
});
elements.saveButton.addEventListener("click", saveFeedback);
elements.taskToggle?.addEventListener("click", toggleTaskPanel);
document.querySelector("#upload-refresh-button")?.addEventListener("click", refreshUploadDashboard);
document.querySelector("#upload-wake-button")?.addEventListener("click", wakeUploadWorker);
document.querySelector("#upload-status-filter")?.addEventListener("change", renderUploadQueue);
document.querySelector("#settings-form")?.addEventListener("submit", saveDashboardPreferences);
document.querySelector("#settings-save-button")?.addEventListener("click", saveDashboardPreferences);
elements.segmentKeepButton?.addEventListener("click", () => manualKeepCurrentSegment().catch((error) => showError(error.message)));
elements.segmentDropButton?.addEventListener("click", () => dropCurrentSegment().catch((error) => showError(error.message)));
elements.segmentRetryButton?.addEventListener("click", () => retryCurrentSegmentJudge().catch((error) => showError(error.message)));
elements.segmentRenderButton?.addEventListener("click", () => renderCurrentSegment().catch((error) => showError(error.message)));
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
  } else if (view === "uploads") {
    refreshUploadDashboard();
  }
});
