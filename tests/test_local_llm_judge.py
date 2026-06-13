import json
from contextlib import contextmanager

from src.autoslice.mllm_sdk import judge


def test_local_subprocess_judge_sends_json_and_parses_result(monkeypatch):
    calls = []

    class Completed:
        returncode = 0
        stdout = json.dumps(
            {
                "retain": False,
                "retain_reason": "flat content",
                "title": "Better title",
                "description": "Short summary",
                "content_type": "chat",
                "tags": ["live"],
            }
        )
        stderr = ""

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return Completed()

    monkeypatch.setattr(judge.subprocess, "run", fake_run)

    result = judge.judge_and_title_local_subprocess(
        ["python", "runner.py"],
        artist="artist",
        danmaku_text="danmaku",
        transcript="transcript",
        timeout=9,
    )

    payload = json.loads(calls[0][1]["input"])
    assert calls[0][0] == ["python", "runner.py"]
    assert calls[0][1]["timeout"] == 9
    assert payload["task"] == "judge_title"
    assert payload["artist"] == "artist"
    assert payload["danmaku_text"] == "danmaku"
    assert payload["transcript"] == "transcript"
    assert "prompt" in payload
    assert result.retain is False
    assert result.retain_reason == "flat content"
    assert result.title == "Better title"
    assert result.description == "Short summary"
    assert result.content_type == "chat"
    assert result.tags == ["live"]


def test_local_subprocess_judge_falls_back_when_command_missing():
    result = judge.judge_and_title_local_subprocess(
        [],
        artist="artist",
        danmaku_text="",
        transcript="",
    )

    assert result.retain is False
    assert result.judge_status == "judge_failed"
    assert "not configured" in result.judge_error
    assert result.title
    assert "not configured" in result.retain_reason


def test_local_subprocess_bad_json_is_judge_failed(monkeypatch):
    class Completed:
        returncode = 0
        stdout = "not json"
        stderr = ""

    monkeypatch.setattr(judge.subprocess, "run", lambda *args, **kwargs: Completed())

    result = judge.judge_and_title_local_subprocess(
        ["python", "runner.py"],
        artist="artist",
        danmaku_text="danmaku",
        transcript="transcript",
    )

    assert result.retain is False
    assert result.judge_status == "judge_failed"
    assert "JSON parse failed" in result.judge_error


def test_managed_provider_uses_runtime_endpoint(monkeypatch):
    calls = {}
    http_client = object()

    @contextmanager
    def fake_request():
        calls["request"] = True
        yield "http://127.0.0.1:2236/v1"

    class Message:
        content = json.dumps(
            {
                "retain": True,
                "retain_reason": "good",
                "title": "title",
                "description": "description",
                "content_type": "chat",
                "tags": ["live"],
            }
        )

    class Completions:
        def create(self, **kwargs):
            calls["completion"] = kwargs
            return type(
                "Completion",
                (),
                {"choices": [type("Choice", (), {"message": Message()})()]},
            )()

    class Client:
        def __init__(self):
            self.chat = type("Chat", (), {"completions": Completions()})()

    monkeypatch.setattr(
        judge,
        "_load_judge_provider_config",
        lambda: ("managed-llama-server", [], 120.0),
    )
    monkeypatch.setattr(judge, "managed_llm_request", fake_request)
    monkeypatch.setattr(
        judge,
        "create_local_openai_client",
        lambda **kwargs: calls.update(
            client={**kwargs, "http_client": http_client}
        )
        or Client(),
    )

    result = judge.judge_and_title(
        artist="artist",
        danmaku_text="danmaku",
        transcript="transcript",
        model_name="qwen",
    )

    assert calls["request"] is True
    assert calls["client"]["base_url"] == "http://127.0.0.1:2236/v1"
    assert calls["client"]["http_client"] is http_client
    assert calls["completion"]["model"] == "qwen"
    assert calls["completion"]["response_format"] == {"type": "json_object"}
    assert result.judge_status == "keep"
