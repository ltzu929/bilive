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

function renderList() {
  const items = filteredSlices();
  elements.sliceCount.textContent = `${items.length} 个候选`;
  elements.sliceList.innerHTML = "";
  for (const item of items) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `slice-row${item.id === state.selectedId ? " active" : ""}`;
    button.innerHTML = `
      <span class="slice-name"></span>
      <span class="slice-meta"></span>
    `;
    button.querySelector(".slice-name").textContent = item.name;
    if (item.refined) {
      const badge = document.createElement("span");
      badge.className = "refined-badge";
      badge.textContent = "已精切";
      button.querySelector(".slice-name").appendChild(badge);
    }
    button.querySelector(".slice-meta").textContent =
      `${item.room_id} · ${formatBytes(item.size_bytes)} · ${item.decision}`;
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

setInterval(() => {
  if (document.visibilityState === "visible") {
    refresh();
  }
}, 30000);

document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") {
    refresh();
  }
});
