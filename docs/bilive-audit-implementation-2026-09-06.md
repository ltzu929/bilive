# Bilive audit 实施与验证记录

对应审计：`bilive-audit-2026-09-05.md`。本次实施在原工作区进行，基线为 `c139d7132e3f9c66718215844d2d3b2741af1b37`。原 audit 与 task.md 保留；实施变更按三个阶段分别提交，未推送、安装 wheel 或部署到生产。

## 实施顺序与结果

| 顺序 | 审计项 | 实际实现与主要文件 |
|---|---|---|
| 1 | F01 | `source_workbench.py` 在编辑、范围、丢弃、重新分析、render/reburn/finalize 入口拒绝已激活上传的成片；SQLite staged 撤回使用条件删除事务。render/reburn 统一调用 canonical finalize。批准请求核对 revision 和实际 final_media_id；重复批准同一工件幂等。前端禁止已激活成片的修改动作。 |
| 1 | F08 | `studio-uploads.component.*` 删除误导性的停止按钮。没有实现新的上传暂停状态机。 |
| 2 | F03、B01 | `slice_control.py`、`watcher.py` 保留并共用跨进程 marker claim 锁，processing 不再重复排队；结束时先写 done 再移除 processing。`routes/segments.py` 在编辑前识别相同 finalize，返回原 job，不重复改 revision。 |
| 2 | F07 | `action_jobs.py` 单项损坏 JSON/目标结构隔离到 invalid，保留原文件与错误，继续正常队列；受影响对象的新动作阻止，无法定位损坏目标时阻止新提交。只读查询返回 blocked，不能把未知结果当作完成。 |
| 3 | F04、F05 | `danmaku_slice.py` 在外围检查 ffmpeg 返回码和非空产物，失败不会将部分文件当成功，也不会替换已有媒体；小数秒保留。`source_workbench.py` 人工 finalize 从源范围提取 ASR，`subtitle_burn.py` 从源精确裁剪并烧录，字幕保持片段相对时间。新工件命名区分旧裁剪时间契约。未修改两个上游子模块。 |
| 4 | F02、F06 | `studio-slices.component.*` 真正绑定 final 媒体并区别源/成片时间轴；选片定位。按 jobId、片段恢复观察，超过 90 秒继续观察，GET 故障不重新 POST；可切换审核其他片段。 |
| 4 | F09 | 同标签页 sessionStorage 保存草稿、原 revision、逐片段待丢弃对象；切换/刷新恢复，版本变化提示冲突；部分字段保存不清空其他草稿。丢弃按固定目标记录，到期请求未知不自动再发，过期恢复须显式提交。关闭标签页后不承诺恢复。 |
| 4 | U01–U03 | 修正日期比较、未知日期末尾和实际分组排序；详情加载/失效清空旧对象；源/成片定位、I/O 边界以及输入控件快捷键保护。密度候选可键盘选择；漏切、整场回收按需展开。 |
| 4 | U04–U07 | 上传行带源与片段回链，自动与人工元数据均记录关联；仅可确定的 failed 且无 remote_filename 项提供显式重试。已上传 CDN 的投稿失败需人工核对，不重复视频字节。业务 unavailable/empty/failed 不报成功；ASS 1–9 位置共用映射；Eagle 使用 Studio 深链接。 |
| 5 | B02、B03、B04 | 小录像保留库存并显示跳过原因。源回收在执行前保存清单并逐项持久化已移动结果；未知移动结果拒绝自动继续。SMB 启停步骤设有限时，停止录制服务失败不继续卸载；service 总预算改为 150 秒，保留现有恢复 timer。 |
| 6 | F10、P01、P02、P04 | 同步阻塞路由交由 FastAPI 线程池，保持写锁；唤醒 Windows 放在提交锁外，唤醒失败保留任务。列表复用已读 history，单场详情直接定位；review-status 共用一次进度/队列快照，worker status 默认不重复 preflight，生产启动前预检保留。后台页面跳过常规快照轮询，活动 job 继续观察。上传查询只读，默认 50/最多 100 行，筛选、分页、聚合分开。 |
| 7 | 文档与默认配置 | 更新 README、architecture、operations 的入口、快捷键和两步发布说明；清除受控配置中的个人模型路径。模型回滚仍由本地未跟踪配置提供，不改生产配置。 |

先完成不可变成片、跨进程互斥和幂等，再将同步路由移到线程池，避免原本串行代码被并发放大。媒体错误传播先于新 final 预览。草稿和任务观察共用服务器 revision/jobId，未引入第二套任务状态库。

## 验证

- Python 默认全套：616 passed、1 deselected；最终结果见 `artifacts/audit-implementation/pytest-final.log`；不含 integration/legacy。测试仅使用临时媒体、数据库和替身，未调用真实模型或上传。
- 新增审计回归覆盖不可变成片、staged 激活/撤回交错、源 marker 并发、重复 finalize、坏任务隔离、千行上传分页、慢请求并发、回收部分失败、源小数时间裁剪与音视频产物、SMB 停止失败和上传重试。
- 真实 ffmpeg 合成媒体检查源范围 1.9–4.8 秒、输出时长、画面与音频长度。不是对所有编码格式的兼容承诺。
- `compileall src tests`、`pip check` 通过；Eagle `node --test` 16 项通过。
- Studio ChromeHeadless 行为测试 13 项通过，包括实际分组排序、媒体 src、超过 90 秒观察、草稿、错误状态和 ASS 位置。完整 Angular 全套为 52 成功、58 失败，失败主要是旧组件测试缺少 HttpClient/NzMessageService 等注入依赖；没有顺手重写这些无关测试，不能声称前端全套通过。
- 生产 Angular 构建通过；仍有初始 bundle 1.25 MB 与 slices 样式 9.05 kB 超预算警告，以及两条上游选择器处理警告。
- 使用本次构建生成隔离 wheel，通过 `BILIVE_TEST_WHEEL` 指向产物执行 Native UI 合同测试；10 项通过。仓库原 wheel 未覆盖，隔离 wheel 未安装。
- 浏览器访问独立的 `127.0.0.1:18235` 夹具：最终媒体绑定 `/studio-api/media/final`；源媒体绑定 `/studio-api/media/source` 并定位 10 秒；编辑标题、切换候选、返回及刷新后草稿保持，发布按钮禁用，放弃草稿后恢复服务器标题。全过程未点击真实投稿。
- Git Bash `bash -n deploy/bilive-smb-recover.sh` 通过；脚本替身测试验证服务停止失败不继续挂载、成功分支限时之和小于 150 秒。WSL 已执行真实 service/timer 的 `systemd-analyze verify`，但本地没有 `/usr/local/sbin/bilive-smb-recover`，返回非零；另有 Windows 挂载权限提示。不能当作 Pi 安装状态验证通过。
- 最终构建另在无旧 Service Worker 缓存的 `127.0.0.1:18236` 验证：整场回收和漏切默认折叠，成片模式下漏切 I/O 取点按钮禁用。旧隔离地址曾加载缓存版本；部署后需确认浏览器实际加载的新构建，不能只看磁盘 wheel。
- 未修改 PowerShell 文件，未运行真实 Pi 重启、SMB 断网、Windows 重启、模型调用、字幕主观质量或真实上传验收。

## 测量项与保留边界

W01 与 P03 按计划只测量，不调整 ASR 预转录策略、720p/码率、MiMo/GPU 并发或协议。无真实样本授权时，不把替身调用次数换算成真实节省时间。

`artifacts/audit-implementation/measure_costs.py` 与 `measurements.json` 记录同机本地磁盘合成输入：

| 合成库存 | 每次 history 读取 | 5 次中位数 | 5 次最大值 |
|---|---:|---:|---:|
| 10 场 | 10 | 44.9 ms | 47.3 ms |
| 100 场 | 100 | 901.3 ms | 1196.7 ms |
| 1000 场 | 1000 | 10522.5 ms | 10757.1 ms |

这是空 history、小文件合成库存，并非生产 SMB 或有大量工件的 p95。当前清单仍线性扫描，1000 场仍明显慢；按 segmentId 的旧动作定位也仍需搜索历史。没有引入长期缓存/新数据库/索引框架。减少重复读取不等于解决历史增长的所有成本。

65 秒 320×180 纯色合成视频，现有 MiMo 分析编码耗时约 0.79 秒，Base64 47556 字节，data URL 47578 字节。纯色高度可压缩，不能代表直播素材体积、48 MB 边界或 RSS 峰值。未测真实模型 ASR 时间与高并发 RSS；保留为需要实际样本的验收项。

单个带 trim 的 review 窗口，在替身 ASR 下调用计数为 1。保留当前行为；未实现自动跳过 review 或 duplicate ASR。

## 交付边界与偏差

正确性和审核闭环按上述顺序落地；W01/P03 保持测量范围。没有完成生产环境验收、完整 Angular 旧测试修复或大库存扫描根治。Origin 改写的部署鉴权问题仍保留独立调查边界，未将静态怀疑包装成已证实可利用漏洞，也未擅改访问控制。

发布前需在实际部署环境完成 unit 校验与隔离人工成片验收。当前交付是可审查的本地代码、测试和构建证据，不是已部署或可保证生产无故障的声明。

## 阶段提交组织

提交按“正确性与恢复 → 审核工作台闭环 → 请求与查询优化”组织。成片身份、版本和动作状态等后端契约作为第一阶段前置基础；前端局部修复与审核闭环在第二阶段一起交付；上传回链/重试与分页在第三阶段一起交付。第二阶段使用现有三个状态接口，第三阶段再切换共享快照，避免中间提交请求尚不存在的接口。三个提交是连续实现步骤，不代表三个阶段均已完成生产验收。
