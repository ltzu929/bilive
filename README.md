# Bilive

Bilive 是自维护的 B 站直播录制、切片分析和投稿队列项目。

## 生产边界

| 节点 | 服务 | 地址 | 责任 |
|---|---|---|---|
| Pi | `bilive.service` | `0.0.0.0:2233` | blrec 录制 |
| Pi | `bilive-dashboard.service` | `0.0.0.0:2234` | 仪表盘、任务落盘、远程触发 |
| Pi | `bilive-smb-recover.timer` | 每 15 秒 | SMB 和服务恢复 |
| Windows | `BiliveWorkerApi` | `127.0.0.1:2235` | 切片、ASR、LLM、字幕、上传 |

Pi 不执行 ffmpeg、faster-whisper 或 LLM。浏览器在仪表盘发起的重试判断和渲染
请求会写入 `Videos/.bilive-jobs/`，再由 Windows worker 领取。

仪表盘继续对局域网开放且不要求登录，但拒绝公网 Host 和跨 Origin 写请求。
Worker API 只监听 Windows localhost。

## Windows 安装

```powershell
.\setup_windows_env.ps1 -Dev
$env:BILIVE_LM_STUDIO_PATH = "D:\LMStudio\LM Studio\LM Studio.exe"
.\install_windows_pi_ssh_key.ps1
.\install_windows_worker_task.ps1 -NoUpload
.\check_windows_health.ps1
```

任务安装器会幂等注册并启动 `BiliveWorkerApi`，同时验证计划任务、端口 `2235`
和 Worker API。默认安全模式等同于 `-NoUpload`。确认 cookie 有效且上传队列为空后：

```powershell
.\install_windows_worker_task.ps1 -EnableUpload
```

Windows 端可配置项：

- `BILIVE_LM_STUDIO_PATH`：LM Studio 可执行文件。
- `BILIVE_AUTO_UPLOAD=0`：禁用上传消费者。
- `BILIVE_CONFIG`、`BILIVE_VIDEOS_DIR`、`BILIVE_DB_PATH`、`BILIVE_COOKIE_FILE`。

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

blrec 通过环境变量 `BLREC_API_KEY` 读取密钥，密钥不会出现在进程参数中。
Windows 夜间关机和次日 SMB 恢复是正常运行场景，保留
`bilive-smb-recover.timer`，不要删除或改成只依赖 automount。

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

动作支持 `retry_judge` 和 `render_segment`。重复提交会复用仍在 pending/processing
的同一任务。`GET /api/jobs/{job_id}` 返回进度和失败原因。

上传和投稿是两个可恢复阶段。CDN 上传成功后，投稿重试复用
`remote_filename`，不会重复上传视频字节。

## Fail-closed

自动入队要求非空 ASR、有效段级时间戳、窗口弹幕与转录共同送入 LLM、明确
`keep`、字幕烧录成功、元数据成功和 SQLite 入队成功。任一步失败都保留候选供
人工复核；只有明确 `drop` 才删除候选。

## 验证

```powershell
python -m pytest -q
python -m compileall src tests
.\.venv-win\Scripts\python.exe -m pip check
```

部署和恢复步骤见 [运维手册](docs/operations.md)，结构说明见
[架构文档](docs/architecture.md)，媒体维护见 [维护手册](docs/maintenance.md)。
