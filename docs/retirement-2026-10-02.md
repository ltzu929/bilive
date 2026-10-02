# Bilive 退役记录

用户于 2026-10-02 明确确认本项目彻底弃用，要求保存到 GitHub，并删除树莓派上的项目文件与开机启动服务。

## 保存范围

- GitHub 仓库：`ltzu929/bilive`；保存当前 `main` 提交及此前未跟踪的 `wheel/blrec-2.0.0b4+bilive.19-py3-none-any.whl`。
- 源码、文档、已有安装包、Git 历史及子模块引用保留。子模块仍指向各自上游仓库，不改写其来源。
- 录像、数据库、任务队列、日志、模型、虚拟环境、机器配置和 `.secrets/` 不上传 GitHub，继续保留在 Windows 本地。
- Windows 本地的 `artifacts/retirement-2026-10-02/` 保存退役前服务文件、计划任务定义与 Git bundle，用于复查和恢复；此目录由 Git 忽略。

## 清理前清单

树莓派上的 `/mnt/win/bilive` 是 Windows SMB 共享目录，实际对应本地仓库与录像；不能把它当作树莓派本地副本删除。

本次清理限定为：

- `bilive.service`、`bilive-dashboard.service`、`bilive-smb-recover.service`、`bilive-smb-recover.timer` 及其启用链接。
- `/usr/local/bin/bilive-start.sh`、`/usr/local/bin/bilive-dashboard-start.sh`、`/usr/local/sbin/bilive-smb-recover` 和发现的同名历史备份文件。
- `/home/ubuntu/miniforge/envs/bilive` 专用 Python 环境及 `/home/ubuntu/.blrec` 旧日志目录。
- Tailscale Serve 中转发至 `127.0.0.1:2233` 和 `127.0.0.1:2234` 的入口。
- Windows 中指向 `D:\alldata\pi\bilive` 的 `BiliveWorkerApi` 计划任务。

保留共享挂载及其通用自动挂载配置、Tailscale 本身和其他服务入口。指向独立 `D:\bilive` 项目的 `BiliveV2Recorder`、`BiliveV2Dashboard` 计划任务不属于本次退役范围。

清理前检查：Pi 两个常驻服务和恢复定时器启用且运行；Windows Worker 端口 2235 未监听；没有录像 pending/processing 标记或待处理/处理中动作任务；两次 FLV 采样大小一致。录制 API 需要认证，未完成认证核验，不据此声称全部直播间处于空闲状态。

## 执行与验证

先推送并独立核对 GitHub 提交，再执行退役。清理脚本必须使用 `--execute`，校验真实路径且拒绝删除挂载目录；不得对 `/mnt/win` 或 Windows 录像执行删除。

最终执行结果在清理完成后补录。
