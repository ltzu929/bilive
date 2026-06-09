# 已知问题

## Pending 已写入但 worker 没有处理

生产切片只通过 `src.server.watcher --once` 消费 `.mp4.pending`。如果页面已经写了 pending，却没有处理：

1. 检查 `start_pc_worker_api.ps1` 或 Windows 计划任务 `BiliveSliceOnce`。
2. 检查 `logs/runtime/pc-worker-*.log` 和 `.mp4.task.json`。
3. 检查 worker 状态接口 `http://127.0.0.1:2235/api/worker/status`。

不要新增全目录扫描绕过 pending 状态，否则会重复处理历史录播或误扫候选切片。

## faster-whisper CUDA 缺 `cublas64_12.dll`

`faster-whisper` 的 CUDA 路径需要 CUDA 12 cuBLAS 运行库。缺 DLL 时会报：

```text
Library cublas64_12.dll is not found or cannot be loaded
```

当前稳定配置是：

```toml
whisper_engine = "faster-whisper"
whisper_model = "large-v3"
whisper_device = "cpu"
whisper_compute_type = "int8"
```

需要 GPU 时先安装/配置 CUDA 12 运行库，再改 `whisper_device = "cuda"`。

## HuggingFace 下载失败

`large-v3-turbo` 或首次加载 `large-v3` 时可能访问 HuggingFace。网络/代理异常时会出现 `ProxyError`、`ConnectionResetError` 或 `MaxRetryError`。

处理方式：

- 优先使用本机已缓存的 `large-v3`。
- 配置可用代理。
- 设置 `HF_TOKEN`。

## Qwen3-ASR 不适合当前字幕烧录主路径

Qwen3-ASR 文本质量可能不错，但当前集成没有可用的真实段级时间戳。字幕烧录现在只接受真实 ASR `transcript_segments`；没有真实时间戳时不再生成伪字幕。

因此当前默认回到 `faster-whisper`。

## LLM judge 502

本地 LM Studio/OpenAI-compatible 接口异常时，judge 可能返回 502。当前处理方式是转人工复核：

- 候选切片保留，状态为 `judge_failed`。
- 不写上传 sidecar，不进入上传队列。
- dashboard 可重新调用同一候选分析器，或由人工执行 `manual_keep`。
- 日志会出现 `Judge LLM call failed: Error code: 502`。

这不会让整场录播任务无限重试，也不会绕过自动投稿门禁。

## 源录播默认保留

早期切片流程会在切完后删除源 `.mp4/.xml`。当前默认已经改为保留源文件，方便重跑。

只有显式设置：

```powershell
$env:BILIVE_DELETE_SOURCE_AFTER_SLICE = "1"
```

才会删除源文件。

## 历史上传失败行不会自动重传

旧消费者调用已失效的 `/x/vu/client/add`，部分队列行可能在视频上传到 CDN
后留下 `locked=1`。当前消费者已改用 Web `/x/vu/web/add/v3`，并把 UPOS
上传和发布拆成两个可恢复阶段。

迁移时已有 `locked=1/2` 行会变为 `failed`，不会自动解锁，因为无法确认旧
CDN 对象是否已被使用。新入队切片不受影响。需要处理历史行时应先人工核对
本地文件和 B 站投稿记录。

自动上传直接读取 `.secrets/bilibili.cookie`，不再依赖 `sync_cookie.py`。

## Windows subprocess 编码

Windows 下子进程默认编码可能导致 ffmpeg 元数据乱码。当前脚本应设置：

```powershell
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
```

如果直接手动启动 Python 进程，建议也设置这两个环境变量。
