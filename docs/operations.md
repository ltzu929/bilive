# 运维手册

## Windows 首次安装

```powershell
cd D:\alldata\pi\bilive
.\setup_windows_env.ps1 -Dev
[Environment]::SetEnvironmentVariable("MIMO_API_KEY", "<your-key>", "User")
.\install_windows_pi_ssh_key.ps1
.\install_windows_worker_task.ps1 -NoUpload
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\check_windows_health.ps1
```

`setup_windows_env.ps1` 默认只安装 Python 依赖并执行 `pip check`。旧本地模型安装器保留为回滚工具，需要时显式执行：

```powershell
.\setup_windows_env.ps1 -Dev -InstallLlamaRuntime
.\install_llama_runtime.ps1 -Force
```

`MIMO_API_KEY` 必须配置到计划任务实际运行的 Windows 用户环境。临时 PowerShell 变量不会自动传播到下次登录或计划任务。

## MiMo 验收

生产切片使用 `mimo-v2.5` 视频理解接口。健康检查只验证 `MIMO_API_KEY` 是否存在，不输出密钥值，也不执行真实 API 调用。

可选真实 API 烟雾测试应使用很短的本地样例视频，并禁止真实上传：

```powershell
$env:BILIVE_MIMO_SMOKE_VIDEO = "D:\path\to\short-sample.mp4"
.\.venv-win\Scripts\python.exe -m pytest tests\integration\test_mimo_api_smoke.py -m integration -q
```

该测试只导入 MiMo 判断器，不导入上传模块、不写 SQLite 队列。未同时设置
`MIMO_API_KEY` 和 `BILIVE_MIMO_SMOKE_VIDEO` 时会跳过。

真实 MiMo 调用失败时，候选会标记为 `judge_failed` 并保留人工复核，不回退本地 Qwen。

## Worker API

计划任务通过 `pythonw.exe` 隐藏运行。打开 Pi 切片页面或提交切片任务时，Pi 执行：

```powershell
schtasks.exe /Run /TN BiliveWorkerApi
```

状态检查：

```powershell
Invoke-RestMethod http://127.0.0.1:2235/api/worker/status |
    ConvertTo-Json -Depth 8
```

关键字段：

- `dependencies.checks.llm`：MiMo API key 预检结果。
- `llm.status = idle`：当前没有 MiMo 请求。
- `llm.status = requesting`：watcher 正在请求 MiMo。
- `llm.status = error`：最近一次 MiMo 请求失败；这不是活跃工作，不阻止空闲退出。
- `watcher`、`lock`、`pending_tasks`：切片 worker 状态。
- `upload`：上传消费者和队列状态。

没有待处理、切片、MiMo 请求或上传工作时，Worker 连续空闲 15 分钟后退出，`2235` 关闭属于正常状态。页面状态轮询不会重新启动 Worker，也不会延长空闲时间。诊断时可用可见控制台入口：

```powershell
.\start_pipeline.ps1
```

需要暂时禁用自动退出时，在启动进程环境中设置：

```powershell
$env:BILIVE_WORKER_IDLE_TIMEOUT = "0"
```

健康检查是只读的：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\check_windows_health.ps1
```

它报告计划任务、`2235`、Worker API、MiMo key 状态、ASR 缓存、SQLite 和上传锁，不创建数据库、不启动切片任务、不修改上传队列。Worker 空闲退出后，`worker_api.status = unavailable` 是预期结果；健康检查不会唤醒它。

确认 `.secrets/bilibili.cookie` 可用后启用上传消费者：

```powershell
.\.venv-win\Scripts\python.exe -m src.upload.upload --check-auth
.\install_windows_worker_task.ps1 -EnableUpload
```

不得通过创建 pending 标记或真实投稿来验证服务启动。

## 模型排障

### MiMo 预检失败

```powershell
[Environment]::GetEnvironmentVariable("MIMO_API_KEY", "User")
```

返回空值时重新设置用户环境变量，然后重新登录或重启计划任务所在会话。不要把 API Key 写入 `bilive-server.toml`、日志或测试快照。

### MiMo 请求失败

查看最新 worker 日志：

```powershell
Get-ChildItem .\logs\runtime\slice-worker-*.log |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1 |
    Get-Content -Tail 200
```

重点检查限流、超时、Base64 超限、非法 JSON 和非法 trim。失败候选会保留人工复核；不要手动删除候选或 `.failed` 来掩盖问题。

### ASR 或字幕失败

确认 `faster-whisper`、模型缓存和 ffmpeg：

```powershell
.\.venv-win\Scripts\python.exe -c "import faster_whisper; print('ok')"
ffmpeg -version
```

当前生产 ASR 是 `large-v3` CPU `int8`。没有 CUDA 12 的 `cublas64_12.dll` 时不要配置 GPU。

## Pi 部署

在 `/mnt/win/bilive/.secrets/env` 配置 Windows SSH 目标，然后：

```bash
cd /mnt/win/bilive
sudo ./deploy/install-bilive-services.sh
sudo systemctl status bilive bilive-dashboard bilive-smb-recover.timer
ss -ltnp | grep -E ':2233|:2234'
```

Windows 每晚关机时 SMB 中断属于正常情况。恢复失败时检查：

```bash
sudo systemctl status mnt-win.mount mnt-win.automount
sudo systemctl status bilive-smb-recover.timer
sudo journalctl -u bilive-smb-recover.service -n 100 --no-pager
```

不要删除恢复 timer，也不要只依赖 `x-systemd.automount`。

## 仪表盘任务验收

仪表盘 retry/render 返回 `accepted`、`job_id` 和 `status_url`。轮询：

```text
GET /api/jobs/{job_id}
```

失败任务保留 `.failed.json` 和 `error`，不得静默删除。

## 回滚

旧本地模型运行时仍保留为手动回滚能力。需要回滚时先停止计划任务，确认没有正在处理的切片批次，再修改配置和脚本。不要直接删除运行中的 `.processing` 标记。

```powershell
Stop-ScheduledTask -TaskName BiliveWorkerApi
.\install_windows_worker_task.ps1 -NoUpload
```

## 静态验证

```powershell
.\.venv-win\Scripts\python.exe -m pytest -q
.\.venv-win\Scripts\python.exe -m compileall src tests
.\.venv-win\Scripts\python.exe -m pip check
```

```bash
find deploy -type f -name '*.sh' -print0 | xargs -0 -n1 bash -n
systemd-analyze verify deploy/*.service deploy/*.mount deploy/*.automount deploy/*.timer
```

验收不得进行真实 B 站投稿，也不得自动处理已有 ready 录像。
