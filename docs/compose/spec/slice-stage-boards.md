---
feature: slice-stage-boards
status: delivered
updated: 2026-09-18
branch: main
commits: uncommitted-on-main-8ce9960
---

# 切片阶段看板界面

## Report

**What was built** — `/studio/slices` 改为五段阶段看板：录播（全量库存）→ 筛选爆点 → AI判断 → 样片 → 字幕精修。处理语义不变，片段阶段由既有 `judge_status` / `upload_status` / `action_state` / `final_media_id` 推导；可预览成片自动进入末板。末板提供字幕精修与上传闸门：确认上传复用 `approve-publish`，暂不上传不入队。全部动作继续走现有 `StudioApiService` 与 segment action，无平行流水线。独立审查无 critical；已按审查修复样片进度来源、阶段外选中回退、唤醒 Worker 与状态筛选项。

**Verification** — `slice-stage` 纯函数断言 PASS；`pytest -q` 673 passed / 1 deselected；`tests/test_native_ui_contract.py` 11 passed；`ng build --configuration development` PASS；`ng test` studio specs ChromeHeadless 34 SUCCESS。

**Journey log**
- 用户先要求 HTML 预览定稿阶段专属布局，再进入实现；worktree 因会话隔离被拦，用户改为在 main 实现。
- 复用优先：阶段只是前端视图推导，未新增后端状态机或任务队列。
- native UI 契约测试原先绑定旧三栏 `trackBy`/wheel 字符串；改为断言阶段导航 + trackBy + wakeWorker + approvePublish。
- 列表 API 无 `history_status`，爆点板列表级计数以 recording `status` 近似；详情打开后仍按精确阶段过滤。
- 样片板进度必须读 `segment.action_state.progress`，不能复用全局 `subtitleJobProgress*`。

## [S1] Problem

`/studio/slices` 现在是固定三栏审核台：录播队列 / 预览 / 检查器。流水线在后端已自动推进
（弹幕密度 → MiMo → 成片 → upload staged），但页面没有阶段视角，用户要自己脑补
「这条现在在哪一步、该做什么」。关键动作（生成成片、允许发布）埋在检查器底部；字幕
列表与上下文拆在两侧；五个心智阶段没有对应界面。

## [S2] Design

### 产品决策（已确认）

1. 顶部五段导航：**录播 → 筛选爆点 → AI判断 → 样片 → 字幕精修**。
2. 处理语义不变：自动链路继续推进；**仅末板（字幕精修）由用户决定是否上传**。
3. 录播板 = 全量源场次库存；后四段 = 按片段/场次现有状态推导的阶段视图。
4. 中间板是导航库存 + 可进入既有工作能力；review / judge_failed / 失败留在对应板并标「需人工」，不阻塞自动 keep。
5. 成片可预览后**自动进入字幕精修板**；样片板偏生产进度/失败恢复。
6. 每阶段使用**专属布局**，不是在旧三栏上简单加 Tab。
7. 实现必须**复用现有工具**，不新建平行流水线、不重写上传/切片语义。

### 复用边界（强制）

| 复用 | 说明 |
|---|---|
| `StudioApiService` | 继续用 `getSourceRecordings` / `getSourceRecording` / `segmentAction` / `startSlice` / `getMediaUrl` / `getReviewStatus` / `createMissedSegment` / `completeSourceReview` / worker 接口 |
| 片段动作 | `range` / `drop` / `finalize` / `subtitles` / `reburn` / `subtitle-style` / `retry-judge` / `render` / `approve-publish` 语义不变 |
| 状态字段 | 阶段归属只从 `judge_status` / `upload_status` / `action_state` / `final_media_id` / `preview_available` / recording `status` / `summary_counts` **推导**，不新增状态机 |
| UI 组件 | 继续用 ng-zorro（button/tag/card/select/progress/alert/empty/spin/table…）与既有草稿/快捷键/字幕校对逻辑 |
| 后端 | 默认**不改**处理链路、任务文件、upload_queue。只读展示可复用现有 list/detail API |

禁止：新建第二套切片任务队列、在 Dashboard 内直接执行重处理、为看板发明新的 judge/upload 状态值。

### 阶段推导（前端纯函数）

放在 `frontend/src/app/studio/slice-stage.ts`，可单测。

**片段当前阶段 `segmentStage(segment)`**

优先级从上到下：

1. `judge_status === 'drop'` → `null`（不进入活跃阶段板）
2. `judge_status` 为 `keep` / `manual_keep`：
   - `action_state.status ∈ {pending,processing,running,blocked}` 且动作不是 `approve_publish` → `sample`
   - `failure` 存在或 `upload_status === 'failed'` → `sample`（生产失败留在样片板）
   - 已有 `final_media_id` 且（`preview_available` 未显式 false）→ `subtitle`
   - 否则（keep 但尚无 final）→ `sample`
3. 其他（`review` / `judge_failed` / 空/未知）→ `judge`

**场次是否属于筛选爆点板 `recordingInBurst(recording)`**

`status` 为 `pending` / `processing` / `running`，或 `history_status` 为 `pending` / `processing`，
或 `status === 'failed'` 且仍可能需要密度/候选侧人工介入。

**阶段计数（顶栏徽章）**

- `recordings`：`recordings.length`
- `burst`：满足 `recordingInBurst` 的场次数
- `judge`：各场 `summary_counts.review + judge_failed` 之和（列表级近似；打开详情后以 `segmentStage` 过滤）
- `sample`：`keep + manual_keep` 减去已可进入 subtitle 的近似项时，列表级用 `keep+manual_keep - awaiting_publish`，且 `>= 0`
- `subtitle`：`summary_counts.awaiting_publish` 之和

列表 API 不含逐条 `final_media_id` 时，顶栏计数允许为导航近似；**详情打开后的板内列表必须用 `segmentStage` 精确过滤**。

### 页面骨架

单一路由 `/studio/slices`，组件仍是 `StudioSlicesComponent`（避免平行页面/双维护）。

```text
顶栏：品牌 | 五段 Tab（计数） | Worker | 刷新/启动/停止
stage-hint：当前阶段一句话说明
stage-root：按 activeStage 切换专属布局
```

各板布局（与预览稿一致）：

1. **录播**：指标条 + 筛选列表 + 场次表 + 右侧生命周期/启动切片。动作复用 `startSlice` / `startSelectedSlice` / `completeReview` / `trashSourceRecording`。
2. **筛选爆点**：左侧阶段场次队列 + 右侧密度大图（复用既有 density path/segment overlay）+ 候选窗说明 + 扫描进度（来自 `progress` / `history_status`）。补标漏切与失败重试入口复用现有表单动作。
3. **AI判断**：左侧 `segmentStage===judge` 的候选卡（标签/分数/需人工）+ 右侧源预览 + AI 结论 + 人工动作（丢弃/边界/重新分析/送交成片）全部调用既有 `runSegmentAction` / `finalizeSegment`。
4. **样片**：卡片墙展示 `segmentStage===sample`（进度来自 `action_state.progress`；失败显示 `failure`）。可预览后不再停在本板。
5. **字幕精修**：左侧 subtitle 阶段队列 + 中间成片预览 + 右侧字幕编辑（复用草稿/校验/保存/reburn）+ **上传闸门**（`暂不上传`=无操作仅提示；`确认上传`= `approvePublish()`）。

点击阶段列表条目：选中 `task_id`（及可选 `segment_id`），按需 `getSourceRecording` 加载详情（现有行为）。URL 查询参数 `stage` / `source_task_id` / `segment_id` 可恢复视图。

### 错误与空态

- Worker 不可用：顶栏 badge 仍显示，可 `wakeWorker`。
- 某阶段无条目：`nz-empty` 文案说明下一步（例如字幕板空 = 暂无待确认成片）。
- 列表加载失败：保留 `error` alert，不伪造数据。

### 测试边界

- 前端：`slice-stage.spec.ts` 覆盖阶段推导与计数；`studio-slices.component.spec.ts` 保留既有行为，并补：阶段切换、字幕板确认上传调用 `approve-publish`、drop 不进入阶段列表。
- 后端：无 schema/状态机变更则仍跑全量 pytest 作回归；不为看板添加新的写路径测试。

## [S3] Out of Scope

- 不改 MiMo / ffmpeg / 上传消费者 / `.bilive-jobs` 语义
- 不新增人工阶段闸门（爆点/AI/样片不强制点通过才自动继续）
- 不做多信号爆点召回、静音裁切、封面贴字等 TODO 项
- 不重写 Eagle 插件、uploads 页、settings 页
- 不在本功能中引入自动上传开关变更（默认仍不自动发布）
- 样片板不做「长期双板可见」库存（预览已确认：可预览即进字幕板）

## Tasks

- [x] T1: 新增 `slice-stage.ts` 阶段推导与计数纯函数 — acceptance: 单测覆盖 drop 排除、keep→sample/subtitle、review→judge、burst 场次判定与四段计数 (covers: S2)
- [x] T2: 切片页顶栏阶段导航与 `activeStage` 状态 — acceptance: 五段可切换，hint/计数展示，刷新后按 URL `stage` 恢复 (covers: S2)
- [x] T3: 录播板专属布局 — acceptance: 全量场次可筛选/选中，启动切片与生命周期动作仍走既有 API (covers: S2)
- [x] T4: 筛选爆点板 — acceptance: 展示 burst 场次与密度图/候选信息，复用 density 计算与 progress，不出现上传控件 (covers: S2)
- [x] T5: AI判断板 — acceptance: 仅列表 `segmentStage=judge`，需人工标记可见，丢弃/边界/重分析/finalize 调用既有 segmentAction (covers: S2; depends: T1)
- [x] T6: 样片板 — acceptance: 列表 `segmentStage=sample`，显示进度/失败，成功可预览后不再停留 (covers: S2; depends: T1)
- [x] T7: 字幕精修板 + 上传闸门 — acceptance: 列表 `segmentStage=subtitle`，字幕保存/reburn 复用现有逻辑，确认上传触发 `approve-publish`，暂不上传不写队列 (covers: S2; depends: T1)
- [x] T8: 更新组件测试并保持既有用例通过 — acceptance: studio specs 34 SUCCESS；pytest 673 passed (covers: S2)
