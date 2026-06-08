# 项目体检

更新时间：2026-06-08

这份文档记录当前仓库的可用入口、历史包袱和后续清理建议。它不是设计稿，而是按当前实际运行状态整理出来的维护索引。

## 当前主线

| 层 | 主路径 | 说明 |
|----|--------|------|
| Pi 录制 | `bilive.service` -> `blrec` | 只负责录制，端口 `2233`，输出到 `/mnt/win/bilive/Videos/` |
| Dashboard | `src/dashboard/app.py` + `frontend/` | `/tasks` 页面提交切片任务、展示任务清单、诊断和恢复操作 |
| 房间筛选 | `src/dashboard/file_store.py` + `GET /api/rooms` | 下拉选项优先显示本地 jsonl 中解析出的 UP 名，房间号作为回退 |
| 任务清单 | `src/dashboard/task_state.py` | `GET /api/tasks` 统一展示所有源录播状态（ready/pending/done/failed等） |
| 恢复操作 | API `/api/tasks/{id}/requeue|cancel-pending|mark-done` | 重跑、取消排队、手动标记已处理 |
| PC worker API | `start_pc_worker_api.ps1` -> `src.server.worker_api` | 浏览器本机调用 `127.0.0.1:2235`，管理切片 worker 和上传消费者 |
| 切片执行 | `src.server.watcher --once` -> `src.burn.slice_only` | 只处理 `.mp4.pending`，成功后写 `.mp4.done` + `.mp4.task.json` |
| 任务历史 | `src/burn/task_history.py` | 每次处理后写 `.mp4.task.json` 保存结果（成功/失败、切片数、错误） |
| ASR/字幕 | `src/autoslice/mllm_sdk/audio_analyzer.py` + `src/burn/subtitle_burn.py` | `faster-whisper large-v3 cpu int8`，只用真实时间戳烧录 |
| 上传 | `src.server.upload_control` -> `src.upload.upload` | worker API 自动启动单实例消费者，UPOS 与 Web 发布可恢复 |

## 根目录入口分级

### 日常入口

| 文件 | 状态 |
|------|------|
| `start_pc_worker_api.ps1` | 推荐。启动本机 worker API、自动上传消费者，并按页面请求运行 one-shot 切片 worker |
| `run_slice.ps1` | 手动处理 pending 队列一次 |
| `slice.sh` | Pi/Linux 手动处理 pending 队列一次 |
| `start_pipeline.ps1` | PC helper 启动器。默认启动 LM Studio、worker API、上传消费者；默认不跑旧 `scan_slice` |
| `server.sh` | Pi/Linux helper 启动器。默认不跑旧 `scan_slice` |
| `sync_cookie.py` | 同步 bilitool cookie 格式 |

### 兼容/历史入口

| 文件 | 问题 |
|------|------|
| `src.burn.scan_slice` | 全目录扫描器，不看 pending 队列。仅兼容排查时用 `--once` |
| `start_pipeline.ps1 -RunLegacyScanSlice` | 显式兼容旧全目录扫描一次 |
| `run_upload.ps1` / `upload.sh` | 手动上传消费者；进程锁阻止与自动消费者重复运行 |
| `_slice_daemon.bat` / `_test_slice.bat` | 已改成 pending one-shot，保留给旧快捷方式 |
| `_upload_daemon.bat` / `_test_upload.bat` | 旧上传快捷方式 |
| `agent.sh` | Pi 端 scanner 方案遗留，当前页面提交 pending 更清晰 |
| `record.sh` / `record-pi.sh` | 本地/手动录制入口；当前生产录制由 Pi systemd 管 |

## 目录分级

| 目录 | 归类 | 说明 |
|------|------|------|
| `src/dashboard/` | 活跃 | dashboard API 和切片页面数据 |
| `src/server/` | 活跃 | worker API、pending watcher |
| `src/burn/` | 活跃/混合 | `slice_only.py` 活跃；`scan.py/render_*` 是上游整场渲染遗留 |
| `src/autoslice/` | 活跃/混合 | burst、ASR、标题分析活跃；多云厂商 SDK 多数是上游遗留 |
| `src/upload/` | 活跃 | 上传队列和 bilitool 封装 |
| `frontend/` | 活跃 | 无构建静态 dashboard |
| `docs/` | 混合 | 顶层文档是当前说明；`docs/plans`、`docs/specs`、`docs/superpowers` 是历史设计记录 |
| `src/subtitle/whisper/` | 债务 | vendored Whisper 源码和资产，体积大，和当前 faster-whisper 主路径重叠 |
| `src/danmaku/DanmakuConvert` | submodule | 弹幕转换依赖 |
| `src/autoslice/auto_slice_video` | submodule | 旧切片依赖 |
| `src/upload/bilitool` | submodule | 仅提供 UPOS 上传依赖；Web 发布封装在主仓库 |

## 发现的问题

1. `cookie.json` 仍被 Git 跟踪，同时属于敏感/本机状态文件。`.gitignore` 已补上 `cookie.json`，但已跟踪文件需要后续用 `git rm --cached cookie.json` 从索引移除。
2. `.worktrees/slice-edit-instructions` 里有旧 worktree 副本和大文件，占空间但已被 ignore。需要确认不再用后再清理。
3. `src/subtitle/whisper/` vendored 了完整 Whisper 实现和 tokenizer 资产；当前主路径是 `faster-whisper`，这里应作为后续瘦身候选。
4. 根目录脚本太多，历史入口和当前入口混在一起。已先把危险的旧全目录扫描从默认脚本里拿掉，后续可继续归档旧脚本。
5. `docs/plans`、`docs/specs`、`docs/superpowers` 记录了很多历史方案，不应被当成当前运行说明。当前说明以 `AGENTS.md`、`README.md`、`docs/scan.md` 为准。
6. `src/upload/bilitool` 是 submodule。不要把本 fork 的 Web 发布逻辑直接改进子模块；当前封装位于 `src/upload/bilibili_web.py`。

## 已做的低风险整理

- `start_pipeline.ps1` 默认不再启动旧 `scan_slice`，只在 `-RunLegacyScanSlice` 下兼容跑一次。
- worker API 默认自动启动上传消费者，`-NoUpload` 或 `BILIVE_AUTO_UPLOAD=0` 可禁用。
- 上传队列改为显式状态机，发布失败保留远端文件名，不重复发送视频字节。
- `run_slice.ps1`、`slice.sh`、`_slice_daemon.bat`、`_test_slice.bat` 改为处理 pending 队列一次。
- 前端无法连接 worker 时只提示 `start_pc_worker_api.ps1`，不再引导去跑旧全目录扫描。
- `.gitignore` 增加 `cookie.json`。
- 文档统一为 Pi 录制、PC 切片/ASR/上传的边界。
- 新增任务清单 API (`GET /api/tasks`) 和恢复操作 API (requeue/cancel-pending/mark-done)。
- Worker 状态查询扩展到返回 `started_at`、`command`、`log_path`；Dashboard 首页工具栏显示实时状态徽章。
- Worker 失败后不再自动重试，写入 `.task.json` 记录错误并删除 `.pending`。
- 新增任务历史侧卡（`.mp4.task.json`），记录处理成功/失败/跳过、切片数和输出路径。
- `slice_only()` 返回结构化结果，watcher 不再把内部失败误判为成功。

## 下一步建议

### 可以直接做

1. 新建 `scripts/legacy/`，把 `_*.bat`、`agent.sh`、上游旧启动脚本归档，并在 README 保留索引。
2. 给 `src/burn/scan.py`、`render_*`、多云 SDK 标注 legacy，减少误用。
3. 把 `docs/superpowers` 改名为 `docs/history/superpowers`，让当前文档更清爽。

### 需要确认后做

1. `git rm --cached cookie.json`，把真实 cookie 从版本索引里移走。
2. 清理 `.worktrees/slice-edit-instructions` 和 prunable worktree。
3. 移除或外置 `src/subtitle/whisper/` vendored 代码。
4. 移除旧 `scan_slice` 全目录扫描入口，完全改为 pending 队列。

## 判断准则

以后新增入口时按这个规则放置：

- 日常操作入口只保留在根目录或 README 的“日常入口”表中。
- 历史兼容脚本必须写明 legacy，不允许默认扫描整个 `Videos/`。
- 运行产物、cookie、配置、模型缓存不得进入 Git。
- 当前运行说明优先级：`AGENTS.md` > `README.md` > `docs/*.md` > 历史 plans/specs。
