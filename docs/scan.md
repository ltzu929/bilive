# 切片管线

当前唯一生产管线是 dashboard 提交 `.pending`，PC worker 一次性处理后退出。全目录轮询入口已经删除。

## 当前完整流程

```text
Pi blrec
  -> 录制 mp4/xml/jsonl/flv 到 /mnt/win/bilive/Videos/<room_id>/

Dashboard /tasks
  -> POST /api/slice/start
  -> src.dashboard.slice_control 扫描整场 mp4+xml
  -> 写 <recording>.mp4.pending

Windows worker trigger
  -> 推荐：Pi dashboard 通过 SSH 触发 Windows Scheduled Task:
     schtasks /Run /TN BiliveSliceOnce
  -> 兼容：浏览器调用 http://127.0.0.1:2235/api/worker/run-once
  -> Windows 执行:
     python -m src.server.watcher --once --videos-dir .\Videos

src.server.watcher
  -> 读取 pending 标记中的 video_rel_path
  -> 调用 slice_only(video_path, **slice_options)
  -> 根据 slice_only 结构化结果判断 done / skipped / failed
  -> 成功后写 .mp4.done 和 .mp4.task.json（含切片数/输出路径），删除 .pending
  -> 失败后写 .mp4.task.json(status=failed)，删除 .pending，等待人工重排
  -> 进程退出

slice_only()
  1. 检查 mp4+xml、文件大小和录制状态
  2. 解析弹幕并做 burst 检测
  3. ffmpeg 生成候选切片，默认 top_n=3
  4. 对每个候选提取音频
  5. faster-whisper 转录；必须有非空文本和有效 transcript_segments
  6. 把转录和候选时间窗弹幕一起交给 LLM
  7. LLM 明确 drop：删除候选；LLM/ASR 失败：保留候选人工复核
  8. LLM 明确 keep 后，根据真实时间戳生成 *_asr.srt 并烧录字幕
  9. 保存 *_analysis.json / *_edit.json，写上传元数据
 10. SQLite 入队成功后才标记为可自动上传
 11. 字幕、元数据或队列失败：删除上传 sidecar，保留候选人工复核
 12. 默认保留源 mp4/xml，除非 BILIVE_DELETE_SOURCE_AFTER_SLICE=1
```

## 关键代码

| 步骤 | 文件 | 函数 |
|------|------|------|
| 任务清单 | `src/dashboard/task_state.py` | `build_task_inventory()` |
| 页面提交切片 | `src/dashboard/slice_control.py` | `start_slice_scan()` |
| Pi 触发 Windows 任务 | `src/dashboard/remote_worker.py` | `trigger_remote_worker()` |
| 恢复操作 | `src/dashboard/task_state.py` | `requeue_task()` / `cancel_pending_task()` / `mark_done_task()` |
| worker API | `src/server/worker_api.py` | `POST /api/worker/run-once`, `GET /api/worker/status` |
| 启动一次性 worker | `src/server/worker_control.py` | `start_worker_once()`, `worker_status()` |
| pending 处理 | `src/server/watcher.py` | `process_pending_videos()` |
| 任务历史 | `src/burn/task_history.py` | `write_task_history()`, `read_task_history()` |
| 切片主流程 | `src/burn/slice_only.py` | `slice_only()` |
| 进度/诊断 | `src/burn/slice_progress.py` | `update_progress()` |
| 弹幕突增检测 | `src/autoslice/burst_detector.py` | `detect_bursts()` |
| ASR 转录 | `src/autoslice/mllm_sdk/audio_analyzer.py` | `analyze_audio()` |
| 候选证据聚合 | `src/autoslice/candidate_analyzer.py` | `analyze_candidate()` |
| 字幕烧录 | `src/burn/subtitle_burn.py` | `burn_subtitles_from_analysis()` |
| LLM 判断 | `src/autoslice/mllm_sdk/judge.py` | `judge_and_title()` |
| 上传队列 | `src/db/conn.py` | SQLite `upload_queue` 表 |

## 进度和诊断

自动切片会写 `logs/runtime/slice-progress.json`。Dashboard 读取：

- `GET /api/slice-progress`：顶部进度条。
- `GET /api/slice-diagnostics`：诊断面板。

诊断面板关注输入文件、弹幕 burst、切片结果、ASR/字幕、上传队列等关键状态，不等同于完整日志。

## pending / done / task.json 语义

- `.mp4.pending`：等待 PC worker 处理（JSON 格式，含 `video_rel_path`、`room_id`、`action`）。
- `.mp4.done`：该源录播已经由 pending worker 成功处理。
- `.mp4.task.json`：处理结果历史（含状态、时间、切片数或错误信息），worker 自动写入。
- 没有 `.pending` 和 `.done` 的整场 `mp4+xml`：页面启动切片时会重新加入队列。
- 失败任务不会无限自动重试；worker 会移除 `.pending` 并在任务清单显示 `failed`，需要从页面点“排队/重跑”或调用 `requeue`。
- 房间下拉的显示名来自本地录播 `jsonl` 的粉丝牌锚点信息；找不到 UP 名时回退房间号。

调试时如果要重跑某个源录播，可以手动移走对应 `.done`，再从页面重新提交。不要删除源 `.mp4/.xml`，当前默认会保留它们。

## Pi 触发 Windows 计划任务

推荐方案是让 Pi 只做编排，Windows 仍执行切片。Windows 先注册一个手动计划任务：

```powershell
cd D:\alldata\pi\bilive
.\install_windows_slice_task.ps1
```

这个任务运行 `run_slice_once.ps1`，脚本会同步执行 `src.server.watcher --once`，写入
`logs/runtime/pc-worker-task-*.log`，切完后退出。脚本包含 `slice-once.lock` 防重入；如果上一次
worker 仍在跑，再触发会直接退出。

Pi dashboard 读取 `bilive-server.toml` 的配置：

```toml
[dashboard.remote_worker]
enabled = true
command = ["ssh", "win", "schtasks", "/Run", "/TN", "BiliveSliceOnce"]
timeout = 10
```

`win` 是 Pi 上 SSH config 里的 Windows 主机别名。配置打开后，点击“启动切片”会先写
`.mp4.pending`，再从 Pi 后端触发该计划任务。若配置未打开，前端仍会回退到旧的
`127.0.0.1:2235` PC worker API 流程。

## 任务状态和恢复 API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/tasks` | GET | 列出所有源录播的状态，支持 `?room_id=` 过滤 |
| `/api/tasks/{task_id}/requeue` | POST | 移除 `.done`，写入新的 `.pending`，重新排队 |
| `/api/tasks/{task_id}/cancel-pending` | POST | 仅移除 `.pending`，保留源文件和 `.xml` |
| `/api/tasks/{task_id}/mark-done` | POST | 写入 `.done` 标记（手动跳过，不执行切片） |

### 任务状态

- `recording`：仍在录制中（待实现检测）
- `ready`：源 `.mp4` + `.xml` 就绪，尚未排队
- `pending`：已写入 `.mp4.pending`，等待 worker
- `running`：worker 正在处理（保留状态，当前主要由 worker 徽章体现）
- `done`：`.mp4.done` 存在，已处理
- `failed`：处理失败，`.task.json` 记录错误信息
- `skipped`：缺少 `.xml` 或文件过小
- `stale`：排队或运行状态超时（保留状态）

### Worker 状态

`GET /api/worker/status` (端口 `2235`) 返回扩展信息，dashboard 首页工具栏实时显示徽章。

## 自动投稿门禁

候选只有同时满足以下条件才会写入上传队列：

1. ASR 返回非空转录。
2. ASR 返回至少一个有效段级时间戳。
3. LLM 返回可解析的明确 `keep` 和非空标题。
4. 字幕成功烧录到候选视频。
5. 上传元数据成功写入。
6. SQLite 队列插入成功，或已存在于可恢复的上传状态中。

`manual_keep` 是 dashboard 中唯一允许人工覆盖自动判断的状态。自动流程不会用默认标题、启发式分数或异常兜底绕过上述门禁。

## 常见排查

| 现象 | 优先看 |
|------|------|
| 页面启动后只有 pending | `start_pc_worker_api.ps1` 是否运行，`pc-worker-*.log` |
| 生成 0 个切片 | 诊断面板 burst 阈值、弹幕数、`burst_ratio` |
| 字幕没有烧录 | ASR 是否返回 `transcript_segments`，是否有 `*_asr.srt` |
| ASR 下载失败 | HuggingFace/代理、模型缓存、`HF_TOKEN` |
| CUDA ASR 失败 | 是否缺 `cublas64_12.dll` |
| 候选停在人工复核 | 检查 ASR、LLM、字幕、元数据和队列错误；这些失败不会自动上传 |

## 已知问题

见 [`known-issues.md`](known-issues.md)。
