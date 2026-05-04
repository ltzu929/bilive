# bilive fork

这个仓库是从上游 `timerring/bilive` fork 后整理出来的本地工作流版本。当前重点不是维护一个通用发行版，而是稳定完成自己的 B 站直播录制、切片分析和上传流程。

当前 README 以本仓库代码和最近 `ltzu / ltzu929` 修改为准。上游文档仍保留在 `docs/`，但其中不少内容和本 fork 的实际运行方式已经不一致。

## 当前定位

这个 fork 主要做四件事：

- 用 `blrec` 录制 B 站直播和弹幕，Web UI 默认在 `http://localhost:2233`。
- 通过 `bilitool` 登录 B 站，并把 cookie 持久化到本地私有文件，避免每次重登。
- 扫描录制完成的视频，处理弹幕、字幕、切片，并把待上传文件写入 SQLite 上传队列。
- 支持独立切片模式，跳过整场渲染，只根据弹幕密度生成切片并上传。

请先确认录制和上传行为符合主播授权、平台规则和你自己的使用场景。本项目不适合未经授权的大规模录制或商业使用。

## 项目现状

### 推荐主路径

当前推荐在 WSL / Linux 下运行：

1. `./record.sh` 启动录制服务。
2. 打开 `http://localhost:2233` 管理录制任务。
3. 另开终端运行 `./upload.sh` 或 `./slice.sh`。

`record.sh` 是本 fork 当前最重要的启动入口。它会：

- 检查 `RECORD_KEY` 长度是否符合 `blrec` 要求。
- 从多个位置查找 B 站 cookie。
- 把 cookie 写入 `.secrets/bilibili.cookie` 做本地持久化。
- 同步更新本地 `settings.toml`。
- 启动 `blrec` 并确认 `127.0.0.1:2233` 真的可连接后才报成功。

### 不再作为主路径的内容

- 上游 README 中的大量推广、通用部署说明和完整模型矩阵不再是本 fork 的主文档。
- Docker / Compose 文件仍在仓库里，但当前没有围绕本 fork 的 cookie 持久化和本地配置策略重新整理，不建议作为首选启动方式。
- `settings.toml` 已从 Git 删除并加入 `.gitignore`，它现在是本机私有配置，不应提交。

## 目录结构

```text
.
├── bilive.toml                 # 项目处理配置，当前仍被 Git 跟踪
├── settings.toml               # blrec 本地私有配置，已忽略，不提交
├── record.sh                    # 录制启动入口
├── upload.sh                    # 普通扫描 + 上传入口
├── slice.sh                     # 独立切片 + 上传入口
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

### WSL / Linux

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

推荐入口：

```bash
cd /home/zk/projects/bilive
source venv/bin/activate
export RECORD_KEY=bilive2026
./record.sh
```

成功后访问：

```text
http://localhost:2233
```

在 Web UI 中管理房间任务、录制开关和录制状态。

## 处理和上传

录制服务只负责产生视频和弹幕文件。处理和上传需要另开终端。

### 普通处理流

```bash
cd /home/zk/projects/bilive
source venv/bin/activate
./upload.sh
```

这个入口会：

- 停掉旧的 `src.burn.scan` 和上传进程。
- 后台启动 `src.burn.scan`。
- 后台启动 `src.upload.upload`。

`src.burn.scan` 会扫描 `Videos/` 下录制完成的文件：

- `model_type = "append"`：逐段处理并上传，适合当前默认本地流。
- `model_type = "pipeline"`：ASR 和渲染队列并行，适合性能更强的环境。
- `model_type = "merge"`：按日期合并后处理，等待更久。

### 独立切片流

```bash
cd /home/zk/projects/bilive
source venv/bin/activate
./slice.sh
```

这个入口会：

- 停掉旧扫描、切片扫描和上传进程。
- 启动 `src.burn.scan_slice`。
- 启动 `src.upload.upload`。

`scan_slice` 只处理录制完成的 `mp4 + xml`，跳过整场弹幕/字幕渲染，直接：

1. 把 XML 弹幕转成 ASS。
2. 根据弹幕密度切片。
3. 调用 `mllm_model` 生成标题或分析结果。
4. 注入标题元数据，生成 `.flv` 切片。
5. 写入上传队列。
6. 默认删除原始录制文件、XML 和 ASS。

本地调试时建议加：

```bash
export BILIVE_KEEP_SOURCE=1
export BILIVE_SKIP_UPLOAD_QUEUE=1
./slice.sh
```

这样会保留原始文件，并跳过写入上传队列，避免误传。

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
mllm_model = "local-audio"
```

`auto_slice` 只影响普通处理流中的附加切片。`slice.sh` 会走独立切片扫描，不依赖普通整场渲染流。

当前支持的 `mllm_model`：

- `local-audio`：默认本地音频分析，适合 8GB 显存或关闭视觉分析的场景。
- `multi-modal`：本地音频 + LM Studio/OpenAI-compatible 视觉模型。
- `qwen-omni`：DashScope Qwen Omni API，返回标题、描述、标签、质量评分等结构化结果。
- `qwen` / `gemini` / `zhipu` / `sensenova`：上游保留的云端标题生成模型。

### `[slice.omni]`

```toml
enable_quality_filter = true
quality_threshold = 0.5
enable_deep_analysis = true
analysis_prompt = ""
```

当 `mllm_model = "qwen-omni"` 或返回 `AnalysisResult` 的本地分析模式启用时，这些配置会影响：

- 是否根据质量评分过滤切片。
- 是否保存 `_analysis.json`，给后续 MCP/二次剪辑使用。
- 是否使用自定义分析 prompt。

### `[slice.multi_modal]`

```toml
visual_model_url = "http://localhost:1234/v1"
visual_model_name = "local-model"
whisper_model = "large-v3"
frame_fps = 0.5
enable_visual = false
enable_audio = true
enable_emotion_analysis = false
```

当前默认更偏向 `local-audio`：

- 关闭视觉分析，减少显存占用。
- 使用本地 Whisper 做音频转录。
- 通过启发式关键词/情绪生成标题、标签和质量评分。

如果要开 `multi-modal`，需要本地有 OpenAI-compatible 服务，例如 LM Studio，并确认模型支持图片输入。

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

它已被 `.gitignore` 忽略。处理流程把待上传文件写入 `upload_queue`，上传进程会循环读取：

- 上传成功：删除视频文件、删除队列记录。
- 上传失败：把队列记录标记为 locked。
- 文件损坏：根据 `reserve_for_fixing` 决定保留还是删除。

## 日志

常用日志位置：

```text
logs/record/      # blrec 启动和录制日志
logs/runtime/     # scan/upload/slice_only 启动日志
logs/scan/        # 处理流程日志
logs/upload/      # 上传流程日志
```

排查顺序：

1. Web UI 打不开：看 `logs/record/` 最新 `blrec-*.log`。
2. 视频不处理：看 `logs/runtime/scan-*.log` 或 `logs/runtime/slice-*.log`。
3. 不上传：看 `logs/runtime/upload-*.log` 和 `logs/upload/`。
4. 切片被跳过：看 `min_video_size`、质量过滤日志和 `BILIVE_SKIP_UPLOAD_QUEUE`。

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

通常是 `blrec` 实际没启动。先确认 `RECORD_KEY`：

```bash
export RECORD_KEY=bilive2026
./record.sh
```

`RECORD_KEY` 必须 8 到 80 个字符。脚本现在会在端口不可连接时直接失败，不再误报。

### 页面提示 `prompt() is not supported`

Codex 内置浏览器不支持部分原生弹窗。只要 `/tasks` 页面能显示任务卡片，录制已经正常。必要时可以换系统浏览器访问 `http://localhost:2233`。

### `gio: http://localhost:2233: Operation not supported`

这是 WSL 下 `blrec --open` 自动开浏览器失败的噪音。推荐入口 `record.sh` 已经不再传 `--open`。

### `local-audio` 没有生成标题

确认环境里有可用的 Whisper 包和模型。相关代码会 `import whisper`，失败时会在 scan 日志里提示。需要时安装：

```bash
python -m pip install openai-whisper
```

同时确认 `ffmpeg` 可用：

```bash
ffmpeg -version
```

## 测试和检查

当前测试里有不少需要真实 API key 或真实视频路径的占位测试，不适合作为完整 CI 直接跑。

可以先跑不依赖外部服务的核心测试：

```bash
source venv/bin/activate
PYTHONPATH=./src python -m unittest \
  tests.test_autoslice.TestAnalysisResult \
  tests.test_autoslice.TestSliceQualityFilter
```

修改 shell 脚本后建议检查：

```bash
bash -n record.sh
bash -n upload.sh
bash -n slice.sh
git diff --check
```

## 文档站

`docs/` 里仍保留上游 VitePress 文档和本 fork 的一些设计记录。它不是当前 fork 的权威运行说明。

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
