# 切片管线优化设计

> 日期: 2025-05-19
> 状态: 待审核
> 涉及模块: `autoslice/`, `burn/slice_only.py`, `burn/scan_slice.py`, `upload/upload.py`, `config/`

## 背景与动机

当前切片管线的决策逻辑存在三个核心问题：

1. **弹幕密度算法过于粗糙**：固定 60s 窗口数弹幕总量，只选 top-2。弹幕持续多的直播间会选中"平均热闹"时段而非真正的突发高能；真正的精彩爆发可能被淹没。
2. **质量筛选用正则启发式**：数"哈哈""牛逼"判断精彩，数"嗯""额"判断废话。直播内容多样（游戏/唱歌/聊天），正则无法覆盖，且评分粗糙。
3. **处理速度慢**：Whisper large-v3 在 CPU 上跑 openai-whisper 每个切片 30-120s；多切片串行处理；上传单线程。

## 设计决策

### 1. 弹幕突增检测（替代固定窗口密度）

**现状**：`sliding_cpu.py` 固定 60s 窗口，按弹幕总数排序取 top-2。

**改为**：基于突增率的自适应峰值检测。

#### 算法

```
输入：弹幕时间戳列表（从 ASS 文件提取），参数配置
输出：突增事件列表，每个事件包含 {peak_time, start, end, peak_density, burst_ratio}

步骤：
1. 将弹幕时间轴按 1s 粒度统计为密度序列 danmaku_per_second[]
2. 计算背景密度 baseline：
   - 取整场直播密度的中位数（排除前 30s 和后 30s，避免开头/结尾异常）
3. 滑动窗口计算局部密度（窗口大小 = burst_window，默认 10s）
4. 计算突增率 = 局部密度 / baseline
5. 标记突增率 >= burst_ratio（默认 3.0）的时段为"突增事件"
6. 合并相邻突增事件（间隔 < burst_merge_gap，默认 5s 的合并为一个）
7. 每个突增事件：
   a. peak_time = 密度最高的时刻
   b. 从突增开始前推 pre_context（默认 15s）
   c. 从突增结束后延 post_context（默认 20s）
   d. 自适应时长：最短 burst_min_duration（默认 30s），最长 burst_max_duration（默认 180s）
   e. 如果突增持续很长（弹幕一直多），切片跟着拉长，不会硬切到固定时长
8. 按 peak_density 降序取 top_n_events（默认 3）
9. 去重：任意两个切片重叠超过 max_overlap（默认 30s）则只保留密度更高的
```

#### 与现有点密度算法的对比

| 特性 | 旧（固定窗口密度） | 新（突增检测） |
|------|---------------------|-----------------|
| 检测目标 | 弹幕绝对数量 | 弹幕增速（相对于背景） |
| 时长 | 固定 60s | 自适应 30-180s |
| 切片数 | 固定 top-2 | 可配置 top-3 |
| 低弹幕直播 | 可能选不到 | 正常检测突发 |
| 高弹幕直播 | 选中的只是平均热闹 | 精确捕捉爆发时刻 |

#### 配置项（`bilive-server.toml [slice]`）

```toml
# 新增突增检测配置
slice_method = "burst"               # "density"(旧) 或 "burst"(新)
burst_ratio = 3.0                     # 突增阈值：局部密度/背景密度 ≥ 此值视为突增
burst_window = 10                     # 突增检测窗口（秒）
burst_min_duration = 30               # 最短切片秒数
burst_max_duration = 180               # 最长切片秒数
burst_merge_gap = 5                   # 相邻突增合并间隔（秒）
burst_pre_context = 15                # 突增前上下文（秒）
burst_post_context = 20               # 突增后上下文（秒）
burst_top_n = 3                       # 最多选几个突增事件
```

#### 兼容性

- `slice_method = "density"` 保持旧算法，完全向后兼容
- `slice_method = "burst"` 启用新算法
- `danmaku_slice.py` 的 `slice_video_by_danmaku()` 增加分支，根据 `SLICE_METHOD` 选择算法
- 旧参数 `SLICE_DURATION`, `SLICE_NUM`, `SLICE_OVERLAP`, `SLICE_STEP` 仍用于 density 模式

#### 新代码文件

- `src/autoslice/burst_detector.py` — 突增检测核心算法
- 单元测试 `tests/test_burst_detector.py`

### 2. LLM 质量判断（替代正则启发式）

**现状**：
- `analyze_audio_content()` 用正则数"哈哈""牛逼""嗯""额"
- `should_retain_slice()` 判断 `quality_score >= threshold`
- `_llm_generate_title()` 单独调 LLM 生成标题
- 两次模型交互，质量评分粗糙

**改为**：Whisper 转录完成后，单次 LLM 调用同时判断保留/丢弃 + 生成标题。

#### Prompt 设计

```
你是一个直播切片审核员。以下是一段直播切片的信息：

主播：{artist}
弹幕内容（观众反应）：{danmaku_text}
主播讲话（Whisper转录）：{transcript}

请判断这段切片是否值得上传，并生成标题。以 JSON 格式返回：
{
  "retain": true/false,
  "retain_reason": "简短理由",
  "title": "不超过30字的吸引人标题",
  "description": "100字以内的内容摘要",
  "content_type": "gameplay/chat/singing/dance/other"
}

判断标准：
- retain=true: 内容有看点，观众互动热烈，主播有精彩表现
- retain=false: 内容平淡，无实质内容，纯沉默期，只有无意义重复
```

#### 流程变更

```
旧流程：
  Whisper转录 → analyze_audio_content(正则) → quality_score
  → should_retain_slice(score >= 0.5)
  → _llm_generate_title()
  → 注入元数据

新流程：
  Whisper转录 → _judge_and_title(danmaku_text, transcript, artist)
    → 一次LLM调用 → {retain, retain_reason, title, description, content_type}
  → retain=false → 删除切片，不入队列
  → retain=true → 注入元数据(title) → 入上传队列
```

#### 删除的代码

- `_emotion_density()` — 正则匹配情绪词
- `_filler_density()` — 正则匹配废话词
- `_info_density()` — 信息密度计算
- `analyze_audio_content()` — 启发式质量评分
- `slice_quality_filter.py` → `should_retain_slice()` — 阈值筛选
- `combine_analysis()` 中的质量评分逻辑

**保留**的代码：
- `extract_audio()` → ffmpeg 音频提取
- `transcribe_audio_whisper()` → Whisper 转录（改用 faster-whisper）
- `normalize_transcript()` → 转录文本清洗
- `_llm_generate_title()` → 改写为 `_judge_and_title()`，返回类型从 `dict` 改为 `JudgeResult`

#### 新代码文件

- `src/autoslice/mllm_sdk/judge.py` — `_judge_and_title()` 函数 + `JudgeResult` 数据类
- `src/autoslice/slice_quality_filter.py` → 改写为调用 LLM judge

#### 降级策略

LLM 调用失败时（LM Studio 无响应 / 超时）：
1. 重试 1 次
2. 仍然失败 → fallback 到模板标题（`{artist}直播片段`），retain=true
3. 日志记录 LLM 失败原因

### 3. faster-whisper + large-v3

**现状**：`audio_analyzer.py` 使用 `openai-whisper`，`device="cpu"`，large-v3 每切片 30-120s。

**改为**：`faster-whisper` (CTranslate2)，相同 large-v3 模型，CPU 上快 3-5 倍，GPU 上更快。

#### 实现

```python
# 旧
import whisper
model = whisper.load_model("large-v3", device="cpu")
result = model.transcribe(audio_path, language="zh")

# 新
from faster_whisper import WhisperModel
model = WhisperModel("large-v3", device="cpu", compute_type="int8")
segments, info = model.transcribe(audio_path, language="zh")
```

#### 配置项

```toml
[slice.multi_modal]
whisper_engine = "faster-whisper"   # "faster-whisper"(新) 或 "openai-whisper"(旧)
whisper_model = "large-v3"           # 支持所有 openai-whisper 的模型大小
whisper_device = "cpu"               # "cpu" 或 "cuda"
whisper_compute_type = "int8"         # CPU推荐int8，GPU推荐float16
```

#### 兼容性

- `whisper_engine = "openai-whisper"` 保持旧行为
- `whisper_engine = "faster-whisper"` 启用新引擎
- 新增依赖 `faster-whisper` 到 `requirements.txt`
- 全局模型缓存，避免重复加载

### 4. 切片并行处理

**现状**：`slice_only.py` 的 for 循环串行处理每个切片。

**改为**：`ThreadPoolExecutor` 并行处理所有切片的 Whisper + LLM 阶段。

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

def _process_single_slice(generated_slice, original_video_path, xml_path, artist, ...):
    """单个切片的完整处理流程（从 Whisper 到入队列）"""
    # 原来循环体内的逻辑
    ...

with ThreadPoolExecutor(max_workers=max(2, len(slices_path))) as pool:
    futures = {
        pool.submit(_process_single_slice, s, ...): s
        for s in slices_path
    }
    for future in as_completed(futures):
        try:
            future.result()
        except Exception as e:
            scan_log.error(f"Slice processing failed: {e}")
```

#### 配置项

```toml
[slice]
max_slice_workers = 2  # 并行处理切片数，默认2
```

#### 注意事项

- Whisper 和 LLM 各占不同资源（Whisper 吃 CPU/RAM，LLM 吃 GPU via LM Studio），2 并行不会争抢
- faster-whisper 的 `int8` 量化比 openai-whisper 内存占用更小，2 实例并行可行
- LM Studio 服务本身支持并发请求

### 5. 上传并行（P2，低优先级）

**现状**：`upload.py` 单线程出队上传。

**改为**：`ThreadPoolExecutor(max_workers=2)` 包裹 `upload_video()`。

独立改动，不影响切片逻辑，可后续单独实施。

### 6. 文件监控替代轮询（P2，低优先级）

**现状**：`scan_slice.py` 用 `while True: sleep(120)` 轮询。

**改为**：`watchdog.Observer` 监控 Videos/ 目录，新 mp4 文件事件触发处理。

独立改动，不影响切片逻辑，可后续单独实施。

---

## 实施优先级

| 优先级 | 改动 | 文件 | 依赖 |
|--------|------|------|------|
| P0-1 | 弹幕突增检测 | 新增 `burst_detector.py`，改 `danmaku_slice.py`、`server_config.py`、`slice_only.py` | 无 |
| P0-2 | LLM 质量判断 | 新增 `judge.py`，改 `multi_modal_analyzer.py`、`slice_only.py`、`render_video.py` | 无 |
| P1-1 | faster-whisper | 改 `audio_analyzer.py`、`server_config.py`，加 `requirements.txt` | 无 |
| P1-2 | 切片并行处理 | 改 `slice_only.py` | 无 |
| P2-1 | 上传并行 | 改 `upload.py` | 无 |
| P2-2 | 文件监控 | 改 `scan_slice.py`，加 `watchdog` 依赖 | 无 |

P0 和 P1 无互相依赖，可并行开发。P2 后续独立实施。

## 测试策略

1. **突增检测**：用现有录制视频的弹幕文件测试，对比旧算法和新算法选出的切片点，人工评估合理性
2. **LLM 质量**：用已上传切片的视频回放测试，检查 retain/retain_reason 的判断是否合理
3. **faster-whisper**：对比 openai-whisper 和 faster-whisper 的转录文本，精度应一致
4. **并行处理**：2 切片并行处理，验证无文件冲突、无竞态条件
5. **回归测试**：`slice_method = "density"` + `whisper_engine = "openai-whisper"` 旧行为仍然正常

## 回滚方案

所有改动通过配置项切换：
- `slice_method = "density"` → 旧算法
- `whisper_engine = "openai-whisper"` → 旧 Whisper
- LLM judge 失败 → fallback 模板标题 + retain=true

配置项回滚即可恢复旧行为，无需代码回滚。