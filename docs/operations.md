# 运维手册

## Windows

创建环境并注册登录任务：

```powershell
.\setup_windows_env.ps1
.\install_windows_pi_ssh_key.ps1
.\install_windows_worker_task.ps1
```

`install_windows_pi_ssh_key.ps1` 需要管理员权限。确认 OpenSSH 服务：

```powershell
Set-Service sshd -StartupType Automatic
Start-Service sshd
```

检查任务和端口：

```powershell
Get-ScheduledTask -TaskName BiliveWorkerApi
Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 2235
Invoke-RestMethod http://127.0.0.1:2235/api/worker/status
```

关闭真实上传运行：

```powershell
.\start_pipeline.ps1 -NoUpload
```

## Pi

安装或升级：

```bash
cd /mnt/win/bilive
sudo ./deploy/install-bilive-services.sh
```

检查：

```bash
sudo systemctl status bilive bilive-dashboard bilive-smb-recover.timer
sudo journalctl -u bilive -u bilive-dashboard -n 100 --no-pager
ss -ltnp | grep -E ':2233|:2234'
```

## 静态验证

```powershell
python -m pytest -q
python -m compileall src tests
.\.venv-win\Scripts\python.exe -m pip check
```

```bash
bash -n deploy/*.sh
systemd-analyze verify \
  deploy/bilive.service \
  deploy/bilive-dashboard.service \
  deploy/bilive-smb-recover.service \
  deploy/bilive-smb-recover.timer
```

验收不得进行真实 B 站投稿。终点是元数据生成并进入干净上传队列。
