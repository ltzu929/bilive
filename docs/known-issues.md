# 已知问题

## scan_slice 跳过逻辑与 blrec `delete_source = "never"` 冲突

**已修复 (2026-05-21)**。原先 `scan_slice.py` 看到任何 `.flv` 就跳过整个文件夹，但 blrec 配置了 `delete_source = "never"`（`settings.toml`），`.flv` 从不删除。修复后只跳过没有配对 `.mp4` 的 `.flv`（正在录制中），同时排除 `_slice` 标记的切片输出文件。

代码：`src/burn/scan_slice.py` → `process_folder_slice_only()`

## B站上传发布接口 code=-101（未解决）

即使 cookie 有效（GET `api.bilibili.com` 已验证登录），POST `/x/vu/client/add` 发布接口仍返回 code=-101 "账号未登录"。

- 已尝试：不同 Referer、csrf 位置、SESSDATA 编解码——均无效
- 视频文件已成功上传到 CDN（preupload → chunk upload → finish 通过），仅最后发布失败
- blrec 录制不受影响（从 `settings.toml` 的 `[header] cookie` 读，用于下载原画流）

**cookie 格式问题**：bilitool 上传模块期望 JSON 格式（`{data: {cookie_info: {cookies: [...]}}}`），而 `.secrets/bilibili.cookie` 是分号分隔文本。运行 `python sync_cookie.py` 可自动转换。

代码：`src/upload/upload.py` → `read_append_and_delete_lines()`, `src/upload/bilitool/bilitool/login/login_bili.py`

## Windows subprocess GBK 编码污染

`subprocess.run(text=True)` 在 Windows 上默认用 GBK 编码命令行参数，导致 ffmpeg 写入的 flv 元数据乱码。

**修复**：设环境变量 `PYTHONUTF8=1`（`start_pipeline.ps1` 已包含）。

代码：`src/autoslice/inject_metadata.py`

## PowerShell 窗口关闭导致进程崩溃

用 `Start-Process -WindowStyle Minimized` 启动的子进程绑定到当前 PowerShell session，关闭窗口会发送 close 信号（`forrtl: error (200)`）。

**修复**：用 `pythonw.exe` + `cmd /c start /b` 完全脱离终端（`start_pipeline.ps1` 已实现）。

## faster-whisper cuBLAS 缺失

faster-whisper 需要 `cublas64_12.dll`（CUDA 12 Toolkit），仅 CUDA 13 驱动不包含。详见 [ASR 引擎文档](asr-engines.md)。

## LLM judge 超时

Qwen3-ASR 转录失败时（如 cuBLAS 缺失），LLM judge 仅依赖弹幕文本，超时 6 分钟后降级为默认标题。上游修复 ASR 后可解决。
