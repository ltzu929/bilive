# 架构

## 数据流

```text
Pi blrec -> SMB Videos/*.flv -> 转封装并保留 FLV
仪表盘 -> *.mp4.pending 或 .bilive-jobs/*.pending.json
       -> SSH 调用 Windows localhost:2235
Windows worker -> 原子领取 -> 切片 -> ASR -> LLM -> 字幕
               -> .upload.json -> SQLite upload_queue
               -> CDN 上传 -> Web 投稿
```

Pi 的 retry/render API 只验证输入、原子写任务并触发 worker，不导入重型处理
模块。Windows worker 对任务执行 `pending -> processing -> done/failed`，
崩溃后只恢复没有存活所有者的 processing 任务。

`manual-keep` 是轻量操作，只更新片段元数据和上传队列。

## 存储与数据库

- 录像和动作任务位于 `Videos/`，不写 Pi SD 卡。
- 上传数据库 schema 由进程启动时迁移，版本记录在 `PRAGMA user_version`。
- 只读状态接口使用 SQLite 只读连接，不建表、不迁移、不执行全表修复。
- 上传队列保持 `video_path` 唯一约束。
- 已完成 CDN 上传的投稿重试保留并复用 `remote_filename`。

## 故障边界

- Windows 夜间关机：SMB 暂时不可用，Pi 有限停止服务；恢复 timer 在 Windows
  上线后重置挂载并恢复录制和仪表盘。
- 重复触发：进程锁和任务去重保证单实例执行。
- Worker 崩溃：失去所有者的 processing 任务下次恢复。
- ASR、LLM、字幕、元数据或入队失败：候选和失败原因保留。
- CDN 已上传但投稿失败：只重试投稿，不重新上传媒体。

## 配置

生产配置基线为 `bilive-server.toml`，机器相关值使用环境变量：

- `BILIVE_WINDOWS_SSH_TARGET`
- `BILIVE_LM_STUDIO_PATH`
- `BILIVE_CONFIG`
- `BILIVE_VIDEOS_DIR`
- `BILIVE_LOG_DIR`
- `BILIVE_DB_PATH`
- `BILIVE_COOKIE_FILE`
- `BILIVE_AUTO_UPLOAD`
- `BILIVE_DASHBOARD_ALLOWED_HOSTS`
