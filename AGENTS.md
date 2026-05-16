# bilive — B 站直播录制 + 切片 + 上传

> fork 自 timerring/bilive，重构为 Pi（录制+扫描）+ PC（处理+上传）分布式架构。

## 架构概述

```
树莓派 Pi5 (SD卡)              PC (SSD/HDD + GPU)
┌──────────────────┐           ┌────────────────────────┐
│ blrec 录制        │──写视频──→│ watcher 监控 .pending    │
│ scanner 扫描      │──写.pending│   → 弹幕转换 → Whisper  │
│ (无 torch 依赖)   │           │   → 切片 → MLLM → 上传 │
└──────────────────┘           └────────────────────────┘
              ↑ CIFS 共享 ↓
         (//192.168.31.202/pi)
```

## Pi 端部署（树莓派）

### 环境

- 树莓派 5，Ubuntu，用户 `ubuntu`
- Python 环境：miniforge (conda)，环境名 `bilive`
- 项目路径：`/mnt/bilive/bilive`（CIFS 挂载自 PC）
- PC IP：`192.168.31.202`，Pi IP：`192.168.31.157`

### 首次部署（只需做一次）

```bash
# 1. 挂载共享文件夹（永久）
sudo mkdir -p /mnt/bilive
# fstab 已配置，重启自动挂载。手动挂载用：
sudo mount -t cifs //192.168.31.202/pi /mnt/bilive \
  -o credentials=/etc/samba/credentials,iocharset=utf8,vers=3.0,uid=1000,gid=1000

# 2. 创建 conda 环境 + 安装依赖
source ~/miniforge/etc/profile.d/conda.sh
conda create -n bilive python=3.12 -y
conda activate bilive
pip install httpx toml 'setuptools<69'
pip install /mnt/bilive/bilive/wheel/blrec-2.0.0b4-py3-none-any.whl
```

### 日常启动（重启后执行）

树莓派重启后，需要手动启动两项服务：

```bash
# 1. 确认挂载还在（fstab 自动挂载）
df -h | grep bilive

# 2. 启动录制
cd /mnt/bilive/bilive
export RECORD_KEY=<密钥>
export BILIVE_VIDEOS_DIR=/mnt/bilive/bilive/Videos
./record-pi.sh

# 3. 启动扫描器
./agent.sh

# 4. 验证
ps aux | grep -E "blrec|scanner"
# Web UI: http://192.168.31.157:2233
```

### SD 卡写入说明

Pi 端所有写入操作都在 CIFS 共享盘（`/mnt/bilive/`）上：
- 视频文件 → `/mnt/bilive/bilive/Videos/`
- 日志文件 → `/mnt/bilive/bilive/logs/`
- `.pending`/`.done` 标记 → 视频同目录

SD 卡上只有：
- 操作系统 + conda 环境（只读）
- Python 进程内存（不写磁盘）

扫描器每 120 秒检查一次目录（纯读操作，走网络），不损耗 SD 卡。

### Pi 端依赖（requirements-agent.txt）

```
httpx>=0.24.0
toml>=0.10.0
```

Pi 端不装 torch、whisper 等重型包。重型处理全部在 PC 端完成。

### 关键路径

| 类型 | 路径 | 说明 |
|------|------|------|
| 项目代码 | `/mnt/bilive/bilive/` | CIFS 共享，PC 也可读写 |
| 视频输出 | `/mnt/bilive/bilive/Videos/` | blrec 录制输出 |
| 日志 | `/mnt/bilive/bilive/logs/` | 写入共享盘，不损耗 SD 卡 |
| conda 环境 | `~/miniforge/envs/bilive/` | 本地 SD 卡 |
| cookie | `/mnt/bilive/.secrets/bilibili.cookie` | 共享盘 |

## 踩坑记录

### mount 重启就丢
`mount` 命令只在当前运行周期有效。必须写 `/etc/fstab` 才能永久挂载。
本次已写入，credentials 文件在 `/etc/samba/credentials`。

### bash 特殊字符 —— 感叹号
密码含 `!` 时，bash 会尝历史扩展。解决方案：
- 挂载前执行 `set +H`
- 或者用 credentials 文件代替命令行密码

### 先了解环境再动手
Tree莓派上已有 miniforge (conda)，不应再装系统级包或用 `python3 -m venv`。
动手前先 `which python`、`conda env list`、`ls ~/` 摸清已有环境。

### CIFS 不支持符号链接
`python3 -m venv` 默认用 symlink，CIFS 上必失败。
要么 `--copies`，要么把 venv 放本地磁盘。本次 conda 环境放在 `~/miniforge/envs/`。

### blrec 依赖旧版 setuptools
blrec 使用废弃的 `pkg_resources`，setuptools >= 69 已移除。
必须 `pip install 'setuptools<69'`。

### shell 脚本要适配环境
原来的 `agent.sh` 和 `record-pi.sh` 硬编码 `source venv/bin/activate`。
已改为自动检测：优先 conda (`~/miniforge/etc/profile.d/conda.sh`)，回退 venv。

### SSH 免密连接
`ssh ubuntu@192.168.31.157` 免密已配置。
部署时直接通过 SSH 远程执行，减少用户在 Pi 上的手动输入。

## 文件清单

```
├── src/config/server_config.py  # PC 完整配置（含 GPU/模型/ASR）——向后兼容
├── src/config/agent_config.py   # Pi 端精简配置（无 torch）
├── src/config/base.py           # 共享路径加载
├── src/agent/scanner.py         # Pi 端扫描器（检测新视频 + 写 .pending）
├── src/server/watcher.py        # PC 端监控（发现 .pending → 处理管线）
├── bilive-agent.toml            # Pi 端配置
├── bilive-server.toml           # PC 端配置
├── agent.sh                     # Pi 启动扫描器
├── server.sh                    # PC 启动 watcher + upload
├── record-pi.sh                 # Pi 启动 blrec 录制
├── record.sh                    # PC/WSL 启动 blrec 录制
├── requirements-agent.txt       # Pi 端最小依赖
```
