# Bilive 维护约束

## 运行边界

- Pi 只运行 blrec 和仪表盘，端口分别为 2233、2234。
- Windows 只通过 `start_pipeline.ps1` 启动生产处理链路。
- Worker API 只监听 `127.0.0.1:2235`。
- 切片、ASR、LLM、字幕和上传不得迁移到 Pi。
- 录制继续写 `/mnt/win/bilive/Videos`，不得改写到 Pi SD 卡。

## 生产状态

- 任务标记：`pending -> processing -> done/failed`。
- 跨进程锁必须保留，不能用线程锁替代。
- 上传队列必须保持 `video_path` 唯一约束。
- 上传成功后的投稿重试必须复用 CDN `remote_filename`。
- Worker 依赖检查失败时必须保留 `.pending`。

## 媒体安全

- blrec 保留源 FLV，只有验证 MP4 后才能删除源文件。
- 转封装失败、解码失败或验证异常时不得删除源文件或已有目标。
- 历史清理先生成报告；删除无效文件必须显式使用 `--execute --delete-invalid`。
- 禁止把无法验证的恢复结果描述为成功。

## 凭据

- 真实凭据只放 `.secrets/` 或未跟踪的 `settings.toml`。
- `cookie.json` 不得重新加入 Git。
- 不在日志、测试快照或提交信息中输出 cookie。

## 验证

提交前至少执行：

```powershell
python -m pytest -q
python -m compileall src tests
```

涉及部署时还要执行 PowerShell 语法检查、`bash -n`、systemd unit 校验和专用
`.venv-win` 的 `pip check`。
