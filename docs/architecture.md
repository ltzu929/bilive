# 架构

## 运行边界

Bilive 分为 Pi 轻服务和 Windows 重任务：

- Pi：录制、切片页面、任务文件落盘、通过 SSH 触发 Windows。
- Windows Worker API：按需启动，空闲 15 分钟后退出。
- Windows watcher：一次性领取 pending 任务，完成后退出。
- MiMo：云端 `mimo-v2.5`，负责大范围候选视频全模态判断和 0..N 个聊天片段粗剪建议。
- Whisper：Windows 本地 `faster-whisper large-v3 CPU int8`，只在 MiMo keep 后运行。
- 上传消费者：由 Worker API 单实例管理，和切片 watcher 独立。

端口：

| 端口 | 进程 | 生命周期 |
|---|---|---|
| `2233` | Pi blrec | 常驻 |
| `2234` | Pi dashboard（由录播端同源代理） | 常驻 |
| `2235` | Windows Worker API | 按需存在，仅 localhost |

## 部署拓扑

同一份代码支持两种部署拓扑，区别只在运行时环境变量 `BILIVE_WINDOWS_SSH_TARGET`，不做编译打包或平台硬判断：

- 分布式（默认）：`BILIVE_WINDOWS_SSH_TARGET` 指向 Windows 主机。blrec 在 Pi 的 `bilive.service`，dashboard 通过 `ssh <target> curl.exe ...` 跨机触发 Windows Worker API。
- 单机 Windows：`BILIVE_WINDOWS_SSH_TARGET` 为空。blrec 由 `start_windows_recorder.ps1` 用 uvicorn 在本机 `.venv-recorder`（Python 3.10）拉起，dashboard 用本地 `curl.exe` 打 `127.0.0.1:2235`，全部端口收敛到同机 localhost。

`src/dashboard/remote_worker.py` 按 `BILIVE_WINDOWS_SSH_TARGET` 是否为空决定命令是否带 `ssh` 前缀，这是唯一的拓扑开关；worker、watcher、MiMo、上传等处理链路两种拓扑完全一致。

## 前端迁移边界

录播端 `2233` 直接提供上游 blrec 的原生 Angular/ng-zorro 外壳。切片、上传和
工作台设置的路由已经进入 Angular 菜单；页面迁移完成前，旧 dashboard 通过
`/studio-proxy/*` 同源代理到 `2234`，因此 API、媒体预览和相对资源仍保持原有
路径语义。代理只处理带该前缀或来自嵌入页面的请求，不改变录制端其他路由。

## 数据流

```text
Pi blrec -> SMB Videos/*.flv -> 转封装并保留 FLV
切片页面 -> *.mp4.pending 或 .bilive-jobs/*.pending.json
         -> SSH -> schtasks /Run -> Windows localhost:2235
Worker API -> 加载 .secrets/env -> 预检 MIMO_API_KEY、ASR 缓存、SQLite、Videos
watcher -> 原子领取 -> 弹幕密度候选范围
        -> 大范围候选 mp4 -> MiMo 聊天切片判断，可返回 0..N 个片段
        -> 本地质量闸门；低分、缺分或重复片段进入人工复核
        -> 达标片段先按源录像区间和主题文本跨候选去重
        -> 达标片段以单实例 ASR 流水线转写 trim 前后的小范围音频
        -> 每个片段单独 ffmpeg 粗剪+烧字幕
        -> .upload.json -> SQLite upload_queue
上传消费者 -> CDN 上传 -> Web 投稿
全部空闲 15 分钟 -> Worker API 退出 -> 2235 关闭
```

Dashboard 的 finalize/retry/render/reburn API 只验证输入、原子写任务并触发 worker，不导入重型处理模块。Windows worker 对任务执行 `pending -> processing -> done/failed`。崩溃后只恢复没有存活所有者的 processing 任务。

## Dashboard 工作台

Dashboard 提供桌面优先的三栏审核工作台，但不改变运行边界：

- `/api/source-recordings` 提供录播列表，前端按 `room_id/room_name` 分组为 `UP 主 -> 直播场次` 队列。
- `/api/source-recordings/{task_id}` 返回源录播、连续弹幕密度点、候选片段，以及兼容性附加的质量、失败、工件、耗时和动作状态。密度图只做导航和边界辅助，真正的裁剪仍由 Windows worker 执行。
- `POST /api/segments/{segment_id}/finalize` 是工作台的人工成片闸门：先保存轻量编辑，再创建 `finalize_segment` 动作任务。ASR、字幕、元数据和入队都在 Windows 完成。
- `manual-keep` 作为兼容接口保留；新工作台使用异步 finalize。drop/range 仍是轻量状态修改，retry/render/reburn 创建 Windows 动作任务。
- `/api/upload-dashboard` 和 `/api/slice-performance` 都是只读状态接口；数据库或表不存在时返回 unavailable，不创建 SQLite 文件、不迁移 schema。
- `/uploads` 保留完整投稿队列；任务详情、发布表现和技术诊断在 `/tasks` 中作为次级折叠面板呈现。

## Eagle 原始录播镜像

Pi dashboard 额外提供 `/api/eagle/source-recordings`，这是给 Eagle 插件使用的只读索引接口。它复用 `/api/source-recordings` 的任务库存和片段统计，只把字段整理为 Eagle 同步需要的 `source_task_id`、`source_rel_path`、房间、录制时间、状态、审核计数和 `/tasks?source_task_id=...` 跳转链接。

Eagle 插件不扫描 `Videos/`，不写 bilive 任务文件，也不复制原始视频。同步时它查询当前 bilive 清单和 Eagle 中已有的 `bilive`、`原始录播` 卡片，按 `source_task_id` 做增量镜像：新增当前录播、更新仍存在录播、把已不存在源文件的旧卡片移入 Eagle 废纸篓。

## 模型边界

`src/autoslice/mllm_sdk/mimo_video.py` 是生产判断适配器：

1. 为候选片段生成临时 720p H.264/AAC 分析副本。
2. Base64 传入 `mimo-v2.5`，不依赖公网文件服务。
3. 请求使用 `fps=1`、`media_resolution=default`、`thinking.type=disabled`。
4. 强制 JSON 输出 `clips` 数组；每个元素包含保留决策、聊天片段类型、标题、简介、标签、质量分、完整度、置信度和 `trim_start/trim_end`。
5. 本地同时检查质量分、完整度和置信度；任一缺失或低于阈值都不自动入队。
6. MiMo 异常、非法 JSON、超限视频或非法 trim 都返回 `judge_failed`，候选保留人工复核。

候选分析采用分阶段并发：分析副本编码使用低并发，MiMo HTTP 请求独立并发；完成本地质量闸门和跨候选去重后，合格结果即可进入单实例 ASR，不需要等待无关候选。ASR 继续使用 `large-v3 CPU int8`，只转写 trim 前后的小范围音频，并复用同一次转录完成段级时间戳边界吸附和字幕生成。

旧本地模型运行时代码仍保留在 `src/autoslice/mllm_sdk/managed_runtime.py`，仅作为手动回滚能力；生产 watcher 和预检不再启动或要求本地模型文件。

## 存储与数据库

- 录像和动作任务位于 `Videos/`，不写 Pi SD 卡。
- MiMo 分析副本位于临时目录，请求成功或失败后清理。
- 上传数据库 schema 由进程启动时迁移，版本记录在 `PRAGMA user_version`。
- 只读状态接口使用 SQLite 只读连接，不建表、不迁移、不执行全表修复。
- 上传队列保持 `video_path` 唯一约束。
- 已完成 CDN 上传的投稿重试保留并复用 `remote_filename`。

## 故障边界

- Windows 夜间关机：SMB 暂时不可用；恢复 timer 在 Windows 上线后重置挂载并恢复录制和仪表盘。
- 重复触发：进程锁和任务去重保证单实例执行。
- Worker 崩溃：失去所有者的 processing 任务下次恢复。
- Worker 空闲：页面状态轮询不续命；待处理、切片、MiMo 请求或上传存在时禁止退出。
- `MIMO_API_KEY` 缺失：预检拒绝启动 watcher，pending 保留；推荐写入 `.secrets/env`，进程环境可覆盖。
- MiMo 请求失败或输出无效：候选保留人工复核。
- MiMo 分数不足或跨候选重复：候选标记为待复核，不执行自动 ASR/渲染/入队。
- Whisper、字幕、元数据或入队失败：候选和失败原因保留。
- 最终成片失败：原始候选、分析 sidecar 和目标输出路径分开记录，重试不需要重新调用 MiMo。
- CDN 已上传但投稿失败：只重试投稿，不重新上传媒体。

## 配置

生产配置基线为 `bilive-server.toml`。机器相关值使用环境变量：

- `MIMO_API_KEY`（推荐 `.secrets/env`，进程环境可覆盖）
- `BILIVE_WINDOWS_SSH_TARGET`
- `BILIVE_CONFIG`
- `BILIVE_VIDEOS_DIR`
- `BILIVE_LOG_DIR`
- `BILIVE_DB_PATH`
- `BILIVE_COOKIE_FILE`
- `BILIVE_AUTO_UPLOAD`
- `BILIVE_WORKER_IDLE_TIMEOUT`
- `BILIVE_WORKER_IDLE_CHECK_INTERVAL`
- `BILIVE_DASHBOARD_ALLOWED_HOSTS`
