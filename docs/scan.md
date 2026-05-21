# 切片管线

## 完整流程

```
scan_slice.py 每 120s 轮询 Videos/ 目录
  ↓ 找到录制完成的 .mp4 + 配对 .xml
  ↓ 排除 _slice 文件和 < 20MB 文件
  ↓ 跳过正在录制中的房间（.flv 无配对 .mp4）
  ↓
1. 弹幕转换 (xml → ass)                  ~1s
2. 获取主播信息                            ~0.5s
3. 弹幕突增切片 (burst_detector + ffmpeg)  ~3s
   burst_ratio=3.0, context=±60s, top_n=3
   ↓
对每个切片（最多3个）：
  4a. 提取弹幕文本 (xml 时间窗口内)
  4b. ASR 转录 (Qwen3-ASR-1.7B / Whisper)  ~20s
  4c. LLM 质量判断 + 标题生成               ~5-15s
      (qwen3.5-9b via LM Studio)
      retain=false → 删除切片
  4d. 深度分析 + 编辑指令（可选）
  4e. 注入元数据 (mp4 → .flv)              ~1s
  4f. 入 SQLite 上传队列
  ↓
5. 清理原始文件 (mp4 + xml + ass)
   (除非 BILIVE_KEEP_SOURCE=1)
```

## 关键代码

| 步骤 | 文件 | 函数 |
|------|------|------|
| 扫描入口 | `src/burn/scan_slice.py` | `process_folder_slice_only()` |
| 切片主流程 | `src/burn/slice_only.py` | `slice_only()` |
| 弹幕转换 | `src/danmaku/generate_danmakus.py` | `process_danmakus()` |
| 突增检测 | `src/autoslice/burst_detector.py` | `detect_bursts()` |
| ASR 转录 | `src/autoslice/mllm_sdk/audio_analyzer.py` | `analyze_audio()` |
| LLM 判断 | `src/autoslice/mllm_sdk/judge.py` | `judge_and_title()` |
| 元数据注入 | `src/autoslice/inject_metadata.py` | `inject_metadata()` |
| 上传队列 | `src/db/conn.py` | SQLite `upload_queue` 表 |

## 两条管线

| 特性 | `scan.py` (完整) | `scan_slice.py` (切片专用) |
|------|-----------------|--------------------------|
| 用途 | 整场渲染+上传 | 仅切片+上传 |
| 弹幕渲染 | 烧录字幕到视频 | 不渲染 |
| 清理 | mp4+xml+ass+srt+jsonl | mp4+xml+ass |

## 已知问题

见 [`known-issues.md`](known-issues.md)：scan_slice 跳过逻辑、GBK 编码、窗口关闭崩溃。
