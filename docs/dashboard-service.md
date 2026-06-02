# Pi dashboard systemd service

## 目的

`bilive-dashboard.service` 让切片面板常驻在 Pi 上，供 blrec 页面里的“切片面板”链接直接打开：

```text
http://192.168.31.157:2234/tasks
```

它只运行轻量 FastAPI dashboard，不在 Pi 上执行切片、ASR、字幕烧录或上传。点击页面里的“启动切片”后，真正的切片任务仍由 Windows 端 PC worker API 处理。

## 服务文件

仓库模板：

```text
deploy/bilive-dashboard.service
```

Pi 上安装位置：

```text
/etc/systemd/system/bilive-dashboard.service
```

安装或更新：

```bash
sudo install -m 0644 /mnt/win/bilive/deploy/bilive-dashboard.service /etc/systemd/system/bilive-dashboard.service
sudo systemctl daemon-reload
sudo systemctl enable --now bilive-dashboard.service
```

常用检查：

```bash
systemctl status bilive-dashboard
ss -ltnp | grep ':2234'
curl -sS -m 5 -o /dev/null -w '%{http_code}\n' http://127.0.0.1:2234/tasks
```

## SD 卡写入控制

这个服务按低写入方式运行：

- `StandardOutput=null`：uvicorn stdout 不落盘。
- `StandardError=journal`：错误只进入 journald。
- `PYTHONDONTWRITEBYTECODE=1`：避免 Python 写 `.pyc`。
- `BILIVE_VIDEOS_DIR=/mnt/win/bilive/Videos`：pending 标记和录播数据写到 Windows 共享目录。

Pi 当前 journald 应保持：

```text
Storage=volatile
```

也就是 journal 在 RAM 中，不持续写 SD 卡。可用下面命令确认：

```bash
grep -R '^Storage=' /etc/systemd/journald.conf /etc/systemd/journald.conf.d 2>/dev/null
```

## 服务边界

`bilive.service` 继续只负责 blrec 录制，监听 `2233`。

`bilive-dashboard.service` 负责切片页面，监听 `2234`。

Windows 端仍需在切片前启动：

```powershell
.\start_pc_worker_api.ps1
```

如果 `2234/tasks` 能打开但点击“启动切片”后提示无法连接 PC worker，问题在 Windows 端 worker API，不在 Pi dashboard 服务。
