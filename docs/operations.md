# 运维手册

## Native Angular entry points

Use the single Tailnet entry `https://ubuntu.tail699f46.ts.net:2233/tasks` for
the recorder shell. Open the native Studio pages from its menu or directly:

- `/studio/slices` — three-column slice review workbench;
- `/studio/uploads` — upload/publish queue status;
- `/studio/settings` — browser preferences and read-only pipeline settings.

The old `/studio-proxy/*` iframe path and the static dashboard files no longer
exist. Studio API and media requests use same-origin `/studio-api/*`; only the
recorder process serves public HTTP, while dashboard port `2234` remains
internal. After deployment, hard-refresh once to activate the new Angular
service-worker manifest.

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

## 单机 Windows 部署

默认拓扑是 Pi 录制 + Windows 重处理（上文即分布式安装）。若要把录制也放在同一台 Windows，改用单机拓扑：`BILIVE_WINDOWS_SSH_TARGET` 留空即可让 dashboard 走本地 `curl.exe`，无需 SSH。blrec 依赖旧版 Python，用独立虚拟环境隔离：

```powershell
cd D:\alldata\pi\bilive
.\setup_windows_recorder_env.ps1
$env:BILIVE_WINDOWS_SSH_TARGET = ""
.\start_windows_recorder.ps1
.\start_windows_dashboard.ps1
```

`setup_windows_recorder_env.ps1` 用 `uv` 创建 `.venv-recorder`（Python 3.10）、安装 `requirements/recorder-windows.txt`、应用 `src.blrec_patch`，并从 `settings.example.toml` 生成机器本地 `settings.toml`。录制在 `127.0.0.1:2233`，dashboard 在 `127.0.0.1:2234`，Worker API 仍在 `127.0.0.1:2235`。开机自启用：

```powershell
.\install_windows_startup_tasks.ps1
```

它把录制和仪表盘注册为当前交互用户的登录自启计划任务（`pythonw.exe`，无窗口）；只装 dashboard 用 `-NoRecorder`。分布式部署不需要这些脚本，继续用 `bilive.service`/`bilive-dashboard.service`。

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

在 Tailnet 中优先从统一入口
`https://ubuntu.tail699f46.ts.net:2233/tasks` 打开原生 Angular 录播控制台。
切片、上传和工作台设置位于 `/studio/slices`、`/studio/uploads`、
`/studio/settings`。浏览器通过同源 `/studio-api/*` 网关访问本机 `2234/api/*`，
不再暴露旧 iframe 或第二个 Tailnet 端口。

```bash
sudo tailscale serve --bg --yes --https=2233 http://127.0.0.1:2233
```

`2234` 仍由 `bilive-dashboard.service` 提供内部代理目标；如需排障，
可在 Pi 本机访问 `http://127.0.0.1:2234/tasks`，不应把它作为公开入口。
`bilive.service` 与 `bilive-dashboard.service` 必须分别监听
`127.0.0.1:2233` 和 `127.0.0.1:2234`。Tailscale Serve 已占用 Tailnet
地址上的同名端口，绑定 `0.0.0.0` 会在 SMB 恢复重启后造成端口冲突和循环退出。

`/tasks` 与 `/studio/slices` 是两个不同的数据视图：

- `/tasks` 是上游 blrec 的原生录制任务页，显示 `settings.toml` 中配置的
  `room_id`，请求 `/api/v1/tasks/data`。它回答“哪些直播间由录制端管理”。
- `/studio/slices` 是 bilive 的切片工作台，读取 `/api/source-recordings`，按
  已存在的源录播、主播和直播场次组织候选片段。它回答“哪些历史录播可以切片”。

因此两个页面的直播间数量不必相同，也不代表视频被删除。排查数量异常时，先检查
`settings.toml` 的 `[[tasks]]`，再检查 `Videos/` 下的房间目录；不要用页面卡片数量
推断历史文件是否存在。录制服务会并发加载配置中的任务，某一房间的 B 站弹幕接口重试
不会再阻塞后续房间显示。

打开 `/studio/slices` 工作台后完成复核和发布确认：

1. 在左侧选择 UP 主分组和直播场次。默认“启动切片”只处理最新待处理录播；需要处理旧场次时先选择它，再点击“处理当前录播”。状态筛选用于快速查看待处理、处理中、失败、已完成和已有保留片段的录播；桌面窄宽度下队列可以收起。
2. 在中间预览源录播，点击候选区间跳转；拖拽密度图入点/出点或用 `I/O` 记录当前播放点，修改只形成草稿。
3. 在右侧“内容”页检查 AI 判断、标题、简介、标签和裁剪区间；“字幕”和“技术详情”只在需要时展开。
4. 点击“生成最终成片”会创建 `finalize_segment` Windows 任务。完成 ASR、字幕渲染和元数据后，成片只写入 `staged` 状态；上传中心的“等待最终确认”不会被上传消费者领取。
5. 预览最终成片确认无误后点击“允许发布”，才会把该行激活为 `queued`。修改标题、边界或字幕后重新生成会重新等待第二次确认；重复确认不会创建重复投稿。
6. 点击“丢弃”只更新复核状态，不删除源录播，并提供短暂撤销。重新分析、重新渲染和字幕重烧位于修复操作中；没有候选时必须点击“人工检查也没有精彩片段”才能关闭整场复核。
7. 在中间预览源录播时可用 `I/O` 标记漏切区间、选择原因并填写备注；人工候选同样必须经过“生成最终成片”与“允许发布”。
8. `/uploads` 查看完整上传/投稿状态。刷新和唤醒上传节点只走 Worker API；不得为了验收而创建真实投稿。

整场复核完成后，系统创建 Windows `trash_recording` 任务。它按任务历史解析源 MP4/FLV、弹幕和临时中间产物，明确排除最终成片、投稿元数据、上传记录和主播档案，再通过 Windows 系统垃圾桶回收。`Videos/.bilive-state/` 中的复核、回收日志和经验记录独立于源文件保留。未复核录播第 11 天预警、第 14 天由 Windows 维护任务再次检查并入队；正在录制、切片、渲染或上传的场次会保留阻塞原因。

首次安装每日维护任务：

```powershell
.\install_windows_recording_retention_task.ps1
```

如果上传数据库尚未初始化，投稿流水线会显示 unavailable 或空队列，这是预期的只读状态，不代表切片工作台不可用。

常用快捷键：`J` 下一条、`K` 上一条候选，空格播放或暂停，`I/O` 设置入点/出点，`Ctrl+Enter` 生成最终成片（仍需再次点击“允许发布”）。光标位于输入框、文本框或下拉框时快捷键停用。
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

工作台显示归类后的失败阶段、推荐动作，以及后端保存的异常类型和消息。当前“技术详情”不保证包含完整 ffmpeg 命令、退出码或 Python 堆栈；需要更完整上下文时结合对应 worker 日志排查。不要把其中可能出现的本地绝对路径写入公开 issue。

字幕渲染失败时优先使用“重新渲染/字幕重烧”，它会复用已经存在的分析与 ASR sidecar。只有模型判断本身不合适时才使用“重新分析”，避免重复 MiMo 调用。

## 受控真实切片验收

真实 MiMo 验收必须同时隔离上传消费者、上传队列和样本目录：

```powershell
$env:BILIVE_AUTO_UPLOAD = "0"
$env:BILIVE_SKIP_UPLOAD_QUEUE = "1"
$env:BILIVE_DB_PATH = "<isolated-temp-db>"
$env:BILIVE_VIDEOS_DIR = "<isolated-benchmark-videos>"
```

- 使用现有录播的只读副本或 NTFS 硬链接，不直接给生产录像写 pending。
- 最多抽取 3 场录播、每场最多 3 个候选；记录编码、MiMo、ASR、渲染和总耗时。
- 验收质量分、完整度、置信度、ASR 分段边界、重复候选和标题真实性。
- 验收完成后确认隔离数据库没有 queued/published 项，生产数据库时间戳和队列计数未变化。
- 不启动上传消费者，不调用 B 站投稿接口。

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
systemd-analyze verify deploy/*.service deploy/*.timer
```

验收不得进行真实 B 站投稿，也不得自动处理已有 ready 录像。
