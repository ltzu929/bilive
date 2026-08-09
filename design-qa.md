# Design QA：切片工作台宽度与导航间距

## 对照证据

- source visual truth:
  - `C:\Users\zk\AppData\Local\Temp\codex-clipboard-343c9c35-1632-43fc-a2c1-ebf95c67a1cb.png`
- implementation screenshots:
  - `D:\alldata\pi\bilive\design-qa-artifacts\review-inspector-width-final.png`
  - `D:\alldata\pi\bilive\design-qa-artifacts\recorder-sidebar-alignment-final.png`
- implementation URL: `http://192.168.1.254:2233/tasks`
- viewport:
  - source：2560 × 1504 px，Windows/Chrome 125% 缩放，对应约 2048 × 1203 CSS px
  - 统一壳实现：2048 × 1203 CSS px，截图 2048 × 1203 px，1x
  - 审阅面板聚焦实现：1280 × 720 CSS px，截图 1265 × 712 px（滚动条占位后内容截图），1x
- density normalization: source 按 1.25 倍桌面缩放归一到 2048 × 1203 CSS px；统一壳截图按 1x 对照。审阅面板另用聚焦截图检查内部占宽，不比较浏览器外壳。
- state: 左侧“切片”选中；切片工作台处于内容审核页签；生产地址 2233/2234 均在监听。

## Full-view comparison

- 信息架构：仍使用录播原生白色侧栏和顶部框架，没有重新引入第二套工作台导航。
- 字体与排版：沿用现有 `Segoe UI`、苹方、微软雅黑回退链；标题、表单标签、导航文字的字号和权重均未改变。
- 间距与布局：六个侧栏入口统一为 `16px` 图标槽、`10px` 列间距，所有文字起点一致；审阅内容强制单列满宽，不再被旧响应式规则分成两列。
- 色彩与 tokens：选中态浅蓝、主色、失败色、边框和背景完全沿用现有 tokens，没有新增漂移色。
- 图像与图标：继续使用项目已有 logo 和 Ant Design 图标资源；没有 CSS 图形、字符图标或替代图片。
- 文案：导航仍为“任务 / 切片 / 上传 / 录播设置 / 工作台设置 / 关于”，未改变产品含义。

## Focused comparison

- 右侧审核检查器：源图中 `.inspector-tab-panel` 仅占可用宽度约一半；实现中 DOM 实测检查器内容区为 303px、活动面板为 303px、标题输入框为 303px，扣除 12px 内边距和滚动条后已完整占满。
- 左侧导航：DOM 实测六个入口的图标 `x=24px、width=16px`，文字容器均为 `x=50px`，列间距均为 `10px`。
- 聚焦证据足以清楚判断本次两个问题；未额外裁切字体和颜色区域，因为本次实现没有改动这些视觉 surfaces，完整截图已可辨认。

## Interactions and runtime checks

- 统一壳能够创建 `#bilive-studio-frame` 并保持“切片”选中态。
- 项目仓库链接仍为 `https://github.com/ltzu929/bilive`。
- 本地静态视觉夹具的 API 404 仅来自无后端预览，不计入生产结果；生产端已只读验证 2233/2234 均在监听，2233 已包含新的导航网格样式，2234 已返回 `20260729-2` 资源版本。
- 自动化验证：目标 UI/桥接测试 28 项通过；完整测试套件 540 项通过、1 项按预期跳过；`frontend/app.js` 通过 Node 语法检查。

## Comparison history

1. 初始证据发现 P1：旧的 `max-width: 1180px` 响应式规则把 `.feedback-body` 切为两列，而新的页签容器只占第一列，造成审阅表单右侧大面积空白。
2. 初始证据发现 P2：原生 Ant 图标与后加的图片图标采用不同 margin，导致侧栏文字起点不一致。
3. 修复：`.review-inspector-body` 改为单列 block 并强制活动页签 `width: 100%`；所有菜单项改用相同的两列 grid 图标槽。
4. 修复后证据：审阅表单的摘要、字段和输入框均与内容区等宽；六个导航入口的图标和文字坐标一致。无剩余 P0/P1/P2。

## Findings

- 无可执行的 P0、P1 或 P2 视觉差异。
- P3：本地静态聚焦截图显示预期的 API 404 提示；这是为了隔离验证 CSS 的预览夹具限制，生产 2233/2234 服务检查正常。

final result: passed
