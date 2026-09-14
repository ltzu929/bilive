# 切片质量优化 TODO

记录于 2026-08 对齐后的结论。目标仍是「聊天精品片段」，不追求产量。
实施时继续遵守：Pi/Windows 边界、fail-closed、无人工标签不改质量阈值。

## 优先级

### P0

#### 1. 多信号爆点召回
- 现状：`src/autoslice/burst_detector.py` 只看弹幕密度突增（`burst_ratio=3.0`，`top_n=3`，`burst_lag_seconds=0.0`）。
- 目标：在弹幕突增之外，把 SC/醒目留言、礼物事件、音频能量峰并入召回与排序；弹幕仍是主线索，多信号只做召回/加权，不直接当保留理由。
- 涉及：
  - 弹幕 XML：已有时间戳；需解析 SC / 礼物类型节点（若边车或录制数据里有）。
  - 音频：候选级音量包络 / VAD 峰，Windows 侧 ffmpeg 或已有 ASR 前置结果。
  - `danmaku_slice.py` / `burst_detector.py` 的候选排序与 `top_n` 选取。
- 验收：固定样本集上，人工 keep 的爆点是否更多落入候选窗；`danmaku_noise` 型空热闹是否下降。不自动改 `min_quality_*`。

#### 2. 判断前预跑 ASR + 字幕专有名词修正
- 状态：**已实现（2026-08）**
- 实现：
  - `pre_judge_asr`（默认开）：`slice_only` 在 MiMo 前对候选窗跑 ASR，`[mm:ss]` 转写注入 prompt；同一批分句复用到 keep 后边界吸附/字幕，避免二次全量转写。
  - `enable_subtitle_correct`（默认开）：成片烧录前对字幕做专名/同音字轻量修正；失败保留原 ASR。
  - 配置：`bilive-server.toml` `[slice.analysis]` / `[slice.subtitle]`；环境变量 `BILIVE_PRE_JUDGE_ASR`、`BILIVE_ENABLE_SUBTITLE_CORRECT`。
- 验收：待真实候选抽看（主题误判、字幕专名）。

#### 3. 静音裁切
- 目标：只压缩句间长停顿/空白，绝不切半句；范围限制在已通过质量闸门的成片。
- 涉及：成片 ffmpeg 阶段（`src/burn/` / pipeline）；可用 ASR/VAD 分段定位静音。
- 验收：句完整性不被破坏；时长缩短且节奏更好；可配置开关，默认策略先只作用于自动成片。

### P1

#### 4. 封面自动帧 + 大字标题
- 目标：
  - 从 MiMo `core_start/core_end` 区间抽 3–5 帧，按亮度/清晰度/构图启发式选 1 张作为封面。
  - 封面叠加一行大字标题（模板贴字，Pillow）；工作台可改。
- 涉及：`.upload.json` 的 `cover` 字段已存在；`src/upload/slice_metadata.py`、成片/入队阶段、Dashboard 预览。
- 验收：自动封面可用率；贴字不溢出、不挡脸。

#### 5. 可执行剪辑效果 timeline
- 目标：不再只输出给人看的 `edit_actions` 文本，而是让 MiMo/本地规则产出可执行 timeline，成片编译为 ffmpeg filtergraph。
- 首批效果（白名单，可开关）：
  1. 静音裁切（与 P0#3 共用）
  2. 爆点 punch-in / 轻推近（`core_start` 附近 1–2s）
  3. 关键词/字幕高亮（可选，后做）
- 参考方向：auto-editor 类静音砍切、能量峰 jump cut、Ken Burns 口播推拉；不引入重型剪辑框架，保持 ffmpeg 原生。
- 涉及：`src/autoslice/edit_instruction*.py` schema 扩展；`src/burn/` 成片；效果默认关或极简默认，避免花活拖垮稳定性。
- 验收：效果开关下的成片可播放、边界仍完整；默认路径不劣化。

#### 6. 边界二次裁决（可选，吸附不够时再上）
- 现状：keep 后 ASR **机械吸附** trim 端点到 3s 内分句边界（`snap_trim_to_segments`）。
- 目标：若边界仍可疑（贴候选边、末句无落点、首句像半截），对 `trim±6s` 小窗再问一次 MiMo：「从哪句完整话开始、到哪句自然结束」。
- 区别：这是内容级重裁，不是吸附。若吸附已满足质量，此项可不做。
- 涉及：`candidate_analyzer.py` 边界闸门之后的小窗再判。

#### 7. 系统性优化提示词
- 目标：对生产 prompt 做一轮结构化整理，而不是零散补丁。
- 范围（至少覆盖）：
  - 判断主 prompt：`src/autoslice/mllm_sdk/mimo_video.py` `_build_prompt`
  - 判断前 ASR 证据如何表述（长度、截断策略、错字免责声明）
  - 字幕校对 prompt：`src/autoslice/transcript_correct.py` `_build_correct_prompt`
  - 与 `docs/chat-slice-quality.md` 保留标准、边界标准、标题风格是否一致
- 做法：
  1. 先盘点现有 prompt 段落与 JSON schema 要求，去掉重复/过时表述。
  2. 对照人工原因代码（`standalone/hook/arc/payoff/...`）检查 prompt 是否仍引导同一套判断。
  3. 在固定样本集上改一版、比一版；无人工标签或样本不足时不降低质量阈值。
  4. 记录每轮改了什么、为什么改、样本上的 false_keep/false_drop 变化。
- 涉及：`mimo_video.py`、`transcript_correct.py`、`docs/chat-slice-quality.md`、校准样本。
- 验收：固定样本上决策更稳，且 prompt 可读性/结构明显好于当前叠层。

## 明确不做 / 搁置

| 项 | 原因 |
|---|---|
| 每候选窗 0..N 多段 | 已确认不同意；维持 0 或 1 段 |
| 标题一次出 3 个人工三选一 | 用户懒得选；MiMo 自己定最终标题 |
| 用 `slice_performance` 反推标题模式 | 样本量与产品回报都偏远 |
| 自我进化自动调参/自动改阈值 | 偏远；仅保留人工反馈落盘，不做闭环调参 |
| 降低质量分 / 弹幕检测 / 候选边界阈值换产量 | 与质量目标冲突 |

## 配套（不挡主路径，随做随记）

- 人工 `keep/review/drop` + `manual_trim` + 原因代码继续落盘，供日后评估；**不**据此自动改阈值。
- 固定样本评估协议见 `docs/slice-quality-calibration.md`；样本扩大前不单独为调参改 prompt。
- 文档中的 Whisper 设备描述（architecture/README）已在 P0#2 同步为 GPU 生产配置。

## 建议实施顺序

```text
P0#1 多信号爆点 → P0#2 ASR前置+字幕修正 → P0#3 静音裁切
→ P1#4 封面+大字 → P1#5 效果 timeline → P1#6 边界二次裁决（按需）
→ P1#7 系统性优化提示词（样本够用后再动）
```

每项做完在对应小节打勾并写一句验收结果，避免只堆未完成清单。
