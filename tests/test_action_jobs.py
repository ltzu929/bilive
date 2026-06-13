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
