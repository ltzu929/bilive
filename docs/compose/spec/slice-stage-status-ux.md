---
feature: slice-stage-status-ux
status: delivered
updated: 2026-09-21
branch: main
commits: 83b7530c45583d2e316bdca477df79f1db229d23..2c3b43b45661c383eacdc76478b14e98c732f637
---

# 阶段看板实机 UX（P1#10 + #9 规格收尾）

## Report

**What was built** — 阶段看板实机 UX：过期深链静默回落到当前板首项并纠正 URL；`segmentStage` 在 keep 且 `subtitle_needs_burn` 时留在字幕精修板，主操作「重新烧录」；样片板按场景给出单一主按钮（失败重试 `render` / 待重烧 `reburn` / 待生成 `render`），`重新分析` 降为次要；busy 改为 per-segment，多片段可排队且 toast 说明 Worker 串行，不再静默拒绝；finalize/reburn/字幕保存有明确反馈；列表级 `summary_counts.subtitle_needs_burn` 与顶栏/场次清单计数对齐。本文档同时补齐 #9 阶段看板之后的 UX 规格债；处理语义、`.bilive-jobs`、Pi/Windows 边界未改。

**Verification** — `pytest -q` 674 passed / 1 deselected；`compileall src tests` OK；`tests/test_native_ui_contract.py` + `test_source_workbench.py` 57 passed；`ng test` slice-stage + studio-slices ChromeHeadless **44 SUCCESS**；`ng build --configuration development` PASS。独立审查 AC1–6 全部 met，0 critical；审查 major M1（计数/场次清单与 needs_burn 脱节）已修复并复测。

**Journey log**
- #9 代码已在 `83b7530` 提交，本次先落 `docs/compose/spec/slice-stage-status-ux.md` 再改实现，对应 TODO #10 第 7 条收尾债。
- 字幕保存后片段「消失」根因是前端阶段归属，不是数据丢失；后端 `subtitle_needs_burn` / `preview_reason` 已存在，只补前端消费与计数。
- 顶栏徽章不能只靠 `awaiting_publish`；列表 API 需新增 `subtitle_needs_burn` summary 键，否则 board membership 与 inventory 再次脱节。
- `segmentBusy`（本地∪服务端）与 `segmentActionBusy`（纯函数，仅 action_state）职责不同，不要合并。
- 实现落在 main（用户确认）；实现提交 `2c3b43b`；部署/wheel 重打包未做。

## [S1] Problem

阶段看板（#9，已提交 `83b7530`）在实机审核中暴露六类语义/操作缺口：过期深链红条卡死；「送交生成样片」后像没反应；字幕保存后片段从字幕精修板「消失」；样片卡按钮过多且重复；`selectedActionBusy` 让一个片段 busy 锁住整板，无法表达「多条可排队、Worker 串行」；旧 job 100% 进度与「字幕待重烧」真实状态不符。后端流水线与 `.bilive-jobs` 语义本身正确，问题集中在前端阶段归属、busy 模型与操作反馈。#9 的阶段看板设计已交付于 `docs/compose/spec/slice-stage-boards.md`，但本 UX 缺口尚无规格文档。

## [S2] Design

### 复用边界（强制）

| 复用 | 说明 |
|---|---|
| 状态源 | 只从现有 segment 字段推导 UI：`judge_status` / `upload_status` / `action_state` / `final_media_id` / `preview_available` / `preview_reason` / `subtitle_needs_burn` / `failure` |
| 后端 API | 继续 `segmentAction` / `getJob` / `getSourceRecording` / `getSourceRecordings`；列表 summary 增加只读计数键 `subtitle_needs_burn` |
| Worker 语义 | `.bilive-jobs` 按 segment 查重、Worker 串行领取保持不变；UI 如实反映排队而非假装并行 |
| 动作集 | `render` / `reburn` / `retry-judge` / `finalize` / `subtitles` / `approve-publish` 语义不变 |
| 文档债 | 本文档即 #9 收尾规格；不另建计划文件 |

禁止：改 Pi/Windows 边界、`.bilive-jobs` 状态机、上传队列、Dashboard 内直接重处理。

### [S2.1] 阶段归属：字幕待重烧留在字幕精修

`segmentStage`（`frontend/src/app/studio/slice-stage.ts`）在 `isKeep` 且无 `hasFailure` 时，**在 published / 上传中路由之后、active action / final 路由之前**增加：

```
if (subtitle_needs_burn === true) return 'subtitle';
```

效果：

- 字幕保存或样式修改后：`preview_available=false`、`final_media_id` 可能为空、`upload_status=not_queued`、`subtitle_needs_burn=true` → **留在字幕精修板**，不落入样片板。
- `upload_status === 'published'` 仍优先返回 `null`（已发布不进工作台板）。
- `upload_status ∈ {queued,uploading,uploaded,publishing}` 且无 needs_burn 时保持现有逻辑（可预览→subtitle，否则离场）。
- 失败（`failure` 或 `upload_status==='failed'`）仍优先 `sample`。

类型补充：`StageSegmentLike` 与 `StudioSegment` 增加 `subtitle_needs_burn?: boolean`、`preview_available?: boolean`、`preview_reason?: string`（后端 `_normalize_segments` / 作废路径已写入这些字段，前端仅补齐类型与消费）。

**计数对齐（审查 M1）**：列表级 `summary_counts.subtitle_needs_burn` 由后端 `_summary_counts` 统计（keep/manual_keep、无 failure、非 published 且 `subtitle_needs_burn`）。前端顶栏：`subtitle = awaiting_publish + subtitle_needs_burn`；`sampleOutstandingCount` 从 keep 中再减去 `subtitle_needs_burn`；`stageRecordings` 字幕板过滤条件同步。避免保存字幕后徽章/场次清单与板内列表不一致。

### [S2.2] 过期深链回落

`refresh()` 中 `selectedTaskId` 不在 `recordings` 时：

1. 回落候选顺序：`stageRecordings[0]?.task_id` → `filteredRecordings[0]?.task_id`。
2. 找到候选 → 静默 `selectedTaskId = 候选`、清空 `selectedSegmentId`，**不设置** error 红条；用 `history.replaceState` 将 URL 的 `stage`/`source_task_id`/`segment_id` 纠正到当前有效选中。
3. 回落候选也为空 → 红条「当前阶段暂无可用场次，请切换阶段或刷新清单」。
4. 回落选中后按现有路径 `loadDetail(selectedTaskId)`。

不在 `refresh` 中改阶段推导，不新增后端查找。

### [S2.3] Busy 模型：按片段排队，Worker 仍串行

**`segmentBusy(segment)`**

- `true` 当且仅当：`busySegments.has(segment_id)` 或 `action_state.status ∈ {pending, processing, running, blocked}`。
- **不含** `detailLoading` / `draftConflict` / `subtitleRefreshPending` / 选中片段的编辑锁（那些仍属于检查器 `selectedActionBusy`，只约束当前选中片段的表单型操作）。

**样片卡 / 字幕队列卡按钮**

- `[disabled]="segmentBusy(segment)"`，不再使用 `selectedActionBusy`。
- 顶栏或样片板显示当前详情内 busy 片段数（不新增 API）。

**`runSegmentAction`**

- 仅按目标 `segmentId` 的 per-segment busy 拦截：
  - 目标片段 busy → toast：`该片段已有任务在排队或处理中`，**不再静默 return**。
  - 目标片段空闲但本详情已有其他 busy 片段 → 允许提交；toast：`已排队，Windows Worker 按序处理`。
- 动作提交成功且返回 `job_id` 时的反馈（按动作）：
  - `finalize`：`已入队生成样片，Worker 处理中（约数分钟）；完成后进入字幕精修`。
  - `reburn` / `render`：`已入队重新生成成片，Worker 按序处理`（有其他 busy 时强调排队）。
  - Worker 不可达：warning「任务已入队，但 Worker 尚未接管；任务会保留在队列」。
- `job` 完成/失败：沿用 `finishAction` → `refresh()`。
- 检查器内与草稿绑定的操作继续使用 `selectedActionBusy` / 草稿校验。

### [S2.4] 样片板场景化主按钮

`samplePrimaryAction(segment)` 纯函数，优先级：

| 条件 | 主按钮 | 调用 | 说明 |
|---|---|---|---|
| `failure` 或 `upload_status==='failed'` | 重试成片 | `render` | 生产失败恢复 |
| `segmentBusy(segment)` | 处理中（disabled） | — | 显示 `segmentJobMessage` |
| `subtitle_needs_burn` | 重新烧录成片 | `reburn` | 与 #10.3 对齐 |
| 已可预览 | 去字幕精修 | 切板 | 不应常驻样片板 |
| 其他 | 生成成片 | `render` | 尚未可预览 |

规则：

- **同一场景只有一个主按钮**；`重试成片` 与 `重新渲染` 视为同一路径，不同时出现。
- `重新分析`（`retry-judge`）降为次要操作，**不得**在 `subtitle_needs_burn` 时作为主按钮。
- 「去字幕精修板」仅当该片段已可预览时出现。
- 样片卡 thumb/进度文案：`subtitle_needs_burn` → `字幕已保存，待重新烧录`；不用完成态 100% 进度条；生产中保留 action 进度；失败 → 异常态。
- 侧栏操作区与卡片主按钮同构，删除重复的「重新渲染」字样。

### [S2.5] 字幕精修板操作路径

- 列表过滤依赖 [S2.1]；保存后刷新不再把 needs_burn 片段甩进样片板。
- 选中 needs_burn 片段时主操作为「重新烧录」；展示 `preview_reason`（或默认「字幕已修改，请重新生成最终成片」）。
- 字幕保存成功 toast 使用 warning 样式：`字幕已保存，片段仍在字幕精修；请点「重新烧录」生成成片`。保存本身不切换 `activeStage`。
- 上传闸门逻辑不变；`canApprovePublish` 仍要求 `final_media_id` 与 `upload_status==='awaiting_publish'`。

### [S2.6] 可选：播放器时间填入入/出点

判断板入/出点输入框旁提供「取播放器当前时间」小按钮。**本期未实现**（可选项，不阻塞 #10 验收）。

### 测试边界

- `slice-stage.spec.ts`：needs_burn 阶段路由、`samplePrimaryAction` 分支、`subtitle_needs_burn` 计数。
- `studio-slices.component.spec.ts`：深链回落、per-card busy、非静默排队 toast、字幕板 needs_burn 文案、finalize 反馈。
- 后端：`test_source_workbench.py` 覆盖 `summary_counts.subtitle_needs_burn`；全量 pytest 回归。
- 已知 PRE-EXISTING：`ng test` 全量中 settings/notification 注入失败与本改动无关。

## [S3] Out of Scope

- P0#3 静音裁切、P1#4 封面贴字、P1#5 效果 timeline、P1#6 边界二次裁决、P1#7 prompt 系统整理、P1#8 叠层动画
- 多信号爆点召回（已取消）
- 改变 Worker 串行领取、上传队列唯一约束、CDN `remote_filename` 复用
- 新增后端 stage 枚举或 action 任务类型
- 修复 settings/notification 历史测试失败
- S2.6 播放器取时按钮
- 重打包 wheel / 部署到 Pi（完成后单独确认）

## Tasks

- [x] T1: 规格落盘 `docs/compose/spec/slice-stage-status-ux.md` — acceptance: status=designed，S2 契约可测，无 TBD (covers: S2)
- [x] T2: `slice-stage.ts` 阶段归属与样片主按钮纯函数 — acceptance: needs_burn→subtitle 单测通过；samplePrimaryAction 分支有单测 (covers: S2.1, S2.4)
- [x] T3: 深链过期静默回落 — acceptance: 组件 spec 中过期 id 回落到 stage 首项且无红条；真空才报错 (covers: S2.2)
- [x] T4: per-card busy 与动作反馈 — acceptance: A busy 不挡 B 排队；runSegmentAction 非静默；finalize/排队 toast 文案可断言 (covers: S2.3)
- [x] T5: 样片/字幕板 UI 对齐 — acceptance: 单主按钮无重复渲染项；needs_burn 进度文案正确；字幕保存后仍可见且可一键重烧 (covers: S2.4, S2.5)
- [x] T6: 类型与验证 — acceptance: StudioSegment 补字段；`pytest -q`、`compileall src tests`、studio `ng test`、`ng build --configuration development` 结果记入 Report (covers: S2)
- [x] T7: 独立审查 — acceptance: 非实现者 subagent 按本文验收项给出 compliance/correctness/consistency 结论；critical 清零 (covers: S2)
- [x] T8: Finalize 文档 + TODO.md 勾选 — acceptance: status=delivered、Report 填写；TODO #9/#10 写验收一句；提交前用户确认 (covers: S2)
