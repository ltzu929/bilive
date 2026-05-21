# bilive — B 站直播录制 + 切片 + 上传

> fork 自 timerring/bilive，重构为 Pi（只负责录制）+ PC（负责全部重活：切片、分析、上传）分布式架构。

## 架构概述

**Pi 只做录制，PC 做所有重活。**

```
树莓派 Pi5 (SD卡)                    PC (SSD/HDD + GPU)
┌──────────────────┐                  ┌─────────────────────────────────┐
│ blrec 录制        │──CIFS共享写视频──→│ scan_slice.py 每120s轮询 Videos/ │
│ (无 torch 依赖)   │                  │   → 弹幕 XML→ASS                │
│                  │                  │   → 弹幕密度切片 (ffmpeg)        │
└──────────────────┘                  │   → Whisper 转录 (local-audio)  │
              ↑ CIFS 共享 ↓            │   → 本地 LLM 标题生成          │
          (//192.168.31.202/pi)        │   → 质量筛选 + 编辑指令          │
                                     │   → 注入元数据 (.flv)            │
                                     │   → SQLite 上传队列              │
                                     │   → upload.py 逐条上传 B站      │
                                     └─────────────────────────────────┘
```

### PC 端切片管线详细流程

```
scan_slice.py 每 120s 轮询 Videos/ 目录
  ↓ 找到录制完成的 mp4 + 配对 xml（排除 .flv 和 _slice 文件）
  ↓ 检查文件大小 ≥ 20MB
  ↓
1. 弹幕转换 (xml → ass)                    ← process_danmakus()
2. 获取主播信息                              ← get_video_info()
3. 弹幕突增切片                              ← burst_detector + ffmpeg
   └── burst_ratio=3.0, context=60s(前后各), top_n=3
   ↓
对每个切片（最多3个）串行处理：
  4a. 提取弹幕文本                           ← extract_danmaku_text(xml)
  4b. Whisper 转录 (large-v3, CUDA, faster-whisper) ← extract_audio() → transcribe_audio_whisper()
  4c. LLM 质量判断 + 标题生成                  ← judge_and_title() (qwen3.5-9b via LM Studio)
      └── retain=false → 删除切片，不入队列
  4d. 深度分析 + 编辑指令（可选）               ← maybe_write_edit_outputs()
  4e. 注入元数据 (mp4 → .flv, 标题写入 generate tag) ← inject_metadata() → ffmpeg
  4f. 入 SQLite 上传队列                      ← insert_upload_queue()
  ↓
5. 清理原始文件 (mp4 + xml + ass)             ← 除非 BILIVE_KEEP_SOURCE=1
  ↓
upload.py 轮询 SQLite → 逐条上传 B站
  ├── .flv 切片 → generate_slice_data() 从 ffmpeg 元数据读标题
  ├── .mp4 整场 → generate_video_data() 按模板生成标题
  └── 上传失败 → locked=1, 重试3次
```

### 当前性能瓶颈（按时间开销排序）

| 阶段 | 实现 | 估计耗时(60s切片) | 瓶颈 |
|------|------|-------------------|------|
| 弹幕转换 xml→ass | process_danmakus | ~1s | 无 |
| 弹幕密度切片 | autosv + ffmpeg | ~2-3s | 无 |
| **Whisper 转录** | large-v3, faster-whisper, CUDA | **3-8s** | ✅ 已优化 |
| LLM 质量判断+标题 | qwen3.5-9b via LM Studio | ~5-15s | 取决于 LM Studio |
| 注入元数据 | ffmpeg copy | ~1s | 无 |
| 上传 | bilitool 单线程 | 取决于网速 | 无并行 |

### 关键代码文件对应

| 流程步骤 | 代码文件 | 关键函数/类 |
|---------|---------|------------|
| 轮询入口 | `src/burn/scan_slice.py` | `process_folder_slice_only()` |
| 切片主流程 | `src/burn/slice_only.py` | `slice_only()` |
| 弹幕突增检测 | `src/autoslice/burst_detector.py` | `detect_bursts()` → `BurstEvent` |
| 弹幕切片调度 | `src/autoslice/danmaku_slice.py` | `slice_video_by_danmaku()` → `GeneratedSlice` |
| 密度核心算法(旧) | `src/autoslice/auto_slice_video/autosv/` | `find_dense_periods()`, `slice_video()` |
| 音频提取+转录 | `src/autoslice/mllm_sdk/audio_analyzer.py` | `extract_audio()`, `transcribe_audio_whisper()` |
| LLM 质量判断+标题 | `src/autoslice/mllm_sdk/judge.py` | `judge_and_title()` → `JudgeResult` |
| LLM 标题生成(旧) | `src/autoslice/mllm_sdk/multi_modal_analyzer.py` | `_llm_generate_title()`, `combine_analysis()` |
| 标题生成调度 | `src/autoslice/title_generator.py` | `generate_title()` 装饰器分发 model_type |
| 质量筛选(旧) | `src/autoslice/slice_quality_filter.py` | `should_retain_slice()` (已被 LLM judge 替代) |
| 编辑指令 | `src/autoslice/edit_instruction_builder.py` | `maybe_write_edit_outputs()` |
| 元数据注入 | `src/autoslice/inject_metadata.py` | `inject_metadata()` |
| 上传队列 | `src/db/conn.py` | SQLite upload_queue 表 |
| 上传消费 | `src/upload/upload.py` | `upload_video()`, `upload_loop()` |
| 切片上传数据 | `src/upload/generate_upload_data.py` | `generate_slice_data()` |
| 反馈精剪 | `src/burn/feedback_refine.py` | Dashboard keep → 重新精剪 |

### 两条管线的区别

| 特性 | `scan.py` (PC 完整流程) | `scan_slice.py` (切片专用) |
|------|----------------------|--------------------------|
| 用途 | 整场渲染+上传 | 仅切片+上传 |
| 渲染 | 烧录弹幕字幕到视频 | 不渲染，直接切原始视频 |
| Whisper | 仅 `model_type != "pipeline"` | 始终在 local-audio 模式 |
| 启动脚本 | `upload.sh` | `slice.sh` |
| 清理 | 删除 mp4+xml+ass+srt+jsonl | 删除 mp4+xml+ass |

## Pi 端部署（树莓派）

### 环境

- 树莓派 5，Ubuntu，用户 `ubuntu`
- Python 环境：miniforge (conda)，环境名 `bilive`
- 项目路径：`/mnt/win/bilive/bilive`（CIFS 挂载自 PC）
- PC IP：`192.168.31.202`，Pi IP：`192.168.31.157`

### 系统依赖

```bash
# ffmpeg 是必须的——blrec 录制完成后用它 remux flv→mp4
sudo apt-get install -y ffmpeg
```

### 首次部署（只需做一次）

```bash
# 1. 挂载共享文件夹（永久）
sudo mkdir -p /mnt/win
# fstab 已配置，重启自动挂载。手动挂载用：
sudo mount -t cifs //192.168.31.202/pi /mnt/win \
  -o credentials=/etc/samba/credentials,iocharset=utf8,vers=3.0,uid=1000,gid=1000

# 2. 创建 conda 环境 + 安装依赖
source ~/miniforge/etc/profile.d/conda.sh
conda create -n bilive python=3.12 -y
conda activate bilive
pip install httpx toml 'setuptools<69'
pip install /mnt/win/bilive/bilive/wheel/blrec-2.0.0b4-py3-none-any.whl
```

### 日常操作

blrec 已注册为 systemd 服务，通过 Dashboard 或 systemctl 管理：

```bash
# 查看状态
sudo systemctl status bilive

# 启动 / 停止 / 重启
sudo systemctl start bilive
sudo systemctl stop bilive
sudo systemctl restart bilive

# 查看日志
sudo journalctl -u bilive -f

# Web UI: http://192.168.31.157:2233
```

scanner（扫描器）需手动启动：`cd /mnt/win/bilive && ./agent.sh`

### systemd 服务配置

服务文件：`deploy/bilive.service`，已在 Pi 上注册并启用。

关键配置：
- 使用 conda `bilive` 环境的 python 直接启动 blrec
- `RECORD_KEY` 从 `/mnt/win/bilive/.secrets/env` 读取（EnvironmentFile）
- 配置文件：`-c /mnt/win/bilive/settings.toml`
- 视频输出：`--out-dir /mnt/win/bilive/Videos`
- 端口：2233

### 依赖兼容性

> blrec 2.0.0b4 要求旧版依赖。如重装环境需注意版本锁定：

```bash
conda create -n bilive python=3.12 -y
conda activate bilive
pip install httpx toml 'setuptools<69'
pip install /mnt/win/bilive/bilive/wheel/blrec-2.0.0b4-py3-none-any.whl
pip install 'pydantic<2.0.0' 'fastapi>=0.88.0,<0.89.0' 'uvicorn[standard]>=0.20.0,<0.21.0' 'email-validator>=1.1.3,<2.0.0'
```

### SD 卡写入说明

Pi 端所有写入操作都在 CIFS 共享盘（`/mnt/win/bilive/`）上：
- 视频文件 → `/mnt/win/bilive/bilive/Videos/`
- 日志文件 → `/mnt/win/bilive/bilive/logs/`
- `.pending`/`.done` 标记 → 视频同目录

SD 卡上只有：
- 操作系统 + conda 环境（只读）
- Python 进程内存（不写磁盘）

ffmpeg 二进制在 SD 卡（一次性几十 MB），但 remux 读写都在 CIFS 共享盘，不磨损 SD 卡。

扫描器每 120 秒检查一次目录（纯读操作，走网络），不损耗 SD 卡。

> ⚠️ `settings.toml` 中 `delete_source = "never"` 意味着录制完成后源 `.flv` 文件不删除。
> 这是故意的——为了保证切片管线能正常运行，PC 端的 `scan_slice.py` 已适配此行为（只跳过正在录制中的 `.flv`，详见「已知问题」）。

### Pi 端依赖（requirements-agent.txt）

```
httpx>=0.24.0
toml>=0.10.0
```

Pi 端不装 torch、whisper 等重型包。重型处理全部在 PC 端完成。

### 关键路径

| 类型 | 路径 | 说明 |
|------|------|------|
| 项目代码 | `/mnt/win/bilive/bilive/` | CIFS 共享，PC 也可读写 |
| 视频输出 | `/mnt/win/bilive/bilive/Videos/` | blrec 录制输出 |
| 日志 | `/mnt/win/bilive/bilive/logs/` | 写入共享盘，不损耗 SD 卡 |
| conda 环境 | `~/miniforge/envs/bilive/` | 本地 SD 卡 |
| cookie | `/mnt/win/bilive/.secrets/bilibili.cookie` | 共享盘 |

## PC 端部署

### 环境

- Windows 11，RTX 4060 (8GB VRAM)
- Python 3.13（注意：requirements.txt 锁定旧版依赖，部分包需单独安装）
- LM Studio：`D:\LMStudio\LM Studio\LM Studio.exe`（本地 LLM，API 端口 6542）
- ffmpeg：`C:\Users\zk\AppData\Local\Microsoft\WinGet\Links\ffmpeg.exe`（winget 安装）

### 依赖安装

```bash
cd bilive
python -m venv venv
source venv/bin/activate

# 创建 venv（CIFS 上需 --copies，这里放本地磁盘不需要）
# 注意：Python 3.13 与 requirements.txt 中 torch<2.3.0 / numpy<1.26.4 不兼容

# 先装核心依赖
pip install -r requirements.txt  # 部分包会失败，忽略

# torch CUDA 版（requirements.txt 锁的版本太旧，Python 3.13 需要 2.6+）
pip install torch --index-url https://download.pytorch.org/whl/cu130

# 新版 openai-whisper（项目自带旧版 src/subtitle/whisper/ 不支持 large-v3）
pip install openai-whisper

# faster-whisper（推荐：CTranslate2 后端，比 openai-whisper 快 3-5x）
pip install faster-whisper

# 缺失的轻量包
pip install pysrt tiktoken more-itertools zhconv groq
```

### 配置要点（bilive-server.toml）

| 配置项 | 当前值 | 说明 |
|--------|--------|------|
| `model_type` | `append` | 管线模式：pipeline/append/merge |
| `asr_method` | `none` | 全局 ASR，但 local-audio 模式内部自己调 Whisper |
| `slice_method` | `burst` | 切片算法：`density`(旧) 或 `burst`(新-突增检测) |
| `burst_ratio` | `3.0` | 突增阈值：局部密度/背景密度 ≥ 3x |
| `burst_context` | `60` | 峰值前后各取秒数（切片总长 120s） |
| `burst_top_n` | `3` | 最多选几个突增事件 |
| `mllm_model` | `local-audio` | 切片标题生成模式（Whisper/Qwen3-ASR + LM Studio LLM） |
| `whisper_model` | `Qwen/Qwen3-ASR-1.7B` | ASR 模型：Qwen3 HuggingFace ID 或 Whisper 模型名 |
| `whisper_engine` | `qwen3-asr` | ASR 引擎：`qwen3-asr`(推荐) / `openai-whisper` / `faster-whisper` |
| `whisper_device` | `cuda` | 推理设备：`cuda`(GPU) 或 `cpu` |
| `visual_model_url` | `http://100.118.141.26:6542/v1` | LM Studio 服务地址 |
| `visual_model_name` | `qwen/qwen3.5-9b` | LM Studio 模型名 |
| `enable_visual` | `false` | 视觉分析（8G 显存建议关） |
| `enable_audio` | `true` | 音频分析（ASR 转录） |
| `min_video_size` | `20` | 最小视频大小（MB） |
| `enable_quality_filter` | `true` | OMNI 质量筛选开关 |
| `quality_threshold` | `0.5` | 质量筛选阈值 |
| `enable_deep_analysis` | `true` | 深度分析（为 MCP 剪辑准备数据） |
| `enable_edit_instruction` | `true` | 编辑指令输出 |

**切片决策机制**（2026-05-21 更新）：
1. **弹幕突增检测**（`burst_detector.py`）：检测弹幕密度突增事件（burst_ratio ≥ 3x），峰值前后各 60s 切片
2. **LLM 质量判断**（`judge.py`）：弹幕文本 + ASR 字幕 → 单次 LLM 调用同时判断 retain + 生成标题
3. **Qwen3-ASR**（2026 年最新）：1.7B 参数，中文 CER 3.2%（vs Whisper large-v3 12%+），RTX 4060 8GB 可跑
4. **faster-whisper**（CTranslate2 后端）：large-v3 + CUDA，比 openai-whisper 快 3-5x，但需 CUDA Toolkit 12.x

**回滚配置**：`whisper_engine = "openai-whisper"` + `whisper_model = "large-v3-turbo"` 恢复 Whisper 方案。

### Qwen3-ASR（推荐，2026 年中文 SOTA）

Qwen3-ASR 是阿里 2026 年 1 月发布的新一代 ASR 模型，中文识别准确率远超 Whisper。

| 模型 | 参数 | 显存 (FP16) | 中文 CER | 方言 | 速度 |
|------|------|------------|---------|------|------|
| Qwen3-ASR-1.7B | 1.7B | ~5 GB | **3.2%** | 22种 ✅ | ~800x 实时 |
| Qwen3-ASR-0.6B | 0.6B | ~2 GB | ~3.8% | 22种 ✅ | ~2000x 实时 |
| Whisper large-v3 | 1.6B | ~10 GB | 12-19% | ❌ | 1x |
| Whisper large-v3-turbo | 0.8B | ~5 GB | ~12% | ❌ | ~8x |

**安装**：
```bash
pip install qwen-asr
```

**首次运行**：模型约 3.4GB，从 HuggingFace 下载。建议设 `HF_TOKEN` 环境变量加速（同 faster-whisper 预下载说明）。

**配置**（`bilive-server.toml`）：
```toml
[slice.multi_modal]
whisper_engine = "qwen3-asr"
whisper_model = "Qwen/Qwen3-ASR-1.7B"   # 或 "Qwen/Qwen3-ASR-0.6B"
whisper_device = "cuda"
```

**代码位置**：`src/autoslice/mllm_sdk/audio_analyzer.py` → `_transcribe_qwen3_asr()`

### ASR 引擎对比

| 引擎 | 配置值 | 后端 | 中文精度 | GPU 需求 | 状态 |
|------|--------|------|---------|---------|------|
| Qwen3-ASR | `qwen3-asr` | transformers | ⭐⭐⭐ SOTA | CUDA (5GB) | ✅ 推荐 |
| openai-whisper | `openai-whisper` | PyTorch | ⭐ 一般 | CUDA (5GB) | ✅ 可用 |
| faster-whisper | `faster-whisper` | CTranslate2 | ⭐ 一般 | CUDA 12 Toolkit | ❌ cuBLAS 缺失 |

### faster-whisper 模型预下载

faster-whisper 使用 CTranslate2 格式的模型文件（~3GB），**首次运行需要从 HuggingFace 下载**。如果未设 `HF_TOKEN` 环境变量，下载会被限速，可能耗时数小时。

**检查模型是否已下载**：
```powershell
# 缓存路径（Windows）
dir $env:USERPROFILE\.cache\huggingface\hub\models--Systran--faster-whisper-large-v3
# 完整模型约 3GB
```

**加速下载**：
1. 在 https://huggingface.co/settings/tokens 创建 token
2. 设环境变量 `$env:HF_TOKEN = "hf_xxx"` 后运行一次
3. 或用 `openai-whisper` 引擎临时过渡（openai-whisper 模型在 `~/.cache/whisper/large-v3.pt`，格式不同，通常已预装）

**两种引擎对比**：

| 引擎 | 后端 | 速度 | 显存 | 模型缓存路径 |
|------|------|------|------|-------------|
| `faster-whisper` | CTranslate2 | 快 3-5x | ~4GB | `~/.cache/huggingface/hub/models--Systran--faster-whisper-large-v3/` |
| `openai-whisper` | PyTorch | 基准 | ~3GB | `~/.cache/whisper/large-v3.pt` |

### 日常操作 — PC 端启动切片管线

PC 端需要同时运行三个进程（可按需启动）：

| 进程 | 命令 | 用途 |
|------|------|------|
| LM Studio | 启动 `D:\LMStudio\LM Studio\LM Studio.exe`，自动加载上次模型 | LLM 推理服务，端口 6542 |
| scan_slice | `$env:PYTHONPATH=".\src"; python -m src.burn.scan_slice` | 每 120s 扫描 Videos/，检测完成录制 → 切片 |
| upload | `$env:PYTHONPATH=".\src"; python -m src.upload.upload` | 每 120s 轮询 SQLite 上传队列 |

**快速启动（PowerShell，在项目根目录 `D:\alldata\pi\bilive` 下执行）**：

```powershell
# 1. 启动 LM Studio（如已在运行可跳过）
Start-Process "D:\LMStudio\LM Studio\LM Studio.exe" -WindowStyle Minimized

# 2. 等待 LM Studio API 就绪（约 15 秒）
do { Start-Sleep 3; try { $null = Invoke-WebRequest "http://100.118.141.26:6542/v1/models" -UseBasicParsing -TimeoutSec 2 } catch { $false } } until ($?)

# 3. 启动扫描器 + 上传器
$env:PYTHONPATH = ".\src"
Start-Process python -ArgumentList "-m", "src.burn.scan_slice" -WindowStyle Minimized
Start-Process python -ArgumentList "-m", "src.upload.upload" -WindowStyle Minimized
```

**停止**：
```powershell
Get-Process python | Where-Object { $_.MainWindowTitle -eq "" } | Stop-Process
Get-Process "LM Studio" -ErrorAction SilentlyContinue | Stop-Process
```

**自动启动脚本**：项目根目录提供了 `run_slice.ps1` 和 `run_upload.ps1`，包含日志记录和环境变量设置（`PYTHONUTF8=1` 修复 GBK 编码问题）。

### 已知问题

#### scan_slice 跳过逻辑与 blrec `delete_source = "never"` 冲突

`scan_slice.py` 的 `process_folder_slice_only()` 检查文件夹内是否有 `.flv` 文件来判断是否正在录制——如果有，跳过整个文件夹。但 blrec 配置了 `delete_source = "never"`（`settings.toml` 第 60 行），录制完成后的源 `.flv` 文件从不删除。

**后果**：`scan_slice.py` 会永久跳过所有包含旧 `.flv` 的文件夹，导致切片管线不处理任何录制。

**已修复**（2026-05-21）：改为只跳过「没有配对 `.mp4`」的 `.flv`（即正在录制中的），同时排除切片输出文件（含 `_slice` 标记的 `.flv`）。详见 `src/burn/scan_slice.py` 第 24-40 行。

#### PowerShell 窗口关闭导致进程崩溃

用 `Start-Process -WindowStyle Minimized` 启动的子进程仍绑定到当前 PowerShell session。**关闭 PowerShell 窗口会发送 close 信号给所有子进程**，导致 `forrtl: error (200)` 崩溃（Intel MKL 收到 window-CLOSE 事件）。

**解法**：
- 使用 `pythonw.exe` 替代 `python.exe`（无控制台窗口，完全脱离终端）
- 或注册为 Windows 任务计划程序（`taskschd.msc`），触发器设为「登录时」或「每天定时」
- 或 WSL 内运行（不受 Windows 终端生命周期影响）

#### B 站上传认证 —— 账号未登录（未解决，AGENTS.md 已记录）

详见下方「B 站上传认证」和「B 站发布接口」章节。

### 待做：程序自管理 LLM 模型生命周期

当前依赖 LM Studio 独立服务，需要手动加载模型。计划改为程序内直接加载模型（用 `llama-cpp-python` 或 `transformers`），实现：
- 切片需要时自动加载模型到 GPU
- 用完自动卸载释放显存
- 不再依赖 LM Studio 常驻运行
- fallback 保留（模型加载失败时用模板标题 + 默认保留）

方案待定：`llama-cpp-python`（轻量，GGUF 格式）vs `transformers`（HuggingFace 原生）。优先级 P2。

### LLM 标题生成 —— Qwen 3.5 max_tokens 陷阱
`local-audio` 模式下，弹幕文本 + Whisper 字幕 → 本地 LLM（LM Studio）生成标题/简介。
**不要设 `max_tokens`**——Qwen 3.5 是推理模型，推理过程写入 `reasoning_content`，最终答案写入 `content`。
设了 `max_tokens`（如 2000）会导致推理吃光所有 token，`content` 为空，标题降级到模板。
去掉 `max_tokens` 后模型完整推理完才会在 `content` 输出 JSON，中文正常。
LM Studio 未运行时自动降级到模板标题。
相关代码：`src/autoslice/mllm_sdk/multi_modal_analyzer.py` → `_llm_generate_title()`。

### B 站上传认证 —— cookie 格式

bilitool 上传模块期望 cookie 文件是特定的 JSON 格式（`{data: {cookie_info: {cookies: [...]}}}`），
而 `.secrets/bilibili.cookie` 是分号分隔的文本格式。

**cookie 同步工具**：运行 `python sync_cookie.py` 可自动将 `.secrets/bilibili.cookie` 转换为
`cookie.json`（bilitool 期望的格式）并同步更新 `config.json` 中的 cookie 值。

上传 worker 启动时会先调 `LoginController().check_bilibili_login()` 检查 config.json 中
的 cookie 是否有效（GET `api.bilibili.com/x/web-interface/nav`）。若未登录，则尝试加载 `cookie.json`。

### B 站发布接口 —— csrf + form-encoded
`publish_video()` 在 `src/upload/bilitool/bilitool/upload/bili_upload.py`。
发布接口 `/x/vu/client/add` 需要 `csrf` 字段（值= `bili_jct` cookie），
且请求必须用 `data=`（form-encoded）而非 `json=`，否则 B 站返回"csrf 校验失败"。

### B 站发布接口 —— 账号未登录（未解决）
即使 cookie 在 GET 请求（`api.bilibili.com`、`member.bilibili.com`）中验证为已登录，
POST `/x/vu/client/add` 仍返回 code=-101 "账号未登录"。已尝试：不同 Referer、csrf 放 URL/body、
SESSDATA 编解码——均无效。可能是 B 站改了发布接口认证方式，或 cookie 中 `bili_jct` 与 `SESSDATA`
之间存在某种不匹配。上传流程中视频文件已成功传到 CDN（preupload → chunk upload → finish 均通过），
仅最后发布一步失败。待排查。

### Windows subprocess 编码 —— GBK 污染 flv 元数据
`inject_metadata()` 用 `subprocess.run(text=True)` 调 ffmpeg 写标题元数据。
Windows 上 `text=True` 默认用 GBK 编码命令行参数，导致 flv 的 `generate` 标签写入 GBK 字节，
后续 `ffprobe` 读出来是乱码。应显式设置 `encoding="utf-8"` 或设环境变量 `PYTHONUTF8=1`。

## 文件清单

```
# ── PC 端配置 ──
├── bilive-server.toml              # PC 完整配置（GPU/模型/ASR/切片）
├── bilive.toml                     # 通用配置模板（PC/Pi 共用参数）

# ── 启动脚本 ──
├── slice.sh                        # PC 启动切片管线 (scan_slice + upload)
├── upload.sh                       # PC 启动完整渲染管线 (scan + upload)
├── server.sh                       # PC 启动 watcher + upload
├── record.sh                       # PC/WSL 启动 blrec 录制
├── record-pi.sh                    # Pi 启动 blrec 录制
├── agent.sh                        # Pi 启动扫描器
├── refine_feedback.sh              # Dashboard 反馈精剪

# ── 配置模块 ──
├── src/config/
│   ├── base.py                     # 共享路径加载（环境变量覆盖）
│   ├── server_config.py           # PC 端完整配置（GPU/模型/ASR/OMNI）
│   └── agent_config.py             # Pi 端精简配置（无 torch）

# ── 切片管线（PC 端核心流程）──
├── src/burn/
│   ├── scan_slice.py               # 切片扫描器入口（每120s轮询 Videos/）
│   ├── slice_only.py                # 切片主流程（不渲染，直接切原始视频）
│   ├── scan.py                     # 完整渲染扫描器（弹幕烧录+切片+上传）
│   ├── render_video.py             # 渲染+切片（整场直播）
│   ├── render_then_merge.py        # 多段合并渲染
│   ├── render_command.py            # ffmpeg 烧录命令
│   ├── render_queue.py             # 渲染队列
│   └── feedback_refine.py          # Dashboard 反馈精剪

# ── 自动切片核心 ──
├── src/autoslice/
│   ├── danmaku_slice.py            # 弹幕密度计算 + 切片 + 弹幕文本提取
│   ├── title_generator.py          # 标题生成调度器（装饰器分发 model_type）
│   ├── slice_quality_filter.py     # 质量筛选（score ≥ threshold）
│   ├── inject_metadata.py          # ffmpeg 注入标题元数据 (mp4→flv)
│   ├── analysis_result.py          # OMNI 分析结果数据类
│   ├── edit_instruction.py         # 编辑指令数据类
│   ├── edit_instruction_builder.py # 分析结果 → 编辑指令
│   ├── prompt_packager.py          # Prompt 打包
│   ├── auto_slice_video/           # 弹幕密度算法子模块
│   │   └── autosv/
│   │       ├── autosv.py           # 入口
│   │       ├── calculate/
│   │       │   ├── selection.py    # find_dense_periods 核心算法
│   │       │   ├── sliding_cpu.py  # CPU 滑动窗口
│   │       │   └── sliding_gpu.py  # GPU 滑动窗口（未使用）
│   │       └── slice/
│   │           └── slice_video.py   # ffmpeg 切片执行
│   └── mllm_sdk/                  # MLLM 分析引擎
│       ├── multi_modal_analyzer.py # 综合分析入口（Whisper + LLM）
│       ├── audio_analyzer.py       # 音频提取 + Whisper 转录 (device="cpu")
│       ├── visual_analyzer.py      # 截帧 + VLM 分析
│       ├── qwen_omni_sdk.py        # Qwen OMNI API 模式
│       ├── qwen_sdk.py             # Qwen API 模式
│       ├── gemini_old_sdk.py       # Gemini API 模式
│       ├── zhipu_sdk.py            # 智谱 API 模式
│       └── sensenova_sdk.py        # 商汤 API 模式

# ── 上传模块 ──
├── src/upload/
│   ├── upload.py                  # 上传消费者（轮询 SQLite 队列）
│   ├── generate_upload_data.py    # 上传元数据生成（切片/整场）
│   ├── extract_video_info.py      # ffprobe 提取视频信息
│   ├── query_search_suggestion.py # B 站搜索建议
│   └── bilitool/                  # B 站上传工具库

# ── 弹幕处理 ──
├── src/danmaku/
│   └── generate_danmakus.py       # XML → ASS 转换 + 分辨率检测

# ── 字幕 ──
├── src/subtitle/
│   ├── subtitle_generator.py      # Whisper 字幕生成（整场渲染用）
│   └── whisper/                   # 旧版 Whisper（不支持 large-v3）

# ── Agent / Server ──
├── src/agent/scanner.py           # Pi 端扫描器（检测新视频 + 写 .pending）
├── src/server/watcher.py          # PC 端监控（发现 .pending → 处理管线）

# ── 数据库 ──
├── src/db/
│   └── conn.py                    # SQLite 上传队列

# ── Dashboard ──
├── src/dashboard/                 # Web 管理界面（查看/保留/丢弃切片）

# ── Pi 端配置 ──
├── bilive-agent.toml              # Pi 端配置（精简，无重型模型参数）
├── settings.toml                  # blrec 录制配置（房间号、输出路径等）
├── requirements-agent.txt         # Pi 端最小依赖

# ── 部署 ──
├── deploy/bilive.service          # Pi 端 systemd 服务文件
```
