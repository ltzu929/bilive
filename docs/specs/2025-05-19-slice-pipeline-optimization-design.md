# 切片管线优化设计

> 日期：2025-05-19
> 状态：已确认

## 背景

当前切片管线有三个决策门：

1. **弹幕密度筛选** — 固定 60s 滑动窗口，选弹幕最多的 top-2 时段
2. **启发式质量评分** — 正则匹配"哈哈""牛逼"等词计算分数
3. **LLM 标题生成** — 标题生成失败则丢弃

问题：
- 固定窗口选弹幕多的时段，捕捉不到"突增"事件
- 正则启发式评分粗糙，直播内容多样无法用关键词覆盖
- 切片串行处理，总耗时翻倍
- Whisper 在 CPU 上跑 large-v3 极慢

## 设计决策

### P0-1：弹幕突增检测（替代固定窗口密度）

**原方案**：固定 60s 窗口，数弹幕总量，选 top-2。

**新方案**：基于突增率的峰值检测，切片时长自适应。

算法：
1. 将弹幕时间轴按 1s 粒度统计为时间序列
2. 计算背景密度 = 整场直播弹幕密度的中位数
3. 计算突增率 = 当前局部密度 / 背景密度
4. 突增率超过阈值（默认 3.0）的时段标记为"突增事件"
5. 合并相邻突增事件（间隔 < burst_merge_gap 秒的合并）
6. 每个突增事件：
   - 找到峰值时刻（弹幕密度最高的那一秒）
   - 峰值前取 60s + 峰值后取 60s = 固定 120s 切片
   - 如果峰值在视频开头或结尾，向非边缘方向补齐
7. 选 top_n（默认 3）个突增事件

新增配置项（`bilive-server.toml [slice]`）：

```toml
slice_method = "burst"           # "density"(旧) 或 "burst"(新)
burst_ratio = 3.0                # 突增阈值：当前密度/背景密度
burst_context = 60              # 峰值前后各取的秒数（切片总长 = 2 × burst_context）
burst_merge_gap = 5              # 合并间隔秒数
burst_top_n = 3                  # 最多选几个突增事件
```

旧 `density` 方法保留为 fallback，通过 `slice_method` 配置切换。

### P0-2：LLM 质量判断（替代正则启发式）

**原方案**：`_emotion_density` 数"哈哈"、`_filler_density` 数"嗯额"、`_info_density` 算字符比。

**新方案**：Whisper 转录后，单次 LLM 调用同时判断是否保留 + 生成标题。

两步筛选：
1. **弹幕突增初筛** — burst_ratio ≥ 3.0 的时段才进入下一步（轻量，纯计算）
2. **LLM 终判** — 弹幕文本 + Whisper 字幕 → LLM 一次性输出 retain/title/description

Prompt 设计：

```
你是一个直播切片审核员。以下是一段直播切片的信息：

主播：{artist}
弹幕内容（观众反应）：{danmaku_text}
主播讲话（转录）：{transcript}

请判断这段切片是否值得上传，并生成标题。以 JSON 返回：
{
  "retain": true/false,
  "retain_reason": "简短理由",
  "title": "不超过30字的吸引人标题",
  "description": "100字以内的内容摘要",
  "content_type": "gameplay/chat/singing/dance/other"
}
```

**删除**：`_emotion_density`、`_filler_density`、`_info_density`、`analyze_audio_content()` 整个启发式函数。

**删除**：`should_retain_slice()` 单独调用。质量判断合并进 LLM 调用结果。

**保留**：
- Whisper 转录 + `normalize_transcript()`（LLM 需要干净输入）
- `AnalysisResult` 数据类（LLM 返回值映射到同一结构）
- LLM 调用失败时的 fallback（模板标题 + 默认保留）

### P1-1：faster-whisper 替代 openai-whisper

**原方案**：`openai-whisper`，large-v3，device="cpu"，每个 60s 切片 30-120s。

**新方案**：`faster-whisper`（CTranslate2 后端），large-v3，device="cuda"，预计每个切片 3-8s。

修改文件：`src/autoslice/mllm_sdk/audio_analyzer.py`

```python
# 旧
import whisper
_whisper_model = whisper.load_model("large-v3", device="cpu")
result = _whisper_model.transcribe(audio_path, language="zh")

# 新
from faster_whisper import WhisperModel
_whisper_model = WhisperModel("large-v3", device="cuda", compute_type="int8")
segments, info = _whisper_model.transcribe(audio_path, language="zh")
```

精度：large-v3 模型参数量足够，INT8 量化后质量差异可忽略。

### P1-2：处理流程保持串行

**方案**：每个切片内部 Whisper→LLM 严格串行，切片之间也串行。

faster-whisper 和 LM Studio 都用 GPU，并行会导致 VRAM 争抢。
因此保持 `slice_only.py` 的 for 循环逐个处理，每个切片 Whisper 完成 → LLM 完成 → 下一个。
速度提升来自 faster-whisper 的 CUDA 加速，而非并行。

## 涉及文件

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `src/autoslice/auto_slice_video/autosv/calculate/burst_detection.py` | **新建** | 弹幕突增检测算法 |
| `src/autoslice/auto_slice_video/autosv/calculate/selection.py` | 修改 | 增加 burst 模式分发 |
| `src/autoslice/danmaku_slice.py` | 修改 | `slice_video_by_danmaku` 支持 burst 模式，自适应时长 |
| `src/autoslice/mllm_sdk/multi_modal_analyzer.py` | 修改 | LLM 质量判断 prompt 替代启发式 |
| `src/autoslice/mllm_sdk/audio_analyzer.py` | 修改 | faster-whisper 替代 openai-whisper |
| `src/autoslice/title_generator.py` | 修改 | 合并质量判断到 LLM 调用 |
| `src/autoslice/slice_quality_filter.py` | 修改 | retain 逻辑改为读 LLM 返回值 |
| `src/burn/slice_only.py` | 修改 | 移除并行计划，保持串行流程 |
| `src/config/server_config.py` | 修改 | 新增 burst 配置项 |
| `bilive-server.toml` | 修改 | 新增 [slice.burst] 配置段 |

## 不涉及

- 上传并行（P2，后续单独做）
- 文件监控替代轮询（P2，后续单独做）
- Pi 端代码（Pi 只录制，不动）