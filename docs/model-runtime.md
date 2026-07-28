# MiMo 模型运行时

## 目标

生产切片使用 `mimo-v2.5` 做候选视频全模态判断。弹幕密度仍是候选范围生成器；MiMo 在每个大范围候选中返回 0..N 个可独立投稿的连续聊天片段。

```text
弹幕密度 -> 候选范围 -> MiMo 全模态判断
  -> drop：删除候选
  -> keep：本地质量闸门 -> 去重 -> faster-whisper 字幕 -> 烧录 -> 上传队列
  -> 分数不足、重复或失败：保留人工复核
```

当前不使用 `mimo-v2.5-asr`，因为自动字幕烧录需要可靠段级时间戳。

## 配置

`bilive-server.toml`：

```toml
[slice.mimo]
model = "mimo-v2.5"
base_url = "https://api.xiaomimimo.com/v1"
fps = 1.0
media_resolution = "default"
timeout = 180
request_parallelism = 3
encode_parallelism = 1
max_base64_bytes = 48000000

[slice.quality]
min_quality_score = 0.80
min_completeness_score = 0.80
min_confidence = 0.80

[slice.multi_modal]
whisper_model = "large-v3"
whisper_device = "cpu"
whisper_compute_type = "int8"
whisper_batch_size = 8
whisper_cpu_threads = 8
whisper_vad_filter = true

[slice.analysis]
snap_trim_to_segments = true
snap_trim_tolerance = 3.0
trim_asr_padding_seconds = 6.0
```

旧 `slice.mimo.parallelism` 仍作为 `request_parallelism` 的兼容别名；新配置应使用含义明确的字段。

API Key 默认从项目本地 `.secrets/env` 读取，进程环境变量可覆盖：

```powershell
function Set-BiliveSecret {
    param([string]$Name, [string]$Value)
    New-Item -ItemType Directory -Force .\.secrets | Out-Null
    $path = ".\.secrets\env"
    $lines = if (Test-Path $path) { Get-Content $path } else { @() }
    $line = "$Name=$Value"
    $pattern = "^\s*$([regex]::Escape($Name))="
    if ($lines -match $pattern) {
        $lines = $lines | ForEach-Object { if ($_ -match $pattern) { $line } else { $_ } }
    } else {
        $lines += $line
    }
    Set-Content -Path $path -Value $lines -Encoding utf8
}
Set-BiliveSecret MIMO_API_KEY "<your-key>"
```

`.secrets/` 已被 git 忽略。不要把 API Key 写入 `bilive-server.toml`、日志、测试快照、提交信息或公开文档。

## 请求形态

`src/autoslice/mllm_sdk/mimo_video.py` 负责：

- 为候选生成临时 720p H.264/AAC 分析副本。
- 使用 Base64 `data:video/mp4;base64,...` 传入 MiMo。
- 编码后 Base64 字符串硬限制为 `48_000_000` 字节。
- 超限时降低码率重试一次；仍超限则 `judge_failed`。
- 请求设置 `fps=1.0`、`media_resolution=default`。本地分析副本编码和 MiMo HTTP 请求使用独立并发限制，避免把 CPU 转码误算成云端并发。
- 请求设置 `thinking.type=disabled`。
- 要求顶层 JSON 输出 `clips` 数组；每个元素包含 `decision`、`clip_type`、`topic_summary`、`why_viewer_would_watch`、`reason`、`title`、`description`、`tags`、`quality_score`、`completeness_score`、`confidence`、`trim_start` 和 `trim_end`。
- 分数字段必须是 `[0,1]` 的有限数值；低于本地阈值不是技术失败，而是转入人工复核。
- `keep` 必须提供非空标题、描述和有限数值 trim；没有达标片段时返回空 `clips`。

候选弹幕默认使用 `[mm:ss]` 时间轴。文本预算为 4000 字符，超限时优先保留开头、密度核心和结尾，避免只把最后 500 字符交给模型。

临时分析副本在成功或失败后清理，不保留在项目目录。

## Keep 路径

MiMo `keep` 后，`candidate_analyzer` 先执行本地质量闸门，再校验：

- `quality_score`、`completeness_score`、`confidence` 均达到生产阈值。
- 每个 clip 只接受一个连续区间；一个候选可以返回多个 clip。
- `trim_start >= 0`。
- `trim_end <= candidate_duration`。
- `trim_end > trim_start`。
- 区间长度至少 5 秒。

完成质量校验和跨候选去重后才运行 Whisper。ASR 只提取 trim 前后各 6 秒（靠近候选边缘时截断）的音频，以同一次段级时间戳把端点吸附到 3 秒内最近的分段边界，再裁成相对最终成片的字幕时间。不会为了边界吸附转写整个大候选，也不保证分段边界一定是语义完整句。

`faster-whisper` 使用 `large-v3 CPU int8`，默认启用批量推理、8 个 CPU 线程和保守 VAD；批量模式异常时回退同模型串行推理。ASR 仍保持单实例，避免多个 large-v3 模型争用内存。字幕烧录用一次 ffmpeg 同时完成粗剪和字幕渲染。

`AnalysisResult` 记录：

- `model_name`
- `token_usage`
- `candidate_start` / `candidate_end`
- `source_start` / `source_end`
- `suggested_trim`
- `completeness_score` / `confidence`

片段历史额外记录原始候选范围、MiMo 相对 trim、最终源录像绝对范围、质量闸门结果、分阶段运行耗时，以及互相独立的原始候选/分析 sidecar/最终成片工件，便于审计和失败重试。

## 状态

`GET http://127.0.0.1:2235/api/worker/status` 保留 `llm` 字段兼容旧前端：

| 状态 | 含义 |
|---|---|
| `idle` | 当前没有 MiMo 请求 |
| `requesting` | watcher 正在请求 MiMo |
| `error` | 最近一次 MiMo 请求失败 |

`error` 不是活跃工作，不阻止 Worker 空闲退出。pending 任务和 watcher 进程仍由各自字段表达。

## Fail-closed

- `MIMO_API_KEY` 缺失：预检失败，pending 保留。
- 临时分析副本生成失败：候选保留。
- Base64 超限：候选保留。
- MiMo 超时、限流或网络错误：候选保留。
- MiMo 非 JSON 或非法区间：候选保留。
- 质量分、完整度或置信度缺失/不足：候选进入人工复核，不运行自动后处理。
- 跨候选重复：较低分片段进入人工复核，不自动删除。
- MiMo `drop`：删除候选，不运行 Whisper。
- Whisper、字幕烧录、元数据或队列失败：候选保留，不自动上传。

旧本地模型运行时代码保留为手动回滚能力，但生产 watcher、预检和默认安装脚本不再启动或要求本地 Qwen/llama 运行时。

## 官方依据

- [MiMo-V2.5 模型规格与价格](https://mimo.mi.com/models/mimo-v2.5)
- [视频理解、Base64 限制与 fps 参数](https://mimo.mi.com/docs/zh-CN/quick-start/usage-guide/multimodal-understanding/video-understanding)
- [深度思考开关](https://mimo.mi.com/docs/zh-CN/quick-start/usage-guide/text-generation/deep-thinking)
- [MiMo-V2.5-ASR](https://mimo.mi.com/docs/zh-CN/quick-start/usage-guide/multimodal-understanding/Speech-Recognition)
