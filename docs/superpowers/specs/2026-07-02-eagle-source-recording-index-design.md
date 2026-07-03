# Eagle 原始录播轻量索引设计

## 目标

让 Eagle 成为 bilive 当前原始录播的轻量素材镜像。Eagle 里每场原始录播是一张封面卡或书签卡，便于按 UP、日期、状态和待审核情况检索；原始视频仍留在 `Videos/`，不复制进 Eagle。

## 范围

- 首期只同步原始录播，不同步切片结果。
- 同步方式为 Eagle 插件里的手动按钮，不做后台定时同步。
- Eagle 条目使用封面图或 bookmark thumbnail 表示录播档案，不导入 `.mp4` 或 `.flv` 原视频。
- 同步模型为增量镜像：新增当前录播、更新仍存在录播、删除 bilive 当前清单里已经不存在的旧 Eagle 卡片。
- 删除只移动本插件管理的 Eagle 条目到废纸篓，不删除 bilive 原始视频或任何手工导入素材。

## 用户工作流

1. 用户打开 Eagle 插件面板。
2. 点击“同步 bilive 原始录播”。
3. 插件请求 bilive 的 Eagle 专用只读索引接口。
4. 插件查找 Eagle 中已有的 `bilive`、`原始录播` 条目。
5. 插件按 `source_task_id` 增量新增、更新或移入废纸篓。
6. 插件显示本次新增、更新、删除和失败数量。

## bilive API

新增只读接口：

```text
GET /api/eagle/source-recordings
```

接口返回当前仍存在的原始录播列表。每项至少包含：

```json
{
  "source_task_id": "stable-task-id",
  "source_rel_path": "22384516/22384516_20260602-12-56-49.mp4",
  "source_name": "22384516_20260602-12-56-49.mp4",
  "room_id": "22384516",
  "room_name": "主播名或房间号",
  "recorded_at": "2026-06-02 12:56:49",
  "source_size_mb": 1234.5,
  "status": "done",
  "segment_count": 2,
  "review_count": 1,
  "keep_count": 1,
  "thumbnail_url": "/api/preview/<media-id>",
  "workspace_url": "/tasks?source_task_id=stable-task-id"
}
```

`source_task_id` 是主去重键；若旧数据缺失该字段，插件可回退到 `source_rel_path`。

## Eagle 条目

首期优先使用 Eagle bookmark 条目，URL 指向 bilive 工作台，缩略图来自 bilive 返回的封面或默认图。

标签：

```text
bilive
原始录播
UP:<房间名或主播名>
日期:YYYY-MM-DD
状态:<ready|pending|processing|done|failed>
待审核:<有|无>
```

备注采用稳定的机器可读文本：

```text
bilive_source_task_id: ...
source_rel_path: ...
room_id: ...
room_name: ...
recorded_at: ...
source_size_mb: ...
status: ...
segment_count: ...
review_count: ...
keep_count: ...
```

## 删除语义

用户切完片后可能删除原始录播文件。下一次手动同步时，如果某个 Eagle 原始录播卡片不再出现在 bilive 当前清单中，插件将该卡片移入 Eagle 废纸篓。它不会保留历史档案，也不会删除任何本地视频文件。

## 失败处理

- bilive 不可访问：停止同步，不修改 Eagle 条目。
- 单个封面不可用：仍创建或更新卡片，使用默认缩略图或无缩略图，并在结果中提示。
- 删除旧卡失败：继续处理其他条目，并在结果里汇总失败。
- 同步中途失败：已完成的改动保留；下一次同步会根据当前 bilive 清单继续修正。

## 验收标准

- API 返回当前存在的原始录播，不包含已删除文件。
- API 字段稳定，包含 Eagle 去重、标签、备注和工作台跳转所需信息。
- Eagle 同步逻辑重复执行不会创建重复卡片。
- bilive 当前清单里缺失的旧 Eagle 条目会被移入废纸篓。
- 不改变现有录制、切片、审核、上传流程。
