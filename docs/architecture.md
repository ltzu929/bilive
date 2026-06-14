# 架构

## 运行边界

Bilive 明确分为 Pi 轻服务和 Windows 重任务两侧：

- Pi：录制、切片页面、任务文件落盘、通过 SSH 触发 Windows。
- Windows Worker API：由切片页面或任务按需启动，空闲 15 分钟后退出。
- Windows watcher：一次性数据面，领取整批任务并在结束后退出。
- 托管 llama.cpp：watcher 首次需要判断时启动，整批复用，最终卸载。
- 上传消费者：由 Worker API 单实例管理，与切片 watcher 独立。

端口：

| 端口 | 进程 | 生命周期 |
|---|---|---|
| `2233` | Pi blrec | 常驻 |
| `2234` | Pi dashboard | 常驻 |
| `2235` | Windows Worker API | 按需存在，仅 localhost |
| `2236` | Windows `llama-server` | 按整批切片临时存在，仅 localhost |

## 数据流

```text
Pi blrec -> SMB Videos/*.flv -> 转封装并保留 FLV
切片页面 -> *.mp4.pending 或 .bilive-jobs/*.pending.json
         -> SSH -> schtasks /Run -> Windows localhost:2235
Worker API -> 预检 -> 启动 watcher --once
watcher -> 原子领取 -> 切片 -> ASR
        -> 首次 LLM 判断时启动 llama-server:2236
        -> 同批判断复用模型 -> 字幕烧录
        -> .upload.json -> SQLite upload_queue
        -> finally 停止 llama-server -> watcher 退出
上传消费者 -> CDN 上传 -> Web 投稿
任务全部空闲 15 分钟 -> Worker API 优雅退出 -> 2235 关闭
```

Pi 的 retry/render API 只验证输入、原子写任务并触发 worker，不导入重型处理
模块。Windows worker 对任务执行 `pending -> processing -> done/failed`。
崩溃后只恢复没有存活所有者的 processing 任务。

`manual-keep` 是轻量操作，只更新片段元数据和上传队列。

## 模型所有权

`src/autoslice/mllm_sdk/managed_runtime.py` 是唯一模型进程所有者：

1. 校验固定运行时和 GGUF 文件。
2. 拒绝复用或结束未知的 `2236` 监听者。
3. 启动项目内 `llama-server.exe`。
4. 轮询 `/health`，成功后才向 judge 返回 `/v1` 地址。
5. 在批次正常结束、异常或超时后，只终止自己创建的进程。

`src/server/watcher.py` 持有批次上下文。上下文是惰性的，因此只有
`render_segment` 的批次不会启动模型。Worker API 通过端口和健康状态观察
watcher 子进程中的模型，但不会接管其所有权。

默认模型：

```text
E:\AImodel\lmstudio-community\Qwen3.5-9B-GGUF\Qwen3.5-9B-Q4_K_M.gguf
```

默认运行时：

```text
.runtime\llama.cpp\b9616\llama-server.exe
```

详细参数见 [模型运行时](model-runtime.md)。

## 存储与数据库

- 录像和动作任务位于 `Videos/`，不写 Pi SD 卡。
- llama.cpp 二进制位于 `.runtime/`，被 Git 忽略。
- 模型位于 Windows 本地 `E:\AImodel\`，不会复制进项目或 SMB。
- 运行日志位于 `logs/runtime/llama-server.log`。
- 上传数据库 schema 由进程启动时迁移，版本记录在 `PRAGMA user_version`。
- 只读状态接口使用 SQLite 只读连接，不建表、不迁移、不执行全表修复。
- 上传队列保持 `video_path` 唯一约束。
- 已完成 CDN 上传的投稿重试保留并复用 `remote_filename`。

## 故障边界

- Windows 夜间关机：SMB 暂时不可用；恢复 timer 在 Windows 上线后重置挂载
  并恢复录制和仪表盘。
- 重复触发：进程锁和任务去重保证单实例执行。
- Worker 崩溃：失去所有者的 processing 任务下次恢复。
- Worker 空闲：页面状态轮询不续命；待处理、切片、模型或上传存在时禁止退出。
- 模型或运行时缺失：预检拒绝启动 watcher，pending 保留。
- `2236` 被占用：不结束未知进程，批次 fail-closed。
- 模型加载超时或异常退出：候选和失败原因保留，owned 进程被清理。
- ASR、LLM、字幕、元数据或入队失败：候选和失败原因保留。
- CDN 已上传但投稿失败：只重试投稿，不重新上传媒体。

## 配置

生产配置基线为 `bilive-server.toml`。机器相关值使用环境变量：

- `BILIVE_WINDOWS_SSH_TARGET`
- `BILIVE_LLM_MODEL_PATH`
- `BILIVE_LLAMA_SERVER_PATH`
- `BILIVE_CONFIG`
- `BILIVE_VIDEOS_DIR`
- `BILIVE_LOG_DIR`
- `BILIVE_DB_PATH`
- `BILIVE_COOKIE_FILE`
- `BILIVE_AUTO_UPLOAD`
- `BILIVE_WORKER_IDLE_TIMEOUT`
- `BILIVE_WORKER_IDLE_CHECK_INTERVAL`
- `BILIVE_DASHBOARD_ALLOWED_HOSTS`
