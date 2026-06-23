import os
from pathlib import Path

import pytest

from src.autoslice.mllm_sdk.mimo_video import judge_candidate_with_mimo
from src.burn.subtitle_burn import probe_video_duration


@pytest.mark.integration
def test_real_mimo_video_judgement_smoke():
    if not os.environ.get("MIMO_API_KEY"):
        pytest.skip("MIMO_API_KEY is not set")

    video_value = os.environ.get("BILIVE_MIMO_SMOKE_VIDEO")
    if not video_value:
        pytest.skip("BILIVE_MIMO_SMOKE_VIDEO is not set")

    video_path = Path(video_value).expanduser().resolve()
    if not video_path.is_file():
        pytest.fail(f"smoke video does not exist: {video_path}")

    duration = probe_video_duration(video_path)
    if duration is None or duration <= 0:
        pytest.fail(f"cannot determine smoke video duration: {video_path}")

    result = judge_candidate_with_mimo(
        video_path=str(video_path),
        artist="MiMo API smoke test",
        danmaku_text="Optional real API connectivity test. No upload is allowed.",
        candidate_duration=duration,
    )

    assert result.judge_status in {"keep", "drop"}, result.judge_error
    assert result.model_name

