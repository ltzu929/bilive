# Bilive Dashboard 设计

## Context

当前 `localhost:2233` 页面来自 `blrec` 安装包中的打包 Web UI，不在本仓库源码内。项目以后不再同步上游 fork，因此前端应成为本仓库的一等模块，而不是 patch `venv/site-packages/blrec`。

## Decision

保留 `blrec` 作为录制引擎，但不再使用它的前端作为主入口。

```text
bilive dashboard: http://localhost:2233
blrec engine:     http://127.0.0.1:2234
```

`record.sh` 负责启动两个服务：

1. `blrec` 后台服务，监听 `127.0.0.1:2234`，继续使用 `RECORD_KEY`。
2. bilive dashboard 后端，监听 `0.0.0.0:2233`，代理必要的 blrec API 并提供切片 API。

浏览器只访问 bilive dashboard。`RECORD_KEY` 不进入浏览器，由 dashboard 后端代理 `/api/blrec/*` 时注入。

## First Version Scope

第一版聚焦切片工作台，不完整复刻 blrec 的所有任务管理能力。

切片页能力：

- 扫描 `Videos/<room_id>/` 下候选切片。
- 播放候选切片。
- 展示文件大小、时长、来源录播、`density_core`、`context_window`、弹幕数。
- 标记 `keep`、`drop`、`review`。
- 填写人工原因。
- 保存手动精切范围 `manual_range`。
- 写入 `<slice_stem>_feedback.json`。

安全边界：

- 默认不跑 Whisper。
- 默认不进上传队列。
- 默认不删源录播。
- 文件访问限制在仓库 `Videos/` 内。
- 删除动作第一版只允许删除生成切片及 sidecar，不删除源录播。

## Data Model

人工反馈 sidecar：

```json
{
  "slice_path": "Videos/8792912/3100s_8792912_20260506-18-56-51.mp4",
  "source_recording": "Videos/8792912/8792912_20260506-18-56-51.mp4",
  "room_id": "8792912",
  "decision": "review",
  "quality_reason": "确实有值得精切的片段",
  "manual_range": {"start": 0.0, "end": 130.0, "relative_to": "slice"},
  "density_core": {"start": 3130.0, "end": 3190.0, "relative_to": "source"},
  "context_window": {"start": 3100.0, "end": 3230.0, "relative_to": "source"}
}
```

旧 sidecar 可能缺少 `density_core` 或 `context_window`，页面必须降级显示。

## Backend

新增 `src/dashboard/` FastAPI 后端：

- `GET /api/rooms`
- `GET /api/recordings?room_id=...`
- `GET /api/slices?room_id=...`
- `PATCH /api/slices/{slice_id}/feedback`
- `GET /api/media/{media_id}`
- `GET /api/blrec/tasks`

第一版不实现自动上传和后台切片 job；页面先管理已经生成的候选切片。

## Frontend

新增 `frontend/` 静态页面。第一版不需要 Node 构建链，FastAPI 直接服务 `frontend/index.html`、`frontend/app.js` 和 `frontend/styles.css`。后续如果切片时间轴和任务页复杂度上升，再迁移到 Vite/Vue。

主布局：

- 左侧导航：任务、录播、切片、上传、设置。
- 顶部工具栏：房间筛选、状态筛选、刷新。
- 切片工作台：左侧候选切片列表，中间视频预览，右侧元数据和人工反馈表单。

## Testing

- Python 后端用 pytest 覆盖文件扫描、安全路径限制、反馈 JSON 读写。
- 前端第一版无构建步骤，用 `npm run dashboard:build` 作为静态前端占位检查。
- 启动脚本用 shell 静态检查和手动端口 smoke check 验证。

## Self Review

- Placeholder scan: 无 TBD/TODO。
- Consistency: 端口、API、数据模型和安全边界一致。
- Scope: 第一版只做切片工作台，不做完整 blrec UI 复刻。
- Ambiguity: 删除、上传、Whisper 都明确为默认关闭或第一版不实现。
