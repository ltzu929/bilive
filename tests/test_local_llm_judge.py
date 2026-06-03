import json

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
