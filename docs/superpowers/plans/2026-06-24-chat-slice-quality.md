# Chat Slice Quality Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build MiMo-driven chat slice selection so broad danmaku candidates can produce zero, one, or multiple independently postable chat clips with Bilibili-style metadata.

**Architecture:** Keep the existing Pi/Windows boundary: Pi only queues work, Windows runs slicing, MiMo, ASR, subtitles, and upload queueing. The pipeline will broaden danmaku candidates, ask MiMo for an array of clip decisions, validate/render each kept clip separately, and preserve review records for dropped or failed clips.

**Tech Stack:** Python 3, pytest, dataclasses, ffmpeg/ffprobe, OpenAI-compatible MiMo API, existing `src.autoslice`, `src.burn`, `src.dashboard`, and SQLite upload queue.

---

## File Structure

- Modify `bilive-server.toml`: raise production chat candidate context defaults.
- Modify `src/autoslice/analysis_result.py`: add multi-clip friendly metadata fields to `AnalysisResult`.
- Modify `src/autoslice/mllm_sdk/mimo_video.py`: update prompt, parse `clips` arrays, and preserve backward-compatible single-result wrapper.
- Modify `src/autoslice/candidate_analyzer.py`: add `analyze_candidate_clips()` while keeping `analyze_candidate()` for callers that still expect one result.
- Modify `src/burn/subtitle_burn.py`: render subtitles from a source candidate to a separate output path without overwriting the broad candidate.
- Modify `src/burn/slice_only.py`: process multiple MiMo clip decisions per broad candidate and write one segment per clip.
- Modify `src/burn/pipeline_stages.py`: add a list-returning analysis stage helper.
- Test `tests/test_mimo_video_analyzer.py`: prompt/schema parsing.
- Test `tests/test_candidate_analyzer.py`: multi-clip ASR validation.
- Test `tests/test_subtitle_burn.py`: separate output rendering.
- Test `tests/test_slice_only_multi_clip.py`: end-to-end slice-only behavior with two kept clips.

## Scope Check

This is one subsystem: the Windows-side slicing quality pipeline. Do not change Pi services, upload publishing behavior, credential handling, or dashboard visual design in this plan.

### Task 1: Add AnalysisResult Fields For Chat Clip Decisions

**Files:**
- Modify: `src/autoslice/analysis_result.py`
- Test: `tests/test_mimo_video_analyzer.py`

- [ ] **Step 1: Write failing serialization test**

Append this test to `tests/test_mimo_video_analyzer.py`:

```python
def test_analysis_result_round_trips_chat_clip_fields():
    from src.autoslice.analysis_result import AnalysisResult, TrimSuggestion

    result = AnalysisResult(
        title="弹幕一句话把主播整不会了",
        description="主播回应弹幕提问时被一句话逗笑，随后接梗收住。",
        tags=["直播切片", "聊天", "弹幕互动"],
        quality_score=0.91,
        retain_recommendation=True,
        quality_reason="完整互动，有铺垫和落点",
        judge_status="keep",
        suggested_trim=TrimSuggestion(12.0, 64.0, "best standalone clip"),
        clip_type="audience_interaction",
        topic_summary="弹幕一句话引出主播接梗",
        why_viewer_would_watch="陌生观众能快速理解包袱并看到主播反应",
        completeness_score=0.87,
        confidence=0.9,
    )

    restored = AnalysisResult.from_dict(result.to_dict())

    assert restored.clip_type == "audience_interaction"
    assert restored.topic_summary == "弹幕一句话引出主播接梗"
    assert restored.why_viewer_would_watch == "陌生观众能快速理解包袱并看到主播反应"
    assert restored.completeness_score == 0.87
    assert restored.confidence == 0.9
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
python -m pytest tests/test_mimo_video_analyzer.py::test_analysis_result_round_trips_chat_clip_fields -q
```

Expected: FAIL because `AnalysisResult.__init__()` does not accept `clip_type`.

- [ ] **Step 3: Add fields and serialization**

In `src/autoslice/analysis_result.py`, add these fields to `AnalysisResult` after `token_usage`:

```python
    clip_type: str = ""
    topic_summary: str = ""
    why_viewer_would_watch: str = ""
    completeness_score: float = 0.0
    confidence: float = 0.0
```

In `from_dict()`, pass these values:

```python
            clip_type=data.get("clip_type", ""),
            topic_summary=data.get("topic_summary", ""),
            why_viewer_would_watch=data.get("why_viewer_would_watch", ""),
            completeness_score=data.get("completeness_score", 0.0),
            confidence=data.get("confidence", 0.0),
```

In `to_dict()`, add:

```python
            "clip_type": self.clip_type,
            "topic_summary": self.topic_summary,
            "why_viewer_would_watch": self.why_viewer_would_watch,
            "completeness_score": self.completeness_score,
            "confidence": self.confidence,
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```powershell
python -m pytest tests/test_mimo_video_analyzer.py::test_analysis_result_round_trips_chat_clip_fields -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/autoslice/analysis_result.py tests/test_mimo_video_analyzer.py
git commit -m "feat: add chat clip analysis fields"
```

### Task 2: Parse MiMo Multi-Clip Decisions

**Files:**
- Modify: `src/autoslice/mllm_sdk/mimo_video.py`
- Test: `tests/test_mimo_video_analyzer.py`

- [ ] **Step 1: Write failing parser tests**

Append these tests to `tests/test_mimo_video_analyzer.py`:

```python
def test_mimo_multi_clip_response_parses_kept_clips():
    from src.autoslice.mllm_sdk.mimo_video import _analysis_list_from_mimo_dict

    data = {
        "clips": [
            {
                "decision": "keep",
                "clip_type": "story",
                "topic_summary": "主播讲第一次遇到离谱弹幕",
                "why_viewer_would_watch": "有完整铺垫、反应和收束",
                "reason": "完整聊天短片",
                "title": "这条弹幕让主播回忆起离谱往事",
                "description": "主播从弹幕问题聊到一次离谱经历。",
                "tags": ["直播切片", "聊天", "故事"],
                "quality_score": 0.93,
                "completeness_score": 0.9,
                "confidence": 0.88,
                "trim_start": 20.0,
                "trim_end": 82.0,
            },
            {
                "decision": "keep",
                "clip_type": "emotional_reaction",
                "topic_summary": "主播被观众一句话逗笑",
                "why_viewer_would_watch": "笑点清楚，结尾自然",
                "reason": "有明确情绪反应",
                "title": "弹幕一句话把主播整笑了",
                "description": "主播接住弹幕玩笑并自然收住。",
                "tags": ["直播切片", "弹幕互动"],
                "quality_score": 0.89,
                "completeness_score": 0.85,
                "confidence": 0.84,
                "trim_start": 120.0,
                "trim_end": 162.0,
            },
        ]
    }

    results = _analysis_list_from_mimo_dict(data, artist="主播", model="mimo-v2.5")

    assert [item.title for item in results] == [
        "这条弹幕让主播回忆起离谱往事",
        "弹幕一句话把主播整笑了",
    ]
    assert results[0].clip_type == "story"
    assert results[0].suggested_trim.trim_start == 20.0
    assert results[1].confidence == 0.84


def test_mimo_multi_clip_response_drops_empty_clip_list():
    from src.autoslice.mllm_sdk.mimo_video import _analysis_list_from_mimo_dict

    results = _analysis_list_from_mimo_dict({"clips": []}, artist="主播", model="mimo-v2.5")

    assert results == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
python -m pytest tests/test_mimo_video_analyzer.py::test_mimo_multi_clip_response_parses_kept_clips tests/test_mimo_video_analyzer.py::test_mimo_multi_clip_response_drops_empty_clip_list -q
```

Expected: FAIL because `_analysis_list_from_mimo_dict` does not exist.

- [ ] **Step 3: Implement parser helper**

In `src/autoslice/mllm_sdk/mimo_video.py`, add this helper below `_analysis_from_mimo_dict()`:

```python
def _analysis_list_from_mimo_dict(
    data: dict[str, Any],
    *,
    artist: str,
    model: str,
) -> list[AnalysisResult]:
    clips = data.get("clips")
    if clips is None:
        single = _analysis_from_mimo_dict(data, artist=artist, model=model)
        return [single] if single.judge_status == "keep" else []
    if not isinstance(clips, list):
        return [
            _failed_result(
                artist,
                "MiMo response clips must be an array",
                model=model,
            )
        ]

    results: list[AnalysisResult] = []
    for index, clip in enumerate(clips, start=1):
        if not isinstance(clip, dict):
            results.append(
                _failed_result(
                    artist,
                    f"MiMo clip #{index} must be an object",
                    model=model,
                )
            )
            continue
        result = _analysis_from_mimo_dict(clip, artist=artist, model=model)
        if result.judge_status == "keep":
            result.clip_type = str(clip.get("clip_type") or "").strip()
            result.topic_summary = str(clip.get("topic_summary") or "").strip()
            result.why_viewer_would_watch = str(clip.get("why_viewer_would_watch") or "").strip()
            result.completeness_score = _bounded_float(clip.get("completeness_score"), default=0.0)
            result.confidence = _bounded_float(clip.get("confidence"), default=0.0)
            results.append(result)
    return results
```

Add this helper near `_usage_to_dict()`:

```python
def _bounded_float(value: Any, *, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(parsed):
        return default
    return max(0.0, min(1.0, parsed))
```

- [ ] **Step 4: Run parser tests**

Run:

```powershell
python -m pytest tests/test_mimo_video_analyzer.py::test_mimo_multi_clip_response_parses_kept_clips tests/test_mimo_video_analyzer.py::test_mimo_multi_clip_response_drops_empty_clip_list -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/autoslice/mllm_sdk/mimo_video.py tests/test_mimo_video_analyzer.py
git commit -m "feat: parse mimo multi-clip decisions"
```

### Task 3: Update MiMo Prompt For Chat Slice Direction

**Files:**
- Modify: `src/autoslice/mllm_sdk/mimo_video.py`
- Test: `tests/test_mimo_video_analyzer.py`

- [ ] **Step 1: Write failing prompt test**

Append this test to `tests/test_mimo_video_analyzer.py`:

```python
def test_mimo_prompt_describes_chat_slice_editor_role():
    from src.autoslice.mllm_sdk.mimo_video import _build_prompt

    prompt = _build_prompt(
        artist="主播",
        danmaku_text="哈哈哈 主播被整不会了",
        candidate_duration=240.0,
    )

    assert "短视频剪辑师" in prompt
    assert "严格主编" in prompt
    assert "弹幕峰值只是候选来源" in prompt
    assert "clips" in prompt
    assert "B 站口语标题" in prompt
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
python -m pytest tests/test_mimo_video_analyzer.py::test_mimo_prompt_describes_chat_slice_editor_role -q
```

Expected: FAIL because the current prompt is generic English highlight judging text.

- [ ] **Step 3: Replace `_build_prompt()` body**

Replace `_build_prompt()` in `src/autoslice/mllm_sdk/mimo_video.py` with:

```python
def _build_prompt(*, artist: str, danmaku_text: str, candidate_duration: float) -> str:
    return (
        "候选元数据:\n"
        f"- 主播: {artist or 'unknown'}\n"
        f"- 候选时长秒数: {float(candidate_duration or 0):.3f}\n"
        f"- 候选范围内弹幕: {str(danmaku_text or '').strip() or '(none)'}\n\n"
        "你的角色:\n"
        "你是短视频剪辑师 + 严格主编。你的目标不是多产出切片，"
        "而是避免发布低质量聊天切片。弹幕峰值只是候选来源，不是保留理由。\n\n"
        "任务:\n"
        "在这个最多约 5 分钟的直播聊天候选里，找出 0 个、1 个或多个"
        "可以独立投稿的聊天短片。故事、观点、情绪反应、弹幕互动没有固定"
        "优先级；选择最能独立成片、最容易被陌生观众理解、最有观看价值的片段。\n\n"
        "每个保留片段必须:\n"
        "- 有明确主题，能被一句具体标题概括。\n"
        "- 陌生观众不看原直播上下文也能理解。\n"
        "- 有清楚开头、发展和落点。\n"
        "- 至少具备一种观看价值: 完整梗或故事、明确观点、强情绪反应、弹幕互动。\n"
        "- 标题采用 B 站口语标题，轻微整活但不夸张，不能写泛泛的直播精彩片段。\n\n"
        "返回 JSON object，必须只有一个顶层字段 clips。clips 是数组。"
        "如果没有达标片段，返回 {\"clips\": []}。每个 clips 元素必须包含:"
        " decision, clip_type, topic_summary, why_viewer_would_watch, reason, "
        "title, description, tags, quality_score, completeness_score, confidence, "
        "trim_start, trim_end。decision 只能是 keep。trim_start/trim_end 是相对"
        "候选视频开头的秒数。tags 是字符串数组。"
    )
```

- [ ] **Step 4: Run prompt test**

Run:

```powershell
python -m pytest tests/test_mimo_video_analyzer.py::test_mimo_prompt_describes_chat_slice_editor_role -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/autoslice/mllm_sdk/mimo_video.py tests/test_mimo_video_analyzer.py
git commit -m "feat: prompt mimo as chat slice editor"
```

### Task 4: Add Multi-Clip MiMo API Wrapper

**Files:**
- Modify: `src/autoslice/mllm_sdk/mimo_video.py`
- Test: `tests/test_mimo_video_analyzer.py`

- [ ] **Step 1: Write failing wrapper test**

Append:

```python
def test_judge_candidate_clips_with_mimo_returns_multiple(monkeypatch):
    from src.autoslice.mllm_sdk import mimo_video
    from src.autoslice.mllm_sdk.mimo_video import EncodedMimoVideo

    class Message:
        content = (
            '{"clips":[{"decision":"keep","clip_type":"story",'
            '"topic_summary":"完整故事","why_viewer_would_watch":"有铺垫和落点",'
            '"reason":"完整","title":"主播讲了一个离谱故事",'
            '"description":"主播从弹幕聊到一次经历。","tags":["直播切片"],'
            '"quality_score":0.9,"completeness_score":0.86,"confidence":0.87,'
            '"trim_start":10,"trim_end":70}]}'
        )

    class Choice:
        message = Message()

    class Completion:
        choices = [Choice()]
        usage = {"total_tokens": 100}
        model = "mimo-v2.5"

    class Completions:
        def create(self, **kwargs):
            return Completion()

    class Chat:
        completions = Completions()

    class Client:
        chat = Chat()

    monkeypatch.setenv("MIMO_API_KEY", "key")

    results = mimo_video.judge_candidate_clips_with_mimo(
        video_path="candidate.mp4",
        artist="主播",
        danmaku_text="弹幕",
        candidate_duration=240.0,
        client_factory=lambda **kwargs: Client(),
        encoder=lambda *args, **kwargs: EncodedMimoVideo("data:video/mp4;base64,AAAA", 4),
    )

    assert len(results) == 1
    assert results[0].title == "主播讲了一个离谱故事"
    assert results[0].token_usage == {"total_tokens": 100}
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
python -m pytest tests/test_mimo_video_analyzer.py::test_judge_candidate_clips_with_mimo_returns_multiple -q
```

Expected: FAIL because `judge_candidate_clips_with_mimo` does not exist.

- [ ] **Step 3: Implement wrapper**

Refactor `judge_candidate_with_mimo()` internals into a new function:

```python
def judge_candidate_clips_with_mimo(
    *,
    video_path: str,
    artist: str,
    danmaku_text: str,
    candidate_duration: float,
    model: str = MIMO_MODEL,
    base_url: str = MIMO_BASE_URL,
    fps: float = MIMO_FPS,
    media_resolution: str = MIMO_MEDIA_RESOLUTION,
    timeout: float = MIMO_TIMEOUT,
    max_base64_bytes: int = MIMO_MAX_BASE64_BYTES,
    client_factory=OpenAI,
    encoder: Callable[..., EncodedMimoVideo] = encode_video_for_mimo,
) -> list[AnalysisResult]:
    api_key = os.environ.get("MIMO_API_KEY")
    if not api_key:
        reason = "MIMO_API_KEY is not set"
        _set_status("error", error=reason)
        return [_failed_result(artist, reason, model=model)]

    try:
        encoded = encoder(video_path, max_base64_bytes=max_base64_bytes)
        client = client_factory(api_key=api_key, base_url=base_url)
        _set_status("requesting")
        completion = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是直播聊天切片的短视频剪辑师和严格主编。"
                        "根据视频、音频、弹幕和时间关系，返回严格 JSON。"
                    ),
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "video_url",
                            "video_url": {"url": encoded.url},
                            "fps": float(fps),
                            "media_resolution": str(media_resolution),
                        },
                        {
                            "type": "text",
                            "text": _build_prompt(
                                artist=artist,
                                danmaku_text=danmaku_text,
                                candidate_duration=candidate_duration,
                            ),
                        },
                    ],
                },
            ],
            max_completion_tokens=2048,
            timeout=timeout,
            response_format={"type": "json_object"},
            extra_body={"thinking": {"type": "disabled"}},
        )
    except Exception as exc:
        reason = f"MiMo failed: {exc}"
        _set_status("error", error=reason)
        scan_log.warning(reason)
        return [_failed_result(artist, reason, model=model)]

    try:
        if not completion.choices:
            raise ValueError("MiMo response did not include any choices")
        message = completion.choices[0].message
        parsed = _extract_json(str(getattr(message, "content", "") or ""))
        if parsed is None:
            raise ValueError("MiMo JSON parse failed")
        results = _analysis_list_from_mimo_dict(parsed, artist=artist, model=model)
        usage = _usage_to_dict(getattr(completion, "usage", None))
        response_model = str(getattr(completion, "model", model) or model)
        for result in results:
            result.token_usage = usage
            result.model_name = response_model
    except Exception as exc:
        reason = f"MiMo response failed: {exc}"
        _set_status("error", error=reason)
        return [_failed_result(artist, reason, model=model)]

    _set_status("idle")
    return results
```

Then update `judge_candidate_with_mimo()` to keep backward compatibility:

```python
    results = judge_candidate_clips_with_mimo(
        video_path=video_path,
        artist=artist,
        danmaku_text=danmaku_text,
        candidate_duration=candidate_duration,
        model=model,
        base_url=base_url,
        fps=fps,
        media_resolution=media_resolution,
        timeout=timeout,
        max_base64_bytes=max_base64_bytes,
        client_factory=client_factory,
        encoder=encoder,
    )
    if not results:
        return AnalysisResult(
            title=f"{artist} candidate",
            description="Pending manual review",
            tags=["live"],
            retain_recommendation=False,
            quality_reason="MiMo found no postable chat clips",
            judge_status="drop",
            model_name=model,
        )
    return results[0]
```

- [ ] **Step 4: Run wrapper tests**

Run:

```powershell
python -m pytest tests/test_mimo_video_analyzer.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/autoslice/mllm_sdk/mimo_video.py tests/test_mimo_video_analyzer.py
git commit -m "feat: add mimo multi-clip judging"
```

### Task 5: Add Multi-Clip Candidate Analyzer

**Files:**
- Modify: `src/autoslice/candidate_analyzer.py`
- Test: `tests/test_candidate_analyzer.py`

- [ ] **Step 1: Write failing multi-clip analyzer test**

Append:

```python
def test_analyze_candidate_clips_runs_asr_for_each_mimo_clip(monkeypatch):
    from src.autoslice import candidate_analyzer

    monkeypatch.setattr(
        candidate_analyzer,
        "judge_candidate_clips_with_mimo",
        lambda **kwargs: [
            _mimo_keep(trim_start=2.0, trim_end=12.0, title="Clip A"),
            _mimo_keep(trim_start=30.0, trim_end=55.0, title="Clip B"),
        ],
    )
    audio_calls = []

    def fake_analyze_audio(video_path, model, **kwargs):
        audio_calls.append(kwargs)
        return {
            "transcript": "有效字幕",
            "segments": [{"start": 0.0, "end": 2.0, "text": "有效字幕"}],
        }

    monkeypatch.setattr(candidate_analyzer, "analyze_audio", fake_analyze_audio)

    results = candidate_analyzer.analyze_candidate_clips(
        "candidate.mp4",
        "主播",
        "弹幕",
        candidate_start=100.0,
        candidate_end=340.0,
        candidate_duration=240.0,
    )

    assert [item.title for item in results] == ["Clip A", "Clip B"]
    assert results[0].source_start == 102.0
    assert results[1].source_end == 155.0
    assert audio_calls == [
        {
            "whisper_device": candidate_analyzer.WHISPER_DEVICE,
            "whisper_compute_type": candidate_analyzer.WHISPER_COMPUTE_TYPE,
            "start_seconds": 2.0,
            "duration_seconds": 10.0,
        },
        {
            "whisper_device": candidate_analyzer.WHISPER_DEVICE,
            "whisper_compute_type": candidate_analyzer.WHISPER_COMPUTE_TYPE,
            "start_seconds": 30.0,
            "duration_seconds": 25.0,
        },
    ]
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
python -m pytest tests/test_candidate_analyzer.py::test_analyze_candidate_clips_runs_asr_for_each_mimo_clip -q
```

Expected: FAIL because `analyze_candidate_clips` does not exist.

- [ ] **Step 3: Implement `analyze_candidate_clips()`**

In `src/autoslice/candidate_analyzer.py`, import the multi-clip MiMo function:

```python
from src.autoslice.mllm_sdk.mimo_video import (
    judge_candidate_clips_with_mimo,
    judge_candidate_with_mimo,
)
```

Add this function above `analyze_candidate()`:

```python
def analyze_candidate_clips(
    video_path: str,
    artist: str,
    danmaku_text: str,
    *,
    candidate_start: float = 0.0,
    candidate_end: float | None = None,
    candidate_duration: float | None = None,
) -> list[AnalysisResult]:
    duration = _resolve_candidate_duration(
        candidate_start,
        candidate_end,
        candidate_duration,
    )
    results = judge_candidate_clips_with_mimo(
        video_path=video_path,
        artist=artist,
        danmaku_text=str(danmaku_text or ""),
        candidate_duration=duration,
    )

    analyzed: list[AnalysisResult] = []
    for result in results:
        _annotate_ranges(
            result,
            candidate_start,
            candidate_end,
            duration,
            include_trim=False,
        )
        if result.judge_status == "judge_failed":
            analyzed.append(result)
            continue
        if result.judge_status == "drop" or not result.retain_recommendation:
            result.judge_status = "drop"
            result.retain_recommendation = False
            analyzed.append(result)
            continue
        if not str(result.title or "").strip():
            analyzed.append(
                _failed_result(
                    artist,
                    "MiMo keep response did not include a title",
                    base=result,
                )
            )
            continue
        trim_error = _validate_trim(result, duration)
        if trim_error:
            result.suggested_trim = None
            analyzed.append(_failed_result(artist, trim_error, base=result))
            continue

        trim = result.suggested_trim
        assert trim is not None
        _annotate_ranges(
            result,
            candidate_start,
            candidate_end,
            duration,
            include_trim=True,
        )
        try:
            audio = analyze_audio(
                video_path,
                MULTI_MODAL_WHISPER_MODEL,
                whisper_device=WHISPER_DEVICE,
                whisper_compute_type=WHISPER_COMPUTE_TYPE,
                start_seconds=float(trim.trim_start),
                duration_seconds=float(trim.trim_end - trim.trim_start),
            )
        except Exception as exc:
            analyzed.append(_failed_result(artist, f"ASR failed: {exc}", base=result))
            continue

        transcript = str(audio.get("transcript") or "").strip()
        if not transcript:
            detail = str(audio.get("error") or "ASR produced no transcript")
            analyzed.append(_failed_result(artist, detail, base=result))
            continue
        segments = _valid_transcript_segments(audio.get("segments"))
        if not segments:
            analyzed.append(
                _failed_result(
                    artist,
                    "ASR produced no valid timestamped transcript segments",
                    base=result,
                )
            )
            continue
        result.transcript = transcript
        result.transcript_segments = segments
        analyzed.append(result)
    return analyzed
```

- [ ] **Step 4: Run analyzer tests**

Run:

```powershell
python -m pytest tests/test_candidate_analyzer.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/autoslice/candidate_analyzer.py tests/test_candidate_analyzer.py
git commit -m "feat: analyze multiple chat clips per candidate"
```

### Task 6: Render Subtitles To Separate Output Files

**Files:**
- Modify: `src/burn/subtitle_burn.py`
- Test: `tests/test_subtitle_burn.py`

- [ ] **Step 1: Write failing output-path test**

Append:

```python
def test_burn_subtitles_can_write_to_separate_output_path(tmp_path):
    from src.autoslice.analysis_result import AnalysisResult, TranscriptSegment, TrimSuggestion
    from src.burn.subtitle_burn import burn_subtitles_from_analysis

    source = tmp_path / "candidate.mp4"
    output = tmp_path / "final_clip.mp4"
    source.write_bytes(b"candidate")
    analysis = AnalysisResult(
        title="Clip",
        description="Description",
        transcript_segments=[TranscriptSegment(start=0.0, end=1.0, text="字幕")],
        suggested_trim=TrimSuggestion(2.0, 8.0, "clip"),
    )

    commands = []

    def fake_run(command, check, capture_output, text, encoding):
        commands.append(command)
        output.write_bytes(b"rendered")

    result = burn_subtitles_from_analysis(source, analysis, output_path=output, run=fake_run)

    assert result.burned is True
    assert source.read_bytes() == b"candidate"
    assert output.read_bytes() == b"rendered"
    assert commands[0][-1] == str(output)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
python -m pytest tests/test_subtitle_burn.py::test_burn_subtitles_can_write_to_separate_output_path -q
```

Expected: FAIL because `burn_subtitles_from_analysis()` has no `output_path` parameter.

- [ ] **Step 3: Implement output path support**

Update the signature in `src/burn/subtitle_burn.py`:

```python
def burn_subtitles_from_analysis(
    video_path: str | Path,
    analysis: AnalysisResult,
    *,
    output_path: str | Path | None = None,
    font_size: int = 20,
    margin_v: int = 60,
    run=subprocess.run,
    probe_duration: Callable[[Path], float | None] | None = None,
    allow_plain_transcript_fallback: bool = False,
) -> BurnSubtitleResult:
```

After `video_path = Path(video_path)`, add:

```python
    final_output = Path(output_path) if output_path is not None else video_path
```

Replace `temp_output = ...` with:

```python
    temp_output = (
        final_output
        if output_path is not None
        else video_path.with_name(f"{video_path.stem}_subtitled.tmp{video_path.suffix}")
    )
```

Replace `os.replace(temp_output, video_path)` with:

```python
        if output_path is None:
            os.replace(temp_output, video_path)
```

Return `video_path=str(final_output)`.

- [ ] **Step 4: Run subtitle tests**

Run:

```powershell
python -m pytest tests/test_subtitle_burn.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/burn/subtitle_burn.py tests/test_subtitle_burn.py
git commit -m "feat: render subtitle clips to separate files"
```

### Task 7: Process Multiple Clips In Slice Pipeline

**Files:**
- Modify: `src/burn/pipeline_stages.py`
- Modify: `src/burn/slice_only.py`
- Test: `tests/test_slice_only_multi_clip.py`

- [ ] **Step 1: Add failing pipeline test**

Create `tests/test_slice_only_multi_clip.py`:

```python
from pathlib import Path

from src.autoslice.analysis_result import AnalysisResult, TrimSuggestion, TranscriptSegment


def _write_source(room: Path) -> Path:
    source = room / "123_20260624-10-00-00.mp4"
    source.write_bytes(b"x" * 1024 * 1024 * 25)
    source.with_suffix(".xml").write_text(
        "<?xml version=\"1.0\"?><i>"
        "<d p=\"10,1,25,16777215,0,0,0,0\">哈哈</d>"
        "<d p=\"20,1,25,16777215,0,0,0,0\">整不会了</d>"
        "</i>",
        encoding="utf-8",
    )
    return source


def _clip(title, start, end):
    return AnalysisResult(
        title=title,
        description=f"{title} desc",
        tags=["直播切片"],
        retain_recommendation=True,
        quality_reason="complete chat clip",
        judge_status="keep",
        quality_score=0.9,
        suggested_trim=TrimSuggestion(start, end, "clip"),
        transcript="有效字幕",
        transcript_segments=[TranscriptSegment(0.0, 1.0, "有效字幕")],
    )


def test_slice_only_outputs_multiple_mimo_clips(monkeypatch, tmp_path):
    from src.burn import slice_only as slice_module
    from src.autoslice.danmaku_slice import GeneratedSlice

    room = tmp_path / "Videos" / "123"
    room.mkdir(parents=True)
    source = _write_source(room)
    candidate = room / "0s_123_20260624-10-00-00.mp4"
    candidate.write_bytes(b"candidate")

    monkeypatch.setattr(slice_module, "MIN_VIDEO_SIZE", 1)
    monkeypatch.setattr(
        slice_module,
        "slice_video_by_danmaku",
        lambda *args, **kwargs: [
            GeneratedSlice(str(candidate), 0.0, 10.0, 0.0, 240.0, 240.0, 2)
        ],
    )
    monkeypatch.setattr(slice_module, "extract_danmaku_text", lambda *args, **kwargs: "弹幕")
    monkeypatch.setattr(slice_module, "analyze_candidate_clips", lambda *args, **kwargs: [
        _clip("Clip A", 10.0, 40.0),
        _clip("Clip B", 90.0, 130.0),
    ])

    burned = []

    def fake_burn(video_path, analysis, *, output_path=None):
        Path(output_path).write_bytes(f"rendered {analysis.title}".encode("utf-8"))
        burned.append((Path(video_path), Path(output_path), analysis.title))
        return type("Burn", (), {"burned": True, "message": "ok"})()

    monkeypatch.setattr(slice_module, "burn_subtitles_from_analysis", fake_burn)
    monkeypatch.setattr(slice_module, "write_slice_upload_metadata", lambda *args, **kwargs: None)
    monkeypatch.setattr(slice_module, "insert_upload_queue", lambda path: True)
    monkeypatch.setattr(slice_module, "get_upload_item", lambda path: None)
    monkeypatch.setattr(slice_module, "get_video_info", lambda path: ("title", "主播", "date"))

    result = slice_module.slice_only(str(source), burst_context=120)

    assert result["status"] == "done"
    assert result["slice_count"] == 2
    assert len(result["segments"]) == 2
    assert [segment["title"] for segment in result["segments"]] == ["Clip A", "Clip B"]
    assert len(burned) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
python -m pytest tests/test_slice_only_multi_clip.py -q
```

Expected: FAIL because `slice_only.py` still calls `analyze_stage()` and expects one result.

- [ ] **Step 3: Add list analysis helper**

In `src/burn/pipeline_stages.py`, add:

```python
def analyze_clips_stage(
    video_path: str,
    *,
    artist: str,
    danmaku_text: str,
    candidate_start: float | None = None,
    candidate_end: float | None = None,
    candidate_duration: float | None = None,
    analyzer: Callable[..., Any],
) -> list[AnalysisResult]:
    results = analyzer(
        video_path,
        artist,
        danmaku_text=danmaku_text,
        candidate_start=candidate_start,
        candidate_end=candidate_end,
        candidate_duration=candidate_duration,
    )
    if not isinstance(results, list) or any(
        not isinstance(item, AnalysisResult) for item in results
    ):
        raise TypeError("candidate analyzer must return list[AnalysisResult]")
    return results
```

- [ ] **Step 4: Update `slice_only.py` imports**

Change imports:

```python
from src.autoslice.candidate_analyzer import (
    analyze_candidate_clips,
    unload_candidate_models,
)
from src.burn.pipeline_stages import (
    analyze_clips_stage,
    enqueue_stage,
    metadata_stage,
    subtitle_stage,
)
```

- [ ] **Step 5: Add final clip path helper**

Add below `source_rel_path()`:

```python
def clip_output_path(candidate_path, analysis, index):
    source_start = (
        analysis.source_start
        if analysis.source_start is not None
        else float(index)
    )
    stem = Path(candidate_path).stem
    suffix = Path(candidate_path).suffix
    return str(Path(candidate_path).with_name(
        f"{format_seconds_for_filename(source_start)}s_{stem}_clip{index}{suffix}"
    ))
```

Import `format_seconds_for_filename`:

```python
from src.autoslice.danmaku_slice import extract_danmaku_text, format_seconds_for_filename
```

- [ ] **Step 6: Replace single-result processing loop**

Inside the `for index, generated_slice ...` block, replace the `result = analyze_stage(...)` call and subsequent single-result handling with:

```python
            results = analyze_clips_stage(
                slice_path,
                artist=artist,
                danmaku_text=danmaku_text,
                candidate_start=generated_slice.context_start,
                candidate_end=generated_slice.context_end,
                candidate_duration=generated_slice.duration,
                analyzer=analyze_candidate_clips,
            )
            if not results:
                scan_log.info(f"MiMo found no postable chat clips in {slice_path}")
                continue

            for clip_index, result in enumerate(results, start=1):
                output_path = clip_output_path(slice_path, result, clip_index)
                segment = build_segment_record(
                    original_video_path,
                    generated_slice,
                    result,
                    upload_status="not_queued",
                    candidate_path_override=output_path,
                )
                if result.judge_status == "judge_failed":
                    judge_failed_count += 1
                    segments.append(segment)
                    continue
                if result.judge_status == "drop" or not result.retain_recommendation:
                    segment["judge_status"] = "drop"
                    segments.append(segment)
                    continue

                burn_result = subtitle_stage(
                    slice_path,
                    result,
                    burner=lambda video, analysis: burn_subtitles_from_analysis(
                        video,
                        analysis,
                        output_path=output_path,
                    ),
                )
                if not burn_result["ok"]:
                    reason = burn_result["error"]
                    judge_failed_count += 1
                    segment["judge_status"] = "judge_failed"
                    segment["judge_error"] = reason
                    segment["quality_reason"] = reason
                    segments.append(segment)
                    continue

                metadata_result = metadata_stage(
                    output_path,
                    result,
                    room_id=room_id,
                    writer=write_slice_upload_metadata,
                )
                if not metadata_result["ok"]:
                    reason = metadata_result["error"]
                    judge_failed_count += 1
                    segment["judge_status"] = "judge_failed"
                    segment["judge_error"] = reason
                    segment["quality_reason"] = reason
                    delete_slice_upload_metadata(output_path)
                    segments.append(segment)
                    continue

                queue_result = enqueue_stage(
                    output_path,
                    insert=insert_upload_queue,
                    lookup=get_upload_item,
                    skip=os.getenv("BILIVE_SKIP_UPLOAD_QUEUE") == "1",
                )
                if not queue_result["ok"]:
                    reason = queue_result["error"]
                    judge_failed_count += 1
                    segment["judge_status"] = "judge_failed"
                    segment["judge_error"] = reason
                    segment["quality_reason"] = reason
                    delete_slice_upload_metadata(output_path)
                    segments.append(segment)
                    continue
                segment["upload_status"] = queue_result["status"]
                output_slices.append(output_path)
                segments.append(segment)
```

Keep the existing cleanup and model unload logic.

- [ ] **Step 7: Update `build_segment_record()` signature**

Change:

```python
def build_segment_record(source_path, generated_slice, analysis, upload_status="not_queued"):
```

to:

```python
def build_segment_record(
    source_path,
    generated_slice,
    analysis,
    upload_status="not_queued",
    candidate_path_override=None,
):
```

Then set:

```python
    slice_path = str(candidate_path_override or generated_slice.path)
```

- [ ] **Step 8: Run multi-clip test**

Run:

```powershell
python -m pytest tests/test_slice_only_multi_clip.py -q
```

Expected: PASS.

- [ ] **Step 9: Run focused pipeline tests**

Run:

```powershell
python -m pytest tests/test_slice_only_model_unload.py tests/test_watcher_once.py tests/test_task_history.py tests/test_source_workbench.py -q
```

Expected: PASS.

- [ ] **Step 10: Commit**

```powershell
git add src/burn/pipeline_stages.py src/burn/slice_only.py tests/test_slice_only_multi_clip.py
git commit -m "feat: process multiple chat clips per candidate"
```

### Task 8: Broaden Candidate Defaults

**Files:**
- Modify: `bilive-server.toml`
- Modify: `src/dashboard/app.py`
- Test: `tests/test_dashboard_api.py`

- [ ] **Step 1: Write failing validation test**

Append to `tests/test_dashboard_api.py`:

```python
def test_slice_options_accept_chat_context_120(client):
    response = client.post(
        "/api/slice/start",
        json={"slice_options": {"burst_context": 120}},
        headers={"origin": "http://testserver"},
    )
    assert response.status_code != 400
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
python -m pytest tests/test_dashboard_api.py::test_slice_options_accept_chat_context_120 -q
```

Expected: FAIL because dashboard validation only accepts `30/45/60/90`.

- [ ] **Step 3: Update config default**

In `bilive-server.toml`, change:

```toml
burst_context = 60
```

to:

```toml
burst_context = 120
```

- [ ] **Step 4: Update dashboard validation**

In `src/dashboard/app.py`, change:

```python
context = _int_option("burst_context", 30, 90)
if context not in (30, 45, 60, 90):
    raise HTTPException(status_code=400, detail="burst_context must be 30/45/60/90")
```

to:

```python
context = _int_option("burst_context", 30, 120)
if context not in (30, 45, 60, 90, 120):
    raise HTTPException(status_code=400, detail="burst_context must be 30/45/60/90/120")
```

- [ ] **Step 5: Run dashboard test**

Run:

```powershell
python -m pytest tests/test_dashboard_api.py::test_slice_options_accept_chat_context_120 -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add bilive-server.toml src/dashboard/app.py tests/test_dashboard_api.py
git commit -m "feat: broaden chat candidate context"
```

### Task 9: Sync Documentation

**Files:**
- Modify: `docs/architecture.md`
- Modify: `docs/chat-slice-quality.md`

- [ ] **Step 1: Update architecture model boundary**

In `docs/architecture.md`, replace the MiMo bullet list item about single rough trim:

```markdown
4. 强制 JSON 输出 `keep/drop`、标题、描述、标签、质量分和 `trim_start/trim_end`。
```

with:

```markdown
4. 强制 JSON 输出 `clips` 数组；每个元素包含保留决策、聊天片段类型、标题、简介、标签、质量分、完整度、置信度和 `trim_start/trim_end`。
```

Also update the data flow line:

```text
-> 候选 mp4 -> MiMo 视频判断
```

to:

```text
-> 大范围候选 mp4 -> MiMo 聊天切片判断，可返回 0..N 个片段
```

- [ ] **Step 2: Add implementation note to quality doc**

Append to `docs/chat-slice-quality.md`:

```markdown
## 实施基线

生产实现应保持 Pi/Windows 边界：Pi 只负责录制、仪表盘和触发 Windows；聊天切片判断、ASR、字幕、元数据和上传入队仍只在 Windows 执行。
```

- [ ] **Step 3: Review doc diff**

Run:

```powershell
git diff -- docs/architecture.md docs/chat-slice-quality.md
```

Expected: diff only updates MiMo/chat-slice docs.

- [ ] **Step 4: Commit**

```powershell
git add docs/architecture.md docs/chat-slice-quality.md
git commit -m "docs: sync chat slice pipeline architecture"
```

### Task 10: Final Verification

**Files:**
- No source edits.

- [ ] **Step 1: Run focused test suite**

Run:

```powershell
python -m pytest tests/test_mimo_video_analyzer.py tests/test_candidate_analyzer.py tests/test_subtitle_burn.py tests/test_slice_only_multi_clip.py tests/test_watcher_once.py tests/test_source_workbench.py tests/test_dashboard_api.py -q
```

Expected: PASS.

- [ ] **Step 2: Run compile check**

Run:

```powershell
python -m compileall src tests
```

Expected: no syntax errors.

- [ ] **Step 3: Check worktree**

Run:

```powershell
git status --short
```

Expected: only pre-existing unrelated `src/upload/bilitool` submodule state may remain. No unstaged changes from this implementation.

- [ ] **Step 4: Commit or report final state**

If all previous tasks committed cleanly, no new commit is needed here. Report the final commit range and verification output.

## Self-Review

- Spec coverage: broad candidate windows, MiMo as editor/main judge, multi-clip output, Bilibili-style metadata, no hard quantity cap, quality-first strict mode, and Pi/Windows boundaries are all covered.
- Placeholder scan: no red-flag placeholder text remains.
- Type consistency: `AnalysisResult` remains the per-final-clip object; `analyze_candidate_clips()` returns `list[AnalysisResult]`; legacy `analyze_candidate()` remains single-result for existing callers.


