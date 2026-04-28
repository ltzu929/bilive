# QWEN 2.5 OMNI 视频智能分析功能设计

## Context

用户希望在 bilive 项目中集成 QWEN 2.5 OMNI 全模态模型，用于对直播切片片段进行深度智能分析。现有项目已支持多个 MLLM 模型（Qwen VL、Gemini、GLM-4V-PLUS、SenseNova）生成切片标题，但功能仅限于标题生成。

QWEN 2.5 OMNI 是阿里巴巴新一代全模态模型，具备：
- 端到端音频处理（语音识别 + 情感语调分析）
- 视频画面 + 音频 + 文本多模态融合理解
- 音频生成能力

本设计将 OMNI 集成到切片处理流程，提供标题、描述、标签、质量评分等完整分析能力，并为后续 MCP 视频剪辑功能预留数据接口。

## 流程架构

```
完整录播视频 + 弹幕 XML
    ↓
弹幕密度分析 (现有 slice_video_by_danmaku)
    ↓
切割生成切片视频
    ↓
QWEN OMNI 分析切片
    ↓
分析结果 JSON
├── 标题、描述、标签（上传用）
├── 质量评分 + 是否保留建议
├── MCP 剪辑数据（精彩时间点、情感曲线、裁剪建议）
    ↓
质量筛选（低于阈值则跳过）
    ↓
[MCP 视频剪辑 - 待办功能]
    ↓
上传
```

## 模块结构

```
src/autoslice/
├── mllm_sdk/
│   ├── qwen_omni_sdk.py     # 新增: OMNI 分析 SDK
│   └── ...                  # 现有 SDK 保持不变
├── analysis_result.py       # 新增: 分析结果数据类
├── slice_quality_filter.py  # 新增: 质量筛选器
├── mcp_clipper.py           # 新增(待办): MCP 剪辑模块
├── title_generator.py       # 扩展: 支持 qwen-omni
├── render_video.py          # 扩展: 集成新流程
└── __init__.py
```

## 配置系统

### bilive.toml 新增配置

```toml
[slice]
mllm_model = "qwen-omni"  # 新增选项

[slice.omni]
omni_api_key = ""           # DashScope API Key
omni_deploy_path = ""       # 本地部署路径（可选）
omni_method = "api"         # "api" 或 "deploy"
enable_quality_filter = true
quality_threshold = 0.6
enable_deep_analysis = true   # 为 MCP 剪辑准备数据
analysis_prompt = ""          # 自定义 prompt（可选）
```

## 分析结果数据结构

```json
{
  "title": "切片标题",
  "description": "内容摘要",
  "tags": ["标签1", "标签2"],
  "content_type": "gameplay|chat|singing|dance|other",
  "quality_score": 0.85,
  "retain_recommendation": true,
  "quality_reason": "评估理由",
  "highlights": [{"start": 5.2, "end": 12.8, "score": 0.95}],
  "emotion_peak_time": 15.0,
  "suggested_trim": {"trim_start": 2.0, "trim_end": 58.0, "reason": "..."}
}
```

## 实现阶段

| 阶段 | 功能 | 状态 |
|------|------|------|
| Phase 1 | OMNI SDK + 分析结果数据类 | 本次实现 |
| Phase 2 | 配置系统 + title_generator 扩展 | 本次实现 |
| Phase 3 | render_video 流程集成 + 质量筛选 | 本次实现 |
| Phase 4 | MCP 二次精准剪辑 | 待办 |
| Phase 5 | MCP 情感曲线剪辑 | 待办 |
| Phase 6 | MCP 内容边界优化 | 待办 |

## 待确认项

| 项目 | 说明 | 确认方式 |
|------|------|---------|
| OMNI API 模型名称 | DashScope 上 QWEN OMNI 的实际模型 ID，可能是 `qwen2.5-omni-7b-instruct` 或类似 | 查看 DashScope 模型列表 |
| API Key 是否共用 | `omni_api_key` 是否与现有 `qwen_api_key` 共用，或单独配置 | DashScope API Key 通用，可共用 |
| Endpoint | 与现有 qwen_sdk.py 相同：`https://dashscope.aliyuncs.com/compatible-mode/v1` | 已确认 |

## 关键文件改动

| 文件 | 改动类型 |
|------|---------|
| `bilive.toml` | 新增 `[slice.omni]` 配置节 |
| `src/config.py` | 新增 OMNI 配置变量 |
| `src/autoslice/mllm_sdk/qwen_omni_sdk.py` | 新建 |
| `src/autoslice/analysis_result.py` | 新建 |
| `src/autoslice/slice_quality_filter.py` | 新建 |
| `src/autoslice/title_generator.py` | 扩展 qwen-omni 分支 |
| `src/burn/render_video.py` | 扩展切片处理逻辑 |

## 验证方案

1. **单元测试**: 在 `tests/test_autoslice.py` 添加 OMNI 测试用例
2. **配置验证**: 使用示例视频测试 API 调用和 JSON 解析
3. **流程验证**: 完整录制一个直播间，检查切片分析输出
4. **质量筛选验证**: 设置不同阈值，观察切片保留/跳过行为