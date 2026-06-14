# Bilive

Bilive 是自维护的 B 站直播录制、切片分析、字幕处理和投稿队列项目。
Pi 负责连续录制与局域网仪表盘，Windows 负责所有重型处理。

## 生产边界

| 节点 | 服务 | 地址 | 责任 |
|---|---|---|---|
| Pi | `bilive.service` | `0.0.0.0:2233` | blrec 录制 |
| Pi | `bilive-dashboard.service` | `0.0.0.0:2234` | 切片页面、任务落盘、远程触发 |
| Pi | `bilive-smb-recover.timer` | 每 15 秒 | SMB 和 Pi 服务恢复 |
| Windows | `BiliveWorkerApi` | 按需 `127.0.0.1:2235` | worker 管理、预检、上传消费者 |
| Windows | 托管 `llama-server` | `127.0.0.1:2236` | 仅在整批切片需要 LLM 时临时运行 |

Pi 不执行 ffmpeg、faster-whisper、LLM、字幕烧录或上传。切片页面写入
`Videos/*.mp4.pending` 或 `Videos/.bilive-jobs/*.pending.json`，再通过 SSH
触发 Windows Worker API。

打开切片页面时，Pi 通过 SSH 按需启动 Windows Worker API；任务和上传全部空闲
15 分钟后自动退出。计划任务直接使用 `pythonw.exe`，不会显示命令行窗口。
每次 `src.server.watcher --once` 是一个模型生命周期批次：第一次 LLM 判断时
加载模型，同批任务复用，整批完成或异常退出时卸载。纯渲染批次不会加载模型，
也不再需要启动 LM Studio。

## Windows 安装

在项目目录执行：

```powershell
.\setup_windows_env.ps1 -Dev
.\install_windows_pi_ssh_key.ps1
.\install_windows_worker_task.ps1 -NoUpload
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\check_windows_health.ps1
```

`setup_windows_env.ps1` 会创建 `.venv-win`、校验 Python 依赖，并安装固定版本
`b9616` 的 llama.cpp CUDA 12 运行时到：

```text
.runtime\llama.cpp\b9616\llama-server.exe
```

生产模型默认使用：

```text
E:\AImodel\lmstudio-community\Qwen3.5-9B-GGUF\Qwen3.5-9B-Q4_K_M.gguf
```

首次安装后执行真实模型烟雾测试：

```powershell
.\.venv-win\Scripts\python.exe -m src.autoslice.mllm_sdk.managed_runtime --smoke-test
```

成功时输出 `{"status":"ok"}`，随后 `2236` 端口关闭且
`llama-server.exe` 进程退出。

任务安装器会幂等注册无登录触发器的 `BiliveWorkerApi`，临时启动它并验证
`2235` 和 API。验证后遵循 15 分钟空闲退出策略。默认安全模式等同于
`-NoUpload`。确认 cookie 有效后再启用上传：

```powershell
.\.venv-win\Scripts\python.exe -m src.upload.upload --check-auth
.\install_windows_worker_task.ps1 -EnableUpload
```

常用 Windows 环境变量：

- `BILIVE_LLM_MODEL_PATH`：覆盖 GGUF 模型路径。
- `BILIVE_LLAMA_SERVER_PATH`：覆盖 `llama-server.exe` 路径。
- `BILIVE_AUTO_UPLOAD=0`：禁用上传消费者。
- `BILIVE_WORKER_IDLE_TIMEOUT=0`：诊断时禁用 Worker 自动退出。
- `BILIVE_CONFIG`、`BILIVE_VIDEOS_DIR`、`BILIVE_LOG_DIR`。
- `BILIVE_DB_PATH`、`BILIVE_COOKIE_FILE`。

完整模型生命周期和排障见 [模型运行时](docs/model-runtime.md)。

## Pi 安装

Pi 的 `.secrets/env` 至少配置：

```bash
BILIVE_WINDOWS_SSH_TARGET=zk@192.168.31.202
```

安装或更新：

```bash
ssh pi
cd /mnt/win/bilive
sudo ./deploy/install-bilive-services.sh
```

blrec 通过环境变量 `BLREC_API_KEY` 读取密钥，密钥不会出现在进程参数中。
Windows 夜间关机和次日 SMB 恢复是正常运行场景。必须保留
`bilive-smb-recover.timer`，不要改成只依赖 automount。

## 任务状态

完整录像处理：

```text
*.mp4.pending -> *.mp4.processing -> *.mp4.done
                                  -> *.mp4.failed
```

仪表盘动作：

```text
<job>.pending.json -> <job>.processing.json -> <job>.done.json
                                           -> <job>.failed.json
```

动作支持 `retry_judge` 和 `render_segment`。重复提交会复用仍在
pending/processing 的同一任务。`GET /api/jobs/{job_id}` 返回进度和失败原因。

上传和投稿是两个可恢复阶段。CDN 上传成功后，投稿重试复用
`remote_filename`，不会重复上传视频字节。

## Fail-closed

自动入队要求非空 ASR、有效段级时间戳、窗口弹幕与转录共同送入 LLM、明确
`keep`、字幕烧录成功、元数据成功和 SQLite 入队成功。任一步失败都保留候选
供人工复核；只有明确 `drop` 才删除候选。

模型文件缺失、运行时缺失、`2236` 被占用、加载超时或 LLM 输出无效时，worker
均停止自动链路并保留候选，不会绕过判断自动上传。

## 验证

```powershell
.\.venv-win\Scripts\python.exe -m pytest -q
.\.venv-win\Scripts\python.exe -m compileall src tests
.\.venv-win\Scripts\python.exe -m pip check
```

部署和恢复见 [运维手册](docs/operations.md)，结构说明见
[架构文档](docs/architecture.md)，媒体维护见 [维护手册](docs/maintenance.md)。
