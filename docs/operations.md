# 运维手册

## Windows 首次安装

```powershell
cd D:\alldata\pi\bilive
.\setup_windows_env.ps1 -Dev
function Set-BiliveSecret {
    param([string]$Name, [string]$Value)
    New-Item -ItemType Directory -Force .\.secrets | Out-Null
    $path = ".\.secrets\env"
    $lines = if (Test-Path $path) { Get-Content $path } else { @() }
    $line = "$Name=$Value"
    $pattern = "^\s*$([regex]::Escape($Name))="
    if ($lines -match $pattern) {
        $lines = $lines | ForEach-Object { if ($_ -match $pattern) { $line } else { $_ } }
    } else {
        $lines += $line
    }
    Set-Content -Path $path -Value $lines -Encoding utf8
}
Set-BiliveSecret MIMO_API_KEY "<your-key>"
.\install_windows_pi_ssh_key.ps1
.\install_windows_worker_task.ps1 -NoUpload
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\check_windows_health.ps1
```

`setup_windows_env.ps1` 默认只安装 Python 依赖并执行 `pip check`。旧本地模型安装器保留为回滚工具，需要时显式执行：

```powershell
.\setup_windows_env.ps1 -Dev -InstallLlamaRuntime
.\install_llama_runtime.ps1 -Force
```

`MIMO_API_KEY` 推荐配置到项目本地 `.secrets/env`。Worker 启动时会先加载该文件，再保留已有的进程环境变量；临时 PowerShell 变量只影响当前启动的 worker。

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

## 日常审核工作流

打开 `http://<pi>:2234/tasks` 后使用同一个工作台完成复核和发布确认：

1. 在左侧选择 UP 主分组和直播场次。状态筛选用于快速查看待处理、处理中、失败、已完成和已有保留片段的录播。
2. 在中间预览源录播，点击密度图中的候选区间可跳到相应片段。密度图用于定位峰值和辅助边界，不直接修改裁剪结果。
3. 在右侧检查 AI 判断、标题、简介、标签和裁剪区间。需要微调边界时先保存区间，再按需重新渲染或重新判断。
4. 点击“保留片段”才会人工确认入投稿队列；点击“丢弃片段”只更新复核状态，不删除源录播。
5. 底部“投稿流水线”显示上传/投稿状态。刷新和唤醒上传节点只走 Worker API；不得为了验收而创建真实投稿。

如果上传数据库尚未初始化，投稿流水线会显示 unavailable 或空队列，这是预期的只读状态，不代表切片工作台不可用。
## 模型排障

### MiMo 预检失败

```powershell
Select-String -Path .\.secrets\env -Pattern "^MIMO_API_KEY="
```

没有匹配时把 key 写入 `.secrets/env`，然后重启 Worker API。不要把 API Key 写入 `bilive-server.toml`、日志或测试快照。

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
