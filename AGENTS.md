# bilive - B站录播、切片、上传

> 当前架构：Pi 只录制，PC/Windows 做切片、ASR、字幕烧录、标题分析和上传。不要把旧的全目录 `scan_slice` 轮询当作推荐入口。

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
  src.server.watcher --once 处理 pending 后退出
  faster-whisper ASR -> SRT -> 字幕烧录
  SQLite 上传队列 -> src.upload.upload
```

## 关键入口

| 入口 | 当前用途 |
|------|------|
| `settings.toml` | Pi 端 `blrec` 本地配置，包含录制房间和 cookie，不应提交 |
| `bilive-server.toml` | PC 端切片/ASR/LLM/上传配置 |
| `frontend/` | `/tasks` 切片页面，写 pending 并触发 PC worker |
| `src/dashboard/app.py` | dashboard API，包括切片进度和诊断面板 |
| `src/dashboard/slice_control.py` | 扫描可处理录播，写 `.mp4.pending` 标记 |
| `src/server/worker_api.py` | 本机 worker API，默认 `127.0.0.1:2235` |
| `src/server/watcher.py` | 一次性处理 `.mp4.pending`，成功后写 `.mp4.done` |
| `src/burn/slice_only.py` | 单个录播的切片主流程 |
| `src/burn/subtitle_burn.py` | 使用真实 ASR 时间戳生成 SRT 并烧录字幕 |
| `src/autoslice/mllm_sdk/audio_analyzer.py` | ASR 引擎分发，当前主路径是 `faster-whisper` |
| `src/upload/upload.py` | 上传队列消费者 |
| `start_pc_worker_api.ps1` | 推荐启动本机 worker API |
| `start_pipeline.ps1` | PC helper 启动器；默认不跑旧 `scan_slice`，`-RunLegacyScanSlice` 才启用兼容扫描 |
| `run_slice.ps1` / `slice.sh` | 手动处理 pending 队列一次 |

## 推荐操作

### Pi 端录制服务

```bash
ssh pi
sudo systemctl status bilive
sudo systemctl restart bilive
```

`bilive.service` 当前只负责 `blrec`，端口是 `2233`。它不负责切片、ASR 或上传。

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

不要用 `python -m src.burn.scan_slice` 做日常切片。它是旧的全目录扫描入口，会扫描整个 `Videos/`，容易重复处理旧录播和已生成切片。

### 上传

上传由 `src.upload.upload` 消费 SQLite 队列。需要上传时单独启动上传进程，避免调试切片时误传。

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

## 日志排查

常看这些文件：

```text
logs/runtime/dashboard-*.log          # dashboard 请求
logs/runtime/pc-worker-*.log          # 页面触发的一次性 worker
logs/runtime/slice-*.err              # 旧 scan_slice 脚本日志
logs/runtime/slice-progress.json      # 切片进度/诊断面板数据
logs/runtime/upload-*.log             # 上传队列消费者
```

判断问题时先看：

1. 是否有 `.mp4.pending` 或 `.mp4.done`。
2. `pc-worker-*.log` 是否启动并处理到目标文件。
3. `slice-progress.json` 当前 `status/phase/source_name`。
4. ASR 是否报 HuggingFace 下载失败或 CUDA cuBLAS 缺失。
5. LLM judge 是否返回 502。LLM 失败不应阻止切片，但标题会降级。

## 当前状态

| 组件 | 状态 |
|------|------|
| Pi blrec 录制 | 正常，systemd 运行在 `2233` |
| Dashboard 切片页 | 可用，展示进度和诊断面板 |
| PC worker API | 手动启动 `start_pc_worker_api.ps1`，监听 `127.0.0.1:2235` |
| ASR | `faster-whisper` `large-v3` CPU `int8` |
| 字幕烧录 | 使用真实 ASR 时间戳生成 `_asr.srt` 并烧录 |
| 源文件清理 | 默认保留源录播 |
| LLM judge | 本地 LM Studio/API 不稳定时可能 502，按降级标题继续 |

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
