
# Bilive Agent Guide

本文件是本仓库中 AI 编码 Agent 的统一约束与项目入口。修改代码前应先阅读本文件；涉及架构细节时再查阅 `docs/architecture.md`，涉及安装、部署和人工操作时查阅 `README.md`。

## 项目概览

Bilive 是一个自维护的 Bilibili 直播录制、切片分析、字幕和上传流水线。同一套代码支持两种拓扑：

* **Pi / Windows 分布式**：Pi 负责轻量服务，Windows 负责全部重处理。
* **Windows 单机**：Windows 同时承担轻量服务和重处理，但仍保持轻服务与重处理边界。

主要端口：

* blrec：`2233`
* Dashboard：`2234`
* Windows Worker API：`127.0.0.1:2235`

主要 Python 入口、数据流和模块关系以 `docs/architecture.md` 为准。

## 运行边界

* Pi 只运行 blrec、Dashboard 和 SMB 恢复相关服务。
* Windows 生产处理链路只通过 `start_pipeline.ps1` 启动。
* Worker API 只监听 `127.0.0.1:2235`。
* ffmpeg、faster-whisper、MiMo、字幕烧录和上传不得在 Pi 执行。
* Pi 上的 finalize / retry / render / reburn API 只能校验请求并原子写入 `.bilive-jobs`，再触发 Windows Worker；不得在 Dashboard 进程内直接执行重处理。
* 录制继续写入 `/mnt/win/bilive/Videos`，不得改写到 Pi SD 卡。
* Windows 夜间关机、次日重新挂载 SMB 属于正常运行场景，相关恢复 timer 必须保留。
* 不得为了方便而新建与现有流水线并行、功能重复的实现；优先复用当前模块和状态模型。

## 状态与一致性

录像任务遵循：

`pending -> processing -> done | failed`

Dashboard 动作任务遵循：

`.pending.json -> .processing.json -> .done.json | .failed.json`

必须遵守：

* 跨进程锁必须保留，不能用线程锁替代。
* Dashboard 动作任务必须保持互斥和幂等；重复提交应复用已有 pending / processing 任务。
* 上传队列必须保持 `video_path` 唯一约束。
* CDN 上传成功后，投稿重试必须复用已有 `remote_filename`，不得重新上传视频字节。
* 依赖检查失败时必须保留 pending 任务。
* 自动成片中 MiMo、质量阈值、ASR、时间戳、渲染、元数据或入队任一步失败，都必须保留候选供人工复核。
* 只有明确的 MiMo `drop` 才允许自动删除候选。
* 只读状态接口不得执行迁移、建表、数据修复或其他写操作；数据库不存在时应返回 unavailable，而不是隐式创建。

## 配置与凭据

* `settings.toml`：blrec 的机器本地配置，必须保持 gitignored。
* `bilive-server.toml`：Windows 侧处理的受版本控制默认配置；机器特定路径和秘密不得写入其中。
* 配置解析优先级为：环境变量 > 配置文件 > 默认值。
* 真实凭据只允许放在 `.secrets/`、未跟踪配置或进程环境变量中。
* `MIMO_API_KEY`、`BLREC_API_KEY`、`BILIVE_WINDOWS_SSH_TARGET`、Bilibili cookie 等不得写入日志、测试快照、提交信息或命令行参数。
* blrec 密钥通过 `BLREC_API_KEY` 环境变量传递。
* Worker 会自动读取 `.secrets/env`；不要另建第二套秘密配置机制。

常见环境变量包括：`MIMO_API_KEY`、`BILIVE_AUTO_UPLOAD`、`BILIVE_WORKER_IDLE_TIMEOUT`、`BILIVE_CONFIG`、`BILIVE_VIDEOS_DIR`、`BILIVE_LOG_DIR`、`BILIVE_DB_PATH`、`BILIVE_COOKIE_FILE`。

## 媒体与删除安全

* blrec 应保留源 FLV，只有在目标 MP4 已验证有效后才允许删除源文件。
* 历史清理必须先生成报告；真正删除必须显式使用 `--execute`。
* 删除逻辑应 fail-closed：任何状态不明确、产物不完整或依赖失败时都优先保留数据。

## 主要架构入口

### Dashboard

* `src/dashboard/app.py`
* `src/dashboard/remote_worker.py`
* `src/dashboard/slice_control.py`
* `src/dashboard/source_workbench.py`
* `src/dashboard/task_state.py`
* `src/dashboard/file_store.py`

Dashboard 负责录播索引、候选复核、人工动作提交、Eagle 源索引和只读上传状态展示；重处理必须交给 Windows Worker。

### Windows Worker

* `src/server/worker_server.py`：生产入口
* `src/server/worker_api.py`：FastAPI app
* `src/server/worker_control.py`：单次 watcher 调度
* `src/server/worker_idle.py`：空闲退出
* `src/server/worker_lock.py`：跨进程锁
* `src/server/upload_control.py`：上传消费者
* `src/server/preflight.py`：生产前检查
* `src/server/watcher.py`：原子 claim pending 任务并持续排空
* `src/server/action_jobs.py`：人工动作任务

### 自动切片 / 字幕 / 上传

自动链路：

`弹幕密度 -> 候选区间 -> MiMo 多模态判断 -> 本地质量门 -> 去重 -> faster-whisper -> ffmpeg -> 字幕 -> 元数据 -> upload_queue`

相关目录：

* `src/autoslice/`
* `src/subtitle/`
* `src/burn/`
* `src/upload/`
* `src/db/`

架构细节、数据流和职责划分以 `docs/architecture.md` 为准，不在本文件重复维护实现细节。

## Git 子模块

以下目录属于上游子模块，不得直接在本仓库内修改：

* `src/autoslice/auto_slice_video`
* `src/upload/bilitool`

如确需改变其行为，应优先在外围适配；确实需要修改上游时，单独处理子模块来源，而不是把本仓库改成隐式 fork。

## 本地运行产物

以下内容是本地运行数据，不得提交，也不得在代码中把生产路径硬编码到这些位置：

* `Videos/*`
* `logs/*`
* `artifacts/`
* `.runtime/`
* `src/db/data.db`
* `src/subtitle/models/*.pt`
* `.secrets/`
* `.sisyphus/`
* `.worktrees/`
* `venv/`
* `.venv-win/`

## 测试与验证

Windows 重处理环境使用：`.venv-win\Scripts\python.exe`。

常规修改至少执行：

```powershell
.\.venv-win\Scripts\python.exe -m pytest -q
.\.venv-win\Scripts\python.exe -m compileall src tests
.\.venv-win\Scripts\python.exe -m pip check
```

需要单独运行测试时：

```powershell
.\.venv-win\Scripts\python.exe -m pytest tests/test_pipeline_stages.py -q
.\.venv-win\Scripts\python.exe -m pytest tests/test_pipeline_stages.py::test_name -q
```

默认测试不包含 `integration` 和 `legacy`；只有具备真实密钥、媒体和 SDK 条件时才主动运行 integration：

```powershell
.\.venv-win\Scripts\python.exe -m pytest -m integration -q
```

Eagle 插件测试：

```powershell
node --test eagle-plugin\tests\sync.test.mjs
```

涉及部署、PowerShell、shell 或 systemd 修改时，还必须执行：

* PowerShell 语法解析
* `bash -n`
* 仓库实际包含的 systemd unit 校验

测试应优先使用 `tests/conftest.py` 已有 fixture，不要直接操作真实 `Videos/`、生产数据库或真实凭据。

## 修改原则

* 修改前先定位现有实现和测试，不要仅凭文档猜测行为。
* 保持现有 Pi / Windows 边界、状态机、fail-closed 和幂等语义。
* 优先做局部修改，避免无关重构。
* 新增行为必须补充或更新相应测试。
* 不要在文档中硬编码当前测试文件数量等容易过期的信息。
* 如果本文件、`docs/architecture.md` 和实现出现冲突：安全与运行边界以本文件为准；具体架构事实以当前实现和 `docs/architecture.md` 交叉确认后修正。
