# ASR 引擎

切片管线中的语音转录组件。当前默认使用 Qwen3-ASR-1.7B。

## 配置

`bilive-server.toml` → `[slice.multi_modal]`：

```toml
whisper_engine = "qwen3-asr"              # 引擎选择
whisper_model = "Qwen/Qwen3-ASR-1.7B"     # 模型 ID (HuggingFace)
whisper_device = "cuda"                   # cuda / cpu
```

引擎分发逻辑：`src/autoslice/mllm_sdk/audio_analyzer.py` → `transcribe_audio_whisper()`

## 引擎对比

| 引擎 | 配置值 | 模型 | 中文 CER | 显存 | 速度 | 状态 |
|------|--------|------|---------|------|------|------|
| **Qwen3-ASR** | `qwen3-asr` | Qwen3-ASR-1.7B | **3.2%** | ~5GB | ~20s/片段 | ✅ 推荐 |
| openai-whisper | `openai-whisper` | large-v3-turbo | ~12% | ~5GB | ~60s/片段 | ✅ 可用 |
| faster-whisper | `faster-whisper` | large-v3 | ~12% | ~5GB | ~8s/片段 | ❌ 缺cuBLAS |

> 中文准确率差距：Qwen3-ASR 的 CER 3.2% vs Whisper 12-19%，好 4-6 倍。在噪音环境下差距更大（16% vs 63%）。

## Qwen3-ASR

2026年1月阿里发布，1.7B 参数，支持 52 种语言 + 22 种中文方言，自带标点。

安装：`pip install qwen-asr`

首次运行从 HuggingFace 下载约 4.5GB 模型，建议设 `HF_TOKEN` 加速（同下）。

代码：`src/autoslice/mllm_sdk/audio_analyzer.py` → `_transcribe_qwen3_asr()`

回退到 Whisper：`whisper_engine = "openai-whisper"`, `whisper_model = "large-v3-turbo"`

## faster-whisper / openai-whisper 预下载

faster-whisper 使用 CTranslate2 格式模型（~3GB），首次运行需从 HuggingFace 下载。
openai-whisper 使用 PyTorch 格式（~3GB），缓存于 `~/.cache/whisper/large-v3.pt`。

**加速下载**：在 https://huggingface.co/settings/tokens 创建 token，设 `$env:HF_TOKEN = "hf_xxx"`。

**cuBLAS 问题**：faster-whisper 依赖 `cublas64_12.dll`（CUDA 12 Toolkit），仅安装驱动（CUDA 13）时不包含此 DLL。表现为 `Library cublas64_12.dll is not found`。目前无解——需安装 CUDA Toolkit 12.x 或改用 openai-whisper。
