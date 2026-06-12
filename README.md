# Bilive

Bilive 是自维护的 B 站直播录制、切片分析和投稿队列项目。生产环境分为两部分：

- Raspberry Pi：运行 blrec 录制和仪表盘，写入 Windows SMB。
- Windows：运行唯一入口 Worker API，负责切片、faster-whisper ASR、LM Studio 判断、字幕、元数据和上传队列。

## 生产拓扑

| 节点 | 服务 | 地址 | 责任 |
|---|---|---|---|
| Pi | `bilive.service` | `0.0.0.0:2233` | blrec 录制 |
| Pi | `bilive-dashboard.service` | `0.0.0.0:2234` | 仪表盘和远程 Worker 触发 |
| Pi | `bilive-smb-recover.timer` | 每 15 秒 | SMB 检查和双服务恢复 |
| Windows | `BiliveWorkerApi` | `127.0.0.1:2235` | Worker API 和上传消费者 |

浏览器只访问 Pi 仪表盘。Pi 通过 SSH 在 Windows 本机请求
`127.0.0.1:2235`，Worker API 不监听局域网地址。

## Windows 安装

```powershell
.\setup_windows_env.ps1
.\install_windows_pi_ssh_key.ps1
.\install_windows_worker_task.ps1
```

`setup_windows_env.ps1` 创建独立的 `.venv-win`，安装
`requirements/windows.txt` 并执行 `pip check`。

`install_windows_pi_ssh_key.ps1` 需要在管理员 PowerShell 中执行一次，
用于允许 Pi 通过 Windows OpenSSH 调用本机 Worker API。Windows 的
`sshd` 服务必须设为自动启动。

`install_windows_worker_task.ps1` 注册登录任务 `BiliveWorkerApi`，入口固定为：

```powershell
.\start_pipeline.ps1
```

该脚本检查并启动 LM Studio，然后以前台方式启动 Worker API。上传消费者由
Worker API 生命周期管理，不应再单独启动 watcher 或上传脚本。

调试时关闭真实上传：

```powershell
.\start_pipeline.ps1 -NoUpload
```

或设置：

```powershell
$env:BILIVE_AUTO_UPLOAD = "0"
```

## Pi 安装

Pi 上的代码路径为 `/mnt/win/bilive`：

```bash
ssh pi
cd /mnt/win/bilive
sudo ./deploy/install-bilive-services.sh
```

安装器负责：

- 安装 Pi 依赖和 `blrec==2.0.0b4`。
- 校验版本与目标文件哈希后应用无限 FPS 补丁。
- 强制 blrec 保留源 FLV。
- 安装录制器、仪表盘、SMB 恢复 service/timer。
- 启用内存限制、有限 TERM/KILL 等待和 RSS 日志。

检查状态：

```bash
sudo systemctl status bilive bilive-dashboard bilive-smb-recover.timer
ss -ltnp | grep -E ':2233|:2234'
```

## 任务状态

仪表盘创建任务后，标记按以下顺序流转：

```text
.mp4.pending -> .mp4.processing -> .mp4.done
                                  -> .mp4.failed
```

Worker 使用跨进程 PID 锁和原子重命名。启动时只恢复确认失去所有者的
`.processing`。同一 `video_path` 在 SQLite 上传队列中具有唯一约束。

`POST /api/worker/run-once` 返回：

- `accepted`
- `already_running`
- `no_pending`
- `dependency_unavailable`

`GET /api/worker/status` 报告 watcher、锁所有者、上传消费者、LM Studio、
ASR 和待处理数量。

## Fail-closed 规则

自动入队必须依次满足：

1. 视频、数据库和输出目录可用。
2. faster-whisper `large-v3` 可用并产生非空转录。
3. 转录包含有效的段级时间戳。
4. 转录和时间窗口内弹幕共同送入 LLM。
5. LLM 明确返回 `keep` 和有效标题。
6. 字幕烧录成功。
7. 投稿元数据写入成功。
8. SQLite 入队成功。

任一步失败都保留候选并记录结构化失败原因；只有 LLM 明确 `drop` 才删除候选。

## 上传恢复

上传和投稿是两个可恢复阶段。视频已上传到 CDN 后，投稿重试复用
`remote_filename`，不会重复上传视频字节。

默认 cookie 路径：

```text
.secrets/bilibili.cookie
```

仓库只保留 `cookie.example.json`，不得提交真实 cookie。

## 测试

```powershell
python -m pytest -q
python -m compileall src tests
```

PowerShell、shell、systemd 和部署检查见 [运维手册](docs/operations.md)。
历史媒体和数据库维护见 [维护手册](docs/maintenance.md)。
