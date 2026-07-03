# Bilive

Bilive 是自维护的 B 站直播录制、切片分析、字幕处理和投稿队列项目。Pi 负责连续录制与局域网仪表盘，Windows 负责所有重型处理。

## 生产边界

| 节点 | 服务 | 地址 | 责任 |
|---|---|---|---|
| Pi | `bilive.service` | `0.0.0.0:2233` | blrec 录制 |
| Pi | `bilive-dashboard.service` | `0.0.0.0:2234` | 切片页面、任务落盘、远程触发 |
| Pi | `bilive-smb-recover.timer` | 每 15 秒 | SMB 和 Pi 服务恢复 |
| Windows | `BiliveWorkerApi` | 按需 `127.0.0.1:2235` | worker 管理、预检、上传消费者 |
| 云端 | `mimo-v2.5` | Xiaomi MiMo API | 候选视频全模态判断和粗剪建议 |

Pi 不执行 ffmpeg、faster-whisper、MiMo、字幕烧录或上传。切片页面写入 `Videos/*.mp4.pending` 或 `Videos/.bilive-jobs/*.pending.json`，再通过 SSH 触发 Windows Worker API。

打开切片页面时，Pi 通过 SSH 按需启动 Windows Worker API；任务和上传全部空闲 15 分钟后自动退出。计划任务直接使用 `pythonw.exe`，不会显示命令行窗口。

## 切片流程

```text
弹幕密度 -> 候选范围 -> MiMo 全模态判断
  -> drop：删除候选
  -> keep：单段粗剪 -> faster-whisper 字幕 -> 一次 ffmpeg 粗剪+烧录 -> 入上传队列
  -> MiMo/Whisper/渲染/元数据/队列失败：保留人工复核
```

MiMo 输入候选视频、窗口弹幕、主播名和候选时长。视频以临时 720p H.264/AAC 分析副本 Base64 传输；`MIMO_API_KEY` 默认从项目本地 `.secrets/env` 读取，也可由进程环境变量覆盖，不写入 git、日志或公共配置。

当前不使用 `mimo-v2.5-asr`。自动字幕烧录需要可靠段级时间戳，仍由 `faster-whisper large-v3 CPU int8` 生成。

## 切片工作台

`/tasks` 是主要使用入口，界面按 `UP 主 -> 直播场次 -> 候选片段` 组织审核队列：

- 左侧审核队列按 UP 主分组，仍可用房间和状态筛选；点击录播后加载该场直播的候选片段。
- 中间是源录播预览和连续弹幕密度图。密度图用于导航和边界辅助，蓝色区间表示推荐保留片段，红色虚线表示需要复核的失败片段。
- 右侧是人工确认面板，可编辑标题、简介、标签和入/出点；点击“保留片段”才会写 `.upload.json` 并进入 SQLite 投稿队列。
- 底部“投稿流水线”复用上传队列状态，显示待上传、处理中、已发布和失败计数。它只读取 `/api/upload-dashboard`，不会执行切片、ASR、LLM 或投稿。

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

动作支持 `retry_judge` 和 `render_segment`。重复提交会复用仍在 pending/processing 的同一任务。上传和投稿是两个可恢复阶段，CDN 上传成功后，投稿重试复用 `remote_filename`，不会重复上传视频字节。

## Fail-closed

自动入队要求 MiMo 明确 `keep`、有效单段粗剪区间、非空 ASR、有效段级时间戳、字幕烧录成功、元数据成功和 SQLite 入队成功。任一步失败都保留候选供人工复核；只有 MiMo 明确 `drop` 才删除候选。

更完整的部署、恢复和模型说明见 [运维手册](docs/operations.md)、[架构文档](docs/architecture.md) 和 [模型运行时](docs/model-runtime.md)。

## 验证

```powershell
.\.venv-win\Scripts\python.exe -m pytest -q
node --test eagle-plugin\tests\sync.test.mjs
.\.venv-win\Scripts\python.exe -m compileall src tests
.\.venv-win\Scripts\python.exe -m pip check
```
