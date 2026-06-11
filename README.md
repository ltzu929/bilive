# bilive fork

这个仓库是从上游 `timerring/bilive` fork 后整理出来的本地工作流版本。当前重点不是维护一个通用发行版，而是稳定完成自己的 B 站直播录制、切片分析和上传流程。

当前 README 以本仓库代码和最近 `ltzu / ltzu929` 修改为准。上游文档仍保留在 `docs/`，但其中不少内容和本 fork 的实际运行方式已经不一致。

## 当前定位

这个 fork 主要做四件事：

- 用 Pi 上的 `blrec` 录制 B 站直播和弹幕，Web UI 默认在 `http://192.168.31.157:2233`。
- 从本地 `.secrets/bilibili.cookie` 读取 B 站凭据并自动发布保留切片。
- 在 Windows/PC 端消费 dashboard 提交的 pending 录播，处理弹幕、ASR、LLM 判断、字幕烧录，并把合格切片写入 SQLite 上传队列。
- 支持 dashboard 启动的一次性切片 worker：页面只写 `.pending`，Pi 可触发 Windows 计划任务，PC worker 处理完自动退出。

请先确认录制和上传行为符合主播授权、平台规则和你自己的使用场景。本项目不适合未经授权的大规模录制或商业使用。

## 项目现状

### 推荐主路径

当前实际运行方式是 Pi 录制、Windows 做重任务：

1. Pi 上 `bilive.service` 常驻运行 `blrec`，负责录制并把文件写到 `/mnt/win/bilive/Videos/`。
2. Windows 端在 `D:\alldata\pi\bilive` 编辑和运行切片/上传代码。
3. 推荐在 Windows 注册 `BiliveSliceOnce` 计划任务，再让 Pi dashboard 点击“启动切片”时触发它。
4. 切片页面写 `.mp4.pending` 标记，Windows 执行 `src.server.watcher --once`，处理完 `.pending` 后写 `.done` 并退出。
5. `start_pc_worker_api.ps1` 自动启动单实例上传消费者；调试时用 `-NoUpload` 禁用。

Pi 端服务检查：

```bash
ssh pi
sudo systemctl status bilive
sudo systemctl restart bilive
```

### Pi 端 SMB 自动恢复

Windows 每晚关机时，Pi 上的 `bilive.service` 会停止 `blrec` 并等待，不会把
录像改写到 Pi 本地盘。`x-systemd.automount` 只负责按需触发挂载；首次挂载
失败后，`mnt-win.mount` 可能停留在 `failed`，因此项目额外使用
`bilive-smb-recover.timer` 每 15 秒检查一次：

- Windows `192.168.31.202:445` 离线：安静等待。
- Windows 上线且挂载失败：清除失败状态并重新挂载。
- CIFS 挂载失效：先停止录制，再清理旧挂载并重挂。
- 挂载恢复：自动重启 `bilive.service`，恢复 `2233`。

在 Pi 上安装或更新本地 systemd 文件：

```bash
ssh pi
cd /mnt/win/bilive
sudo ./deploy/install-bilive-services.sh
```

检查恢复器：

```bash
systemctl status bilive-smb-recover.timer
sudo journalctl -u bilive-smb-recover.service -n 50 --no-pager
```

Windows 端推荐注册一次性切片计划任务：

```powershell
cd D:\alldata\pi\bilive
.\install_windows_slice_task.ps1
```

然后在 `bilive-server.toml` 打开 Pi 触发配置：

```toml
[dashboard.remote_worker]
enabled = true
command = ["ssh", "win", "schtasks", "/Run", "/TN", "BiliveSliceOnce"]
timeout = 10
```

`win` 是 Pi 上 SSH config 里的 Windows 主机别名。未配置这个远程触发时，仍可用兼容入口：

```powershell
cd D:\alldata\pi\bilive
.\start_pc_worker_api.ps1
```

如果不走页面，也可以手动处理 pending 队列：

```powershell
cd D:\alldata\pi\bilive
$env:PYTHONPATH = "$PWD;$PWD\src"
$env:BILIVE_CONFIG = "$PWD\bilive-server.toml"
$env:BILIVE_VIDEOS_DIR = "$PWD\Videos"
python -m src.server.watcher --once --videos-dir .\Videos
```

### 不再作为主路径的内容

- 上游 README 中的大量推广、通用部署说明和完整模型矩阵不再是本 fork 的主文档。
- Docker / Compose 文件仍在仓库里，但当前没有围绕本 fork 的 cookie 持久化和本地配置策略重新整理，不建议作为首选启动方式。
- `settings.toml` 已从 Git 删除并加入 `.gitignore`，它现在是本机私有配置，不应提交。
- 旧的全目录 `scan_slice` 入口已经删除；生产切片只消费 dashboard 写入的 pending 队列。

## 目录结构

```text
.
├── bilive.toml                 # 项目处理配置，当前仍被 Git 跟踪
├── settings.toml               # blrec 本地私有配置，已忽略，不提交
├── record.sh                    # 录制启动入口
├── upload.sh                    # 普通扫描 + 上传入口
├── slice.sh                     # 处理 pending 切片队列一次
├── start_pc_worker_api.ps1       # Windows 本机 worker API，供 dashboard 触发一次性切片
├── run_slice_once.ps1            # Windows 计划任务执行的一次性 pending worker
├── install_windows_slice_task.ps1 # 注册 BiliveSliceOnce 手动计划任务
├── start_pipeline.ps1            # Windows PC helper 启动器
├── refine_feedback.sh           # 人工反馈驱动的精切 + 入上传队列入口
├── src/
│   ├── burn/                    # 扫描、渲染、切片处理
│   ├── autoslice/               # 切片标题、多模态分析、质量筛选
│   ├── upload/                  # bilitool 上传封装
│   ├── danmaku/                 # 弹幕转换
│   ├── subtitle/                # Whisper 字幕
│   ├── cover/                   # 可选封面生成
│   └── db/                      # SQLite 上传队列
├── Videos/                      # 录制输出目录
├── logs/                        # 运行日志
├── .secrets/                    # 本地 secret，已忽略
└── .devcontainer/               # VS Code Dev Container 配置
```

## 环境准备

### Pi / Linux

建议使用 Python 3.10。当前仓库里有历史 `venv/`，新环境建议自己创建：

```bash
cd /home/zk/projects/bilive
python3.10 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

还需要系统依赖：

```bash
sudo apt-get update
sudo apt-get install -y ffmpeg procps lsof curl vim gcc fonts-noto-cjk fontconfig
sudo install -D -m 0644 assets/msyh.ttf /usr/share/fonts/msyh.ttf
sudo fc-cache -f
```

如果不是用 `--recurse-submodules` clone 的仓库，需要初始化 submodule：

```bash
git submodule update --init --recursive
```

当前 submodule 用于：

- `src/danmaku/DanmakuConvert`
- `src/autoslice/auto_slice_video`
- `src/upload/bilitool`

### Dev Container

仓库包含 `.devcontainer/devcontainer.json`。它会安装 Python 依赖、ffmpeg、字体和 submodule，并转发 2233 端口。适合重新搭环境，但本地 secret 仍然需要你自己准备。

## 本地配置和敏感文件

### `settings.toml`

`settings.toml` 是 `blrec` 的本地配置，包含录制房间、输出路径、cookie 等敏感或机器相关内容。它已经被 `.gitignore` 忽略。

新机器上必须准备自己的 `settings.toml`。可以从已有机器复制本地文件，或用 `blrec` Web UI/上游示例重新生成后再按本 fork 的路径约定调整。

不要修改录制输出目录到不兼容的位置。当前处理链默认读取：

```text
./Videos
```

### `.secrets/bilibili.cookie`

`record.sh` 会把可用 cookie 写入：

```text
.secrets/bilibili.cookie
```

这个目录已被忽略，不会提交。启动时 cookie 查找顺序是：

1. `src/upload/bilitool/bilitool/model/config.json`
2. `cookie.json`
3. `cookies.json`
4. `.secrets/bilibili.cookie`
5. `settings.toml` 中已有的 `cookie`

只要其中任意位置还有有效 cookie，就不需要每次重新登录。

### `bilive.toml`

`bilive.toml` 是处理配置，目前仍被 Git 跟踪。它包含 API key 字段，但默认应保持为空。

如果你要在里面填真实 key，提交前必须检查 diff，避免泄漏。更好的做法是只在本地临时修改，或者后续把这些 key 迁移到本地私有配置。

## 登录和 cookie 持久化

第一次使用或 cookie 失效时，登录一次：

```bash
cd /home/zk/projects/bilive
source venv/bin/activate
cd src/upload/bilitool
python -m bilitool.cli login
```

扫码成功后回到仓库根目录：

```bash
cd /home/zk/projects/bilive
export RECORD_KEY=bilive2026
./record.sh
```

`RECORD_KEY` 是 `blrec` Web UI 的访问密码，不是 B 站 cookie。长度必须是 8 到 80 个字符。不要把它写进项目内会提交的文件。

如果想持久化到 shell 配置，可以写到自己的 `~/.bashrc`：

```bash
echo 'export RECORD_KEY=bilive2026' >> ~/.bashrc
source ~/.bashrc
```

## 启动录制

当前运行环境里，录制由 Pi 上的 systemd 服务负责：

```bash
ssh pi
sudo systemctl status bilive
sudo systemctl restart bilive
```

成功后访问：

```text
http://192.168.31.157:2233
```

在 Web UI 中管理房间任务、录制开关和录制状态。

如果 Windows 刚开机，通常等待 15 到 30 秒即可恢复访问。不要手工把录制
目录改到 Pi SD 卡；恢复 timer 会重新建立 `/mnt/win` 并启动录制。

`record.sh` 仍可用于 WSL/Linux 本地开发或重新搭环境，但不是当前 Pi + Windows 分布式运行的日常入口。

## 处理和上传

录制服务只负责产生视频和弹幕文件。切片、ASR、字幕烧录、标题分析和上传都在 PC 端完成。

### Dashboard 一次性切片流

当前推荐入口是 Pi 触发 Windows 计划任务。先在 Windows 注册：

```powershell
cd D:\alldata\pi\bilive
.\install_windows_slice_task.ps1
```

再在 Pi 可访问的 `bilive-server.toml` 中启用：

```toml
[dashboard.remote_worker]
enabled = true
command = ["ssh", "win", "schtasks", "/Run", "/TN", "BiliveSliceOnce"]
timeout = 10
```

之后直接在 `/tasks` 页面点击“启动切片”。流程是：

1. dashboard 扫描 `Videos/<room_id>/*.mp4`，只把整场录播写成 `.mp4.pending`。
2. Pi dashboard 通过 SSH 触发 Windows 手动计划任务 `BiliveSliceOnce`。
3. Windows 任务运行 `run_slice_once.ps1`。
4. 脚本同步启动 `python -m src.server.watcher --once --videos-dir .\Videos`。
5. watcher 只处理 pending 队列，调用 `slice_only()`。
6. `slice_only()` 做弹幕 burst 检测和 ffmpeg 候选切片。
7. 每个候选必须获得非空 ASR、有效段级时间戳，并把窗口弹幕和转录一起交给 LLM。
8. 只有 LLM 明确返回 `keep`、字幕烧录成功、元数据写入成功且队列落库成功，切片才进入自动上传。
9. ASR、LLM、字幕、元数据或队列失败时保留候选供人工复核；LLM 明确 `drop` 时删除候选。
10. 处理结束后 `.mp4.pending` 变成 `.mp4.done`，worker 自动退出，计划任务结束。

兼容入口仍可用：

```powershell
cd D:\alldata\pi\bilive
.\start_pc_worker_api.ps1
```

如果远程触发未启用，浏览器会继续尝试调用本机 `http://127.0.0.1:2235/api/worker/run-once`。

当前默认保留源录播和 XML，方便重跑。只有显式设置：

```powershell
$env:BILIVE_DELETE_SOURCE_AFTER_SLICE = "1"
```

才会在切片完成后删除源文件。

### 单一切片入口

生产切片只允许通过 `src.server.watcher --once` 消费 `.mp4.pending`。旧的全目录扫描入口已经删除，避免重复处理历史录播或误扫切片产物。

### 上传流

切片会把待上传文件写入 SQLite 上传队列。推荐的 PC worker API 会自动启动
上传消费者，无需单独运行命令：

```powershell
cd D:\alldata\pi\bilive
.\start_pc_worker_api.ps1
```

查看状态：

```powershell
Invoke-RestMethod http://127.0.0.1:2235/api/upload/status
```

调试切片、避免投稿时运行 `.\start_pipeline.ps1 -NoUpload`，或在启动
worker API 前设置 `BILIVE_AUTO_UPLOAD=0`。

### 人工反馈精切流

LLM 判定保留的候选会自动入队；`judge_failed` 候选不会自动上传，仍可在
dashboard 人工判断。当前源录播默认保留，不需要再设置 `BILIVE_KEEP_SOURCE`。

在 `/tasks` 标注候选后，再运行：

```powershell
cd D:\alldata\pi\bilive
.\refine_feedback.sh
```

这个入口会扫描 `Videos/**/*_feedback.json`：

- `drop`：跳过，不入上传队列。
- `review`：保留继续人工判断，不入上传队列。
- `keep`：生成新的 `_refined.flv` 和 `_refined_edit.json`，再把精切结果写入上传队列。

精切范围优先使用 dashboard 保存的 `manual_range`。如果没有有效手动范围，则使用 `context_window`；如果两者都没有，会尝试保留完整候选范围。原候选片段不会被覆盖。

## `bilive.toml` 关键配置

### `[model]`

```toml
model_type = "append"
```

可选值：

- `append`：当前推荐默认值，逐段处理。
- `pipeline`：并行处理，吞吐更高。
- `merge`：合并同日分段后处理。

### `[asr]`

```toml
asr_method = "none"
inference_model = "small"
```

可选值：

- `none`：不生成字幕，最快。
- `api`：使用 Groq Whisper API，需要 `whisper_api_key`。
- `deploy`：本地 Whisper，需要模型文件和可用 GPU/CPU。

### `[video]`

控制上传标题、简介、分区和上传线路：

```toml
title = "{artist}直播-{date}"
description = "..."
tid = 138
upload_line = "auto"
reserve_for_fixing = false
```

支持模板变量：

- `{artist}`
- `{date}`
- `{title}`
- `{source_link}`

### `[slice]`

控制自动切片和切片分析：

```toml
auto_slice = false
slice_duration = 60
slice_num = 2
slice_overlap = 30
slice_step = 1
min_video_size = 20
```

`auto_slice` 只影响普通处理流中的附加切片。当前 `slice.sh` 只处理 pending 队列一次，不依赖普通整场渲染流。

生产路径不再通过 `mllm_model` 选择标题生成器。候选统一由
`src.autoslice.candidate_analyzer` 执行 ASR，再由 `[slice.llm_judge]`
配置的 LLM 同时读取转录和窗口弹幕：

```toml
[slice.llm_judge]
provider = "openai-compatible" # 或 local-subprocess
local_command = []
timeout = 120
```

`openai-compatible` 使用 `[slice.multi_modal]` 中的
`visual_model_url` 和 `visual_model_name`。`local-subprocess` 每个候选启动
一次本地命令，从 stdin 读取 JSON，并从 stdout 返回判断 JSON。

### `[slice.omni]`

```toml
enable_quality_filter = true
quality_threshold = 0.5
enable_deep_analysis = true
analysis_prompt = ""
```

这些配置当前主要影响：

- 是否保存 `_analysis.json`，给后续 MCP/二次剪辑使用。
- 是否使用自定义分析 prompt。

自动投稿是否放行只看 LLM 的明确 `keep` 状态，不使用启发式分数兜底。

### `[slice.multi_modal]`

```toml
visual_model_url = "http://localhost:1234/v1"
visual_model_name = "local-model"
whisper_engine = "faster-whisper"
whisper_model = "large-v3"
whisper_device = "cpu"
whisper_compute_type = "int8"
frame_fps = 0.5
enable_visual = false
enable_audio = true
enable_emotion_analysis = false
```

当前生产候选分析：

- 关闭视觉分析，减少显存占用。
- 使用 `faster-whisper` `large-v3` CPU `int8` 做音频转录。
- 字幕烧录只使用 ASR 返回的真实 `transcript_segments` 时间戳；没有真实时间戳时不烧录伪字幕。
- 把转录文本和同一候选时间窗内的弹幕一起交给 LLM 判断和生成标题。
- 不做标题或质量判断降级；分析失败的候选保留人工复核且不自动上传。

本地需有 OpenAI-compatible 服务，例如 LM Studio；当前主路径只发送文本证据，不要求模型支持图片输入。

如果要改成 CUDA，需要先安装可被 faster-whisper/CTranslate2 找到的 CUDA 12 cuBLAS DLL；缺 `cublas64_12.dll` 时会失败。

### `[cover]`

```toml
generate_cover = false
image_gen_model = "minimax"
```

封面生成仍是可选功能。当前 fork 的主流程不依赖它。

## 上传队列

上传队列保存在：

```text
src/db/data.db
```

它已被 `.gitignore` 忽略。队列显式记录
`queued/uploading/uploaded/publishing/published/failed` 状态：

- UPOS 成功后先保存 `remote_filename`，发布失败不会重复上传视频。
- 发布成功后记录 BVID，并按配置删除本地切片和 `.upload.json`。
- 网络和服务错误有限重试，达到上限后变为 `failed`。
- 历史 `locked=1/2` 行不会自动恢复或重传。

## 日志

常用日志位置：

```text
logs/record/      # blrec 启动和录制日志
logs/runtime/     # dashboard/worker/slice/upload 运行日志
logs/scan/        # 处理流程日志
logs/upload/      # 上传流程日志
```

排查顺序：

1. blrec 打不开：SSH 到 Pi，看 `sudo systemctl status bilive`。
2. 页面启动切片没反应：看是否启动了 `start_pc_worker_api.ps1`，以及 `logs/runtime/pc-worker-*.log`。
3. 切片进度异常：看 `logs/runtime/slice-progress.json` 和页面诊断面板。
4. ASR 失败：看 `logs/runtime/pc-worker-*.log` 里的 HuggingFace 下载、`cublas64_12.dll` 或 faster-whisper 错误。
5. 不上传：看 `/api/upload/status`、`logs/runtime/upload-status.json` 和 `upload-process-*.log`。
6. 切片被跳过：看 `min_video_size`、弹幕 burst 诊断和 pending/done 标记。

## 常见问题

### `No cookie found! Please login first`

说明脚本在所有候选位置都没找到有效 `SESSDATA`。重新登录一次：

```bash
cd /home/zk/projects/bilive/src/upload/bilitool
python -m bilitool.cli login
cd /home/zk/projects/bilive
./record.sh
```

成功启动后，cookie 会被写入 `.secrets/bilibili.cookie`，下次无需重复登录，除非 cookie 被 B 站服务端失效。

### 浏览器提示 `ERR_CONNECTION_REFUSED`

通常是目标服务没启动，先确认访问的是哪个端口：

```bash
ssh pi
sudo systemctl status bilive
```

- `http://192.168.31.157:2233`：Pi 上的 `blrec`。
- `/tasks` dashboard：切片页面进程。
- `http://127.0.0.1:2235`：Windows 本机 worker API，只给浏览器触发 worker 用。

如果是本地开发跑 `record.sh`，再检查 `RECORD_KEY`，它必须 8 到 80 个字符。

### 页面提示 `prompt() is not supported`

部分内置浏览器不支持原生弹窗。只要 `/tasks` 页面能显示任务卡片，录制已经正常。必要时可以换系统浏览器访问 `http://localhost:2233`。

### `gio: http://localhost:2233: Operation not supported`

这是 WSL 下 `blrec --open` 自动开浏览器失败的噪音。只影响本地开发入口；当前 Pi systemd 服务不依赖它。

### 候选没有生成字幕或标题

确认环境里有可用的 `faster-whisper` 和模型缓存。当前推荐 `whisper_engine = "faster-whisper"`、`whisper_model = "large-v3"`、`whisper_device = "cpu"`、`whisper_compute_type = "int8"`。

如果日志里出现 HuggingFace 下载失败，先确认模型是否已缓存，或临时配置代理/`HF_TOKEN`。如果日志里出现 `cublas64_12.dll`，说明误用了 CUDA 路径，先改回 CPU 或安装 CUDA 12 运行库。

同时确认 `ffmpeg` 可用：

```bash
ffmpeg -version
```

## 测试和检查

默认测试套件指本机离线、无需真实 API key、无需云 SDK、无需真实视频路径、无需外部服务的快速回归测试。它覆盖当前活跃的 dashboard pending worker 主线、任务状态、进度诊断、字幕烧录、上传元数据等契约。

默认运行：

```bash
source venv/bin/activate
PYTHONPATH=.:./src python -m pytest
```

如果只改了切片主线，可以先跑目标测试：

```bash
PYTHONPATH=.:./src python -m pytest \
  tests/test_slice_control.py \
  tests/test_watcher_once.py \
  tests/test_task_state.py \
  tests/test_slice_only_model_unload.py \
  tests/test_slice_progress.py \
  tests/test_subtitle_burn.py \
  tests/test_dashboard_api.py \
  tests/test_dashboard_frontend.py
```

需要真实 API key、云 SDK、真实媒体文件或外部服务的测试标记为 `integration`，默认不运行。确认本机依赖和密钥都已准备好后再手动运行：

```bash
PYTHONPATH=.:./src python -m pytest -m integration
```

部分上游兼容模块测试标记为 `legacy`。它们仍包含在默认测试套件里；如果只想看当前主路径，可以临时排除：

```bash
PYTHONPATH=.:./src python -m pytest -m "not integration and not legacy"
```

修改 shell 脚本后建议在 Pi 上检查：

```bash
ssh pi "bash -n /mnt/win/bilive/record.sh"
ssh pi "bash -n /mnt/win/bilive/upload.sh"
ssh pi "bash -n /mnt/win/bilive/slice.sh"
git diff --check
```

## 文档站

`docs/` 里仍保留上游 VitePress 文档和本 fork 的一些设计记录。它不是当前 fork 的权威运行说明。

当前仓库维护和清理索引见：

- `docs/project-health.md`
- `docs/scan.md`
- `docs/asr-engines.md`
- `docs/known-issues.md`

如果需要预览：

```bash
npm install
npm run docs:dev
```

## Git 注意事项

这些文件不要提交：

- `settings.toml`
- `.secrets/`
- `cookies.json`
- `cookie.json`
- `src/db/data.db`
- `Videos/*`
- `logs/*` 中的运行日志

提交前至少跑：

```bash
git status --short
git diff --check
git diff --stat
```

如果 `bilive.toml` 里填过真实 API key，提交前必须确认 diff 中没有泄漏。
