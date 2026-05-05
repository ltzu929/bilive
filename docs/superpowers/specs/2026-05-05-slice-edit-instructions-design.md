# Slice Edit Instruction 设计

## Context

当前切片流程已经可以完成录制、弹幕密度切片，并通过 Whisper 产出字幕分析。下一步目标是把这些分析结果转成可执行的剪辑指令，先供自动剪辑程序消费，再进一步包装成给大模型二次处理的提示词。

本设计分两阶段：

1. **阶段 B：结构化剪辑 JSON 指令**。为每个切片输出稳定的 `_edit.json`，描述保留/丢弃、裁剪范围、高光片段、字幕证据、弹幕证据和剪辑动作。
2. **阶段 C：模型二次处理 Prompt**。基于 `_edit.json`、Whisper 字幕、弹幕密度摘要和已有分析结果，输出 `_prompt.md`，作为后续模型继续分析或生成更复杂剪辑方案的输入。

## Current Flow

当前主要链路：

```text
record.sh
  -> blrec 录制视频和弹幕
slice.sh
  -> src.burn.scan_slice
  -> src.burn.slice_only.slice_only()
  -> process_danmakus(xml -> ass)
  -> slice_video_by_danmaku()
  -> generate_title()
  -> AnalysisResult / title
  -> quality filter
  -> inject metadata
  -> upload queue
```

`multi_modal_analyzer.py` 已经能通过 Whisper 得到音频文本，并生成 `AnalysisResult`。但当前结果更偏向上传 metadata 和质量判断，还缺少面向自动剪辑的结构化指令。

## Recommended Architecture

新增一个独立的剪辑指令层，不把所有字段继续堆到 `AnalysisResult`。

```text
src/autoslice/
  edit_instruction.py          # 数据类、JSON 读写、基础校验
  edit_instruction_builder.py  # 从 AnalysisResult、字幕、弹幕摘要构建指令
  prompt_packager.py           # 阶段 C：生成模型二次处理 prompt
```

`AnalysisResult` 继续负责内容理解和质量判断；`EditInstruction` 负责自动剪辑控制。这样后续可以替换剪辑器、替换模型，或者单独重跑 prompt 包装，而不影响现有上传流程。

## Stage B: EditInstruction JSON

每个通过质量过滤的切片旁边输出：

```text
<slice_stem>_analysis.json
<slice_stem>_edit.json
```

建议 schema：

```json
{
  "schema_version": "1.0",
  "source_video": "Videos/.../record.mp4",
  "slice_video": "Videos/.../record_slice_001.mp4",
  "decision": "keep",
  "confidence": 0.82,
  "trim": {
    "start": 2.5,
    "end": 58.0,
    "reason": "开头静默较长，高潮集中在中后段"
  },
  "segments": [
    {
      "start": 8.0,
      "end": 18.5,
      "type": "highlight",
      "score": 0.9,
      "reason": "弹幕密度上升且字幕出现关键反应"
    }
  ],
  "subtitle_evidence": [
    {
      "start": 7.2,
      "end": 10.8,
      "text": "关键字幕内容"
    }
  ],
  "danmaku_evidence": {
    "peak_time": 12.0,
    "density_reason": "该时间段弹幕明显集中"
  },
  "edit_actions": [
    "保留 8.0-18.5 作为主高潮",
    "删除开头 0-2.5 秒空白",
    "在 12 秒附近加强字幕或音效提示"
  ],
  "upload_suggestion": {
    "title": "建议标题",
    "description": "建议简介",
    "tags": ["直播", "高光"]
  }
}
```

### Field Rules

- `decision`: `keep`、`review`、`drop` 三选一。自动上传仍只上传通过质量过滤的切片；`review` 可保留文件但不强制上传，后续可扩展。
- `confidence`: 0 到 1。优先继承 `AnalysisResult.quality_score`，再结合字幕证据和弹幕高峰调整。
- `trim`: 优先使用 `AnalysisResult.suggested_trim`。没有模型建议时默认保留完整切片。
- `segments`: 优先使用 `AnalysisResult.highlights`。没有 highlights 时用弹幕高峰附近生成一个保守片段。
- `subtitle_evidence`: 从切片对应时间范围内的 SRT 提取，数量控制在 3 到 8 条，避免 prompt 过长。
- `danmaku_evidence`: 第一版只保存切片来源和峰值说明；如果 `slice_video_by_danmaku()` 后续暴露密度明细，再补充密度曲线。
- `edit_actions`: 用确定性规则生成，避免第一版依赖额外模型调用。
- `upload_suggestion`: 复用 `AnalysisResult` 的标题、简介和标签。

## Stage C: Prompt Packaging

每个 `_edit.json` 可进一步生成：

```text
<slice_stem>_prompt.md
```

Prompt 内容包含：

1. 切片基本信息：来源、长度、主播、切片文件。
2. 结构化剪辑指令：完整嵌入 `_edit.json`。
3. 字幕证据：压缩后的关键 SRT 片段。
4. 弹幕证据：弹幕密度触发原因和高峰时间。
5. 任务说明：要求模型给出二次剪辑建议，输出 JSON，不改变已有时间轴单位。

Prompt 只作为后续模型输入，不直接影响当前上传链路。这样阶段 B 可以先落地并验证，阶段 C 再接模型。

## Data Flow

阶段 B 接入点：

```text
slice_only()
  -> generate_title(slice_path, artist)
  -> AnalysisResult
  -> should_retain_slice()
  -> build_edit_instruction(...)
  -> write <slice_stem>_edit.json
  -> inject_metadata()
  -> upload queue
```

普通 `render_video()` 的自动切片分支也使用同一个 builder，避免两套逻辑分叉。

字幕来源策略：

- 如果切片旁边已经有对应 SRT，直接读取。
- 如果只有整场 SRT，则根据切片文件名或后续元数据推断时间偏移，提取切片区间内字幕。
- 如果无法可靠获得字幕时间偏移，阶段 B 仍输出 `_edit.json`，但 `subtitle_evidence` 为空，并在 `edit_actions` 中标记“字幕证据缺失，建议人工复核”。

## Configuration

新增配置建议：

```toml
[slice.edit]
enable_edit_instruction = true
enable_prompt_package = false
max_subtitle_evidence = 6
default_highlight_window = 12
```

默认启用 `_edit.json`，默认不启用 `_prompt.md`。原因是阶段 B 是自动剪辑需要的基础产物；阶段 C 可能增加文件数量和后续模型调用成本，应显式打开。

## Error Handling

- 剪辑指令生成失败不应中断切片上传，只记录错误并继续处理当前切片。
- JSON 写入失败返回 `False` 并记录日志，不删除原视频。
- 缺少字幕或弹幕细节时输出降级指令，而不是返回 `None`。
- 时间字段必须裁剪到切片时长范围内，避免生成负数或超过视频长度。

## Testing

第一阶段测试覆盖：

- `EditInstruction.from_dict()` / `to_dict()` / `to_json_file()`。
- 从带 highlights 的 `AnalysisResult` 构建 segments。
- 从带 `suggested_trim` 的 `AnalysisResult` 构建 trim。
- 缺少字幕证据时仍能输出有效 JSON。
- 配置关闭时不生成 `_edit.json`。

第二阶段测试覆盖：

- 从 `_edit.json` 生成 prompt。
- Prompt 包含 schema、字幕证据和任务说明。
- Prompt 对超长字幕做截断，不生成过长文件。

## Scope

本轮不实现真正的视频重剪、转场、BGM、字幕烧录或二次模型调用。本轮只产出稳定的自动剪辑指令和后续模型输入，保证后续剪辑器可以基于该接口独立开发。

## Self Review

- 占位符扫描: 未发现未定内容。
- Consistency: 阶段 B 和阶段 C 的产物、配置、接入点已分离。
- Scope: 第一轮只生成指令和 prompt，不改变上传主链路行为。
- Ambiguity: 字幕缺失、弹幕密度明细缺失和时间越界均有降级规则。
