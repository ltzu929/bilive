# 切片质量优化 TODO

记录于 2026-08 对齐后的结论。目标仍是「聊天精品片段」，不追求产量。
实施时继续遵守：Pi/Windows 边界、fail-closed、无人工标签不改质量阈值。

## 优先级

### P0

#### 1. 多信号爆点召回
- 状态：**取消（2026-09）**
- 原因：多信号只影响「送哪几段给 MiMo」，不直接决定保留；现有弹幕密度 + MiMo 判断已覆盖主路径。SC/礼物节点虽已在 blrec XML 旁车（`sc`/`toast`/`guard`），但为召回加权/扩窗的复杂度与收益不匹配，不值得单独实现。
- 保留结论：继续只用弹幕密度突增召回；漏检与 `danmaku_noise` 靠固定样本人工标签和 MiMo 闸门处理，不改检测逻辑。

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

#### 8. 视频叠层动画（远期探索，可能用 HTML/CSS 动画）
- 想法：在成片上叠加少量动态元素，例如标题弹入、关键词高亮、表情包/进度条、片头 hook 卡片，而不是整段重剪。
- 技术路线候选（未选定，先探索）：
  1. **HTML/CSS 动画 → 透明视频/PNG 序列 → ffmpeg overlay**：用浏览器/无头渲染出带 alpha 的片段，再合成；表达力强，依赖渲染环境。
  2. **纯 ffmpeg / drawtext / ass 特效**：无额外运行时，但复杂动画难写。
  3. **After Effects / Remotion / Motion Canvas 一类模板**：效果最好，流水线成本最高。
- 原则：默认关；只做白名单模板；不拖垮 Windows worker 稳定性和成片时长。
- 前置：P0#3 静音裁切、P1#5 效果 timeline 先站稳，再谈叠层动画。
- 涉及：成片阶段合成、模板资源目录、工作台预览（若做）。
- 验收：至少 1 个可开关模板（如标题弹入）能稳定叠在自动成片上，且不改内容边界。

#### 9. 切片流水线状态与审核 UI 可读性（Dashboard）
- 状态：**已交付（2026-09-20 代码 + 2026-09-21 规格/UX 收尾）**；规格见 `docs/compose/spec/slice-stage-boards.md` 与 `docs/compose/spec/slice-stage-status-ux.md`。
- 验证：`pytest -q` 674 passed；`compileall src tests` OK；studio `ng test` ChromeHeadless 44 SUCCESS；`ng build --configuration development` PASS。全套 `ng test` 仍有历史 settings/notification 注入失败（PRE-EXISTING，与本改动无关）。
- 背景（2026-09-20 实机反馈）：
  1. 阶段板场次徽标只显示「已排队」，progress 可能显示「等待 MiMo 返回」或残留「切片处理完成」，看不出在等谁、卡在哪；密度图有数据也不代表 Worker 已处理。
  2. progress 写「MiMo 返回 1 个可处理片段」时，本板场次仍是「0 候选」——Worker progress 与 task history 落盘有时差，segments 只在整场 `slice_only` 结束后写入，用户会以为结果丢了。
  3. AI 判断列表用「Q 0.85 C 0.9 conf 0.9」等缩写，用户不知道含义；详情区虽有中文，列表卡仍看不懂。
  4. 入点/出点显示裸秒数（如 `2484 - 2517` / 输入框 `2484`），无法对照播放器进度条；应显示 `HH:MM:SS`（或 `H:MM:SS`）。
  5. 已上传/已发布的片段仍挂在 04 样片板：卡片文案却是「成片生成中… / 等待生成可预览成片」，与真实状态不符。根因：`segmentStage` 对 keep 只看 `final_media_id` + `preview_available`，不看 `upload_status ∈ {published,...}`；`stageCountFromSummary(sample)` 用 `keep - awaiting_publish`，已发布仍算 keep、又不是 awaiting_publish，会继续计入样片板。上传成功后本地成片清理（architecture：publish 后删本地 final）会让 `final_media_id` 变空，片段永久滞留样片板。样片卡 thumb 还硬编码了「成片生成中…」。
- 目标：打开阶段板 / 判断板即可读懂在等什么、结果在哪、边界对应视频哪一段：
  1. 状态说明：Windows Worker 未领取 / Worker 预检失败 / 已送 MiMo 等返回 / 解析中 / 人工复核；Worker 不可用时任务保留在队列的原因。
  2. 进度对齐：progress 说「已返回 N 个」时，明确「尚未写入工作台」或直接展示已解析候选；history 落盘后自动刷新到 03/04 板。
  3. 指标文案：列表与详情统一用中文（质量分 / 完整度 / 置信度），不用 Q/C/conf 缩写。
  4. 时间码：候选区间、入点/出点输入框与密度图标注一律 `HH:MM:SS`；播放器当前时间可一键填入入/出点；内部存储仍用秒，只改展示与编辑交互。
  5. 阶段归属：`upload_status` 为 published / 已进上传完成的片段不得留在样片板；可进「已完成」类列表或从工作台阶段板移除。样片卡文案按真实状态切换（生成中 / 待预览 / 已发布 / 失败），禁止统一「成片生成中」。
- 涉及：
  - 状态源：`src/burn/slice_progress.py`、`src/burn/slice_only.py` progress.message、`src/dashboard/task_state.py`；
  - UI：`frontend/src/app/studio/studio-slices.component.*`（阶段徽标、progress 卡、判断列表 score-row、入出点 range-fields、密度图标签）；
  - 时间格式化可在前端做，不必改后端秒字段 schema。
  - 不改 Pi/Windows 边界与状态机。
- 验收：
  1. 用户无需对照代码/日志能说出「在等谁、下一步是什么」；
  2. Worker 不可用时场次卡片有明确原因，而不是只有「已排队」；
  3. 判断列表不出现未翻译缩写；
  4. 入出点显示为 `H:MM:SS`，与播放器进度条时间可直接对照。
  5. 已上传片段不再出现在 04 样片板；卡片状态与 upload/publish 一致，不再显示虚假的「成片生成中」。
- 2026-09-21 验收结论：阶段中文文案、`H:MM:SS`、published 离场样片板、指标中文已随 `83b7530` + status-ux 交付；S2.6「播放器取时填入入/出点」仍为可选未做。

#### 10. 阶段看板实机 UX 缺口（2026-09-20 夜 · 明天优先）
- 状态：**已交付（2026-09-21）**；规格 `docs/compose/spec/slice-stage-status-ux.md`。独立审查 0 critical；major M1（`summary_counts.subtitle_needs_burn` 与顶栏/场次清单脱节）已修复。
- 背景：#9 看板落地后当晚实机审核暴露界面语义/操作路径问题。流水线/Worker 本身正常。
- 问题清单与交付结果：
  1. **URL 选中失效** → 过期深链静默回落 `stageRecordings[0]`/`filtered[0]` 并纠正 URL；清单真空才红条。
  2. **提交样片没反应** → finalize toast「已入队生成样片…完成后进入字幕精修」；job 完成 `refresh()`；busy 不再静默 return。
  3. **字幕保存后视频不见了** → `subtitle_needs_burn` keep 留在字幕精修板；warning toast；主操作「重新烧录」；展示 `preview_reason`。
  4. **样片板按钮太多** → `samplePrimaryAction` 单主按钮；去掉重复「重新渲染」；「重新分析」次要。
  5. **不能排队吗** → per-card `segmentBusy`；多片段可 pending；toast「已排队，Windows Worker 按序处理」；顶栏显示排队数。
  6. **样片卡进度误导** → needs_burn 文案「字幕已保存，待重新烧录」，不用完成态进度条。
  7. **#9 收尾债** → 本 spec 已落盘；代码+文档待用户确认后 commit。
- 验收：
  1. 过期 `source_task_id` 打开爆点/样片板不再卡死红条，能落到当前板可用场次；
  2. 送交成片后有明确进度反馈；完成后列表/计数自动更新；
  3. 保存字幕后片段仍在字幕精修，一键「重新烧录」，不会「消失」；
  4. 样片/字幕板同一场景只有一个主操作，无「重试成片=重新渲染」重复项；`重新分析` 不会成为字幕待重烧时的主按钮；
  5. 对多个片段连续点重烧时，UI 表现为排队（可多条 pending），Worker 仍串行，不假装并行；
  6. 与 #9 一并完成规格、测试与提交（提交前再次确认）。
- 2026-09-21 验收结论：前端 spec 44 SUCCESS + pytest 674 passed；上述 1–5 已在代码与测试中落地。第 6 条「提交」待用户确认；是否重打包 `bilive.18`/更新 Pi 部署另议。不改 Worker 串行与 `.bilive-jobs` 语义。

## 明确不做 / 搁置

| 项 | 原因 |
|---|---|
| 多信号爆点召回（P0#1） | 只影响送 AI 的候选窗，不直接决定 keep；弹幕密度 + MiMo 已够，SC/礼物/音频扩召回不值得做 |
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
P0#2 ASR前置+字幕修正（已完成）→ P0#3 静音裁切
→ P1#9 + P1#10 阶段看板状态反馈 + 实机 UX 缺口（2026-09-21 已交付；commit 待确认）
→ P1#4 封面+大字 → P1#5 效果 timeline → P1#6 边界二次裁决（按需）
→ P1#7 系统性优化提示词（样本够用后再动）
→ P1#8 叠层动画（远期，HTML/渲染路线先做 spike）
```

每项做完在对应小节打勾并写一句验收结果，避免只堆未完成清单。
