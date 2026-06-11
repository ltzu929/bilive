# bilive - B站录播、切片、上传

> 当前架构：Pi 只录制，PC/Windows 做切片、ASR、LLM 判断、字幕烧录和上传。生产切片只消费 dashboard 提交的 pending 队列。

## 当前架构

```text
Pi / Ubuntu / ARM
  blrec systemd 服务
  http://0.0.0.0:2233
  输出 mp4/xml/jsonl/flv 到 /mnt/win/bilive/Videos/
        |
        | CIFS / SMB 共享
        v
Windows / D:\alldata\pi\bilive
  dashboard /tasks 写 .mp4.pending
  worker_api 127.0.0.1:2235
  src.server.watcher --once 处理 pending 后退出；失败写 task history 并等待人工重排
  弹幕 burst -> 候选切片 -> faster-whisper ASR
  转录 + 窗口弹幕 -> LLM keep/drop
  keep -> SRT -> 字幕烧录 -> SQLite 队列
  任一证据/落库步骤失败 -> 人工复核，不上传
  worker_api 自动启动单实例 src.upload.upload
  SQLite 上传队列 -> UPOS 上传 -> Web add/v3 发布
  任务清单 GET /api/tasks（状态：ready/pending/done/failed）
  恢复操作 requeue / cancel-pending / mark-done
  .mp4.task.json 记录处理历史、错误、切片数和输出路径
```

## 关键入口

| 入口 | 当前用途 |
|------|------|
| `settings.toml` | Pi 端 `blrec` 本地配置，包含录制房间和 cookie，不应提交 |
| `bilive-server.toml` | PC 端切片/ASR/LLM/上传配置 |
| `frontend/` | `/tasks` 切片页面，含 worker 状态显示、任务清单和恢复操作 |
| `src/dashboard/app.py` | dashboard API，包括任务清单、切片进度、诊断面板和恢复操作 |
| `src/dashboard/file_store.py` | 切片/房间信息读取；房间下拉优先从本地 jsonl 粉丝牌锚点提取 UP 名 |
| `src/dashboard/task_state.py` | 任务状态模型：统一展示源录播状态（ready/pending/done/failed等） |
| `src/dashboard/slice_control.py` | 扫描可处理录播，写 `.mp4.pending` 标记 |
| `src/server/worker_api.py` | 本机 worker API，默认 `127.0.0.1:2235`，含切片和上传状态接口 |
| `src/server/worker_control.py` | worker 生命周期管理，状态含 `started_at`/`command`/`log_path` |
| `src/server/upload_control.py` | 自动上传消费者的单实例子进程管理 |
| `src/server/watcher.py` | 一次性处理 `.mp4.pending`；成功写 `.done` 和历史，失败写 `.task.json` 并移除 `.pending` |
| `src/burn/task_history.py` | 任务历史侧卡（`.mp4.task.json`），记录成功/失败和切片数 |
| `src/burn/slice_only.py` | 单个录播的切片主流程 |
| `src/autoslice/candidate_analyzer.py` | 严格候选分析：ASR 时间戳 + 窗口弹幕 + LLM 判断 |
| `src/burn/subtitle_burn.py` | 使用真实 ASR 时间戳生成 SRT 并烧录字幕 |
| `src/autoslice/mllm_sdk/audio_analyzer.py` | ASR 引擎分发，当前主路径是 `faster-whisper` |
| `src/upload/upload.py` | 上传队列消费者 |
| `start_pc_worker_api.ps1` | 推荐启动本机 worker API |
| `start_pipeline.ps1` | PC helper 启动器；启动 LM Studio、worker API 和自动上传消费者 |
| `run_slice.ps1` / `slice.sh` | 手动处理 pending 队列一次 |

## 推荐操作

### Pi 端录制服务

```bash
ssh pi
sudo systemctl status bilive
sudo systemctl restart bilive
```

`bilive.service` 当前只负责 `blrec`，端口是 `2233`。它不负责切片、ASR 或上传。

Windows SMB 每晚离线属于正常运行场景。Pi 本地
`bilive-smb-recover.timer` 每 15 秒运行一次 root oneshot：Windows 445
离线时等待，恢复上线后清除 `mnt-win.mount` 的失败状态、处理 stale CIFS
挂载并重启 `bilive.service`。不要只依赖 `x-systemd.automount`，也不要把
录像临时迁到 Pi SD 卡。

安装/更新 Pi 本地服务：

```bash
ssh pi
cd /mnt/win/bilive
sudo ./deploy/install-bilive-services.sh
```

### PC 端切片

```powershell
cd D:\alldata\pi\bilive
.\start_pc_worker_api.ps1
```

然后打开切片页面，点击“启动切片”。页面会：

1. 调用 `/api/slice/start`，给可处理的整场录播写 `.mp4.pending`。
2. 调用本机 `http://127.0.0.1:2235/api/worker/run-once`。
3. PC worker 启动 `src.server.watcher --once`，处理 pending 队列。
4. 每个录播处理完成后写 `.mp4.done`，worker 自己退出。

如果要手动跑一次 pending 队列：

```powershell
cd D:\alldata\pi\bilive
$env:PYTHONPATH = "$PWD;$PWD\src"
$env:BILIVE_CONFIG = "$PWD\bilive-server.toml"
$env:BILIVE_VIDEOS_DIR = "$PWD\Videos"
python -m src.server.watcher --once --videos-dir .\Videos
```

旧的全目录扫描入口已经删除。不要新增绕过 `.pending`、`.done` 和任务历史的目录轮询入口。

### 上传

`start_pc_worker_api.ps1` 默认自动启动单实例 `src.upload.upload`。LLM 判定保留的
切片入队后会自动上传并通过 Web `add/v3` 发布。发布失败会保留远端文件名，
后续只重试发布，不重复上传视频字节。

调试切片而不上传时使用：

```powershell
.\start_pipeline.ps1 -NoUpload
```

状态接口：`GET http://127.0.0.1:2235/api/upload/status`。历史 `locked=1/2`
队列行迁移为 `failed`，不会自动重传。

## 当前 ASR 配置

`bilive-server.toml` 的 `[slice.multi_modal]` 当前推荐：

```toml
whisper_engine = "faster-whisper"
whisper_model = "large-v3"
whisper_device = "cpu"
whisper_compute_type = "int8"
```

- 只使用 ASR 返回的真实 `transcript_segments` 时间戳烧录字幕。
- `Qwen3-ASR` 不再是当前默认，因为它没有真实词/段时间戳，字幕会变成长句。
- `large-v3-turbo` 首次下载可能受 HuggingFace/代理影响；本机已有缓存时优先用 `large-v3`。
- `whisper_device = "cuda"` 需要 CUDA 12 的 `cublas64_12.dll`。缺这个 DLL 时会报 `Library cublas64_12.dll is not found`。

## 文件保留

- 当前切片默认保留原始 `.mp4` 和 `.xml`，方便重跑。
- 只有显式设置 `BILIVE_DELETE_SOURCE_AFTER_SLICE=1` 时，才会在切片后删除源文件。
- `.mp4.pending` 表示等待 PC worker；`.mp4.done` 表示该源录播已处理过。
- `.mp4.task.json` 记录最近一次 worker 结果；失败任务会显示 `failed`，需要从页面或 API 重新排队。

## 日志排查

常看这些文件：

```text
logs/runtime/dashboard-*.log          # dashboard 请求
logs/runtime/pc-worker-*.log          # 页面触发的一次性 worker
logs/runtime/slice-progress.json      # 切片进度/诊断面板数据
logs/runtime/upload-process-*.log     # 自动上传消费者
logs/runtime/upload-status.json       # 上传状态、队列计数和最近 BVID
```

判断问题时先看：

1. 是否有 `.mp4.pending` 或 `.mp4.done`。
2. `pc-worker-*.log` 是否启动并处理到目标文件。
3. `slice-progress.json` 当前 `status/phase/source_name`。
4. ASR 是否报 HuggingFace 下载失败或 CUDA cuBLAS 缺失。
5. LLM judge 是否返回 502。LLM、ASR、字幕或队列失败时，候选应保留人工复核且不得自动上传。

## 当前状态

| 组件 | 状态 |
|------|------|
| Pi blrec 录制 | 正常，systemd 运行在 `2233` |
| Dashboard 切片页 | 可用，展示进度和诊断面板 |
| PC worker API | 手动启动 `start_pc_worker_api.ps1`，监听 `127.0.0.1:2235` |
| ASR | `faster-whisper` `large-v3` CPU `int8` |
| 字幕烧录 | 使用真实 ASR 时间戳生成 `_asr.srt` 并烧录 |
| 源文件清理 | 默认保留源录播 |
| LLM judge | 本地 LM Studio/API 不稳定时可能 502；候选转人工复核，不自动上传 |

## 详细文档

| 文档 | 内容 |
|------|------|
| `docs/scan.md` | 当前切片流程、pending worker、诊断状态 |
| `docs/project-health.md` | 项目体检、入口分级、清理建议 |
| `docs/asr-engines.md` | 当前 ASR 引擎选择和 CUDA 注意事项 |
| `docs/known-issues.md` | 已知问题和排查线索 |
| `docs/upload.md` | 上传流程、cookie 认证、发布问题 |
| `docs/plans/` | 历史设计记录，不一定代表当前运行方式 |
| `docs/specs/` | 历史规格和优化计划，不一定代表当前运行方式 |
