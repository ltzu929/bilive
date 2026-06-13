# Bilive 维护约束

## 运行边界

- Pi 只运行 blrec、仪表盘和 SMB 恢复，端口为 2233、2234。
- Windows 只通过 `start_pipeline.ps1` 启动生产处理链路。
- Worker API 只监听 `127.0.0.1:2235`。
- 切片、ASR、LLM、字幕和上传不得在 Pi 执行。
- Pi 的 retry/render API 只能原子写入 `.bilive-jobs` 并远程触发 Windows。
- 录制继续写 `/mnt/win/bilive/Videos`，不得改写到 Pi SD 卡。
- Windows 夜间关机和次日 SMB 恢复是正常运行场景，保留恢复 timer。

## 生产状态

- 录像与动作任务均遵循 `pending -> processing -> done/failed`。
- 跨进程锁必须保留，不能仅使用线程锁。
- 上传队列必须保持 `video_path` 唯一约束。
- 投稿重试必须复用 CDN `remote_filename`。
- 依赖检查失败时必须保留 pending 任务。
- 只读状态接口不得执行迁移、建表或数据修复。

## 媒体与凭据

- blrec 保留源 FLV，只有验证 MP4 后才能删除源文件。
- 历史清理先生成报告；删除必须显式使用 `--execute`。
- 真实凭据只放 `.secrets/` 或未跟踪配置。
- blrec 密钥通过 `BLREC_API_KEY` 环境变量传递，不放进进程参数。
- 不在日志、测试快照或提交信息中输出 cookie。

## 验证

```powershell
python -m pytest -q
python -m compileall src tests
.\.venv-win\Scripts\python.exe -m pip check
```

涉及部署时还要执行 PowerShell 解析、`bash -n` 和 systemd unit 校验。
