# 运维手册

## Windows 首次安装

```powershell
cd D:\alldata\pi\bilive
.\setup_windows_env.ps1 -Dev
.\install_windows_pi_ssh_key.ps1
.\install_windows_worker_task.ps1 -NoUpload
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\check_windows_health.ps1
```

`setup_windows_env.ps1` 默认安装固定版本 llama.cpp 运行时。仅在运行时已由外部
流程准备好时使用 `-SkipLlamaRuntime`：

```powershell
.\setup_windows_env.ps1 -Dev -SkipLlamaRuntime
```

也可独立安装或强制重装：

```powershell
.\install_llama_runtime.ps1
.\install_llama_runtime.ps1 -Force
```

生产 GGUF 默认位于：

```text
E:\AImodel\lmstudio-community\Qwen3.5-9B-GGUF\Qwen3.5-9B-Q4_K_M.gguf
```

路径不同的机器应设置：

```powershell
$env:BILIVE_LLM_MODEL_PATH = "E:\models\Qwen3.5-9B-Q4_K_M.gguf"
$env:BILIVE_LLAMA_SERVER_PATH = "D:\runtime\llama-server.exe"
```

环境变量必须同时配置到计划任务实际运行的用户环境，临时 PowerShell 变量不会
自动传播到下次登录。

## 模型验收

真实加载、请求和卸载：

```powershell
.\.venv-win\Scripts\python.exe -m src.autoslice.mllm_sdk.managed_runtime --smoke-test
```

成功标准：

1. 输出 `{"status":"ok"}`。
2. 命令退出后没有 `llama-server.exe` 进程。
3. 命令退出后没有 `2236` 监听。

```powershell
Get-Process llama-server -ErrorAction SilentlyContinue
Get-NetTCPConnection -LocalPort 2236 -State Listen -ErrorAction SilentlyContinue
```

整批切片时，第一次 LLM 判断会加载模型；同批后续判断复用该进程；整批完成、
异常或取消后卸载。只含 `render_segment` 的批次不会加载模型。

## Worker API

任务安装器会替换旧计划任务，并在确认旧 `2235` 监听者属于本项目后停止它。
安装后验证：

```powershell
Invoke-RestMethod http://127.0.0.1:2235/api/worker/status |
    ConvertTo-Json -Depth 8
```

关键字段：

- `dependencies.checks.llm`：运行时和模型文件预检。
- `llm.status = idle`：当前没有模型进程。
- `llm.status = running`：watcher 正在使用模型。
- `llm.status = occupied`：`2236` 被非健康或未知服务占用。
- `llm.owned`：状态读取进程是否直接拥有该模型进程；Worker API 通常为
  `false`，因为实际所有者是 watcher。
- `watcher`、`lock`、`pending_tasks`：切片 worker 状态。
- `upload`：上传消费者和队列状态。

健康检查是只读的：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\check_windows_health.ps1
```

它报告计划任务、`2235`、Worker API、托管模型文件、ASR 缓存、SQLite 和上传
锁，不创建数据库、不启动切片任务、不修改上传队列。

确认 `.secrets/bilibili.cookie` 可用后启用上传消费者：

```powershell
.\.venv-win\Scripts\python.exe -m src.upload.upload --check-auth
.\install_windows_worker_task.ps1 -EnableUpload
```

不得通过创建 pending 标记或真实投稿来验证服务启动。已有 ready 录像不会因为
服务恢复而自动排队。

## 模型排障

### 文件预检失败

检查配置和文件：

```powershell
Test-Path .\.runtime\llama.cpp\b9616\llama-server.exe
Test-Path "E:\AImodel\lmstudio-community\Qwen3.5-9B-GGUF\Qwen3.5-9B-Q4_K_M.gguf"
```

运行时缺失时重新执行 `install_llama_runtime.ps1 -Force`。模型缺失时修正
`bilive-server.toml` 或 `BILIVE_LLM_MODEL_PATH`，不要复制模型到 Pi 或 SMB。

### `2236` 被占用

```powershell
Get-NetTCPConnection -LocalPort 2236 -State Listen |
    Select-Object LocalAddress,LocalPort,OwningProcess
Get-Process -Id <OwningProcess>
```

运行时管理器不会结束未知监听者。先识别来源，再由对应程序正常退出。

### 加载超时或 LLM 判断失败

查看：

```powershell
Get-Content .\logs\runtime\llama-server.log -Tail 200
Get-ChildItem .\logs\runtime\slice-worker-*.log |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1 |
    Get-Content -Tail 200
```

重点检查 CUDA DLL、显存不足、模型路径、`exited with code` 和
`did not become ready`。判断失败会保留候选供人工复核，不要手工删除
`.failed` 或候选文件来掩盖问题。

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

托管模型运行时功能提交为 `4b94274`。需要回退时先停止计划任务，确保没有正在
处理的切片批次，再执行 Git 回退并重新安装任务：

```powershell
Stop-ScheduledTask -TaskName BiliveWorkerApi
git revert 4b94274
.\install_windows_worker_task.ps1 -NoUpload
```

不要直接删除运行中的 `llama-server.exe` 或 `.processing` 标记。

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
