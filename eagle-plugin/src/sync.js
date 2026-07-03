export const MANAGED_TAGS = ["bilive", "原始录播"];
export const ROOT_FOLDER_NAME = "bilive 原始录播";
export const THUMBNAIL_MODE = "bookmark-base64-v2";

export function recordingKey(recording) {
  return String(recording?.source_task_id || recording?.source_rel_path || "").trim();
}

export function tagsForRecording(recording) {
  const date = String(recording.recorded_at || "").slice(0, 10) || "unknown";
  const roomName = String(recording.room_name || recording.room_id || "unknown");
  const status = String(recording.status || "unknown");
  const reviewState = Number(recording.review_count || 0) > 0 ? "有" : "无";
  return [
    ...MANAGED_TAGS,
    `UP:${roomName}`,
    `日期:${date}`,
    `状态:${status}`,
    `待审核:${reviewState}`,
  ];
}

export function annotationForRecording(recording) {
  const fields = [
    ["bilive_source_task_id", recording.source_task_id],
    ["source_rel_path", recording.source_rel_path],
    ["room_id", recording.room_id],
    ["room_name", recording.room_name],
    ["recorded_at", recording.recorded_at],
    ["source_size_mb", recording.source_size_mb],
    ["status", recording.status],
    ["segment_count", recording.segment_count],
    ["review_count", recording.review_count],
    ["keep_count", recording.keep_count],
  ];
  if (recording.thumbnail_url) {
    fields.push(["thumbnail_url", recording.thumbnail_url]);
  }
  if (recording.thumbnail_mode) {
    fields.push(["thumbnail_mode", recording.thumbnail_mode]);
  }
  return fields.map(([key, value]) => `${key}: ${String(value ?? "")}`).join("\n");
}

export function parseManagedAnnotation(annotation) {
  const parsed = {};
  for (const line of String(annotation || "").split(/\r?\n/)) {
    const separator = line.indexOf(":");
    if (separator <= 0) continue;
    const key = line.slice(0, separator).trim();
    const value = line.slice(separator + 1).trim();
    if (key) parsed[key] = value;
  }
  return parsed;
}

export function bookmarkPayloadForRecording(recording, baseUrl, folderIds = []) {
  const thumbnailUrl = recording.thumbnail_url ? absoluteUrl(baseUrl, recording.thumbnail_url) : "";
  const annotatedRecording = thumbnailUrl
    ? { ...recording, thumbnail_url: thumbnailUrl, thumbnail_mode: THUMBNAIL_MODE }
    : recording;
  return {
    name: bookmarkName(recording),
    url: absoluteUrl(baseUrl, recording.workspace_url || "/tasks"),
    tags: tagsForRecording(recording),
    annotation: annotationForRecording(annotatedRecording),
    folders: folderIds,
    base64: thumbnailBase64(recording),
    thumbnailUrl,
  };
}

export function planSync(recordings, existingItems, baseUrl, folderMap = new Map()) {
  const byKey = new Map();
  for (const recording of recordings || []) {
    const key = recordingKey(recording);
    if (!key || byKey.has(key)) continue;
    byKey.set(key, recording);
  }

  const seenExisting = new Set();
  const existingByKey = new Map();
  const trash = [];

  for (const item of existingItems || []) {
    const key = existingItemKey(item);
    if (!key) continue;
    if (seenExisting.has(key)) {
      // Duplicate existing items for the same key (e.g. an orphaned bookmark
      // left behind when a previous recreate's addBookmark succeeded in Eagle
      // but rejected on the JS side). Prefer the item that already carries the
      // thumbnail_mode marker (the newer, correct one) and trash the other so
      // we don't keep the stale copy and re-trigger a recreate loop.
      const kept = existingByKey.get(key);
      const preferNew = hasThumbnailMode(item);
      if (preferNew && !hasThumbnailMode(kept)) {
        existingByKey.set(key, item);
        trash.push({ key, item: kept });
      } else {
        trash.push({ key, item });
      }
      continue;
    }
    seenExisting.add(key);
    existingByKey.set(key, item);
  }

  const create = [];
  const update = [];
  for (const [key, recording] of byKey) {
    const folderId = folderMap.get(folderNameForRecording(recording));
    const payload = bookmarkPayloadForRecording(recording, baseUrl, folderId ? [folderId] : []);
    const item = existingByKey.get(key);
    if (!item) {
      create.push({ key, recording, payload });
    } else if (needsThumbnailRecreate(item, payload)) {
      payload.tags = mergeManagedTags(item.tags || [], payload.tags);
      create.push({ key, recording, payload });
      trash.push({ key, item, requiresCreate: true });
    } else if (needsUpdate(item, payload)) {
      payload.tags = mergeManagedTags(item.tags || [], payload.tags);
      update.push({ key, item, recording, payload });
    }
  }

  for (const [key, item] of existingByKey) {
    if (!byKey.has(key)) {
      trash.push({ key, item });
    }
  }

  return { create, update, trash };
}

export async function applySyncPlan(eagleItemApi, plan) {
  const result = { created: 0, updated: 0, trashed: 0, failed: 0 };
  const createdKeys = new Set();

  for (const entry of plan.create || []) {
    try {
      await eagleItemApi.addBookmark(entry.payload.url, {
        name: entry.payload.name,
        base64: entry.payload.base64,
        tags: entry.payload.tags,
        folders: entry.payload.folders,
        annotation: entry.payload.annotation,
      });
      result.created += 1;
      createdKeys.add(entry.key);
    } catch (_error) {
      result.failed += 1;
    }
  }

  for (const entry of plan.update || []) {
    try {
      entry.item.name = entry.payload.name;
      entry.item.url = entry.payload.url;
      entry.item.tags = entry.payload.tags;
      entry.item.folders = entry.payload.folders;
      entry.item.annotation = entry.payload.annotation;
      await entry.item.save();
      result.updated += 1;
    } catch (_error) {
      result.failed += 1;
    }
  }

  for (const entry of plan.trash || []) {
    if (entry.requiresCreate && !createdKeys.has(entry.key)) {
      continue;
    }
    try {
      await entry.item.moveToTrash();
      result.trashed += 1;
    } catch (_error) {
      result.failed += 1;
    }
  }

  return result;
}

export async function ensureFolderHierarchy(folderApi, recordings) {
  const folders = await folderApi.getAll();
  let root = findFolder(folders, ROOT_FOLDER_NAME, "");
  if (!root) {
    root = await folderApi.create({
      name: ROOT_FOLDER_NAME,
      description: "bilive current source recordings",
    });
  }

  const mapping = new Map();
  for (const recording of recordings || []) {
    const name = folderNameForRecording(recording);
    if (!name || mapping.has(name)) continue;
    let folder = findFolder(folders, name, root.id);
    if (!folder) {
      folder = await folderApi.createSubfolder(root.id, {
        name,
        description: `bilive source recordings for ${name}`,
      });
    }
    mapping.set(name, folder.id);
  }
  return mapping;
}

export function folderNameForRecording(recording) {
  const value = String(recording?.room_name || recording?.room_id || "unknown").trim();
  return value.replace(/[\\/:*?"<>|]/g, "_") || "unknown";
}

export async function hydratePlanThumbnails(plan, baseUrl, fetchImageAsDataUrl) {
  const entries = [...(plan.create || []), ...(plan.update || [])];
  for (const entry of entries) {
    const thumbnailUrl = entry.recording?.thumbnail_url;
    if (!thumbnailUrl) continue;
    try {
      entry.payload.base64 = normalizeBase64(
        await fetchImageAsDataUrl(absoluteUrl(baseUrl, thumbnailUrl)),
      );
    } catch (_error) {
      // Keep generated SVG fallback if the live cover is unavailable.
    }
  }
}

function existingItemKey(item) {
  const parsed = parseManagedAnnotation(item?.annotation || "");
  return String(parsed.bilive_source_task_id || parsed.source_rel_path || "").trim();
}

function hasThumbnailMode(item) {
  const parsed = parseManagedAnnotation(item?.annotation || "");
  return Boolean(parsed.thumbnail_mode);
}

function needsUpdate(item, payload) {
  const expectedTags = mergeManagedTags(item.tags || [], payload.tags);
  const expectedFolders = payload.folders || [];
  return (
    String(item.name || "") !== payload.name
    || String(item.url || "") !== payload.url
    || String(item.annotation || "") !== payload.annotation
    || tagsChanged(item.tags || [], expectedTags)
    || foldersChanged(item.folders || [], expectedFolders)
  );
}

function needsThumbnailRecreate(item, payload) {
  if (!payload.thumbnailUrl) {
    return false;
  }
  const current = parseManagedAnnotation(item.annotation || "");
  const expected = parseManagedAnnotation(payload.annotation || "");
  return (
    current.thumbnail_url !== expected.thumbnail_url
    || current.thumbnail_mode !== expected.thumbnail_mode
  );
}

function tagsChanged(current, next) {
  return normalizeTags(current).join("\n") !== normalizeTags(next).join("\n");
}

function normalizeTags(tags) {
  return [...new Set((tags || []).map((tag) => String(tag).trim()).filter(Boolean))].sort();
}

function foldersChanged(current, next) {
  return normalizeFolderIds(current).join("\n") !== normalizeFolderIds(next).join("\n");
}

function normalizeFolderIds(folders) {
  return [...new Set((folders || []).map((folder) => String(folder).trim()).filter(Boolean))].sort();
}

function findFolder(folders, name, parentId) {
  const normalizedParent = String(parentId || "");
  return (folders || []).find((folder) => (
    folder.name === name && String(folder.parent || "") === normalizedParent
  ));
}

function mergeManagedTags(currentTags, managedTags) {
  const next = [...managedTags];
  for (const tag of currentTags || []) {
    const value = String(tag).trim();
    if (!value || isManagedTag(value) || next.includes(value)) continue;
    next.push(value);
  }
  return next;
}

function isManagedTag(tag) {
  return (
    MANAGED_TAGS.includes(tag)
    || tag.startsWith("UP:")
    || tag.startsWith("日期:")
    || tag.startsWith("状态:")
    || tag.startsWith("待审核:")
  );
}

function bookmarkName(recording) {
  const date = String(recording.recorded_at || "").slice(0, 10) || "unknown";
  const roomName = String(recording.room_name || recording.room_id || "unknown");
  return `${date} ${roomName} 原始录播`;
}

function absoluteUrl(baseUrl, path) {
  return new URL(String(path || "/tasks"), normalizedBaseUrl(baseUrl)).toString();
}

function normalizedBaseUrl(baseUrl) {
  const value = String(baseUrl || "http://127.0.0.1:2234").trim();
  return value.endsWith("/") ? value : `${value}/`;
}

function thumbnailBase64(recording) {
  const title = escapeXml(String(recording.room_name || recording.room_id || "bilive"));
  const date = escapeXml(String(recording.recorded_at || "").slice(0, 10));
  const status = escapeXml(String(recording.status || "unknown"));
  const review = Number(recording.review_count || 0) > 0 ? "review" : "clear";
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360" viewBox="0 0 640 360">
  <rect width="640" height="360" fill="#111827"/>
  <rect x="32" y="32" width="576" height="296" rx="24" fill="#1f2937"/>
  <text x="64" y="128" fill="#f9fafb" font-family="Arial, sans-serif" font-size="44" font-weight="700">${title}</text>
  <text x="64" y="190" fill="#cbd5e1" font-family="Arial, sans-serif" font-size="30">${date}</text>
  <text x="64" y="252" fill="#93c5fd" font-family="Arial, sans-serif" font-size="28">status: ${status} / ${review}</text>
</svg>`;
  return toBase64Utf8(svg);
}

function normalizeBase64(value) {
  const text = String(value || "");
  const marker = ";base64,";
  const markerIndex = text.indexOf(marker);
  if (text.startsWith("data:") && markerIndex >= 0) {
    return text.slice(markerIndex + marker.length);
  }
  return text;
}

function toBase64Utf8(value) {
  if (typeof Buffer !== "undefined") {
    return Buffer.from(value, "utf8").toString("base64");
  }
  const bytes = new TextEncoder().encode(value);
  let binary = "";
  for (const byte of bytes) {
    binary += String.fromCharCode(byte);
  }
  return btoa(binary);
}

function escapeXml(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}
