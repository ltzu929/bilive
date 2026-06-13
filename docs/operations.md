# 运维手册

## Windows 首次恢复

```powershell
.\setup_windows_env.ps1 -Dev
$env:BILIVE_LM_STUDIO_PATH = "D:\LMStudio\LM Studio\LM Studio.exe"
.\install_windows_pi_ssh_key.ps1
.\install_windows_worker_task.ps1 -NoUpload
.\check_windows_health.ps1
```

健康检查是只读的，报告计划任务、`2235`、Worker API、LM Studio、ASR 模型、
SQLite 和上传锁。它不会创建数据库、启动任务或修改上传队列。

确认 `.secrets/bilibili.cookie` 可用且上传队列为空后启用消费者：

```powershell
.\.venv-win\Scripts\python.exe -m src.upload.upload --check-auth
.\install_windows_worker_task.ps1 -EnableUpload
.\check_windows_health.ps1
```

不得通过创建 pending 标记或真实投稿来验证启动。已有 ready 录像不会因为服务
恢复而自动排队。

## Pi 部署

在 `/mnt/win/bilive/.secrets/env` 配置 Windows SSH 目标，然后：

```bash
cd /mnt/win/bilive
sudo ./deploy/install-bilive-services.sh
sudo systemctl status bilive bilive-dashboard bilive-smb-recover.timer
ss -ltnp | grep -E ':2233|:2234'
```

Windows 每晚关机时 SMB 中断属于正常情况。恢复失败时先检查：

```bash
sudo systemctl status mnt-win.mount mnt-win.automount
sudo systemctl status bilive-smb-recover.timer
sudo journalctl -u bilive-smb-recover.service -n 100 --no-pager
```

不要删除恢复 timer，也不要只依赖 `x-systemd.automount`。

## API 验收

```powershell
Invoke-RestMethod http://127.0.0.1:2235/api/worker/status
```

仪表盘 retry/render 返回 `accepted`、`job_id` 和 `status_url`。轮询：

```text
GET /api/jobs/{job_id}
```

失败任务保留 `.failed.json` 和 `error`，不得静默删除。

## 静态验证

```powershell
python -m pytest -q
python -m compileall src tests
.\.venv-win\Scripts\python.exe -m pip check
```

```bash
find deploy -type f -name '*.sh' -print0 | xargs -0 -n1 bash -n
systemd-analyze verify deploy/*.service deploy/*.mount deploy/*.automount deploy/*.timer
```

验收不得进行真实 B 站投稿，也不得自动处理已有 ready 录像。
