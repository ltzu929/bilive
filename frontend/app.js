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

const state = {
  slices: [],
  tasks: [],
  selectedId: "",
  decision: "review",
};

const PC_WORKER_RUN_ONCE_URL = "http://127.0.0.1:2235/api/worker/run-once";
const PC_WORKER_STATUS_URL = "http://127.0.0.1:2235/api/worker/status";

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
  taskList: document.querySelector("#task-list"),
  taskCount: document.querySelector("#task-count"),
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
  done: { cls: "tag-green", label: "done" },
  failed: { cls: "tag-red", label: "failed" },
  skipped: { cls: "tag-orange", label: "skipped" },
  stale: { cls: "tag-red", label: "stale" },
};

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
  if (status !== "done") {
    actions.push({ action: "mark-done", label: "标记完成" });
  }
  return actions;
}

function renderTaskList(tasks) {
  if (!elements.taskList || !elements.taskCount) return;
  elements.taskCount.textContent = `${tasks.length} items`;
  elements.taskList.innerHTML = "";

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
    room.textContent = task.room_name && task.room_name !== task.room_id
      ? `${task.room_name} (${task.room_id})`
      : task.room_id || "-";
    const size = document.createElement("span");
    size.textContent = `${Number(task.source_size_mb || 0).toFixed(1)} MB`;
    meta.append(room, document.createTextNode(" / "), size, taskStatusTag(task.status));

    const message = document.createElement("div");
    message.className = "task-message";
    message.textContent = task.message || "";

    main.append(title, meta, message);

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

    row.append(main, buttons);
    elements.taskList.appendChild(row);
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

async function startPcWorkerOnce() {
  const response = await fetch(PC_WORKER_RUN_ONCE_URL, { method: "POST" });
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return response.json();
}

async function runTaskAction(task, action) {
  showError("");
  try {
    let workerError = "";
    await request(`/api/tasks/${encodeURIComponent(task.task_id)}/${action}`, {
      method: "POST",
    });
    if (action === "requeue") {
      try {
        await startPcWorkerOnce();
      } catch {
        workerError = "已重新排队，但未连接到本机 PC worker。请先运行 .\\start_pc_worker_api.ps1";
      }
    }
    await refreshTasks();
    await refresh();
    await refreshSliceProgress();
    await refreshSliceDiagnostics();
    await refreshWorkerStatus();
    if (workerError) {
      showError(workerError);
    }
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
      try {
        const worker = await startPcWorkerOnce();
        workerMessage = worker.status === "already_running"
          ? "PC worker 已在处理，处理完会自动退出"
          : "PC worker 已启动，处理完会自动退出";
      } catch (error) {
        workerMessage = "已提交任务，但未连接到本机 PC worker。请先运行 .\\start_pc_worker_api.ps1，再从页面启动切片";
      }
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
    elements.startSliceButton.disabled = false;
    elements.startSliceButton.textContent = "启动切片";
  } catch (error) {
    showError(error.message);
    elements.startSliceButton.disabled = false;
    elements.startSliceButton.textContent = "启动切片";
  }
}

async function saveFeedback() {
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
elements.refreshButton.addEventListener("click", refresh);
elements.statusFilter.addEventListener("change", render);
elements.roomFilter.addEventListener("change", () => {
  refresh();
  refreshTasks();
});
elements.saveButton.addEventListener("click", saveFeedback);
for (const button of elements.decisionButtons) {
  button.addEventListener("click", () => {
    state.decision = button.dataset.decision;
    syncDecisionButtons();
  });
}

async function refreshWorkerStatus() {
  const badge = elements.workerBadge;
  if (!badge) return;
  try {
    const resp = await fetch(PC_WORKER_STATUS_URL, { signal: AbortSignal.timeout(3000) });
    if (!resp.ok) throw new Error("not ok");
    const data = await resp.json();
    badge.className = `worker-badge ${data.status === "running" ? "worker-running" : "worker-idle"}`;
    if (data.status === "running") {
      badge.textContent = `PC worker: 处理中 PID ${data.pid}`;
    } else if (data.last_returncode !== undefined) {
      badge.textContent = `PC worker: 上次退出 ${data.last_returncode}`;
    } else {
      badge.textContent = "PC worker: 空闲";
    }
  } catch {
    badge.className = "worker-badge worker-idle";
    badge.textContent = "PC worker: 未连接";
  }
}

refresh();
refreshRooms();
refreshSliceProgress();
refreshSliceDiagnostics();
refreshTasks();
refreshWorkerStatus();

setInterval(() => {
  if (document.visibilityState === "visible") {
    refresh();
    refreshTasks();
    refreshWorkerStatus();
  }
}, 30000);

setInterval(() => {
  if (document.visibilityState === "visible") {
    refreshSliceProgress();
    refreshSliceDiagnostics();
  }
}, 2000);

setInterval(() => {
  if (document.visibilityState === "visible") {
    refreshWorkerStatus();
  }
}, 5000);

document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") {
    refreshRooms();
    refresh();
    refreshTasks();
    refreshSliceProgress();
    refreshSliceDiagnostics();
    refreshWorkerStatus();
  }
});
