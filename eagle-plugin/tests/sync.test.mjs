import assert from "node:assert/strict";
import test from "node:test";

import {
  annotationForRecording,
  applySyncPlan,
  bookmarkPayloadForRecording,
  ensureFolderHierarchy,
  folderNameForRecording,
  hydratePlanThumbnails,
  parseManagedAnnotation,
  planSync,
  recordingKey,
  tagsForRecording,
} from "../src/sync.js";

const recording = {
  source_task_id: "task-1",
  source_rel_path: "22384516/22384516_20260602-12-56-49.mp4",
  source_name: "22384516_20260602-12-56-49.mp4",
  room_id: "22384516",
  room_name: "22384516",
  recorded_at: "2026-06-02 12:56:49",
  source_size_mb: 1234.5,
  status: "done",
  segment_count: 3,
  review_count: 2,
  keep_count: 1,
  workspace_url: "/tasks?source_task_id=task-1",
};

test("recordingKey prefers source_task_id and falls back to source_rel_path", () => {
  assert.equal(recordingKey(recording), "task-1");
  assert.equal(
    recordingKey({ ...recording, source_task_id: "" }),
    "22384516/22384516_20260602-12-56-49.mp4",
  );
});

test("tagsForRecording creates stable searchable Eagle tags", () => {
  assert.deepEqual(tagsForRecording(recording), [
    "bilive",
    "原始录播",
    "UP:22384516",
    "日期:2026-06-02",
    "状态:done",
    "待审核:有",
  ]);
});

test("annotationForRecording is machine-readable and parseable", () => {
  const annotation = annotationForRecording(recording);

  assert.match(annotation, /bilive_source_task_id: task-1/);
  assert.match(annotation, /source_rel_path: 22384516\/22384516_20260602-12-56-49\.mp4/);
  assert.deepEqual(parseManagedAnnotation(annotation), {
    bilive_source_task_id: "task-1",
    source_rel_path: "22384516/22384516_20260602-12-56-49.mp4",
    room_id: "22384516",
    room_name: "22384516",
    recorded_at: "2026-06-02 12:56:49",
    source_size_mb: "1234.5",
    status: "done",
    segment_count: "3",
    review_count: "2",
    keep_count: "1",
  });
});

test("bookmarkPayloadForRecording builds Eagle bookmark fields", () => {
  const payload = bookmarkPayloadForRecording(recording, "http://127.0.0.1:2234");

  assert.equal(payload.name, "2026-06-02 22384516 原始录播");
  assert.equal(
    payload.url,
    "http://127.0.0.1:2234/tasks?source_task_id=task-1",
  );
  assert.deepEqual(payload.tags, tagsForRecording(recording));
  assert.equal(payload.annotation, annotationForRecording(recording));
  assert.doesNotMatch(payload.base64, /^data:/);
  assert.deepEqual(payload.folders, []);
});

test("bookmarkPayloadForRecording records thumbnail markers when a cover is available", () => {
  const payload = bookmarkPayloadForRecording(
    { ...recording, thumbnail_url: "https://i0.hdslb.com/bfs/live/cover.jpg" },
    "http://127.0.0.1:2234",
  );

  assert.equal(payload.thumbnailUrl, "https://i0.hdslb.com/bfs/live/cover.jpg");
  assert.match(payload.annotation, /thumbnail_url: https:\/\/i0\.hdslb\.com\/bfs\/live\/cover\.jpg/);
  assert.match(payload.annotation, /thumbnail_mode: bookmark-base64-v2/);
});

test("folderNameForRecording creates stable UP folder names", () => {
  assert.equal(folderNameForRecording(recording), "22384516");
  assert.equal(
    folderNameForRecording({ ...recording, room_name: "李豆沙_Channel" }),
    "李豆沙_Channel",
  );
  assert.equal(
    folderNameForRecording({ ...recording, room_name: "a/b:c*" }),
    "a_b_c_",
  );
});

test("planSync creates, updates, deletes missing recordings, and removes duplicates", () => {
  const existing = [
    {
      id: "kept",
      annotation: annotationForRecording({ ...recording, status: "ready" }),
      tags: ["bilive", "原始录播", "状态:ready"],
      url: "http://127.0.0.1:2234/tasks?source_task_id=task-1",
    },
    {
      id: "duplicate",
      annotation: annotationForRecording(recording),
      tags: ["bilive", "原始录播"],
      url: "http://127.0.0.1:2234/tasks?source_task_id=task-1",
    },
    {
      id: "stale",
      annotation: annotationForRecording({
        ...recording,
        source_task_id: "gone",
        source_rel_path: "22384516/gone.mp4",
      }),
      tags: ["bilive", "原始录播"],
      url: "http://127.0.0.1:2234/tasks?source_task_id=gone",
    },
  ];

  const plan = planSync(
    [
      recording,
      {
        ...recording,
        source_task_id: "task-2",
        source_rel_path: "22384516/22384516_20260603-12-56-49.mp4",
        source_name: "22384516_20260603-12-56-49.mp4",
        recorded_at: "2026-06-03 12:56:49",
      },
    ],
    existing,
    "http://127.0.0.1:2234",
  );

  assert.equal(plan.create.length, 1);
  assert.equal(plan.create[0].key, "task-2");
  assert.equal(plan.update.length, 1);
  assert.equal(plan.update[0].item.id, "kept");
  assert.equal(plan.update[0].payload.annotation, annotationForRecording(recording));
  assert.deepEqual(
    plan.trash.map((entry) => entry.item.id),
    ["duplicate", "stale"],
  );
});

test("ensureFolderHierarchy creates root and per-UP folders once", async () => {
  const calls = [];
  const folders = [];
  const folderApi = {
    getAll: async () => folders,
    create: async (options) => {
      const folder = { id: `folder-${folders.length + 1}`, name: options.name, parent: "" };
      folders.push(folder);
      calls.push(["create", options]);
      return folder;
    },
    createSubfolder: async (parentId, options) => {
      const folder = { id: `folder-${folders.length + 1}`, name: options.name, parent: parentId };
      folders.push(folder);
      calls.push(["createSubfolder", parentId, options]);
      return folder;
    },
  };

  const mapping = await ensureFolderHierarchy(folderApi, [
    recording,
    { ...recording, source_task_id: "task-2", room_name: "22384516" },
    { ...recording, source_task_id: "task-3", room_name: "呜米" },
  ]);

  assert.deepEqual(calls, [
    ["create", { name: "bilive 原始录播", description: "bilive current source recordings" }],
    ["createSubfolder", "folder-1", { name: "22384516", description: "bilive source recordings for 22384516" }],
    ["createSubfolder", "folder-1", { name: "呜米", description: "bilive source recordings for 呜米" }],
  ]);
  assert.deepEqual(Object.fromEntries(mapping), {
    "22384516": "folder-2",
    "呜米": "folder-3",
  });
});

test("planSync places created and updated bookmarks into UP folders", () => {
  const plan = planSync(
    [recording],
    [
      {
        id: "kept",
        annotation: annotationForRecording({ ...recording, status: "ready" }),
        tags: ["bilive", "原始录播", "状态:ready"],
        url: "http://127.0.0.1:2234/tasks?source_task_id=task-1",
      },
    ],
    "http://127.0.0.1:2234",
    new Map([["22384516", "folder-up"]]),
  );

  assert.deepEqual(plan.update[0].payload.folders, ["folder-up"]);
});

test("planSync updates existing bookmarks when only folder assignment changed", () => {
  const payload = bookmarkPayloadForRecording(recording, "http://127.0.0.1:2234");
  const plan = planSync(
    [recording],
    [
      {
        id: "kept",
        name: payload.name,
        url: payload.url,
        annotation: payload.annotation,
        tags: payload.tags,
        folders: [],
      },
    ],
    "http://127.0.0.1:2234",
    new Map([["22384516", "folder-up"]]),
  );

  assert.equal(plan.update.length, 1);
  assert.deepEqual(plan.update[0].payload.folders, ["folder-up"]);
});

test("planSync recreates old bookmarks that lack the thumbnail marker", () => {
  const recordingWithCover = {
    ...recording,
    thumbnail_url: "https://i0.hdslb.com/bfs/live/cover.jpg",
  };
  const payload = bookmarkPayloadForRecording(recordingWithCover, "http://127.0.0.1:2234");
  const plan = planSync(
    [recordingWithCover],
    [
      {
        id: "old-bookmark",
        name: payload.name,
        url: payload.url,
        annotation: annotationForRecording(recording),
        tags: payload.tags,
        folders: [],
      },
    ],
    "http://127.0.0.1:2234",
  );

  assert.equal(plan.create.length, 1);
  assert.equal(plan.create[0].key, "task-1");
  assert.equal(plan.trash.length, 1);
  assert.equal(plan.trash[0].item.id, "old-bookmark");
  assert.equal(plan.trash[0].requiresCreate, true);
  assert.equal(plan.update.length, 0);
});


test("hydratePlanThumbnails uses bilive thumbnail_url when available", async () => {
  const plan = planSync(
    [{ ...recording, thumbnail_url: "/api/live-cover/22384516.jpg" }],
    [],
    "http://127.0.0.1:2234",
  );

  await hydratePlanThumbnails(
    plan,
    "http://127.0.0.1:2234",
    async (url) => {
      assert.equal(url, "http://127.0.0.1:2234/api/live-cover/22384516.jpg");
      return "data:image/jpeg;base64,real-cover";
    },
  );

  assert.equal(plan.create[0].payload.base64, "real-cover");
});

test("planSync preserves manual Eagle tags while replacing managed tags", () => {
  const existing = [
    {
      id: "kept",
      annotation: annotationForRecording({ ...recording, status: "ready" }),
      tags: ["bilive", "原始录播", "状态:ready", "手动收藏"],
      url: "http://127.0.0.1:2234/tasks?source_task_id=task-1",
    },
  ];

  const plan = planSync([recording], existing, "http://127.0.0.1:2234");

  assert.equal(plan.update.length, 1);
  assert.deepEqual(plan.update[0].payload.tags, [
    "bilive",
    "原始录播",
    "UP:22384516",
    "日期:2026-06-02",
    "状态:done",
    "待审核:有",
    "手动收藏",
  ]);
});

test("applySyncPlan calls Eagle bookmark, save, and trash APIs", async () => {
  const calls = [];
  const updatedItem = {
    id: "existing",
    save: async function save() {
      calls.push(["save", this.name, this.url, this.tags, this.annotation]);
      return true;
    },
  };
  const trashedItem = {
    id: "stale",
    moveToTrash: async function moveToTrash() {
      calls.push(["trash", this.id]);
      return true;
    },
  };

  const plan = {
    create: [
      {
        key: "task-1",
        payload: bookmarkPayloadForRecording(recording, "http://127.0.0.1:2234"),
      },
    ],
    update: [
      {
        key: "task-2",
        item: updatedItem,
        payload: bookmarkPayloadForRecording(
          { ...recording, source_task_id: "task-2" },
          "http://127.0.0.1:2234",
        ),
      },
    ],
    trash: [{ key: "gone", item: trashedItem }],
  };

  const result = await applySyncPlan(
    {
      addBookmark: async (url, options) => {
        calls.push(["addBookmark", url, options]);
        return "new-item-id";
      },
    },
    plan,
  );

  assert.deepEqual(result, { created: 1, updated: 1, trashed: 1, failed: 0 });
  assert.equal(calls[0][0], "addBookmark");
  assert.equal(calls[0][1], "http://127.0.0.1:2234/tasks?source_task_id=task-1");
  assert.equal(calls[0][2].name, "2026-06-02 22384516 原始录播");
  assert.deepEqual(calls[0][2].tags, tagsForRecording(recording));
  assert.deepEqual(calls[0][2].folders, []);
  assert.equal(calls[1][0], "save");
  assert.equal(calls[2][0], "trash");
});

test("applySyncPlan keeps the old bookmark when replacement creation fails", async () => {
  const calls = [];
  const oldItem = {
    id: "old-bookmark",
    moveToTrash: async function moveToTrash() {
      calls.push(["trash", this.id]);
      return true;
    },
  };
  const plan = {
    create: [
      {
        key: "task-1",
        payload: bookmarkPayloadForRecording(
          { ...recording, thumbnail_url: "https://i0.hdslb.com/bfs/live/cover.jpg" },
          "http://127.0.0.1:2234",
        ),
      },
    ],
    update: [],
    trash: [{ key: "task-1", item: oldItem, requiresCreate: true }],
  };

  const result = await applySyncPlan(
    {
      addBookmark: async () => {
        throw new Error("create failed");
      },
    },
    plan,
  );

  assert.deepEqual(result, { created: 0, updated: 0, trashed: 0, failed: 1 });
  assert.deepEqual(calls, []);
});

test("planSync prefers the duplicate bookmark that carries the thumbnail marker", () => {
  // Simulates an orphaned recreate: addBookmark succeeded in Eagle but
  // rejected on the JS side, leaving a new (with marker) and an old (without
  // marker) bookmark for the same key. The next sync must keep the new one
  // and trash the stale one instead of nondeterministically keeping the old.
  const withMarker = {
    id: "new-bookmark",
    annotation: annotationForRecording({
      ...recording,
      thumbnail_url: "https://i0.hdslb.com/bfs/live/cover.jpg",
      thumbnail_mode: "bookmark-base64-v2",
    }),
    tags: ["bilive", "原始录播"],
    url: "http://127.0.0.1:2234/tasks?source_task_id=task-1",
  };
  const withoutMarker = {
    id: "old-bookmark",
    annotation: annotationForRecording(recording),
    tags: ["bilive", "原始录播"],
    url: "http://127.0.0.1:2234/tasks?source_task_id=task-1",
  };

  const planKeepingNewFirst = planSync([recording], [withMarker, withoutMarker], "http://127.0.0.1:2234");
  assert.deepEqual(
    planKeepingNewFirst.trash.map((entry) => entry.item.id),
    ["old-bookmark"],
  );

  const planKeepingNewSecond = planSync([recording], [withoutMarker, withMarker], "http://127.0.0.1:2334");
  assert.deepEqual(
    planKeepingNewSecond.trash.map((entry) => entry.item.id),
    ["old-bookmark"],
  );
});

