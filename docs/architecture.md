# 架构

## 数据流

```text
Pi blrec
  -> Windows SMB Videos/*.flv
  -> blrec 转封装并保留 FLV
  -> 仪表盘创建 *.mp4.pending
  -> Pi SSH 调用 Windows localhost Worker API
  -> Windows 原子领取为 *.mp4.processing
  -> 弹幕突增切片
  -> faster-whisper ASR
  -> LM Studio keep/drop 判断
  -> 字幕烧录
  -> .upload.json
  -> SQLite upload_queue
  -> CDN 上传
  -> Web 投稿
```

## 故障边界

- SMB 失联：Pi wrapper 有限停止 blrec，恢复 timer 重新挂载并恢复两个服务。
- Worker 重复触发：PID 文件锁保证只有一个进程获得处理权。
- Worker 崩溃：无存活所有者的 `.processing` 在下次启动恢复为 `.pending`。
- LM Studio、ASR、数据库或输出目录不可用：Worker 不领取任务。
- ASR、LLM、字幕、元数据或入队失败：候选保留并标记 `failed`。
- CDN 已上传但投稿失败：队列保留 `remote_filename`，只重试投稿。

## 配置

生产配置只有 `bilive-server.toml`。路径优先使用环境变量：

- `BILIVE_CONFIG`
- `BILIVE_VIDEOS_DIR`
- `BILIVE_LOG_DIR`
- `BILIVE_DB_PATH`
- `BILIVE_COOKIE_FILE`
- `BILIVE_AUTO_UPLOAD`
