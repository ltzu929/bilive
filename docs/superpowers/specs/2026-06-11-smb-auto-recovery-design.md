# SMB 自动恢复设计

## 背景

Pi 通过 `/etc/fstab` 的 `x-systemd.automount` 挂载 Windows 共享
`//192.168.31.202/pi`。Windows 每晚关机后，Pi 继续运行；第二天 Windows
重新上线时，CIFS 挂载需要自动恢复，`bilive.service` 才能重新启动
`blrec` 并监听 `2233`。

现有 wrapper 能在共享不可用时保持 `bilive.service` 存活，但无法清除
`mnt-win.mount` 的 `failed` 状态。启动阶段第一次挂载失败后，普通文件访问
不会可靠地再次触发挂载。现有 300 秒等待也导致恢复延迟过长。

## 目标

- Windows 离线时 Pi 保持稳定，不反复启动录制或写入 SD 卡视频。
- Windows 恢复且 SMB 445 可达后，Pi 在约 30 秒内重新挂载共享。
- 挂载恢复后自动重启 `bilive.service`，恢复 `2233`。
- stale CIFS 挂载可以被清理并重新挂载。
- 挂载恢复使用 root systemd 单元，不给普通录制进程 sudo 权限。

## 方案

新增三个部署文件：

- `deploy/bilive-smb-recover.sh`：root oneshot 恢复脚本。
- `deploy/bilive-smb-recover.service`：执行恢复脚本。
- `deploy/bilive-smb-recover.timer`：开机后及每 15 秒触发一次。

恢复脚本按以下顺序执行：

1. 如果 `/mnt/win/bilive` 可在短超时内访问，则立即退出。
2. 如果 Windows `192.168.31.202:445` 不可达，则正常退出，等待下次 timer。
3. 如果存在不健康的 CIFS 挂载，先停止 `bilive.service`，再停止或 lazy
   unmount 旧挂载。
4. 清除 `mnt-win.mount` 的失败状态并重新启动 mount unit。
5. 挂载健康后重启 `bilive.service`。

`bilive-wrapper.sh` 继续负责录制进程生命周期，但共享检查和健康检查间隔从
300/30 秒改为 15/15 秒。wrapper 不执行特权挂载命令。

## 错误处理

- Windows 离线不是 systemd failure，恢复 oneshot 返回成功并安静等待。
- 挂载失败只记录 warning，下一个 timer 周期继续尝试。
- stale mount 普通停止失败时使用 lazy unmount，避免恢复器永久卡住。
- 恢复脚本所有网络和文件探针都必须有超时。

## 部署

安装脚本和 unit 到 Pi 本地磁盘：

- wrapper: `/usr/local/bin/bilive-start.sh`
- recover script: `/usr/local/sbin/bilive-smb-recover`
- units: `/etc/systemd/system/`

启用 `bilive-smb-recover.timer` 和 `bilive.service`。部署内容不依赖 Windows
共享持续在线，因此共享断开后 Pi 仍能执行恢复逻辑。

## 验证

- 静态测试覆盖 timer 周期、root service、mount reset/start、stale unmount
  和 15 秒 wrapper 等待。
- Pi 上将 mount unit 置为失败后，等待 timer 自动恢复，不手工运行
  `reset-failed`。
- 验证 `mnt-win.mount` 为 `active/mounted`、`bilive.service` 为 `active`、
  `0.0.0.0:2233` 正在监听。

