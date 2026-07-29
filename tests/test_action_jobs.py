import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from src.server import action_jobs


def test_enqueue_and_read_action_job(tmp_path):
    videos = tmp_path / "Videos"
    videos.mkdir()

    created = action_jobs.enqueue_action_job(
        videos,
        action="retry_judge",
        segment_id="segment-1",
    )

    assert created["status"] == "accepted"
    assert created["job"]["action"] == "retry_judge"
    assert created["job"]["execution_target"] == "windows"
    stored = action_jobs.read_action_job(videos, created["job"]["job_id"])
    assert stored["status"] == "pending"
    assert stored["segment_id"] == "segment-1"


def test_duplicate_pending_action_job_is_reused(tmp_path):
    videos = tmp_path / "Videos"
    videos.mkdir()

    first = action_jobs.enqueue_action_job(
        videos,
        action="render_segment",
        segment_id="segment-1",
    )
    second = action_jobs.enqueue_action_job(
        videos,
        action="render_segment",
        segment_id="segment-1",
    )

    assert second["status"] == "already_pending"
    assert second["job"]["job_id"] == first["job"]["job_id"]


def test_segment_actions_are_mutually_exclusive_and_payload_is_immutable(tmp_path):
    videos = tmp_path / "Videos"
    videos.mkdir()
    action_jobs.enqueue_action_job(
        videos,
        action="finalize_segment",
        segment_id="segment-1",
        payload={"title": "first", "_expected_revision": 1},
    )

    with pytest.raises(action_jobs.SegmentActionConflict):
        action_jobs.enqueue_action_job(
            videos,
            action="finalize_segment",
            segment_id="segment-1",
            payload={"title": "changed", "_expected_revision": 2},
        )
    with pytest.raises(action_jobs.SegmentActionConflict):
        action_jobs.enqueue_action_job(
            videos,
            action="render_segment",
            segment_id="segment-1",
        )


def test_two_claimers_cannot_claim_same_action_job(tmp_path):
    videos = tmp_path / "Videos"
    videos.mkdir()
    action_jobs.enqueue_action_job(
        videos,
        action="retry_judge",
        segment_id="segment-1",
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        claims = list(executor.map(lambda _: action_jobs.claim_next_action_job(videos), range(2)))

    assert sum(claim is not None for claim in claims) == 1


def test_recover_stale_processing_action_job(tmp_path):
    videos = tmp_path / "Videos"
    videos.mkdir()
    created = action_jobs.enqueue_action_job(
        videos,
        action="retry_judge",
        segment_id="segment-1",
    )
    claimed = action_jobs.claim_next_action_job(videos)
    assert claimed is not None

    recovered = action_jobs.recover_action_jobs(
        videos,
        pid_checker=lambda _pid: False,
    )

    assert recovered == 1
    job = action_jobs.read_action_job(videos, created["job"]["job_id"])
    assert job["status"] == "pending"
    assert job["recovered_from"] == "processing"


def test_read_action_job_rejects_path_traversal(tmp_path):
    videos = tmp_path / "Videos"
    videos.mkdir()

    with pytest.raises(ValueError):
        action_jobs.read_action_job(videos, "../outside")


def test_process_action_jobs_persists_success(tmp_path):
    videos = tmp_path / "Videos"
    videos.mkdir()
    created = action_jobs.enqueue_action_job(
        videos,
        action="render_segment",
        segment_id="segment-1",
    )

    processed = action_jobs.process_action_jobs(
        videos,
        executor=lambda job: {"segment_id": job["segment_id"], "candidate_rel_path": "room/clip.mp4"},
    )

    assert processed == 1
    job = action_jobs.read_action_job(videos, created["job"]["job_id"])
    assert job["status"] == "done"
    assert job["result"]["candidate_rel_path"] == "room/clip.mp4"


def test_process_action_jobs_synchronizes_segment_terminal_state(
    tmp_path,
    monkeypatch,
):
    videos = tmp_path / "Videos"
    videos.mkdir()
    action_jobs.enqueue_action_job(
        videos,
        action="render_segment",
        segment_id="segment-1",
    )
    states = []
    monkeypatch.setattr(
        action_jobs,
        "_record_segment_job_state",
        lambda _root, _job, status, **kwargs: states.append(
            (status, kwargs.get("failure"))
        ),
    )

    action_jobs.process_action_jobs(
        videos,
        executor=lambda _job: {"segment_id": "segment-1"},
    )

    assert states == [("processing", None), ("done", None)]


def test_process_action_jobs_persists_failure(tmp_path):
    videos = tmp_path / "Videos"
    videos.mkdir()
    created = action_jobs.enqueue_action_job(
        videos,
        action="retry_judge",
        segment_id="segment-1",
    )

    def fail(_job):
        raise RuntimeError("LLM unavailable")

    processed = action_jobs.process_action_jobs(videos, executor=fail)

    assert processed == 0
    job = action_jobs.read_action_job(videos, created["job"]["job_id"])
    assert job["status"] == "failed"
    assert job["error"] == "LLM unavailable"
    assert job["error_type"] == "RuntimeError"
    assert job["failure"] == {
        "stage": "retry_judge",
        "code": "retry_judge_failed",
        "summary": "LLM unavailable",
        "technical_details": "RuntimeError: LLM unavailable",
        "recovery_action": "检查技术详情后重试该任务",
    }


def test_finalize_action_is_supported_and_preserves_structured_failure(tmp_path):
    videos = tmp_path / "Videos"
    videos.mkdir()
    created = action_jobs.enqueue_action_job(
        videos,
        action="finalize_segment",
        segment_id="segment-1",
    )
    expected = {
        "stage": "subtitle_burn",
        "code": "subtitle_burn_failed",
        "summary": "字幕烧录失败",
        "technical_details": "ffmpeg exited 1",
        "recovery_action": "修正字幕样式后重试",
    }

    class StructuredError(RuntimeError):
        failure = expected

    def fail(_job):
        raise StructuredError(expected["summary"])

    assert action_jobs.process_action_jobs(videos, executor=fail) == 0

    job = action_jobs.read_action_job(videos, created["job"]["job_id"])
    assert job["status"] == "failed"
    assert job["failure"] == expected


def test_finalize_action_dispatches_to_source_workbench(tmp_path, monkeypatch):
    from src.dashboard import source_workbench

    videos = tmp_path / "Videos"
    videos.mkdir()
    calls = []
    monkeypatch.setattr(action_jobs.os, "name", "nt")
    monkeypatch.setattr(
        source_workbench,
        "finalize_segment",
        lambda root, segment_id, payload=None: calls.append(
            (root, segment_id, payload)
        )
        or {"segment_id": segment_id, "upload_status": "queued"},
    )

    result = action_jobs._execute_action_job(
        videos,
        {
            "job_id": "a" * 32,
            "action": "finalize_segment",
            "segment_id": "segment-1",
        },
    )

    assert result["upload_status"] == "queued"
    assert calls == [
        (videos, "segment-1", {"_job_id": "a" * 32})
    ]


@pytest.mark.parametrize(
    "action",
    ["finalize_segment", "retry_judge", "render_segment", "reburn_subtitles"],
)
def test_all_heavy_actions_reject_non_windows_workers(tmp_path, monkeypatch, action):
    videos = tmp_path / "Videos"
    videos.mkdir()
    monkeypatch.setattr(action_jobs.os, "name", "posix")

    with pytest.raises(action_jobs.ActionJobExecutionError) as error:
        action_jobs._execute_action_job(
            videos,
            {"action": action, "segment_id": "segment-1"},
        )

    assert error.value.failure["code"] == "windows_worker_required"


def test_claim_uses_creation_order_not_random_job_id(tmp_path):
    videos = tmp_path / "Videos"
    jobs = videos / ".bilive-jobs"
    jobs.mkdir(parents=True)
    earlier = {
        "job_id": "f" * 32,
        "action": "retry_judge",
        "segment_id": "earlier",
        "status": "pending",
        "created_at": "2026-01-01T00:00:00",
        "created_ns": 1,
    }
    later = {
        "job_id": "a" * 32,
        "action": "retry_judge",
        "segment_id": "later",
        "status": "pending",
        "created_at": "2026-01-01T00:00:01",
        "created_ns": 2,
    }
    (jobs / f"{earlier['job_id']}.pending.json").write_text(
        json.dumps(earlier),
        encoding="utf-8",
    )
    (jobs / f"{later['job_id']}.pending.json").write_text(
        json.dumps(later),
        encoding="utf-8",
    )

    claimed = action_jobs.claim_next_action_job(videos)

    assert claimed is not None
    assert claimed[1]["segment_id"] == "earlier"


def test_invalid_pending_job_is_not_counted_and_is_quarantined(tmp_path):
    videos = tmp_path / "Videos"
    jobs = videos / ".bilive-jobs"
    jobs.mkdir(parents=True)
    invalid = jobs / f"{'a' * 32}.pending.json"
    invalid.write_text("{not-json", encoding="utf-8")

    assert action_jobs.count_pending_action_jobs(videos) == 0
    assert action_jobs.claim_next_action_job(videos) is None
    assert not invalid.exists()
    assert (jobs / f"{'a' * 32}.invalid.json").exists()


def test_structurally_invalid_pending_job_is_also_quarantined(tmp_path):
    videos = tmp_path / "Videos"
    jobs = videos / ".bilive-jobs"
    jobs.mkdir(parents=True)
    invalid = jobs / f"{'c' * 32}.pending.json"
    invalid.write_text("{}", encoding="utf-8")

    assert action_jobs.count_pending_action_jobs(videos) == 0
    assert action_jobs.claim_next_action_job(videos) is None
    assert (jobs / f"{'c' * 32}.invalid.json").exists()


def test_job_files_are_valid_json_after_concurrent_enqueue(tmp_path):
    videos = tmp_path / "Videos"
    videos.mkdir()

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(
            executor.map(
                lambda index: action_jobs.enqueue_action_job(
                    videos,
                    action="retry_judge",
                    segment_id=f"segment-{index}",
                ),
                range(20),
            )
        )

    for path in (videos / ".bilive-jobs").glob("*.json"):
        assert json.loads(path.read_text(encoding="utf-8"))["job_id"]
