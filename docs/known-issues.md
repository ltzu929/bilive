# 已知问题

## 旧 `scan_slice` 仍可被显式启用

当前不建议用旧 `scan_slice` 做日常切片。`start_pipeline.ps1` 默认不再启动它，但兼容参数仍可显式启用一次全目录扫描：

```powershell
.\start_pipeline.ps1 -RunLegacyScanSlice
```

等价于兼容跑一次：

```powershell
python -m src.burn.scan_slice --once
```

这个入口会扫描整个 `Videos/`。风险：

- 不是只处理 dashboard 写入的 `.mp4.pending`。
- 可能重复切已经处理过但没有 `.done` 的旧录播。
- 可能把已生成的 `123s_room_time.mp4` 切片产物也扫到，然后出现 `No danmaku file`。

日常推荐：

```powershell
cd D:\alldata\pi\bilive
.\start_pc_worker_api.ps1
```

再从 `/tasks` 页面点击“启动切片”。页面会触发 `src.server.watcher --once`，处理完自动退出。

## 旧 `scan_slice` 和当前 pending worker 的语义不同

`src.burn.scan_slice` 是全目录扫描器；`src.server.watcher` 是 pending 队列处理器。两者不能混用为同一个概念。

| 入口 | 行为 |
|------|------|
| `src.server.watcher --once` | 只处理 `.mp4.pending`，成功后写 `.mp4.done` |
| `src.burn.scan_slice` | 扫整个 `Videos/` 下未被过滤的 mp4 |

如果页面已经写了 pending，却没有任何处理发生，优先检查本机 worker API 是否启动，而不是去跑 `scan_slice`。

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

本地 LM Studio/OpenAI-compatible 接口异常时，judge 可能返回 502。当前处理方式是降级继续：

- 切片仍保留。
- 标题/质量结果使用默认值或启发式结果。
- 日志会出现 `Judge LLM call failed: Error code: 502`。

这不是切片失败，但会影响标题质量。

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
