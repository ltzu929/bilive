# ASR 引擎

切片管线中的语音转录组件。当前默认使用 `faster-whisper`，因为字幕烧录需要真实时间戳。

## 当前推荐配置

`bilive-server.toml` -> `[slice.multi_modal]`：

```toml
whisper_engine = "faster-whisper"
whisper_model = "large-v3"
whisper_device = "cpu"
whisper_compute_type = "int8"
```

引擎分发逻辑：`src/autoslice/mllm_sdk/audio_analyzer.py` -> `transcribe_audio_whisper()`。

## 为什么回到 faster-whisper

字幕烧录必须使用真实时间戳。`Qwen3-ASR` 可以给出整段文本，但当前集成没有可用的真实段级时间戳；如果强行把一整段 transcript 平均切开，字幕会变成长句或节奏错误。

`faster-whisper` 返回 `segments`，每段包含 `start/end/text`，可以直接生成 SRT：

```text
transcript_segments -> *_asr.srt -> ffmpeg subtitles filter -> burned mp4
```

因此当前策略是：

- 有真实 `transcript_segments`：生成 SRT 并烧录。
- 没有真实时间戳：不烧录伪字幕。

## 引擎对比

| 引擎 | 配置值 | 当前用途 | 时间戳 | 状态 |
|------|--------|----------|--------|------|
| faster-whisper | `faster-whisper` | 当前默认 ASR + 字幕烧录 | 有真实段时间戳 | 推荐，CPU `int8` 可用 |
| openai-whisper | `openai-whisper` | 兼容回退 | 有真实段时间戳 | 可用但慢 |
| Qwen3-ASR | `qwen3-asr` | 只适合文本转录参考 | 当前无可用真实时间戳 | 不适合烧录字幕主路径 |

## 模型选择

当前实际可用模型：

```toml
whisper_model = "large-v3"
```

原因：

- 本机已经缓存 `Systran/faster-whisper-large-v3`。
- `large-v3-turbo` 首次下载可能因为 HuggingFace/代理失败。
- CPU `int8` 虽然慢，但稳定，不依赖 CUDA DLL。

如果后续网络和缓存稳定，可以再测试 `large-v3-turbo`。测试前先确认 HuggingFace 下载能完成。

## CUDA 注意事项

`faster-whisper` 的 CUDA 路径依赖 CTranslate2 对应的 CUDA 12 运行库。只有显卡驱动或 CUDA 13 驱动通常不包含：

```text
cublas64_12.dll
```

缺这个 DLL 时会报：

```text
Library cublas64_12.dll is not found or cannot be loaded
```

处理方式：

1. 继续使用当前 CPU 配置：`whisper_device = "cpu"`、`whisper_compute_type = "int8"`。
2. 或安装/配置 CUDA 12 cuBLAS 运行库，再改为 CUDA。

不要只把配置改成 `whisper_device = "cuda"`，否则 worker 会在 ASR 阶段失败。

## 下载和缓存

faster-whisper 使用 HuggingFace 模型缓存。网络不稳定时会出现代理或连接重置错误。可以：

- 使用已经缓存的 `large-v3`。
- 配置可用代理。
- 设置 `HF_TOKEN`。

PowerShell 示例：

```powershell
$env:HF_TOKEN = "hf_xxx"
```

## 相关文件

| 文件 | 用途 |
|------|------|
| `bilive-server.toml` | 当前 ASR 配置 |
| `src/autoslice/mllm_sdk/audio_analyzer.py` | ASR 引擎加载和转录 |
| `src/autoslice/mllm_sdk/multi_modal_analyzer.py` | 分析管线参数透传 |
| `src/autoslice/candidate_analyzer.py` | 生产候选 ASR，并把转录和窗口弹幕交给 LLM |
| `src/autoslice/title_generator.py` | 上游标题生成兼容模块，不在 pending 生产主路径 |
| `src/burn/subtitle_burn.py` | SRT 生成和字幕烧录 |
| `tests/test_subtitle_burn.py` | 字幕烧录测试 |
