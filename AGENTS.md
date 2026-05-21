# bilive — B站直播录制 + 切片 + 上传

> Pi 录制，PC 做 AI 重活（切片 / 转录 / 标题 / 上传）。分布式架构，通过 CIFS 共享 Videos/ 目录。

## 架构

```
树莓派 Pi5 (ARM)                    PC (Win11, RTX 4060 8GB)
┌──────────────────┐                ┌──────────────────────────────┐
│ blrec 录制        │──CIFS共享写──→│ scan_slice.py 每120s轮询      │
│ 原画+弹幕(.mp4/.xml)│              │  → Qwen3-ASR-1.7B 转录       │
│ systemd 自动启动   │               │  → LM Studio 标题/质量判断    │
└──────────────────┘                │  → ffmpeg 切片+注入元数据     │
                                    │  → SQLite上传队列             │
                                    │  → upload.py 逐条上传B站      │
                                    └──────────────────────────────┘
```

## 关键文件

| 文件 | 作用 |
|------|------|
| `src/burn/scan_slice.py` | 切片扫描器入口，每120s轮询 Videos/ |
| `src/burn/slice_only.py` | 切片主流程：弹幕转换→burst检测→转录→LLM→注入→入队列 |
| `src/autoslice/mllm_sdk/audio_analyzer.py` | ASR 核心：Qwen3-ASR / Whisper 转录 |
| `src/autoslice/burst_detector.py` | 弹幕突增检测（ratio≥3x, top3, ±60s） |
| `src/autoslice/mllm_sdk/judge.py` | LLM 质量判断 + 标题生成 |
| `src/upload/upload.py` | 上传消费：轮询 SQLite → 上传 B站 |
| `bilive-server.toml` | PC 端配置 (ASR/LLM/切片参数) |
| `settings.toml` | Pi 端 blrec 录制配置 |
| `start_pipeline.ps1` | 一键启动全部 PC 组件 |
| `sync_cookie.py` | Cookie 格式转换 (.secrets → bilitool JSON) |

完整文件清单 → `docs/` 目录。

## PC 端操作

```powershell
# 一键启动（在项目根目录）
.\start_pipeline.ps1

# 单独启动
.\run_slice.ps1      # 仅切片扫描
.\run_upload.ps1     # 仅上传

# 查看日志
Get-Content logs\runtime\slice-*.log -Wait -Tail 20
```

> 进程用 `pythonw.exe` 启动，关闭 PowerShell 窗口不影响运行。
> 停止：`Get-Process python | Stop-Process`

## Pi 端操作

```bash
# 录制服务
sudo systemctl status bilive     # 查看状态
sudo systemctl restart bilive    # 重启
# Web UI: http://192.168.31.157:2233
```

Pi 只跑 blrec。conda 环境 `bilive`，代码路径 `/mnt/win/bilive/`（CIFS 挂载）。

## 当前状态

| 组件 | 状态 |
|------|------|
| Pi blrec 录制 | ✅ systemd 运行中 |
| Qwen3-ASR-1.7B | ✅ 中文 CER 3.2%，模型已缓存 |
| LM Studio LLM | ⚠️ 需手动启动 (`D:\LMStudio\LM Studio\LM Studio.exe`) |
| 切片产出 | ✅ 正常 |
| B站上传 | ⚠️ 文件已传CDN，发布接口 code=-101（未解决） |
| faster-whisper | ❌ 缺 cuBLAS DLL |

## 关键坑位

1. **别关 PowerShell 窗口** ← `start_pipeline.ps1` 已用 `pythonw.exe` 修复
2. **`delete_source = "never"`** ← blrec 不删 .flv，`scan_slice.py` 已适配
3. **B站发布 code=-101** ← 已知未解决，详见 `docs/known-issues.md`
4. **Whisper 模型下载慢** ← 设 `HF_TOKEN` 环境变量加速
5. **faster-whisper cuBLAS** ← CUDA 13 驱动缺 `cublas64_12.dll`，用 Qwen3-ASR 替代

## 详细文档

| 文档 | 内容 |
|------|------|
| `docs/known-issues.md` | 已知 bug 及修复状态 |
| `docs/asr-engines.md` | ASR 引擎对比、安装、预下载 |
| `docs/scan.md` | 切片管线详细流程 |
| `docs/upload.md` | 上传流程、cookie 认证问题 |
| `docs/setup.md` | PC/Pi 首次部署步骤 |
| `docs/models.md` | 模型选择与性能对比 |
