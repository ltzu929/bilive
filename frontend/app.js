// ── Icon SVGs (ant-design outline style, 16x16 viewBox) ──
const ICONS = {
  record: '<svg viewBox="64 64 896 896" fill="currentColor"><path d="M512 64C264.6 64 64 264.6 64 512s200.6 448 448 448 448-200.6 448-448S759.4 64 512 64zm0 820c-205.4 0-372-166.6-372-372s166.6-372 372-372 372 166.6 372 372-166.6 372-372 372z"/><path d="M512 312m-112 0a112 112 0 1 0 224 0 112 112 0 1 0-224 0zM512 560c-118.6 0-216 56.2-216 128v16c0 8.8 7.2 16 16 16h400c8.8 0 16-7.2 16-16v-16c0-71.8-97.4-128-216-128z"/></svg>',
  scissor: '<svg viewBox="64 64 896 896" fill="currentColor"><path d="M567.1 512l318.5-318.5c8.2-8.2 8.2-21.5 0-29.7s-21.5-8.2-29.7 0L512 482.3 168.1 138.4c-8.2-8.2-21.5-8.2-29.7 0s-8.2 21.5 0 29.7L456.9 486 138.4 804.5c-8.2 8.2-8.2 21.5 0 29.7a20.95 20.95 0 0030.2-.3l.1-.1L512 541.7l343.8 344.4c8.2 8.2 21.5 8.2 29.7 0s8.2-21.5 0-29.7L567.1 512z"/></svg>',
  upload: '<svg viewBox="64 64 896 896" fill="currentColor"><path d="M400 317.7h73.9V656c0 4.4 3.6 8 8 8h60c4.4 0 8-3.6 8-8V317.7H624c6.7 0 10.4-7.7 6.3-12.9L518.3 163a8 8 0 00-12.6 0l-112 141.7c-4.1 5.3-.4 13 6.3 13zM878 626h-60c-4.4 0-8 3.6-8 8v154H214V634c0-4.4-3.6-8-8-8h-60c-4.4 0-8 3.6-8 8v198c0 17.7 14.3 32 32 32h684c17.7 0 32-14.3 32-32V634c0-4.4-3.6-8-8-8z"/></svg>',
  setting: '<svg viewBox="64 64 896 896" fill="currentColor"><path d="M924.8 625.7l-65.5-56c3.1-19 4.7-38.4 4.7-57.8s-1.6-38.8-4.7-57.8l65.5-56a32.03 32.03 0 009.3-35.2l-.9-2.6a443.74 443.74 0 00-79.7-137.9l-1.8-2.1a32.12 32.12 0 00-35.1-9.5l-81.3 28.9c-30-24.6-63.5-44-99.7-57.6l-15.7-85a32.05 32.05 0 00-25.8-25.7l-2.7-.5c-52.1-9.4-106.9-9.4-159 0l-2.7.5a32.05 32.05 0 00-25.8 25.7l-15.8 85.4a351.86 351.86 0 00-99 57.4l-81.9-29.1a32 32 0 00-35.1 9.5l-1.8 2.1a446.02 446.02 0 00-79.7 137.9l-.9 2.6c-4.5 12.5-.8 26.5 9.3 35.2l66.3 56.6c-3.1 18.8-4.6 38-4.6 57.1 0 19.2 1.5 38.4 4.6 57.1L99 625.5a32.03 32.03 0 00-9.3 35.2l.9 2.6c18.1 50.4 44.9 96.9 79.7 137.9l1.8 2.1a32.12 32.12 0 0035.1 9.5l81.9-29.1c29.8 24.5 63.1 43.9 99 57.4l15.8 85.4a32.05 32.05 0 0025.8 25.7l2.7.5c26.2 4.7 53.2 7.1 79.5 7.1 26.4 0 53.4-2.4 79.5-7.1l2.7-.5a32.05 32.05 0 0025.8-25.7l15.7-85a350.2 350.2 0 0099.7-57.6l81.3 28.9a32 32 0 0035.1-9.5l1.8-2.1c34.8-41.1 61.6-87.5 79.7-137.9l.9-2.6c4.5-12.3.8-26.2-9.3-35zM788.3 465.9c2.5 16.1 3.8 32.6 3.8 49.1s-1.3 33-3.8 49.1l-3.2 19.7 58.6 50.2a348.86 348.86 0 01-42.3 73.1l-72.3-25.7-15.4 12.5c-24.8 20.1-52.7 35.7-82.9 46.2l-18.6 6.1-14 75.5a402.46 402.46 0 01-92 0l-14-75.5-18.6-6.1c-30.2-10.5-58.1-26.1-82.9-46.2l-15.4-12.5-72.2 25.7a350.5 350.5 0 01-42.4-73.1l58.6-50.2-3.2-19.7c-2.5-16.1-3.8-32.6-3.8-49.1s1.3-33 3.8-49.1l3.2-19.7-58.6-50.2a348.86 348.86 0 0142.3-73.1l72.3 25.7 15.4-12.5c24.8-20.1 52.7-35.7 82.9-46.2l18.6-6.1 14-75.5a402.46 402.46 0 0192 0l14 75.5 18.6 6.1c30.2 10.5 58.1 26.1 82.9 46.2l15.4 12.5 72.3-25.7a350.5 350.5 0 0142.4 73.1l-58.6 50.2 3.2 19.7zM512 378c-75.3 0-136 60.7-136 136s60.7 136 136 136 136-60.7 136-136-60.7-136-136-136zm0 208c-39.7 0-72-32.3-72-72s32.3-72 72-72 72 32.3 72 72-32.3 72-72 72z"/></svg>',
  fold: '<svg viewBox="64 64 896 896" fill="currentColor"><path d="M408 688h48c4.4 0 8-3.6 8-8V344c0-4.4-3.6-8-8-8h-48c-4.4 0-8 3.6-8 8v336c0 4.4 3.6 8 8 8zm-136-56h48c4.4 0 8-3.6 8-8V400c0-4.4-3.6-8-8-8h-48c-4.4 0-8 3.6-8 8v224c0 4.4 3.6 8 8 8zm460-312H652V128H372v192H252c-6.6 0-12 5.4-12 12v472c0 6.6 5.4 12 12 12h480c6.6 0 12-5.4 12-12V332c0-6.6-5.4-12-12-12zM420 188h184v120H420V188zm240 540H324V412h336v316z"/></svg>',
  unfold: '<svg viewBox="64 64 896 896" fill="currentColor"><path d="M420 128H252c-6.6 0-12 5.4-12 12v472c0 6.6 5.4 12 12 12h480c6.6 0 12-5.4 12-12V332c0-6.6-5.4-12-12-12H420V128zm184 64v120H420V192h184zM324 540V412h336v316H324V540zm96-168h48c4.4 0 8-3.6 8-8V344c0-4.4-3.6-8-8-8h-48c-4.4 0-8 3.6-8 8v20c0 4.4 3.6 8 8 8zm184 0h48c4.4 0 8-3.6 8-8V344c0-4.4-3.6-8-8-8h-48c-4.4 0-8 3.6-8 8v20c0 4.4 3.6 8 8 8z"/></svg>',
};

// Inject icons into nav items
document.querySelectorAll('.nav-icon[data-icon]').forEach(el => {
  el.innerHTML = ICONS[el.dataset.icon] || '';
});

// ── Sidebar collapse ──
const appShell = document.getElementById('app-shell');
const siderToggle = document.getElementById('sider-toggle');
const siderIcon = siderToggle?.querySelector('.nav-icon');

function applyCollapsed(collapsed) {
  appShell.classList.toggle('collapsed', collapsed);
  if (siderIcon) siderIcon.dataset.icon = collapsed ? 'unfold' : 'fold';
  siderIcon.innerHTML = ICONS[siderIcon.dataset.icon] || '';
  localStorage.setItem('sider-collapsed', collapsed ? '1' : '');
}

if (siderToggle) {
  siderToggle.addEventListener('click', () => {
    applyCollapsed(!appShell.classList.contains('collapsed'));
  });
  // Restore state
  if (localStorage.getItem('sider-collapsed') === '1') applyCollapsed(true);
}

const state = {
  slices: [],
  selectedId: "",
  decision: "review",
};

const elements = {
  roomFilter: document.querySelector("#room-filter"),
  statusFilter: document.querySelector("#status-filter"),
  refreshButton: document.querySelector("#refresh-button"),
  sliceCount: document.querySelector("#slice-count"),
  sliceList: document.querySelector("#slice-list"),
  error: document.querySelector("#error"),
  previewVideo: document.querySelector("#preview-video"),
  sourceRecording: document.querySelector("#source-recording"),
  densityCore: document.querySelector("#density-core"),
  contextWindow: document.querySelector("#context-window"),
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

function selectedSlice() {
  return filteredSlices().find((item) => item.id === state.selectedId) || null;
}

function filteredSlices() {
  const status = elements.statusFilter.value;
  if (status === "all") return state.slices;
  return state.slices.filter((item) => item.decision === status);
}

function ensureVisibleSelection() {
  const items = filteredSlices();
  if (!items.some((item) => item.id === state.selectedId)) {
    state.selectedId = items[0]?.id || "";
  }
}

const DECISION_TAG = {
  review: { cls: 'tag-blue',   label: 'review' },
  keep:   { cls: 'tag-green',  label: 'keep' },
  drop:   { cls: 'tag-red',    label: 'drop' },
};

function decisionTag(decision) {
  const cfg = DECISION_TAG[decision] || DECISION_TAG.review;
  const span = document.createElement('span');
  span.className = `tag ${cfg.cls}`;
  span.textContent = cfg.label;
  return span;
}

function renderList() {
  const items = filteredSlices();
  elements.sliceCount.textContent = `${items.length} 个候选`;
  elements.sliceList.innerHTML = "";
  for (const item of items) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `slice-row${item.id === state.selectedId ? " active" : ""}`;
    const nameRow = document.createElement('span');
    nameRow.className = 'slice-name';
    nameRow.textContent = item.name;
    if (item.refined) {
      const badge = document.createElement("span");
      badge.className = "refined-badge";
      badge.textContent = "已精切";
      nameRow.appendChild(badge);
    }
    const metaRow = document.createElement('span');
    metaRow.className = 'slice-meta';
    const room = document.createElement('span');
    room.textContent = item.room_id;
    const size = document.createElement('span');
    size.textContent = formatBytes(item.size_bytes);
    metaRow.append(room, document.createTextNode('·'), size, decisionTag(item.decision));
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
    ? "进度已停止更新，请检查切片进程"
    : (progress.error || progress.message || "暂无切片任务");
  elements.progressSource.textContent = progress.source_name || "-";
  elements.progressCount.textContent = `${Number(progress.current_slice || 0)}/${Number(progress.total_slices || 0)}`;
  elements.progressPercent.textContent = `${percent.toFixed(0)}%`;
  elements.progressBar.style.width = `${percent}%`;
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

async function refresh() {
  showError("");
  const roomId = elements.roomFilter.value.trim();
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
    });
    render();
  } catch (error) {
    showError(error.message);
  } finally {
    elements.saveButton.disabled = false;
  }
}

elements.refreshButton.addEventListener("click", refresh);
elements.statusFilter.addEventListener("change", render);
elements.roomFilter.addEventListener("keydown", (event) => {
  if (event.key === "Enter") refresh();
});
elements.saveButton.addEventListener("click", saveFeedback);
for (const button of elements.decisionButtons) {
  button.addEventListener("click", () => {
    state.decision = button.dataset.decision;
    syncDecisionButtons();
  });
}

refresh();
refreshSliceProgress();

setInterval(() => {
  if (document.visibilityState === "visible") {
    refresh();
  }
}, 30000);

setInterval(() => {
  if (document.visibilityState === "visible") {
    refreshSliceProgress();
  }
}, 2000);

document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") {
    refresh();
    refreshSliceProgress();
  }
});
