# bilive — B 站直播录制 + 切片 + 上传

> fork 自 timerring/bilive，聚焦稳定完成录制→切片→上传流程。

## 一句话描述

用 blrec 录制 B 站直播和弹幕，扫描录制文件进行弹幕处理/字幕/切片，通过 bilitool 上传到 B 站。

## 项目结构

```
├── bilive.toml         # 处理配置（Git 跟踪）
├── settings.toml        # blrec 本地配置（gitignored）
├── record.sh            # 录制启动入口
├── upload.sh            # 扫描 + 上传
├── slice.sh             # 独立切片 + 上传
├── src/
│   ├── burn/            # 扫描、渲染、切片
│   ├── autoslice/       # 切片标题、多模态分析、质量筛选
│   ├── upload/          # bilitool 上传封装
│   ├── danmaku/         # 弹幕转换
│   ├── subtitle/        # Whisper 字幕
│   └── db/              # SQLite 上传队列
├── Videos/              # 录制输出（gitignored）
├── logs/                # 运行日志（gitignored）
└── .secrets/            # cookie 等敏感文件（gitignored）
```

## 当前状态

- 主要在 WSL/Linux 下开发，尚未在树莓派上部署
- 需要在 Pi 上跑之前解决：SD 卡写入（Videos/ + logs/ 目录）、4GB 内存跑 Whisper/ASR 的可行性

## 快速运行（WSL/Linux）

```bash
# 录制
cd /home/zk/projects/bilive && source venv/bin/activate
export RECORD_KEY=bilive2026
./record.sh
# Web UI: http://localhost:2233

# 处理+上传（另开终端）
./upload.sh

# 独立切片（另开终端）
./slice.sh
```

## 关键约束

- `settings.toml` 是本地私有配置，不提交
- `RECORD_KEY` 长度必须 8-80 字符，是 blrec Web UI 密码
- cookie 持久化到 `.secrets/bilibili.cookie`，失效后需重新 `python -m bilitool.cli login`
- 子模块需要 `git submodule update --init --recursive`
