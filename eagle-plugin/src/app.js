import {
  MANAGED_TAGS,
  applySyncPlan,
  ensureFolderHierarchy,
  hydratePlanThumbnails,
  planSync,
} from "./sync.js";

const DEFAULT_BASE_URL = "http://192.168.31.157:2234";

const baseUrlInput = document.querySelector("#base-url");
const syncButton = document.querySelector("#sync-button");
const summary = document.querySelector("#summary");
const log = document.querySelector("#log");

baseUrlInput.value = localStorage.getItem("bilive.dashboard.baseUrl") || DEFAULT_BASE_URL;

syncButton.addEventListener("click", () => {
  sync().catch((error) => {
    writeSummary("同步失败");
    writeLog(error?.stack || String(error));
  });
});

async function sync() {
  const baseUrl = normalizeBaseUrl(baseUrlInput.value);
  localStorage.setItem("bilive.dashboard.baseUrl", baseUrl);
  syncButton.disabled = true;
  writeSummary("正在同步...");
  writeLog(`GET ${new URL("/api/eagle/source-recordings", baseUrl).toString()}`);

  try {
    const recordings = await fetchSourceRecordings(baseUrl);
    const folderMap = await ensureFolderHierarchy(eagle.folder, recordings);
    const existing = await eagle.item.get({
      tags: MANAGED_TAGS,
      fields: ["id", "name", "url", "tags", "folders", "annotation"],
    });
    const plan = planSync(recordings, existing, baseUrl, folderMap);
    await hydratePlanThumbnails(plan, baseUrl, fetchImageAsDataUrl);
    writeLog([
      `recordings: ${recordings.length}`,
      `folders: ${folderMap.size + 1}`,
      `create: ${plan.create.length}`,
      `update: ${plan.update.length}`,
      `trash: ${plan.trash.length}`,
    ].join("\n"));
    const result = await applySyncPlan(eagle.item, plan);
    writeSummary(
      `新增 ${result.created}，更新 ${result.updated}，删除 ${result.trashed}，失败 ${result.failed}`,
    );
    writeLog(`${log.textContent}\nresult: ${JSON.stringify(result, null, 2)}`);
  } finally {
    syncButton.disabled = false;
  }
}

async function fetchSourceRecordings(baseUrl) {
  const response = await fetch(new URL("/api/eagle/source-recordings", baseUrl));
  if (!response.ok) {
    throw new Error(`bilive API returned ${response.status}`);
  }
  const payload = await response.json();
  if (!Array.isArray(payload)) {
    throw new Error("bilive API returned a non-array payload");
  }
  return payload;
}

async function fetchImageAsDataUrl(url) {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`thumbnail returned ${response.status}`);
  }
  const contentType = response.headers.get("content-type") || "image/jpeg";
  const buffer = await response.arrayBuffer();
  return `data:${contentType};base64,${arrayBufferToBase64(buffer)}`;
}

function arrayBufferToBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  const chunks = [];
  // Build the binary string in fixed-size chunks instead of one
  // String.fromCharCode per byte; the per-byte concat is O(n^2) for large
  // cover images and can stall the Eagle plugin UI during a sync.
  const chunkSize = 0x8000;
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    const slice = bytes.subarray(offset, Math.min(offset + chunkSize, bytes.length));
    chunks.push(String.fromCharCode.apply(null, slice));
  }
  return btoa(chunks.join(""));
}

function normalizeBaseUrl(value) {
  const trimmed = String(value || DEFAULT_BASE_URL).trim();
  return trimmed.endsWith("/") ? trimmed.slice(0, -1) : trimmed;
}

function writeSummary(message) {
  summary.textContent = message;
}

function writeLog(message) {
  log.textContent = message;
}
