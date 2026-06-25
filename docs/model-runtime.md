# MiMo 模型运行时

## 目标

生产切片使用 `mimo-v2.5` 做候选视频全模态判断。弹幕密度仍是唯一候选范围生成器；MiMo 只判断候选价值并返回一个连续粗剪区间。

```text
弹幕密度 -> 候选范围 -> MiMo 全模态判断
  -> drop：删除候选
  -> keep：单段粗剪 -> faster-whisper 字幕 -> 烧录 -> 上传队列
  -> 失败：保留人工复核
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
max_base64_bytes = 48000000
```

API Key 默认从项目本地 `.secrets/env` 读取，进程环境变量可覆盖：

```powershell
Add-Content .\.secrets\env "MIMO_API_KEY=<your-key>"
```

`.secrets/` 已被 git 忽略。不要把 API Key 写入 `bilive-server.toml`、日志、测试快照、提交信息或公开文档。

## 请求形态

`src/autoslice/mllm_sdk/mimo_video.py` 负责：

- 为候选生成临时 720p H.264/AAC 分析副本。
- 使用 Base64 `data:video/mp4;base64,...` 传入 MiMo。
- 编码后 Base64 字符串硬限制为 `48_000_000` 字节。
- 超限时降低码率重试一次；仍超限则 `judge_failed`。
- 请求设置 `fps=1.0`、`media_resolution=default`。
- 请求设置 `thinking.type=disabled`。
- 要求 JSON 输出：`decision`、`reason`、`title`、`description`、`tags`、`quality_score`、`trim_start`、`trim_end`。
- 所有字段都必须存在并通过本地类型校验；`quality_score` 范围为 `[0,1]`。
- `keep` 必须提供非空标题、描述和有限数值 trim；`drop` 的两个 trim 字段必须为 `null`。

临时分析副本在成功或失败后清理，不保留在项目目录。

## Keep 路径

MiMo `keep` 后，`candidate_analyzer` 校验：

- 只接受一个连续区间。
- `trim_start >= 0`。
- `trim_end <= candidate_duration`。
- `trim_end > trim_start`。
- 区间长度至少 5 秒。

校验通过后才运行 Whisper。音频提取使用 MiMo 相对区间，因此 Whisper 段级时间戳相对于最终粗剪片段。字幕烧录阶段用一次 ffmpeg 同时完成粗剪和字幕渲染，避免重复编码。

`AnalysisResult` 记录：

- `model_name`
- `token_usage`
- `candidate_start` / `candidate_end`
- `source_start` / `source_end`
- `suggested_trim`

片段历史额外记录原始候选范围、MiMo 相对 trim 和最终源录像绝对范围，便于审计。

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
- MiMo `drop`：删除候选，不运行 Whisper。
- Whisper、字幕烧录、元数据或队列失败：候选保留，不自动上传。

旧本地模型运行时代码保留为手动回滚能力，但生产 watcher、预检和默认安装脚本不再启动或要求本地 Qwen/llama 运行时。

## 官方依据

- [MiMo-V2.5 模型规格与价格](https://mimo.mi.com/models/mimo-v2.5)
- [视频理解、Base64 限制与 fps 参数](https://mimo.mi.com/docs/zh-CN/quick-start/usage-guide/multimodal-understanding/video-understanding)
- [深度思考开关](https://mimo.mi.com/docs/zh-CN/quick-start/usage-guide/text-generation/deep-thinking)
- [MiMo-V2.5-ASR](https://mimo.mi.com/docs/zh-CN/quick-start/usage-guide/multimodal-understanding/Speech-Recognition)
