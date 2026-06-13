# 托管模型运行时

## 目标

项目直接管理 llama.cpp，不依赖桌面模型程序。默认加载：

```text
E:\AImodel\lmstudio-community\Qwen3.5-9B-GGUF\Qwen3.5-9B-Q4_K_M.gguf
```

模型仅在整批切片第一次需要 LLM 判断时加载，同批复用，批次结束后卸载。

## 安装

```powershell
.\install_llama_runtime.ps1
```

安装器从 llama.cpp 官方 GitHub release 下载固定版本 `b9616` 的 Windows
CUDA 12.4 二进制和匹配的 CUDA runtime DLL，校验
`llama-server.exe --version` 后安装到：

```text
.runtime\llama.cpp\b9616\
```

`.runtime/` 不进入 Git。强制重装：

```powershell
.\install_llama_runtime.ps1 -Force
```

## 配置

`bilive-server.toml`：

```toml
[slice.llm_judge]
provider = "managed-llama-server"
model_path = "E:\\AImodel\\lmstudio-community\\Qwen3.5-9B-GGUF\\Qwen3.5-9B-Q4_K_M.gguf"
server_path = ".runtime\\llama.cpp\\b9616\\llama-server.exe"
host = "127.0.0.1"
port = 2236
context_size = 4096
gpu_layers = "all"
parallel = 1
startup_timeout = 180
shutdown_timeout = 15
```

机器覆盖：

```powershell
$env:BILIVE_LLM_MODEL_PATH = "E:\models\model.gguf"
$env:BILIVE_LLAMA_SERVER_PATH = "D:\runtime\llama-server.exe"
```

运行参数：

```text
llama-server.exe
  --model <model_path>
  --host 127.0.0.1
  --port 2236
  --ctx-size 4096
  --gpu-layers all
  --parallel 1
  --reasoning off
  --flash-attn auto
  --no-ui
  --log-file logs/runtime/llama-server.log
```

## 生命周期

```text
watcher --once 启动
  -> 进入 managed_llm_batch
  -> 领取动作任务和录像任务
  -> 第一次 judge 请求
     -> 校验模型和运行时
     -> 确认 2236 未被占用
     -> 启动 llama-server
     -> 等待 GET /health
  -> 同批 judge 请求复用 /v1
  -> finally 停止 owned llama-server
  -> watcher 退出
```

关键约束：

- Worker API 常驻但不加载模型。
- 纯渲染批次不触发模型。
- 并发 start 会等待同一个启动过程完成，不会提前返回未就绪地址。
- 管理器只结束自己创建的进程。
- 未知的 `2236` 监听者不会被复用或结束。
- 正常结束、异常、启动超时都会执行清理。

## 状态

`GET http://127.0.0.1:2235/api/worker/status` 的 `llm` 字段：

| 状态 | 含义 |
|---|---|
| `idle` | 端口关闭，模型已卸载 |
| `running` + `owned=true` | 当前 Python 进程直接持有模型 |
| `running` + `owned=false` | watcher 子进程中的健康模型服务 |
| `occupied` | `2236` 开放但 `/health` 不健康或来源未知 |

Worker API 和 watcher 是不同进程，因此生产状态通常显示
`running, owned=false`。

## 验证

真实模型烟雾测试：

```powershell
.\.venv-win\Scripts\python.exe -m src.autoslice.mllm_sdk.managed_runtime --smoke-test
```

预期：

```json
{"status":"ok"}
```

退出后确认模型已卸载：

```powershell
Get-Process llama-server -ErrorAction SilentlyContinue
Get-NetTCPConnection -LocalPort 2236 -State Listen -ErrorAction SilentlyContinue
```

两条命令都应无输出。

## Fail-closed

- 运行时或模型缺失：预检失败，pending 保留。
- 端口冲突：拒绝启动，不结束未知进程。
- 进程提前退出：记录退出码，判断失败，候选保留。
- 180 秒内未健康：终止 owned 进程，候选保留。
- 非 JSON 或空响应：`judge_failed`，不自动上传。
- 明确 `drop`：按现有候选清理规则处理。

日志：

```text
logs/runtime/llama-server.log
logs/runtime/slice-worker-*.log
```

更完整的恢复步骤见 [运维手册](operations.md)。
