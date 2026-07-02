import shutil
from pathlib import Path

from src.autoslice.analysis_result import AnalysisResult, TrimSuggestion


class _TempDir:
    def __init__(self, path):
        self.path = Path(path)

    def __enter__(self):
        self.path.mkdir(parents=True, exist_ok=True)
        return str(self.path)

    def __exit__(self, exc_type, exc, tb):
        shutil.rmtree(self.path, ignore_errors=True)


def test_encode_video_for_mimo_retries_and_cleans_temp_dir(tmp_path):
    from src.autoslice.mllm_sdk.mimo_video import encode_video_for_mimo

    source = tmp_path / "clip.mp4"
    source.write_bytes(b"video")
    temp_dir = tmp_path / "mimo-temp"
    commands = []

    def fake_run(command, check, capture_output, text, encoding, timeout):
        commands.append(command)
        output = Path(command[-1])
        output.write_bytes(b"x" * (15 if len(commands) == 1 else 3))

    payload = encode_video_for_mimo(
        source,
        max_base64_bytes=8,
        run=fake_run,
        temporary_directory=lambda prefix: _TempDir(temp_dir),
    )

    assert payload.base64_bytes == 4
    assert payload.url == "data:video/mp4;base64,eHh4"
    assert len(commands) == 2
    assert "900k" in commands[0]
    assert "450k" in commands[1]
    assert not temp_dir.exists()


def test_server_config_exports_mimo_settings():
    from src.config import server_config

    assert server_config.MIMO_MODEL == "mimo-v2.5"
    assert server_config.MIMO_BASE_URL == "https://api.xiaomimimo.com/v1"
    assert server_config.MIMO_FPS == 1.0
    assert server_config.MIMO_MEDIA_RESOLUTION == "default"
    assert server_config.MIMO_TIMEOUT == 180.0
    assert server_config.MIMO_MAX_BASE64_BYTES == 48_000_000


def test_encode_video_for_mimo_raises_when_retry_exceeds_limit(tmp_path):
    from src.autoslice.mllm_sdk.mimo_video import (
        MimoVideoTooLarge,
        encode_video_for_mimo,
    )

    source = tmp_path / "clip.mp4"
    source.write_bytes(b"video")

    def fake_run(command, check, capture_output, text, encoding, timeout):
        Path(command[-1]).write_bytes(b"x" * 12)

    try:
        encode_video_for_mimo(
            source,
            max_base64_bytes=8,
            run=fake_run,
            temporary_directory=lambda prefix: _TempDir(tmp_path / "mimo-temp"),
        )
    except MimoVideoTooLarge as exc:
        assert "base64 payload exceeds" in str(exc)
    else:
        raise AssertionError("expected MimoVideoTooLarge")
    assert not (tmp_path / "mimo-temp").exists()


def test_judge_candidate_with_mimo_requests_structured_video_json(monkeypatch):
    from src.autoslice.mllm_sdk import mimo_video

    calls = {}

    class Completions:
        @staticmethod
        def create(**kwargs):
            calls.update(kwargs)
            message = type(
                "Message",
                (),
                {
                    "content": (
                        '{"decision":"keep","reason":"strong moment",'
                        '"title":"Clip title","description":"Clip desc",'
                        '"tags":["live","highlight"],"quality_score":0.82,'
                        '"trim_start":2.0,"trim_end":8.0}'
                    )
                },
            )()
            usage = type(
                "Usage",
                (),
                {
                    "model_dump": lambda self: {
                        "prompt_tokens": 100,
                        "completion_tokens": 40,
                        "total_tokens": 140,
                    }
                },
            )()
            return type(
                "Completion",
                (),
                {
                    "choices": [type("Choice", (), {"message": message})()],
                    "usage": usage,
                    "model": "mimo-v2.5",
                },
            )()

    client = type(
        "Client",
        (),
        {"chat": type("Chat", (), {"completions": Completions()})()},
    )()
    monkeypatch.setenv("MIMO_API_KEY", "secret-key")

    def fake_client_factory(**kwargs):
        calls["client"] = kwargs
        return client

    result = mimo_video.judge_candidate_with_mimo(
        video_path="clip.mp4",
        artist="artist",
        danmaku_text="danmaku spike",
        candidate_duration=12.0,
        client_factory=fake_client_factory,
        encoder=lambda path, max_base64_bytes: type(
            "Encoded",
            (),
            {
                "url": "data:video/mp4;base64,AAAA",
                "base64_bytes": 4,
            },
        )(),
    )

    assert calls["client"]["api_key"] == "secret-key"
    assert calls["client"]["base_url"] == "https://api.xiaomimimo.com/v1"
    assert calls["model"] == "mimo-v2.5"
    assert calls["response_format"] == {"type": "json_object"}
    assert calls["extra_body"] == {"thinking": {"type": "disabled"}}
    assert calls["timeout"] == 180
    content = calls["messages"][1]["content"]
    assert content[0]["type"] == "video_url"
    assert content[0]["video_url"]["url"] == "data:video/mp4;base64,AAAA"
    assert content[0]["fps"] == 1.0
    assert content[0]["media_resolution"] == "default"
    assert "artist" in content[1]["text"]
    assert "danmaku spike" in content[1]["text"]
    assert result.judge_status == "keep"
    assert result.retain_recommendation is True
    assert result.suggested_trim == TrimSuggestion(
        trim_start=2.0,
        trim_end=8.0,
        reason="strong moment",
    )
    assert result.model_name == "mimo-v2.5"
    assert result.token_usage["total_tokens"] == 140


def test_judge_candidate_with_mimo_fails_closed_on_invalid_json(monkeypatch):
    from src.autoslice.mllm_sdk import mimo_video

    class Completions:
        @staticmethod
        def create(**kwargs):
            message = type("Message", (), {"content": "not json"})()
            return type(
                "Completion",
                (),
                {"choices": [type("Choice", (), {"message": message})()]},
            )()

    client = type(
        "Client",
        (),
        {"chat": type("Chat", (), {"completions": Completions()})()},
    )()
    monkeypatch.setenv("MIMO_API_KEY", "secret-key")

    result = mimo_video.judge_candidate_with_mimo(
        video_path="clip.mp4",
        artist="artist",
        danmaku_text="danmaku",
        candidate_duration=12.0,
        client_factory=lambda **kwargs: client,
        encoder=lambda path, max_base64_bytes: type(
            "Encoded",
            (),
            {"url": "data:video/mp4;base64,AAAA", "base64_bytes": 4},
        )(),
    )

    assert result.judge_status == "judge_failed"
    assert result.retain_recommendation is False
    assert "JSON" in result.judge_error
    assert mimo_video.mimo_status()["status"] == "error"


def test_judge_candidate_with_mimo_sets_error_status_without_api_key(monkeypatch):
    from src.autoslice.mllm_sdk import mimo_video

    monkeypatch.delenv("MIMO_API_KEY", raising=False)

    result = mimo_video.judge_candidate_with_mimo(
        video_path="clip.mp4",
        artist="artist",
        danmaku_text="danmaku",
        candidate_duration=12.0,
    )

    status = mimo_video.mimo_status()
    assert result.judge_status == "judge_failed"
    assert status["status"] == "error"
    assert "MIMO_API_KEY" in status["last_error"]


def test_judge_candidate_with_mimo_fails_closed_on_timeout_or_rate_limit(
    monkeypatch,
):
    from src.autoslice.mllm_sdk import mimo_video

    monkeypatch.setenv("MIMO_API_KEY", "secret-key")

    for error in (TimeoutError("request timed out"), RuntimeError("429 rate limited")):
        class Completions:
            @staticmethod
            def create(**kwargs):
                raise error

        client = type(
            "Client",
            (),
            {"chat": type("Chat", (), {"completions": Completions()})()},
        )()
        result = mimo_video.judge_candidate_with_mimo(
            video_path="clip.mp4",
            artist="artist",
            danmaku_text="danmaku",
            candidate_duration=12.0,
            client_factory=lambda **kwargs: client,
            encoder=lambda path, max_base64_bytes: type(
                "Encoded",
                (),
                {"url": "data:video/mp4;base64,AAAA", "base64_bytes": 4},
            )(),
        )

        assert result.judge_status == "judge_failed"
        assert str(error) in result.judge_error
        status = mimo_video.mimo_status()
        assert status["status"] == "error"
        assert str(error) in status["last_error"]


def test_mimo_keep_without_title_fails_closed():
    from src.autoslice.mllm_sdk.mimo_video import _analysis_from_mimo_dict

    result = _analysis_from_mimo_dict(
        {
            "decision": "keep",
            "reason": "good moment",
            "description": "desc",
            "tags": ["live"],
            "quality_score": 0.8,
            "trim_start": 1,
            "trim_end": 10,
        },
        artist="artist",
        model="mimo-v2.5",
    )

    assert result.judge_status == "judge_failed"
    assert "title" in result.judge_error


def test_mimo_payload_missing_required_fields_or_types_fails_closed():
    from src.autoslice.mllm_sdk.mimo_video import _analysis_from_mimo_dict

    base = {
        "decision": "keep",
        "reason": "good moment",
        "title": "Clip",
        "description": "Description",
        "tags": ["live"],
        "quality_score": 0.8,
        "trim_start": 1,
        "trim_end": 10,
    }
    invalid_payloads = [
        {key: value for key, value in base.items() if key != "description"},
        {**base, "reason": ""},
        {**base, "tags": "live"},
        {**base, "quality_score": "high"},
        {**base, "quality_score": 1.5},
    ]

    for payload in invalid_payloads:
        result = _analysis_from_mimo_dict(
            payload,
            artist="artist",
            model="mimo-v2.5",
        )
        assert result.judge_status == "judge_failed"
        assert result.judge_error


def test_judge_candidate_with_mimo_fails_closed_on_empty_choices(monkeypatch):
    from src.autoslice.mllm_sdk import mimo_video

    class Completions:
        @staticmethod
        def create(**kwargs):
            return type("Completion", (), {"choices": []})()

    client = type(
        "Client",
        (),
        {"chat": type("Chat", (), {"completions": Completions()})()},
    )()
    monkeypatch.setenv("MIMO_API_KEY", "secret-key")

    result = mimo_video.judge_candidate_with_mimo(
        video_path="clip.mp4",
        artist="artist",
        danmaku_text="danmaku",
        candidate_duration=12.0,
        client_factory=lambda **kwargs: client,
        encoder=lambda path, max_base64_bytes: type(
            "Encoded",
            (),
            {"url": "data:video/mp4;base64,AAAA", "base64_bytes": 4},
        )(),
    )

    assert result.judge_status == "judge_failed"
    assert "response" in result.judge_error.lower()
    assert mimo_video.mimo_status()["status"] == "error"


def test_mimo_payload_without_explicit_decision_fails_closed():
    from src.autoslice.mllm_sdk.mimo_video import _analysis_from_mimo_dict

    result = _analysis_from_mimo_dict(
        {
            "reason": "ambiguous response",
            "title": "",
            "description": "",
            "tags": [],
            "quality_score": 0.5,
        },
        artist="artist",
        model="mimo-v2.5",
    )

    assert result.judge_status == "judge_failed"
    assert "decision" in result.judge_error


def test_mimo_drop_payload_accepts_null_trim():
    from src.autoslice.mllm_sdk.mimo_video import _analysis_from_mimo_dict

    result = _analysis_from_mimo_dict(
        {
            "decision": "drop",
            "reason": "no standalone value",
            "title": "",
            "description": "",
            "tags": [],
            "quality_score": 0.2,
            "trim_start": None,
            "trim_end": None,
        },
        artist="artist",
        model="mimo-v2.5",
    )

    assert result.judge_status == "drop"
    assert result.retain_recommendation is False
    assert result.suggested_trim is None


def test_analysis_result_round_trips_mimo_audit_fields():
    original = AnalysisResult(
        title="Clip",
        description="Description",
        tags=["live"],
        model_name="mimo-v2.5",
        token_usage={"total_tokens": 140},
        suggested_trim=TrimSuggestion(2.0, 8.0, "best moment"),
        candidate_start=100.0,
        candidate_end=120.0,
        source_start=102.0,
        source_end=108.0,
    )

    restored = AnalysisResult.from_dict(original.to_dict())

    assert restored.model_name == "mimo-v2.5"
    assert restored.token_usage == {"total_tokens": 140}
    assert restored.suggested_trim == TrimSuggestion(2.0, 8.0, "best moment")
    assert restored.candidate_start == 100.0
    assert restored.candidate_end == 120.0
    assert restored.source_start == 102.0
    assert restored.source_end == 108.0


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


def test_mimo_empty_clip_response_preserves_reason():
    from src.autoslice.mllm_sdk.mimo_video import _analysis_list_from_mimo_dict

    results = _analysis_list_from_mimo_dict(
        {
            "clips": [],
            "empty_reason": "missing standalone context",
            "observed_issue": "mostly greetings and gift thanks",
        },
        artist="主播",
        model="mimo-v2.5",
    )

    assert results == []
    assert results.empty_reason == "missing standalone context"
    assert results.raw_response_summary == (
        "empty_reason=missing standalone context; "
        "observed_issue=mostly greetings and gift thanks"
    )


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
    assert "empty_reason" in prompt
    assert "B 站口语标题" in prompt


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


def test_judge_candidate_clips_with_mimo_preserves_empty_reason(monkeypatch):
    from src.autoslice.mllm_sdk import mimo_video
    from src.autoslice.mllm_sdk.mimo_video import EncodedMimoVideo

    class Message:
        content = (
            '{"clips":[],"empty_reason":"missing standalone context",'
            '"observed_issue":"mostly greetings"}'
        )

    class Choice:
        message = Message()

    class Completion:
        choices = [Choice()]
        usage = {"total_tokens": 60}
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

    assert results == []
    assert results.empty_reason == "missing standalone context"
    assert results.raw_response_summary == (
        "empty_reason=missing standalone context; observed_issue=mostly greetings"
    )
