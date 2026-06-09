# 上传管线

## 当前流程

Windows 端推荐入口：

```powershell
cd D:\alldata\pi\bilive
.\start_pc_worker_api.ps1
```

FastAPI worker 启动后会自动拉起一个 `src.upload.upload` 消费者。LLM 判定
保留的切片写入 SQLite 队列后，不需要再手动运行上传命令。

```text
slice_only 写 <slice>.upload.json
  -> SQLite upload_queue(status=queued)
  -> UPOS 分片上传
  -> 持久化 remote_filename(status=uploaded)
  -> POST /x/vu/web/add/v3
  -> 记录 BVID(status=published)
  -> 删除本地切片和上传 sidecar
```

UPOS 上传和稿件发布是两个可恢复阶段。发布失败后保留
`remote_filename`，下一次只重试 Web 发布，不会重新上传视频字节。

## 状态与重试

队列状态：

| 状态 | 含义 |
|------|------|
| `queued` | 等待上传视频字节 |
| `uploading` | 正在上传到 UPOS |
| `uploaded` | 已有远端文件名，等待发布 |
| `publishing` | 正在提交稿件 |
| `published` | 发布成功并记录 BVID |
| `failed` | 达到重试上限或本地输入无效 |

网络或 B 站服务错误默认最多尝试 3 次，前两次失败后分别退避 30、60 秒。
认证失败会显示 `paused_auth`，不消耗普通重试次数，消费者定期重新读取 Cookie。已有
`locked=1/2` 的历史失败行迁移为 `failed`，不会自动重传。

## Cookie

自动上传直接读取：

```text
.secrets/bilibili.cookie
```

格式为浏览器 Cookie 字符串，至少需要：

```text
SESSDATA=...; bili_jct=...
```

不再要求先运行 `sync_cookie.py`。该脚本仅保留给旧 bilitool 命令兼容。
Cookie 不写入 SQLite 或运行日志。

## 配置

`bilive-server.toml`：

```toml
[upload]
auto_start = true
poll_interval_seconds = 10
max_attempts = 3
retry_base_seconds = 30
auth_retry_seconds = 120
delete_after_success = true
```

本地调试切片、禁止自动上传：

```powershell
.\start_pipeline.ps1 -NoUpload
```

或：

```powershell
$env:BILIVE_AUTO_UPLOAD = "0"
.\start_pc_worker_api.ps1
```

## 状态和手动命令

```powershell
# HTTP 状态
Invoke-RestMethod http://127.0.0.1:2235/api/upload/status

# 只查看队列，不认领任务
python -m src.upload.upload --status

# 只检查 Cookie，不认领任务
python -m src.upload.upload --check-auth

# 最多处理一个任务
python -m src.upload.upload --once

# 手动启动长驻消费者；进程锁会阻止重复实例
.\run_upload.ps1
```

运行状态写入：

```text
logs/runtime/upload-status.json
logs/runtime/upload-process-*.log
```

## 关键代码

| 职责 | 文件 |
|------|------|
| 队列状态机 | `src/db/conn.py` |
| 消费与恢复 | `src/upload/upload.py` |
| Web 发布 | `src/upload/bilibili_web.py` |
| UPOS 上传依赖 | `src/upload/bilitool/` |
| 子进程控制 | `src/server/upload_control.py` |
| 自动启动和状态 API | `src/server/worker_api.py` |

Pi 上的 `bilive.service` 仍只负责 `blrec` 录制，不执行上传。
