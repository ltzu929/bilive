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
| `2234` | Pi dashboard | 常驻 |
| `2235` | Windows Worker API | 按需存在，仅 localhost |

## 数据流

```text
Pi blrec -> SMB Videos/*.flv -> 转封装并保留 FLV
切片页面 -> *.mp4.pending 或 .bilive-jobs/*.pending.json
         -> SSH -> schtasks /Run -> Windows localhost:2235
Worker API -> 加载 .secrets/env -> 预检 MIMO_API_KEY、ASR 缓存、SQLite、Videos
watcher -> 原子领取 -> 弹幕密度候选范围
        -> 大范围候选 mp4 -> MiMo 聊天切片判断，可返回 0..N 个片段
        -> 无达标片段跳过自动投稿；明确 drop 删除候选
        -> 每个 keep 片段校验 trim -> Whisper 仅转写该 trim 音频
        -> 每个片段单独 ffmpeg 粗剪+烧字幕
        -> .upload.json -> SQLite upload_queue
上传消费者 -> CDN 上传 -> Web 投稿
全部空闲 15 分钟 -> Worker API 退出 -> 2235 关闭
```

Pi 的 retry/render API 只验证输入、原子写任务并触发 worker，不导入重型处理模块。Windows worker 对任务执行 `pending -> processing -> done/failed`。崩溃后只恢复没有存活所有者的 processing 任务。

## 模型边界

`src/autoslice/mllm_sdk/mimo_video.py` 是生产判断适配器：

1. 为候选片段生成临时 720p H.264/AAC 分析副本。
2. Base64 传入 `mimo-v2.5`，不依赖公网文件服务。
3. 请求使用 `fps=1`、`media_resolution=default`、`thinking.type=disabled`。
4. 强制 JSON 输出 `clips` 数组；每个元素包含保留决策、聊天片段类型、标题、简介、标签、质量分、完整度、置信度和 `trim_start/trim_end`。
5. MiMo 异常、非法 JSON、超限视频或非法 trim 都返回 `judge_failed`，候选保留人工复核。

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
- Whisper、字幕、元数据或入队失败：候选和失败原因保留。
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
