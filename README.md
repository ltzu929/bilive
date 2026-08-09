# Bilive

## Native Angular Studio

The production browser entry is the upstream Angular/ng-zorro shell served by
blrec on port `2233`.  `/studio/slices`, `/studio/uploads`, and
`/studio/settings` are native Angular routes; the former static dashboard and
iframe/injection navigation have been removed.

The browser calls the Windows dashboard through the explicit same-origin
`/studio-api/*` gateway.  The gateway maps to internal `2234/api/*` routes and
never proxies recorder-native `/api` or `/api/v1` requests.  Port `2234` remains
an API-only internal service and is not a second public entry point.

Bilive 是自维护的 B 站直播录制、切片分析、字幕处理和投稿队列项目。Pi 负责连续录制与局域网仪表盘，Windows 负责所有重型处理。

## 生产边界

| 节点 | 服务 | 地址 | 责任 |
|---|---|---|---|
| Pi | `bilive.service` | `127.0.0.1:2233` | blrec 录制，由 Tailscale Serve 对外提供入口 |
| Pi | `bilive-dashboard.service` | `127.0.0.1:2234` | 内部切片 API、任务落盘、远程触发 |
| Pi | `bilive-smb-recover.timer` | 每 15 秒 | SMB 和 Pi 服务恢复 |
| Windows | `BiliveWorkerApi` | 按需 `127.0.0.1:2235` | worker 管理、预检、上传消费者 |
| 云端 | `mimo-v2.5` | Xiaomi MiMo API | 候选视频全模态判断和粗剪建议 |

Pi 不执行 ffmpeg、faster-whisper、MiMo、字幕烧录或上传。切片页面写入 `Videos/*.mp4.pending` 或 `Videos/.bilive-jobs/*.pending.json`，再通过 SSH 触发 Windows Worker API。

浏览器统一从 `2233` 的原生 blrec Angular 外壳进入；迁移期间切片、上传和设置页面
通过 `/studio-api/*` 同源网关访问内部 `2234/api/*`，因此公开入口只需要
Tailscale Serve `2233`；`2234` 仅提供 API，不再托管页面。
`2234` 仍是 Pi 上的内部 dashboard 服务，不应作为第二个公网入口。
两个 Pi 服务都只监听 localhost，避免 SMB 恢复重启时与 Tailscale Serve
占用的 Tailnet 端口发生绑定冲突。

打开切片页面时，Pi 通过 SSH 按需启动 Windows Worker API；任务和上传全部空闲 15 分钟后自动退出。计划任务直接使用 `pythonw.exe`，不会显示命令行窗口。

## 部署拓扑

同一份代码支持两种部署拓扑，用运行时环境变量 `BILIVE_WINDOWS_SSH_TARGET` 切换，不需要编译打包或维护分支：

| 拓扑 | `BILIVE_WINDOWS_SSH_TARGET` | 录制 | dashboard → worker | 适用场景 |
|---|---|---|---|---|
| 分布式（默认） | 设置为 Windows 主机（如 `zk@192.168.31.202`） | Pi 上 `bilive.service` 跑 blrec | dashboard 通过 `ssh <target> curl.exe ...` 远程触发 | Pi 连续录制 + Windows 重处理 |
| 单机 Windows | 留空 | 同机 `start_windows_recorder.ps1` 用 uvicorn 拉起 blrec | dashboard 直接用本地 `curl.exe` 打 `127.0.0.1:2235` | 全部服务集中在一台 Windows |

当 `BILIVE_WINDOWS_SSH_TARGET` 为空时，`src/dashboard/remote_worker.py` 生成不带 `ssh` 前缀的本地命令，dashboard 与 worker 在同机通过 localhost 通信。单机模式下用 `start_windows_recorder.ps1`、`start_windows_dashboard.ps1` 启动本地录制和仪表盘，或用 `install_windows_startup_tasks.ps1` 注册登录自启计划任务；本地录制环境见下文“单机 Windows 录制”。

## 切片流程

```text
弹幕密度 -> 候选范围 -> MiMo 全模态判断
  -> drop：删除候选
  -> keep：0..N 个聊天片段 -> 本地质量闸门与去重
           -> faster-whisper 字幕 -> 一次 ffmpeg 粗剪+烧录 -> 入上传队列
  -> 分数不足或 MiMo/Whisper/渲染/元数据/队列失败：保留人工复核
```

MiMo 输入候选视频、窗口弹幕、主播名和候选时长。视频以临时 720p H.264/AAC 分析副本 Base64 传输；`MIMO_API_KEY` 默认从项目本地 `.secrets/env` 读取，也可由进程环境变量覆盖，不写入 git、日志或公共配置。

当前不使用 `mimo-v2.5-asr`。自动字幕烧录需要可靠段级时间戳，仍由 `faster-whisper large-v3 CPU int8` 生成。

## 切片工作台

`/studio/slices` 是切片审核入口，界面按 `UP 主 -> 直播场次 -> 候选片段` 组织桌面审核工作台。
`/tasks` 保留为原生 blrec 录制任务页，显示 `settings.toml` 中的 `room_id`；它与切片
工作台的历史录播清单不是同一份数据，因此两页的直播间数量可以不同。

切片工作台包含：

- 左侧队列按 UP 主分组，可用房间和状态筛选；桌面窄宽度下可收起为抽屉。
- 中间是源录播预览、连续弹幕密度图和候选导航。密度图支持定位视频与拖拽入点/出点。
- 右侧审核检查器集中编辑标题、简介、标签、边界和字幕样式；技术错误默认折叠，只显示可执行的恢复建议。
- “通过并生成成片”会创建 Windows `finalize_segment` 任务。只有 ASR、字幕渲染、上传元数据和 SQLite 入队全部成功，片段才进入投稿队列。
- 投稿队列和发布表现属于次级工作区；它们只读 dashboard/SQLite 状态，不会在 Pi 上运行重任务。

审核快捷键：`J/K` 切换候选，空格播放/暂停，`I/O` 以当前播放点设置入点/出点，`Ctrl+Enter` 通过并生成成片。输入框聚焦时不会触发快捷键。

自动流程仍然 fail-closed：只有满足自动入队条件的 MiMo keep 片段才会进入上传队列；人工复核保留的片段必须显式确认后才投稿。

## Eagle 原始录播索引

`eagle-plugin/` 是 Eagle 轻量索引插件草案，用于把当前仍存在的原始录播同步为 Eagle 书签卡片。它只调用 `/api/eagle/source-recordings` 读取录播索引，再在 Eagle 中创建、更新或移入废纸篓对应卡片；原始 `.mp4` 文件仍保留在 `Videos/`，不会复制进 Eagle。

同步是手动增量镜像：bilive 当前清单里有的新录播会新增卡片，仍存在的录播会更新标签和备注，已经删除的原始录播会在下次同步时把对应 Eagle 卡片移入废纸篓。插件只管理带 `bilive` 和 `原始录播` 标签且含有 bilive 机器可读备注的条目。

## Windows 安装

在项目目录执行：

```powershell
.\setup_windows_env.ps1 -Dev
.\install_windows_pi_ssh_key.ps1
.\install_windows_worker_task.ps1 -NoUpload
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\check_windows_health.ps1
```

需要先在项目本地密钥文件 `.secrets/env` 中配置：

```powershell
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
```

`setup_windows_env.ps1` 默认只创建 `.venv-win`、安装依赖并执行 `pip check`。旧本地模型运行时安装脚本保留为回滚工具，默认不会下载。

确认 cookie 有效后再启用上传：

```powershell
.\.venv-win\Scripts\python.exe -m src.upload.upload --check-auth
.\install_windows_worker_task.ps1 -EnableUpload
```

常用 Windows 环境变量：

- `MIMO_API_KEY`：MiMo API Key，生产切片必需；推荐写入 `.secrets/env`，进程环境可覆盖。
- `BILIVE_AUTO_UPLOAD=0`：禁用上传消费者。
- `BILIVE_WORKER_IDLE_TIMEOUT=0`：诊断时禁用 Worker 自动退出。
- `BILIVE_CONFIG`、`BILIVE_VIDEOS_DIR`、`BILIVE_LOG_DIR`。
- `BILIVE_DB_PATH`、`BILIVE_COOKIE_FILE`。

生产切片默认使用带时间戳的弹幕上下文、MiMo 请求并发和本地严格质量闸门。阈值、ASR batch、边界吸附和并发配置见 [`bilive-server.toml`](bilive-server.toml)；真实凭据不得写入该文件。

## 单机 Windows 录制

单机模式在同一台 Windows 上再跑本地 blrec 录制，与重处理环境隔离。blrec 依赖旧版 Python，用独立的 `.venv-recorder`（Python 3.10）：

```powershell
.\setup_windows_recorder_env.ps1
$env:BILIVE_WINDOWS_SSH_TARGET = ""   # 留空即单机模式
.\start_windows_recorder.ps1          # 本地 blrec，127.0.0.1:2233
.\start_windows_dashboard.ps1         # 本地仪表盘，127.0.0.1:2234
```

`setup_windows_recorder_env.ps1` 用 `uv` 创建 `.venv-recorder`、安装 `requirements/recorder-windows.txt`、应用 `src.blrec_patch`，并从 `settings.example.toml` 生成机器本地 `settings.toml`。`install_windows_startup_tasks.ps1` 可把录制和仪表盘注册为当前交互用户的登录自启计划任务（`pythonw.exe`，无窗口）。分布式部署不需要这些脚本。

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

blrec 通过环境变量 `BLREC_API_KEY` 读取密钥，密钥不会出现在进程参数中。Windows 夜间关机和次日 SMB 恢复是正常运行场景，必须保留 `bilive-smb-recover.timer`。

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

重任务动作支持 `finalize_segment`、`retry_judge`、`render_segment` 和 `reburn_subtitles`。重复提交会复用仍在 pending/processing 的同一任务。上传和投稿是两个可恢复阶段，CDN 上传成功后，投稿重试复用 `remote_filename`，不会重复上传视频字节。

## Fail-closed

自动入队要求 MiMo 明确 `keep`、质量分/完整度/置信度均达到本地阈值、有效粗剪区间、非空 ASR、有效段级时间戳、字幕烧录成功、元数据成功和 SQLite 入队成功。分数不足、重复候选或任一技术步骤失败都保留供人工复核；只有 MiMo 明确 `drop` 才删除候选。

更完整的部署、恢复和模型说明见 [运维手册](docs/operations.md)、[架构文档](docs/architecture.md) 和 [模型运行时](docs/model-runtime.md)。

## 验证

```powershell
.\.venv-win\Scripts\python.exe -m pytest -q
node --test eagle-plugin\tests\sync.test.mjs
.\.venv-win\Scripts\python.exe -m compileall src tests
.\.venv-win\Scripts\python.exe -m pip check
```
