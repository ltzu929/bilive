# 切片管线

当前推荐管线是 dashboard 提交 `.pending`，PC worker 一次性处理后退出。旧的 `scan_slice.py` 全目录轮询仍保留作兼容入口，但不再作为日常切片主路径。

## 当前完整流程

```text
Pi blrec
  -> 录制 mp4/xml/jsonl/flv 到 /mnt/win/bilive/Videos/<room_id>/

Dashboard /tasks
  -> POST /api/slice/start
  -> src.dashboard.slice_control 扫描整场 mp4+xml
  -> 写 <recording>.mp4.pending

Windows PC worker API
  -> http://127.0.0.1:2235/api/worker/run-once
  -> src.server.worker_control 启动:
     python -m src.server.watcher --once --videos-dir .\Videos

src.server.watcher
  -> 读取 pending 标记中的 video_rel_path
  -> 调用 slice_only(video_path)
  -> 成功后写 .mp4.done，删除 .pending
  -> 进程退出

slice_only()
  1. 检查 mp4+xml、文件大小和录制状态
  2. 解析弹幕并做 burst 检测
  3. ffmpeg 生成候选切片，默认 top_n=3
  4. 对每个切片提取音频
  5. faster-whisper 转录，保留真实 transcript_segments
  6. LLM judge/标题分析，失败时降级继续
  7. 根据真实 ASR 时间戳生成 *_asr.srt 并烧录字幕
  8. 保存 *_analysis.json / *_edit.json
  9. 写入 SQLite 上传队列
 10. 默认保留源 mp4/xml，除非 BILIVE_DELETE_SOURCE_AFTER_SLICE=1
```

## 关键代码

| 步骤 | 文件 | 函数 |
|------|------|------|
| 页面提交切片 | `src/dashboard/slice_control.py` | `start_slice_scan()` |
| worker API | `src/server/worker_api.py` | `POST /api/worker/run-once` |
| 启动一次性 worker | `src/server/worker_control.py` | `start_worker_once()` |
| pending 处理 | `src/server/watcher.py` | `process_pending_videos()` |
| 切片主流程 | `src/burn/slice_only.py` | `slice_only()` |
| 进度/诊断 | `src/burn/slice_progress.py` | `update_progress()` |
| 弹幕突增检测 | `src/autoslice/burst_detector.py` | `detect_bursts()` |
| ASR 转录 | `src/autoslice/mllm_sdk/audio_analyzer.py` | `analyze_audio()` |
| 字幕烧录 | `src/burn/subtitle_burn.py` | `burn_subtitles_from_analysis()` |
| LLM 判断 | `src/autoslice/mllm_sdk/judge.py` | `judge_and_title()` |
| 上传队列 | `src/db/conn.py` | SQLite `upload_queue` 表 |

## 进度和诊断

自动切片会写 `logs/runtime/slice-progress.json`。Dashboard 读取：

- `GET /api/slice-progress`：顶部进度条。
- `GET /api/slice-diagnostics`：诊断面板。

诊断面板关注输入文件、弹幕 burst、切片结果、ASR/字幕、上传队列等关键状态，不等同于完整日志。

## pending / done 语义

- `.mp4.pending`：等待 PC worker 处理。
- `.mp4.done`：该源录播已经由 pending worker 成功处理。
- 没有 `.pending` 和 `.done` 的整场 `mp4+xml`：页面启动切片时会重新加入队列。

调试时如果要重跑某个源录播，可以手动移走对应 `.done`，再从页面重新提交。不要删除源 `.mp4/.xml`，当前默认会保留它们。

## 旧入口

`src.burn.scan_slice` 仍存在：

```powershell
python -m src.burn.scan_slice --once
```

它会扫描整个 `Videos/`，不是只处理 pending 队列。常驻模式还会每 120 秒重复扫描。当前只建议在兼容排查时临时使用，日常切片请走 `src.server.watcher --once`。

## 常见排查

| 现象 | 优先看 |
|------|------|
| 页面启动后只有 pending | `start_pc_worker_api.ps1` 是否运行，`pc-worker-*.log` |
| 切片扫到整个 Videos | 是否误用了 `src.burn.scan_slice` 或 `start_pipeline.ps1 -RunLegacyScanSlice` |
| 生成 0 个切片 | 诊断面板 burst 阈值、弹幕数、`burst_ratio` |
| 字幕没有烧录 | ASR 是否返回 `transcript_segments`，是否有 `*_asr.srt` |
| ASR 下载失败 | HuggingFace/代理、模型缓存、`HF_TOKEN` |
| CUDA ASR 失败 | 是否缺 `cublas64_12.dll` |
| 标题降级 | LM Studio/OpenAI-compatible 接口是否 502 |

## 已知问题

见 [`known-issues.md`](known-issues.md)。
