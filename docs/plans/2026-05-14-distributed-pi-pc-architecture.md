# bilive 分布式架构重构计划 v2

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 bilive 从单机架构重构为 Pi（录制+扫描）+ PC（处理+上传）的分布式架构，利用共享文件系统通信，零 HTTP 依赖。

**Architecture:** Pi 运行 blrec 录制和轻量 scanner，视频输出到 NFS 共享目录。Scanner 检测到新视频后写 `.pending` 标记文件到同一 NFS。PC 运行 watcher 监控 `.pending` 文件，发现后执行现有处理管线（弹幕转换→Whisper→切片→MLLM→上传），完成后改为 `.done`。

**Tech Stack:** Python 3.10+, toml, blrec, ffmpeg, whisper, torch

---

## 架构图

```
树莓派 Pi5 (SD卡)                      PC (SSD/HDD)
┌───────────────────┐                  ┌────────────────────────────┐
│ bilive-agent       │                  │ bilive-server               │
│ ├─ blrec 录制     │──写视频到NFS──→ │ /Videos/22966160/xxx.mp4    │
│ │  (out_dir=NFS)  │                  │ /Videos/xxx.mp4.pending     │ ← Pi 写标记
│ └─ scanner.py     │                  │                              │
│    (检测新文件)    │                  │ watcher 监控 .pending        │
│    写.pending标记  │                  │   → 弹幕转换(xml→ass)        │
│                   │                  │   → Whisper ASR               │
│ SD卡只存:          │                  │   → 弹幕密度切片              │
│ - OS + Python     │                  │   → MLLM分析+标题生成         │
│ - blrec wheel     │                  │   → 封面生成                  │
│ - agent代码       │                  │   → 改 .pending → .done      │
│ - 日志→NFS        │                  │   → 入上传队列                │
└───────────────────┘                  │   → Upload worker 上传       │
                                       │   → Dashboard              │
                                       └────────────────────────────┘
                 ↑ NFS/SMB 共享 ↓
            (两个路径指向同一物理磁盘)
```

## 通信机制：.pending 标记文件

```
1. Pi scanner 检测到新视频 xxx.mp4
2. Pi 在同目录写 xxx.mp4.pending（内容: JSON 元数据，含相对路径）
3. PC watcher 检测到 .pending 文件
4. PC 读取元数据，拼接本地绝对路径，执行完整处理管线
5. PC 处理完成后将 .pending 改为 .done
6. 如果 PC 处理失败，.pending 保留，下次重试
```

关键：`.pending` 中只存**相对路径**（如 `22966160/xxx.mp4`），PC 拼接自己的 `VIDEOS_DIR`。

---

## 文件结构规划

### 新增文件
```
src/
├── agent/                      # Pi 端轻量 agent
│   ├── __init__.py
│   └── scanner.py              # 文件扫描 + 写 .pending 标记
├── server/                     # PC 端处理逻辑
│   ├── __init__.py
│   └── watcher.py              # 监控 .pending 文件 + 调用处理管线
src/config/                     # 重构后的配置模块
├── __init__.py
├── base.py                     # 共享配置加载逻辑
├── agent_config.py              # Pi 端配置（无 torch）
└── server_config.py             # PC 端配置（完整）
```

### 修改文件
```
src/config.py                   # 重构为 lazy import + 重导出
src/db/conn.py                  # DB 路径支持环境变量配置
src/autoslice/title_generator.py # 确保 config lazy
src/cover/cover_generator.py    # 同上
src/burn/scan_slice.py          # 保留兼容入口
```

### 新增配置
```
bilive-agent.toml               # Pi 端精简配置
bilive-server.toml              # PC 端完整配置（基于现有 bilive.toml）
agent.sh                        # Pi 端启动脚本
server.sh                       # PC 端启动脚本
requirements-agent.txt          # Pi 端最小依赖
```

---

## Task 1: 解耦 config.py — 消除模块级 torch 依赖

**目标:** 让 Pi 端能在没有 torch 的环境下导入配置模块而不崩溃。这是最高优先级，不做这个 Pi 上任何代码都跑不起来。

### 步骤

- [ ] 1.1 创建 `src/config/__init__.py`
- [ ] 1.2 创建 `src/config/base.py` — 共享路径和配置加载
  - `load_config_from_toml()` 移入
  - 路径通过环境变量覆盖: `BILIVE_DIR`, `BILIVE_VIDEOS_DIR`, `BILIVE_LOG_DIR`, `BILIVE_DB_PATH`
  - **不导入 torch**
- [ ] 1.3 创建 `src/config/agent_config.py` — Pi 端精简配置
  - 只加载: 路径、扫描间隔、最小视频大小、视频元数据模板
  - **不导入 torch，不检查 GPU**
- [ ] 1.4 创建 `src/config/server_config.py` — PC 端完整配置
  - GPU 检测: lazy `import torch`，放在 `_check_gpu()` 函数内
  - 从 `bilive-server.toml` 加载所有配置项（现有 config.py 的全部内容）
  - 包括模型、ASR、切片、封面等所有配置
- [ ] 1.5 修改 `src/config.py` — 向后兼容重导出
  - `from src.config.server_config import *`
  - 保持所有现有 `from src.config import ...` 兼容
- [ ] 1.6 创建 `bilive-agent.toml`
- [ ] 1.7 创建 `bilive-server.toml`（基于现有 bilive.toml + paths section）
- [ ] 1.8 运行 `lsp_diagnostics` 验证无类型错误
- [ ] 1.9 验证 `python -c "from src.config.agent_config import *"` 不触发 torch

---

## Task 2: 创建 bilive-agent（Pi 端扫描器）

**目标:** Pi 端 scanner 检测新视频文件并写 `.pending` 标记到 NFS。

### 步骤

- [ ] 2.1 创建 `src/agent/__init__.py`
- [ ] 2.2 创建 `src/agent/scanner.py`
  - 复用 `scan_slice.py` 的文件检测逻辑
  - 检测到新视频后写 `.pending` 标记（JSON 元数据，含相对路径）
  - 原子写：先写 `.tmp` 再 `os.replace` rename
  - 幂等：已有 `.pending` 或 `.done` 的文件跳过
- [ ] 2.3 创建 `agent.sh` — Pi 端启动脚本
- [ ] 2.4 创建 `requirements-agent.txt`

---

## Task 3: 创建 PC 端 watcher

**目标:** PC 端监控 `.pending` 文件，发现后执行处理管线。

### 步骤

- [ ] 3.1 创建 `src/server/__init__.py`
- [ ] 3.2 创建 `src/server/watcher.py`
  - 扫描 `VIDEOS_DIR` 下的 `*.pending` 文件
  - 读取 JSON 元数据，拼接 PC 端绝对路径
  - 调用 `slice_only()` 处理
  - 成功后 `.pending` → `.done`
  - 失败保留 `.pending`，下次重试
- [ ] 3.3 创建 `server.sh` — PC 端启动脚本
  - 启动 watcher + upload worker + 可选 Dashboard
- [ ] 3.4 验证 `lsp_diagnostics` 无错误

---

## Task 4: 重构现有管线适配

**目标:** 确保现有处理函数在被 watcher 调用时正确工作。

### 步骤

- [ ] 4.1 修改 `src/db/conn.py` — DB 路径支持环境变量
- [ ] 4.2 审查 `slice_only.py` — 确认路径通过 config 获取
- [ ] 4.3 审查 `title_generator.py` — 确保 MLLM_MODEL 是 lazy 获取
- [ ] 4.4 审查 `cover_generator.py` — 确保 IMAGE_GEN_MODEL 是 lazy 获取
- [ ] 4.5 审查 `subtitle_generator.py` — 确保 ASR 配置正确加载
- [ ] 4.6 全局搜索验证无残留模块级 `import torch`

---

## Task 5: blrec 和路径适配

**目标:** blrec 录制输出到 NFS，所有路径操作正确。

### 步骤

- [ ] 5.1 修改 blrec `settings.toml` — `out_dir` 改为 NFS 挂载路径
- [ ] 5.2 修改 `record.sh` — 支持环境变量配置 NFS 路径
- [ ] 5.3 创建 `record-pi.sh` — Pi 端录制专用启动脚本
- [ ] 5.4 审查所有硬编码路径，确保通过 config 获取

---

## Task 6: 端到端验证

**目标:** 验证 Pi→PC 完整流水线。

### 步骤

- [ ] 6.1 PC: 运行 `server.sh`，确认 watcher 正常启动
- [ ] 6.2 PC: 手动创建 `.pending` 标记，确认 watcher 检测并处理
- [ ] 6.3 Pi: 运行 `from src.config.agent_config import *`，确认不触发 torch
- [ ] 6.4 Pi: 运行 `python -m src.agent.scanner`，确认标记文件生成
- [ ] 6.5 NFS: 验证 Pi 写入的文件 PC 可见，路径映射正确

---

## 风险和注意事项

1. **路径映射** — `.pending` 中只存相对路径（如 `22966160/xxx.mp4`），PC 拼接自己的 `VIDEOS_DIR`。Pi 和 PC 对同一 NFS 目录挂载路径不同，绝对路径不能互认。

2. **blrec 输出路径** — 必须改成 NFS 挂载路径，否则视频写到 Pi SD 卡。

3. **数据库** — SQLite 只在 PC 端使用，Pi 不操作 DB。DB 文件在共享盘上。

4. **模块级 import torch** — `config.py` 第 7 行 `import torch` 是第一阻塞点。

5. **原子性** — `.pending` 标记用写临时文件+rename 保证原子性。

6. **blrec wheel** — `blrec-2.0.0b4-py3-none-any.whl` 是纯 Python，aarch64 应该可用。