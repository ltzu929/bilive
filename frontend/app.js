const ICONS = {
  record: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="3"/></svg>',
  scissor: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="6" cy="7" r="3"/><circle cx="6" cy="17" r="3"/><path d="M8.5 8.5 20 20M8.5 15.5 20 4"/></svg>',
  upload: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 16V4"/><path d="m7 9 5-5 5 5"/><path d="M20 16v4H4v-4"/></svg>',
  setting: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1-2 2-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.6v.2h-3v-.2a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1-2-2 .1-.1A1.7 1.7 0 0 0 7.2 15a1.7 1.7 0 0 0-1.6-1H5.4v-3h.2a1.7 1.7 0 0 0 1.6-1 1.7 1.7 0 0 0-.3-1.9l-.1-.1 2-2 .1.1a1.7 1.7 0 0 0 1.9.3 1.7 1.7 0 0 0 1-1.6V4.6h3v.2a1.7 1.7 0 0 0 1 1.6 1.7 1.7 0 0 0 1.9-.3l.1-.1 2 2-.1.1a1.7 1.7 0 0 0-.3 1.9 1.7 1.7 0 0 0 1.6 1h.2v3H21a1.7 1.7 0 0 0-1.6 1Z"/></svg>',
  fold: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 4h12v16H6z"/><path d="M10 4v16"/></svg>',
  unfold: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 4h12v16H6z"/><path d="M14 4v16"/></svg>',
};

const embedShell = new URLSearchParams(window.location.search).get("embed");
const isBlrecEmbed = embedShell === "blrec";

if (isBlrecEmbed) {
  document.body.classList.add("blrec-embed");
  document.body.dataset.shell = "blrec";
}

document.querySelectorAll("[data-recorder-link]").forEach((element) => {
  const recorderUrl = new URL(window.location.href);
  recorderUrl.port = "2233";
  recorderUrl.pathname = "/tasks";
  recorderUrl.search = "";
  recorderUrl.hash = "";
  element.href = recorderUrl.toString();
});

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
  inspectorTab: "content",
  queueDrawerOpen: false,
  pendingDrop: null,
  actionBusy: false,
  pollingJobId: "",
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
  completenessScore: document.querySelector("#completeness-score"),
  confidenceScore: document.querySelector("#confidence-score"),
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
  queueToggle: document.querySelector("#source-queue-toggle"),
  sourceQueuePanel: document.querySelector("#source-queue-panel"),
  inspectorTabs: Array.from(document.querySelectorAll("[data-inspector-tab]")),
  inspectorPanels: Array.from(document.querySelectorAll("[data-inspector-panel]")),
  segmentFailureSummary: document.querySelector("#segment-failure-summary"),
  segmentRecoveryHint: document.querySelector("#segment-recovery-hint"),
  segmentRawError: document.querySelector("#segment-raw-error"),
  liveRegion: document.querySelector("#workbench-live-region"),
  actionToast: document.querySelector("#action-toast"),
  actionToastMessage: document.querySelector("#action-toast-message"),
  actionToastUndo: document.querySelector("#action-toast-undo"),
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
    const error = new Error(await response.text());
    error.status = response.status;
    throw error;
  }
  return response.json();
}

function showError(message) {
  elements.error.textContent = message;
  elements.error.classList.toggle("hidden", !message);
}

function announce(message) {
  if (!elements.liveRegion) return;
  elements.liveRegion.textContent = "";
  window.requestAnimationFrame(() => {
    elements.liveRegion.textContent = message || "";
  });
}

function showActionToast(message, { undo = false } = {}) {
  if (!elements.actionToast || !elements.actionToastMessage) return;
  elements.actionToastMessage.textContent = message;
  elements.actionToast.classList.remove("hidden");
  elements.actionToastUndo?.classList.toggle("hidden", !undo);
  announce(message);
}

function hideActionToast() {
  elements.actionToast?.classList.add("hidden");
  elements.actionToastUndo?.classList.add("hidden");
}

function humanizeFailure(rawValue, stage = "") {
  const raw = String(rawValue || "").trim();
  const normalized = `${stage} ${raw}`.toLowerCase();
  if (!raw) {
    return {
      summary: "å½“å‰æ²¡æœ‰æŠ€æœ¯æ•…éšœ",
      hint: "å¦‚éœ€é‡æ–°å¤„ç†ï¼Œå¯ä½¿ç”¨ä¸‹æ–¹ä¿®å¤åŠ¨ä½œã€‚",
    };
  }
  if (normalized.includes("3221225786") || normalized.includes("c000013a")) {
    return {
      summary: "å­—å¹•æ¸²æŸ“è¢«ç³»ç»Ÿä¸­æ–­",
      hint: "æºç‰‡æ®µå’Œæ¨¡åž‹ç»“æžœä»ä¼šä¿ç•™ï¼Œå¯ç›´æŽ¥é‡æ–°æ¸²æŸ“ï¼Œæ— éœ€é‡æ–°åˆ†æžã€‚",
    };
  }
  if (normalized.includes("ffmpeg") || normalized.includes("render") || normalized.includes("burn")) {
    return {
      summary: "æˆç‰‡æˆ–å­—å¹•æ¸²æŸ“å¤±è´¥",
      hint: "å…ˆæ£€æŸ¥ Windows é‡ä»»åŠ¡èŠ‚ç‚¹ï¼Œå†ä½¿ç”¨â€œé‡æ–°æ¸²æŸ“ç‰‡æ®µâ€ã€‚",
    };
  }
  if (normalized.includes("timeout") || normalized.includes("timed out")) {
    return {
      summary: "å¤„ç†è¯·æ±‚è¶…æ—¶",
      hint: "ç¡®è®¤ Windows é‡ä»»åŠ¡èŠ‚ç‚¹åœ¨çº¿åŽé‡æ–°åˆ†æžï¼›çŽ°æœ‰å€™é€‰ä¸ä¼šè‡ªåŠ¨æŠ•ç¨¿ã€‚",
    };
  }
  if (normalized.includes("queue") || normalized.includes("å…¥é˜Ÿ")) {
    return {
      summary: "æˆç‰‡æœªè¿›å…¥æŠ•ç¨¿é˜Ÿåˆ—",
      hint: "æ£€æŸ¥ä¸Šä¼ å…ƒæ•°æ®ä¸Žé˜Ÿåˆ—çŠ¶æ€ï¼Œä¿®å¤åŽé‡æ–°ç”Ÿæˆæˆç‰‡ã€‚",
    };
  }
  if (normalized.includes("mimo") || normalized.includes("judge") || normalized.includes("åˆ¤æ–­")) {
    return {
      summary: "æ¨¡åž‹åˆ¤æ–­æ²¡æœ‰å®Œæˆ",
      hint: "å€™é€‰å·²ä¿ç•™ä¾›äººå·¥å¤æ ¸ï¼Œå¯ç¨åŽé‡æ–°åˆ†æžã€‚",
    };
  }
  if (normalized.includes("worker") || normalized.includes("offline") || normalized.includes("unavailable")) {
    return {
      summary: "Windows é‡ä»»åŠ¡èŠ‚ç‚¹ä¸å¯ç”¨",
      hint: "å¯åŠ¨ start_pipeline.ps1 åŽé‡è¯•ï¼›å½“å‰æ“ä½œä¸ä¼šè‡ªåŠ¨æŠ•ç¨¿ã€‚",
    };
  }
  return {
    summary: "å¤„ç†æœªå®Œæˆï¼Œéœ€è¦äººå·¥æ£€æŸ¥",
    hint: "å±•å¼€åŽŸå§‹é”™è¯¯ç¡®è®¤é˜¶æ®µï¼Œå†é€‰æ‹©å¯¹åº”çš„ä¿®å¤åŠ¨ä½œã€‚",
  };
}

function setInspectorTab(tabName, { focus = false } = {}) {
  const tab = ["content", "subtitles", "technical"].includes(tabName) ? tabName : "content";
  state.inspectorTab = tab;
  for (const button of elements.inspectorTabs) {
    const active = button.dataset.inspectorTab === tab;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", active ? "true" : "false");
    button.tabIndex = active ? 0 : -1;
    if (active && focus) button.focus();
  }
  for (const panel of elements.inspectorPanels) {
    panel.classList.toggle("hidden", panel.dataset.inspectorPanel !== tab);
  }
}

function toggleSourceQueue(open = !state.queueDrawerOpen) {
  state.queueDrawerOpen = Boolean(open);
  document.body.classList.toggle("source-queue-open", state.queueDrawerOpen);
  elements.queueToggle?.setAttribute("aria-expanded", state.queueDrawerOpen ? "true" : "false");
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
  failed: { cls: "tag-red", labelÛ­:ÒÚ$z{-®éÜj×çV&Æ—6…VWVTÆ—7BæVæD6†–ÆB†7&VFUWÆöE&÷r†—FVÒÂG'VR’“°¢Ð§Ð ¦gVæ7F–öâf÷&ÖEW&f÷&Öæ6TçVÖ&W"‡fÇVR’°¢6öç7BçVÒÒçVÖ&W"‡fÇVR“°¢–b‚çVÖ&W"æ—4f–æ—FR†çVÒ’’&WGW&â"Ò#°¢–b†çVÒãÒ’&WGW&âG²†çVÒò’çFôf—†VBƒ—ÞKˆv°¢&WGW&â7G&–ær†çVÒ“°§Ð ¦7–æ2gVæ7F–öâ&Vg&W6…W&f÷&Öæ6UæVÂ‚’°¢–b‚VÆVÖVçG2çW&f÷&Öæ6T&öG’’&WGW&ã°¢ÆWB–ÆöC°¢G'’°¢–ÆöBÒv—B&WVW7B‚"ö’÷6Æ–6R×W&f÷&Öæ6R"“°¢Ò6F6‚‡&V6öâ’°¢VÆVÖVçG2çW&f÷&Öæ6T&öG’æ–ææW$…DÔÂÒÆF—b6Æ73Ò'F6²ÖV×G’#îŠû¾XùnZK‹J^ûÉ¢G¶W66T‡FÖÂ‡&V6öâæÖW76vR—ÓÂöF—cæ°¢&WGW&ã°¢Ð¢–b‡–ÆöBç7FGW2ÓÓÒ'Væf–Æ&ÆR"’°¢–b†VÆVÖVçG2çW&f÷&Öæ6T6÷VçB’VÆVÖVçG2çW&f÷&Öæ6T6÷VçBçFW‡D6öçFVçBÒ.i¨.izi[hÚâ#°¢VÆVÖVçG2çW&f÷&Öæ6T&öG’æ–ææW$…DÔÂÒsÆF—b6Æ73Ò'F6²ÖV×G’#î[	®izXù[ˆ>ŠŽxëi[hÚîûÈŽ™ÈXXŽYÊ‚v–æF÷w2zºþ˜x~™¸nûÈ“ÂöF—câs°¢&WGW&ã°¢Ð¢6öç7B—FV×2Ò–ÆöBæ—FV×2ÇÂµÓ°¢–b†VÆVÖVçG2çW&f÷&Öæ6T6÷VçB’VÆVÖVçG2çW&f÷&Öæ6T6÷VçBçFW‡D6öçFVçBÒG¶—FV×2æÆVæwF‡ÒKŠ®Xˆ~x˜v°¢–b‚—FV×2æÆVæwF‚’°¢VÆVÖVçG2çW&f÷&Öæ6T&öG’æ–ææW$…DÔÂÒsÆF—b6Æ73Ò'F6²ÖV×G’#îi¨.iz[{.Xù[ˆ>Xˆ~x˜sÂöF—câs°¢&WGW&ã°¢Ð¢6öç7B&÷w2Ò—FV×0¢æÖ€¢†—FVÒ’Óâ ¢ÇG#à¢ÇFB6Æ73Ò'W&f÷&Öæ6R×F—FÆR"F—FÆSÒ"G¶W66T‡FÖÂ†—FVÒçF—FÆRÇÂ—FVÒæ'f–BÇÂ"Ò"—Ò#âG¶W66T‡FÖÂ†—FVÒçF—FÆRÇÂ—FVÒæ'f–BÇÂ"Ò"—ÓÂ÷FCà¢ÇFCâG¶f÷&ÖEW&f÷&Öæ6TçVÖ&W"†—FVÒçf–Wr—ÓÂ÷FCà¢ÇFCâG¶f÷&ÖEW&f÷&Öæ6TçVÖ&W"†—FVÒæÆ–¶W2—ÓÂ÷FCà¢ÇFCâG¶f÷&ÖEW&f÷&Öæ6TçVÖ&W"†—FVÒæ6ö–â—ÓÂ÷FCà¢ÇFCâG¶f÷&ÖEW&f÷&Öæ6TçVÖ&W"†—FVÒæff÷&—FR—ÓÂ÷FCà¢ÇFCâG¶f÷&ÖEW&f÷&Öæ6TçVÖ&W"†—FVÒæFæÖ·R—ÓÂ÷FCà¢ÇFCâG¶—FVÒçVÆ—G•÷66÷&RÒçVÆÂòçVÖ&W"†—FVÒçVÆ—G•÷66÷&R’çFôf—†VBƒ"’¢"Ò'ÓÂ÷FCà¢Â÷G#æ ¢¢æ¦ö–â‚""“°¢VÆVÖVçG2çW&f÷&Öæ6T&öG’æ–ææW$…DÔÂÒ ¢ÇF&ÆR6Æ73Ò'W&f÷&Öæ6R×F&ÆR#à¢ÇF†VCà¢ÇG#ãÇFƒîXˆ~x˜sÂ÷FƒãÇFƒîi*ÞiKãÂ÷FƒãÇFƒîx+ž‹YãÂ÷FƒãÇFƒîh©^[ˆÂ÷FƒãÇFƒîiKn‰xóÂ÷FƒãÇFƒî[Ëž[™SÂ÷FƒãÇFƒî‹JŽ˜xþXˆcÂ÷FƒãÂ÷G#à¢Â÷F†VCà¢ÇF&öG“âG·&÷w7ÓÂ÷F&öG“à¢Â÷F&ÆSæ°§Ð ¦gVæ7F–öâ&VæFW%WÆöEVWVR‚’°¢6öç7B6÷VçG2ÒWÆöDF6†&ö&E7FFRçVWVUö6÷VçG2ÇÂ·Ó°¢WFFUWÆöDÖWG&–72‚'WÆöB"Â6÷VçG2“°¢WFFUWÆöDÖWG&–72‚'V&Æ—6‚"Â6÷VçG2“° ¢6öç7Bv÷&¶W"ÒWÆöDF6†&ö&E7FFRçv÷&¶W"ÇÂ·Ó°¢6öç7B–ÆÂÒFö7VÖVçBçVW'•6VÆV7F÷"‚"7WÆöB×v÷&¶W"×–ÆÂ"“°¢–b‡–ÆÂ’°¢6öç7B'Vææ–ærÒv÷&¶W"ç&ö6W75÷7FGW2ÓÓÒ''Vææ–ær#°¢–ÆÂæ6Æ74æÖRÒÆ—fR×–ÆÂG·'Vææ–ærò'F6²×7FFR×'Vææ–ær"¢'F6²×7FFRÖ–FÆR'Ö°¢–ÆÂçVW'•6VÆV7F÷"‚'7ã¦Æ7BÖ6†–ÆB"’çFW‡D6öçFVçBÒ'Vææ–ærò.Kˆ®KÊˆ¨.x+ž‹ùŠÎKŠÒ"¢.Kˆ®KÊˆ¨.x+žz›®™{"#°¢Ð ¢6öç7Bf–ÇFW"ÒFö7VÖVçBçVW'•6VÆV7F÷"‚"7WÆöB×7FGW2Öf–ÇFW""“òçfÇVRÇÂ&ÆÂ#°¢6öç7B—FV×2Òf–ÇFW&VEWÆöD—FV×2†f–ÇFW"“°¢6öç7B6÷VçBÒFö7VÖVçBçVW'•6VÆV7F÷"‚"7WÆöB×VWVRÖ6÷VçB"“°¢6öç7BÆ—7BÒFö7VÖVçBçVW'•6VÆV7F÷"‚"7WÆöB×VWVRÖÆ—7B"“°¢–b†6÷VçB’6÷VçBçFW‡D6öçFVçBÒG¶—FV×2æÆVæwF‡ÒKŠ®šžyºæ°¢–b†Æ—7B’°¢Æ—7Bæ–ææW$…DÔÂÒ"#°¢–b‚—FV×2æÆVæwF‚’°¢Æ—7Bæ–ææW$…DÔÂÒsÆF—b6Æ73Ò'F6²ÖV×G’#î[Ù>X˜ÞzÙ¾˜žiÚK»nKˆ¾k*iÈžh©^z‹þK»¾XªÂöF—câs°¢ÒVÇ6R°¢f÷"†6öç7B—FVÒöb—FV×2’°¢Æ—7BæVæD6†–ÆB†7&VFUWÆöE&÷r†—FVÒ’“°¢Ð¢Ð¢Ð¢&VæFW%V&Æ—6…VWVR‚“°¢&VæFW$f–ÇW&T–æ&÷‚‚“°§Ð¦7–æ2gVæ7F–öâv¶UWÆöEv÷&¶W"‚’°¢6öç7B'WGFöâÒFö7VÖVçBçVW'•6VÆV7F÷"‚"7WÆöB×v¶RÖ'WGFöâ"“°¢–b†'WGFöâ’'WGFöâæF—6&ÆVBÒG'VS°¢G'’°¢v—B&WVW7B‚"ö’÷v÷&¶W"×G&–vvW"÷v¶R"Â²ÖWF†öC¢%õ5B"Ò“°¢v—B&Vg&W6…WÆöDF6†&ö&B‚“°¢Ò6F6‚†W'&÷"’°¢6öç7B&÷‚ÒFö7VÖVçBçVW'•6VÆV7F÷"‚"7WÆöBÖW'&÷""“°¢–b†&÷‚’°¢&÷‚çFW‡D6öçFVçBÒW'&÷"æÖW76vS°¢&÷‚æ6Æ74Æ—7Bç&VÖ÷fR‚&†–FFVâ"“°¢Ð¢Òf–æÆÇ’°¢–b†'WGFöâ’'WGFöâæF—6&ÆVBÒfÇ6S°¢Ð§Ð ¦7–æ2gVæ7F–öâÆöDF6†&ö&E6WGF–æw2‚’°¢6öç7BFFÒv—B&WVW7B‚"ö’öF6†&ö&B×6WGF–æw2"“°¢6öç7B6WEfÇVRÒ†–BÂfÇVR’Óâ°¢6öç7BVÆVÖVçBÒFö7VÖVçBævWDVÆVÖVçD'”–B†–B“°¢–b†VÆVÖVçB’VÆVÖVçBçfÇVRÒfÇVS°¢Ó°¢6WEfÇVR‚'6WGF–ærÖ'W'7B×&F–ò"ÂG¶FFç6Æ–6Ræ'W'7E÷&F–÷×†“°¢6WEfÇVR‚'6WGF–ærÖ'W'7BÖ6öçFW‡B"Â+G¶FFç6Æ–6Ræ'W'7Eö6öçFW‡GÒzy&“°¢6WEfÇVR‚'6WGF–ærÖ'W'7B×F÷Öâ"ÂFFç6Æ–6Ræ'W'7E÷F÷öâ“°¢6WEfÇVR‚'6WGF–ærÖÖ–â×f–FVò×6—¦R"ÂG¶FFç6Æ–6RæÖ–å÷f–FVõ÷6—¦UöÖ'ÒÔ&“°¢6WEfÇVR‚'6WGF–ærÖÖ–ÖòÖÖöFVÂ"ÂFFæÖ–ÖòæÖöFVÂ“°¢6WEfÇVR‚'6WGF–ærÖÖ–ÖòÖg2"ÂG¶FFæÖ–Öòæg7Òe2+rG¶FFæÖ–ÖòæÖVF–÷&W6öÇWF–öçÖ“°¢6WEfÇVR€¢'6WGF–ærÖÖ–ÖòÖ¶W’"À¢FFæÖ–Öòæ6öæf–wW&VBò.[{.˜XÞ{Úâ"¢.yKv–æF÷w2xêþZ(>zêyb"À¢“°¢6WEfÇVR‚'6WGF–ær×v†—7W""ÂG¶FFçv†—7W"æÖöFVÇÒ+rG¶FFçv†—7W"æFWf–6WÒG¶FFçv†—7W"æ6ö×WFU÷G—WÖ“° ¢6öç7B&VfW&Væ6W2Ò¥4ôâç'6R†Æö6Å7F÷&vRævWD—FVÒ‚&F6†&ö&B×&VfW&Væ6W2"’ÇÂ'·Ò"“°¢6öç7B–çFW'fÂÒFö7VÖVçBçVW'•6VÆV7F÷"‚"7&Vb×&Vg&W6‚Ö–çFW'fÂ"“°¢6öç7B6ö×7BÒFö7VÖVçBçVW'•6VÆV7F÷"‚"7&VbÖ6ö×7B×VWVR"“°¢6öç7B6öÆÆ6RÒFö7VÖVçBçVW'•6VÆV7F÷"‚"7&VbÖ6öÆÆ6R×6–FV&""“°¢–b†–çFW'fÂ’–çFW'fÂçfÇVRÒ7G&–ær‡&VfW&Væ6W2ç&Vg&W6„–çFW'fÂÇÂ3“°¢–b†6ö×7B’6ö×7Bæ6†V6¶VBÒ&ööÆVâ‡&VfW&Væ6W2æ6ö×7EVWVR“°¢–b†6öÆÆ6R’6öÆÆ6Ræ6†V6¶VBÒÆö6Å7F÷&vRævWD—FVÒ‚'6–FW"Ö6öÆÆ6VB"’ÓÓÒ##°¢Fö7VÖVçBæ&öG’æ6Æ74Æ—7BçFövvÆR‚&6ö×7B×VWVR"Â&ööÆVâ‡&VfW&Væ6W2æ6ö×7EVWVR’“°§Ð ¦gVæ7F–öâ6fTF6†&ö&E&VfW&Væ6W2†WfVçB’°¢WfVçCòç&WfVçDFVfVÇB‚“°¢6öç7B&VfW&Væ6W2Ò°¢&Vg&W6„–çFW'fÃ¢çVÖ&W"†Fö7VÖVçBçVW'•6VÆV7F÷"‚"7&Vb×&Vg&W6‚Ö–çFW'fÂ"“òçfÇVRÇÂ3’À¢6ö×7EVWVS¢&ööÆVâ†Fö7VÖVçBçVW'•6VÆV7F÷"‚"7&VbÖ6ö×7B×VWVR"“òæ6†V6¶VB’À¢Ó°¢Æö6Å7F÷&vRç6WD—FVÒ‚&F6†&ö&B×&VfW&Væ6W2"Â¥4ôâç7G&–æv–g’‡&VfW&Væ6W2’“°¢6öç7B6öÆÆ6RÒ&ööÆVâ†Fö7VÖVçBçVW'•6VÆV7F÷"‚"7&VbÖ6öÆÆ6R×6–FV&""“òæ6†V6¶VB“°¢Ç”6öÆÆ6VB†6öÆÆ6R“°¢Fö7VÖVçBæ&öG’æ6Æ74Æ—7BçFövvÆR‚&6ö×7B×VWVR"Â&VfW&Væ6W2æ6ö×7EVWVR“°¢6öç7BÖW76vRÒFö7VÖVçBçVW'•6VÆV7F÷"‚"76WGF–æw2ÖÖW76vR"“°¢–b†ÖW76vR’°¢ÖW76vRçFW‡D6öçFVçBÒ.yXÎ™Ú.XþZ[Þ[{.KùÞZÙŽYÊŽ[Ù>X˜ÞkXþŠxŽYšŽ8.yIþKª~Xø.i[K¸ÞyK&–Æ—fR×6W'fW"çFöÖÂzêyn8"#°¢ÖW76vRæ6Æ74Æ—7Bç&VÖ÷fR‚&†–FFVâ"“°¢Ð§Ð ¦Fö7VÖVçBæFDWfVçDÆ—7FVæW"‚&¶W–F÷vâ"Â†WfVçB’Óâ°¢6öç7B7F—fRÒFö7VÖVçBæ7F—fTVÆVÖVçC°¢6öç7BFrÒ7F—fSòçFtæÖS°¢–b‡FrÓÓÒ$”åUB"ÇÂFrÓÓÒ%DU…D$T"ÇÂFrÓÓÒ%4TÄT5B"ÇÂ7F—fSòæ—46öçFVçDVF—F&ÆR’&WGW&ã°¢–b†7W'&VçEf–WtæÖR‚’ÓÒ'F6·2"’&WGW&ã°¢6öç7B¶W’ÒWfVçBæ¶W’çFôÆ÷vW$66R‚“°¢–b†WfVçBæ7G&Ä¶W’bb¶W’ÓÓÒ&VçFW""’°¢WfVçBç&WfVçDFVfVÇB‚“°¢f–æÆ—¦T7W'&VçE6VvÖVçB‚’æ6F6‚‚†W'&÷"’Óâ6†÷tW'&÷"†W'&÷"æÖW76vR’“°¢ÒVÇ6R–b†¶W’ÓÓÒ&¢"’°¢WfVçBç&WfVçDFVfVÇB‚“°¢6VÆV7E&VÆF—fU6VvÖVçBƒ“°¢ÒVÇ6R–b†¶W’ÓÓÒ&²"’°¢WfVçBç&WfVçDFVfVÇB‚“°¢6VÆV7E&VÆF—fU6VvÖVçB‚Ó“°¢ÒVÇ6R–b†¶W’ÓÓÒ""’°¢WfVçBç&WfVçDFVfVÇB‚“°¢FövvÆU6÷W&6U&Wf–WuÆ–&6²‚“°¢ÒVÇ6R–b†¶W’ÓÓÒ&’"’°¢WfVçBç&WfVçDFVfVÇB‚“°¢6WE&ævT&÷VæF'”g&öÕÆ–†VB‚'7F'B"“°¢ÒVÇ6R–b†¶W’ÓÓÒ&ò"’°¢WfVçBç&WfVçDFVfVÇB‚“°¢6WE&ævT&÷VæF'”g&öÕÆ–†VB‚&VæB"“°¢ÒVÇ6R–b†¶W’ÓÓÒ&B"’°¢WfVçBç&WfVçDFVfVÇB‚“°¢66†VGVÆTG&÷7W'&VçE6VvÖVçB‚“°¢ÒVÇ6R–b†¶W’ÓÓÒ&W66R"bb7FFRçVWVTG&vW$÷Vâ’°¢FövvÆU6÷W&6UVWVR†fÇ6R“°¢Ð§Ò“° ¦VÆVÖVçG2ç7F'E6Æ–6T'WGFöâæFDWfVçDÆ—7FVæW"‚&6Æ–6²"Â‚’Óâ7F'E6Æ–6–ær‚’“°¦VÆVÖVçG2ç7F'E6VÆV7FVE6Æ–6T'WGFöãòæFDWfVçDÆ—7FVæW"‚&6Æ–6²"Â‚’Óâ7F'E6Æ–6–ær‡²6VÆV7FVDöæÇ“¢G'VRÒ’“°¦VÆVÖVçG2ç7F÷6Æ–6T'WGFöãòæFDWfVçDÆ—7FVæW"‚&6Æ–6²"Â7F÷6Æ–6–ær“°¦VÆVÖVçG2ç&öw&W74÷Vå6÷W&6T'WGFöãòæFDWfVçDÆ—7FVæW"‚&6Æ–6²"Â‚’Óâ°¢v÷Fô7W'&VçE6÷W&6U&V6÷&F–ær‚’æ6F6‚‚†W'&÷"’Óâ6†÷tW'&÷"†W'&÷"æÖW76vR’“°§Ò“°¦VÆVÖVçG2ç&Vg&W6„'WGFöâæFDWfVçDÆ—7FVæW"‚&6Æ–6²"Â‚’Óâ°¢&Vg&W6‚‚“°¢&Vg&W6…6÷W&6U&V6÷&F–æw2‚“°§Ò“°¦VÆVÖVçG2ç7FGW4f–ÇFW"æFDWfVçDÆ—7FVæW"‚&6†ævR"Â‚’Óâ°¢6öç7B6†ævVBÒVç7W&Uf—6–&ÆU6÷W&6U6VÆV7F–öâ‚“°¢&VæFW%6÷W&6U&V6÷&F–æw2‚“°¢–b†6†ævVBbb7FFRç6VÆV7FVE6÷W&6T–B’°¢&Vg&W6…6÷W&6TFWF–Â‡7FFRç6VÆV7FVE6÷W&6T–B’æ6F6‚‚†W'&÷"’Óâ6†÷tW'&÷"†W'&÷"æÖW76vR’“°¢ÒVÇ6R–b‚7FFRç6VÆV7FVE6÷W&6T–B’°¢7FFRç6÷W&6TFWF–ÂÒçVÆÃ°¢&VæFW%6÷W&6TFWF–Â‚“°¢Ð§Ò“°¦VÆVÖVçG2ç&ööÔf–ÇFW"æFDWfVçDÆ—7FVæW"‚&6†ævR"Â‚’Óâ°¢&Vg&W6‚‚“°¢&Vg&W6…F6·2‚“°¢&Vg&W6…6÷W&6U&V6÷&F–æw2‚“°§Ò“°¦VÆVÖVçG2ç6fT'WGFöâæFDWfVçDÆ—7FVæW"‚&6Æ–6²"Â‚’Óâ6fU6VvÖVçE&ævR‚’æ6F6‚‚†W'&÷"’Óâ6†÷tW'&÷"†W'&÷"æÖW76vR’’“°¦VÆVÖVçG2æÖçVÅ7F'CòæFDWfVçDÆ—7FVæW"‚&–çWB"ÂÖ&µ&ævTG&gDg&öÔ–çWG2“°¦VÆVÖVçG2æÖçVÄVæCòæFDWfVçDÆ—7FVæW"‚&–çWB"ÂÖ&µ&ævTG&gDg&öÔ–çWG2“°¦VÆVÖVçG2çF6µæVÃòæFDWfVçDÆ—7FVæW"‚'FövvÆR"Â‚’Óâ°¢7FFRçF6µæVÄ6öÆÆ6VBÒVÆVÖVçG2çF6µæVÂæ÷Vã°¢–b†VÆVÖVçG2çF6µFövvÆR’VÆVÖVçG2çF6µFövvÆRçFW‡D6öçFVçBÒVÆVÖVçG2çF6µæVÂæ÷Vâò.iKn‹[r"¢.[^[È#°§Ò“°¦Fö7VÖVçBçVW'•6VÆV7F÷"‚"7WÆöB×&Vg&W6‚Ö'WGFöâ"“òæFDWfVçDÆ—7FVæW"‚&6Æ–6²"Â&Vg&W6…WÆöDF6†&ö&B“°¦VÆVÖVçG2çV&Æ—6…&Vg&W6„'WGFöãòæFDWfVçDÆ—7FVæW"‚&6Æ–6²"Â&Vg&W6…WÆöDF6†&ö&B“°¦VÆVÖVçG2çW&f÷&Öæ6U&Vg&W6„'WGFöãòæFDWfVçDÆ—7FVæW"‚&6Æ–6²"Â&Vg&W6…W&f÷&Öæ6UæVÂ“°¦Fö7VÖVçBçVW'•6VÆV7F÷"‚"7WÆöB×v¶RÖ'WGFöâ"“òæFDWfVçDÆ—7FVæW"‚&6Æ–6²"Âv¶UWÆöEv÷&¶W"“°¦VÆVÖVçG2çV&Æ—6…v¶T'WGFöãòæFDWfVçDÆ—7FVæW"‚&6Æ–6²"Âv¶UWÆöEv÷&¶W"“°¦Fö7VÖVçBçVW'•6VÆV7F÷"‚"7WÆöB×7FGW2Öf–ÇFW""“òæFDWfVçDÆ—7FVæW"‚&6†ævR"Â&VæFW%WÆöEVWVR“°¦Fö7VÖVçBçVW'•6VÆV7F÷"‚"76WGF–æw2Öf÷&Ò"“òæFDWfVçDÆ—7FVæW"‚'7V&Ö—B"Â6fTF6†&ö&E&VfW&Væ6W2“°¦Fö7VÖVçBçVW'•6VÆV7F÷"‚"76WGF–æw2×6fRÖ'WGFöâ"“òæFDWfVçDÆ—7FVæW"‚&6Æ–6²"Â6fTF6†&ö&E&VfW&Væ6W2“°¦VÆVÖVçG2ç6VvÖVçD¶VW'WGFöãòæFDWfVçDÆ—7FVæW"‚&6Æ–6²"Â‚’Óâf–æÆ—¦T7W'&VçE6VvÖVçB‚’æ6F6‚‚†W'&÷"’Óâ6†÷tW'&÷"†W'&÷"æÖW76vR’’“°¦VÆVÖVçG2ç6VvÖVçDG&÷'WGFöãòæFDWfVçDÆ—7FVæW"‚&6Æ–6²"Â66†VGVÆTG&÷7W'&VçE6VvÖVçB“°¦VÆVÖVçG2ç6VvÖVçE&WG'”'WGFöãòæFDWfVçDÆ—7FVæW"‚&6Æ–6²"Â‚’Óâ&WG'”7W'&VçE6VvÖVçD§VFvR‚’æ6F6‚‚†W'&÷"’Óâ6†÷tW'&÷"†W'&÷"æÖW76vR’’“°¦VÆVÖVçG2ç6VvÖVçE&VæFW$'WGFöãòæFDWfVçDÆ—7FVæW"‚&6Æ–6²"Â‚’Óâ&VæFW$7W'&VçE6VvÖVçB‚’æ6F6‚‚†W'&÷"’Óâ6†÷tW'&÷"†W'&÷"æÖW76vR’’“°¦VÆVÖVçG2ç7V'F—FÆU6fT'WGFöãòæFDWfVçDÆ—7FVæW"‚&6Æ–6²"Â‚’Óâ6fU7V'F—FÆU7G–ÆR‚’æ6F6‚‚†W'&÷"’Óâ6†÷tW'&÷"†W'&÷"æÖW76vR’’“°¦VÆVÖVçG2ç7V'F—FÆU&V'W&ä'WGFöãòæFDWfVçDÆ—7FVæW"‚&6Æ–6²"Â‚’Óâ&V'W&ä7W'&VçE7V'F—FÆW2‚’æ6F6‚‚†W'&÷"’Óâ6†÷tW'&÷"†W'&÷"æÖW76vR’’“°¦VÆVÖVçG2ç6VvÖVçE6fU&VæFW$'WGFöãòæFDWfVçDÆ—7FVæW"‚&6Æ–6²"Â‚’Óâ6fTæE&VæFW$7W'&VçE6VvÖVçB‚’æ6F6‚‚†W'&÷"’Óâ6†÷tW'&÷"†W'&÷"æÖW76vR’’“°¦VÆVÖVçG2æ7F–öåFö7EVæFóòæFDWfVçDÆ—7FVæW"‚&6Æ–6²"ÂVæFõVæF–ætG&÷“°¦VÆVÖVçG2çVWVUFövvÆSòæFDWfVçDÆ—7FVæW"‚&6Æ–6²"Â‚’ÓâFövvÆU6÷W&6UVWVR‚’“°¦f÷"†6öç7B'WGFöâöbVÆVÖVçG2æ–ç7V7F÷%F'2’°¢'WGFöâæFDWfVçDÆ—7FVæW"‚&6Æ–6²"Â‚’Óâ6WD–ç7V7F÷%F"†'WGFöâæFF6WBæ–ç7V7F÷%F"’“°¢'WGFöâæFDWfVçDÆ—7FVæW"‚&¶W–F÷vâ"Â†WfVçB’Óâ°¢–b‚²$'&÷tÆVgB"Â$'&÷u&–v‡B%Òæ–æ6ÇVFW2†WfVçBæ¶W’’’&WGW&ã°¢WfVçBç&WfVçDFVfVÇB‚“°¢6öç7B–æFW‚ÒVÆVÖVçG2æ–ç7V7F÷%F'2æ–æFW„öb†'WGFöâ“°¢6öç7Böfg6WBÒWfVçBæ¶W’ÓÓÒ$'&÷u&–v‡B"ò¢Ó°¢6öç7BæW‡BÒVÆVÖVçG2æ–ç7V7F÷%F'5²†–æFW‚²öfg6WB²VÆVÖVçG2æ–ç7V7F÷%F'2æÆVæwF‚’RVÆVÖVçG2æ–ç7V7F÷%F'2æÆVæwF…Ó°¢6WD–ç7V7F÷%F"†æW‡BæFF6WBæ–ç7V7F÷%F"Â²fö7W3¢G'VRÒ“°¢Ò“°§Ð¦f÷"†6öç7B'WGFöâöbVÆVÖVçG2æFV6—6–öä'WGFöç2’°¢'WGFöâæFDWfVçDÆ—7FVæW"‚&6Æ–6²"Â‚’Óâ°¢7FFRæFV6—6–öâÒ'WGFöâæFF6WBæFV6—6–öã°¢7–æ4FV6—6–öä'WGFöç2‚“°¢Ò“°§Ð ¦gVæ7F–öâ&VæFW%&VÖ÷FUv÷&¶W%7FGW2†FF’°¢6öç7B&FvRÒVÆVÖVçG2çv÷&¶W$&FvS°¢–b‚&FvR’&WGW&âfÇ6S°¢–b†FFòæÖöFRÓÒ'&VÖ÷FR"ÇÂFFæVæ&ÆVB’&WGW&âfÇ6S°¢6öç7B'Vææ–ærÒFFç7FGW2ÓÓÒ''Vææ–ær#°¢&FvRæ6Æ74æÖRÒv÷&¶W"Ö&FvRG·'Vææ–ærò'v÷&¶W"×'Vææ–ær"¢'v÷&¶W"Ö–FÆR'Ö°¢–b‡'Vææ–ær’°¢6öç7B–BÒFFçvF6†W#òç–BÇÂFFæÆö6³òç–BÇÂ"#°¢&FvRçFW‡D6öçFVçBÒv–æF÷w2˜xÞK»¾Xªˆ¨.x+žûÉ®ZHNynKŠÒG·–Bò”BG·–GÖ¢"'Ö°¢ÒVÇ6R–b†FFç7FGW2ÓÓÒ'Væf–Æ&ÆR"’°¢&FvRçFW‡D6öçFVçBÒ%v–æF÷w2˜xÞK»¾Xªˆ¨.x+žûÉ®zk¾{«ò#°¢ÒVÇ6R°¢&FvRçFW‡D6öçFVçBÒv–æF÷w2˜xÞK»¾Xªˆ¨.x+žûÉ®z›®™{.ûÈÎ[è^ZHNybG´çVÖ&W"†FFçVæF–æu÷F6·2ÇÂ—Ö°¢Ð¢6öç7Bf–ÇW&RÒ‡VÖæ—¦Tf–ÇW&R†FFæÖW76vRÂFFç7FGW2“°¢&FvRçF—FÆRÒFFç7FGW2ÓÓÒ'Væf–Æ&ÆR ¢òG¶f–ÇW&Rç7VÖÖ'—Þ8"G¶f–ÇW&Ræ†–çGÖ ¢¢%v–æF÷w2˜xÞK»¾Xªˆ¨.x+žx«nh#°¢&WGW&âG'VS°§Ð ¦7–æ2gVæ7F–öâ&Vg&W6…v÷&¶W%7FGW2‚’°¢G'’°¢6öç7B&VÖ÷FU7FGW2Òv—B&WVW7B‚"ö’÷v÷&¶W"×G&–vvW"÷7FGW2"“°¢–b‡&VæFW%&VÖ÷FUv÷&¶W%7FGW2‡&VÖ÷FU7FGW2’’&WGW&ã°¢Ò6F6‚°¢òòF†R&FvR&VÆ÷r&W÷'G2F†RVæf–Æ&ÆRv–æF÷w2v÷&¶W"à¢Ð¢–b†VÆVÖVçG2çv÷&¶W$&FvR’°¢VÆVÖVçG2çv÷&¶W$&FvRæ6Æ74æÖRÒ'v÷&¶W"Ö&FvRv÷&¶W"Ö–FÆR#°¢VÆVÖVçG2çv÷&¶W$&FvRçFW‡D6öçFVçBÒ%v–æF÷w2˜xÞK»¾Xªˆ¨.x+žûÉ®zk¾{«ò#°¢Ð§Ð ¦7–æ2gVæ7F–öâv¶Uv÷&¶W$öåvTÆöB‚’°¢–b‚VÆVÖVçG2çv÷&¶W$&FvR’&WGW&ã°¢VÆVÖVçG2çv÷&¶W$&FvRæ6Æ74æÖRÒ'v÷&¶W"Ö&FvRv÷&¶W"×'Vææ–ær#°¢VÆVÖVçG2çv÷&¶W$&FvRçFW‡D6öçFVçBÒ%v–æF÷w2˜xÞK»¾Xªˆ¨.x+žûÉ®Y
þXªŽKŠÒ#°¢G'’°¢6öç7B7FGW2Òv—B&WVW7B‚"ö’÷v÷&¶W"×G&–vvW"÷v¶R"Â°¢ÖWF†öC¢%õ5B"À¢Ò“°¢&VæFW%&VÖ÷FUv÷&¶W%7FGW2‡7FGW2“°¢Ò6F6‚°¢VÆVÖVçG2çv÷&¶W$&FvRæ6Æ74æÖRÒ'v÷&¶W"Ö&FvRv÷&¶W"Ö–FÆR#°¢VÆVÖVçG2çv÷&¶W$&FvRçFW‡D6öçFVçBÒ%v–æF÷w2˜xÞK»¾Xªˆ¨.x+žûÉ®zk¾{«ò#°¢Ð§Ð ¦6öç7B7F—fUf–WrÒ7F—fFT7W'&VçEf–Wr‚“°§6WD–ç7V7F÷%F"‚&6öçFVçB"“°¦–b†VÆVÖVçG2çF6µæVÂ’VÆVÖVçG2çF6µæVÂæ÷VâÒfÇ6S°§v–æF÷ræFDWfVçDÆ—7FVæW"‚'&W6—¦R"Â‚’Óâ°¢–b‚v–æF÷ræÖF6„ÖVF–‚"†Ö‚×v–GFƒ¢3#‚’"’æÖF6†W2’FövvÆU6÷W&6UVWVR†fÇ6R“°§Ò“°¦–b†7F—fUf–WrÓÓÒ'F6·2"’°¢&Vg&W6‚‚“°¢&Vg&W6…&öö×2‚“°¢&Vg&W6…6÷W&6U&V6÷&F–æw2‚“°¢&Vg&W6…6Æ–6U&öw&W72‚“°¢&Vg&W6…6Æ–6TF–væ÷7F–72‚“°¢&Vg&W6…F6·2‚“°¢&Vg&W6…WÆöDF6†&ö&B‚“°¢&Vg&W6…W&f÷&Öæ6UæVÂ‚“°¢v¶Uv÷&¶W$öåvTÆöB‚“°§ÒVÇ6R–b†7F—fUf–WrÓÓÒ'WÆöG2"’°¢&Vg&W6…WÆöDF6†&ö&B‚“°¢&Vg&W6…v÷&¶W%7FGW2‚“°§ÒVÇ6R°¢ÆöDF6†&ö&E6WGF–æw2‚’æ6F6‚‚†W'&÷"’Óâ°¢6öç7BÖW76vRÒFö7VÖVçBçVW'•6VÆV7F÷"‚"76WGF–æw2ÖÖW76vR"“°¢–b†ÖW76vR’°¢ÖW76vRçFW‡D6öçFVçBÒW'&÷"æÖW76vS°¢ÖW76vRæ6Æ74Æ—7Bç&VÖ÷fR‚&†–FFVâ"“°¢Ð¢Ò“°§Ð §6WD–çFW'fÂ‚‚’Óâ°¢–b†Fö7VÖVçBçf—6–&–Æ—G•7FFRÓÒ'f—6–&ÆR"’&WGW&ã°¢6öç7Bf–WrÒ7W'&VçEf–WtæÖR‚“°¢–b‡f–WrÓÓÒ'F6·2"’°¢&Vg&W6‚‚“°¢&Vg&W6…6÷W&6U&V6÷&F–æw2‚“°¢&Vg&W6…F6·2‚“°¢&Vg&W6…v÷&¶W%7FGW2‚“°¢&Vg&W6…WÆöDF6†&ö&B‚“°¢ÒVÇ6R–b‡f–WrÓÓÒ'WÆöG2"’°¢&Vg&W6…WÆöDF6†&ö&B‚“°¢Ð§ÒÂçVÖ&W"„¥4ôâç'6R†Æö6Å7F÷&vRævWD—FVÒ‚&F6†&ö&B×&VfW&Væ6W2"’ÇÂ'·Ò"’ç&Vg&W6„–çFW'fÂÇÂ3’¢“° §6WD–çFW'fÂ‚‚’Óâ°¢–b†Fö7VÖVçBçf—6–&–Æ—G•7FFRÓÓÒ'f—6–&ÆR"bb7W'&VçEf–WtæÖR‚’ÓÓÒ'F6·2"’°¢&Vg&W6…6Æ–6U&öw&W72‚“°¢&Vg&W6…6Æ–6TF–væ÷7F–72‚“°¢Ð§ÒÂ#“° §6WD–çFW'fÂ‚‚’Óâ°¢–b†Fö7VÖVçBçf—6–&–Æ—G•7FFRÓÓÒ'f—6–&ÆR"bb7W'&VçEf–WtæÖR‚’ÓÓÒ'F6·2"’°¢&Vg&W6…v÷&¶W%7FGW2‚“°¢Ð§ÒÂS“° ¦Fö7VÖVçBæFDWfVçDÆ—7FVæW"‚'f—6–&–Æ—G–6†ævR"Â‚’Óâ°¢–b†Fö7VÖVçBçf—6–&–Æ—G•7FFRÓÒ'f—6–&ÆR"’&WGW&ã°¢6öç7Bf–WrÒ7W'&VçEf–WtæÖR‚“°¢–b‡f–WrÓÓÒ'F6·2"’°¢&Vg&W6…&öö×2‚“°¢&Vg&W6‚‚“°¢&Vg&W6…6÷W&6U&V6÷&F–æw2‚“°¢&Vg&W6…F6·2‚“°¢&Vg&W6…6Æ–6U&öw&W72‚“°¢&Vg&W6…6Æ–6TF–væ÷7F–72‚“°¢&Vg&W6…v÷&¶W%7FGW2‚“°¢&Vg&W6…WÆöDF6†&ö&B‚“°¢&Vg&W6…W&f÷&Öæ6UæVÂ‚“°¢ÒVÇ6R–b‡f–WrÓÓÒ'WÆöG2"’°¢&Vg&W6…WÆöDF6†&ö&B‚“°¢Ð§Ò“° 