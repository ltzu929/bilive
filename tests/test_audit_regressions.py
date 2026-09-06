"""Behavioral regressions from the September audit; no production I/O."""
import asyncio
import io
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

from src.dashboard import source_workbench as wb
from src.db import conn
from src.server import action_jobs
from tests.test_source_workbench import _create_processed_source


@pytest.mark.parametrize("status", ["queued", "uploading", "uploaded", "publishing", "published", "failed"])
@pytest.mark.parametrize("action", ["reburn", "range", "finalize"])
def test_activated_final_is_immutable(tmp_path, monkeypatch, status, action):
    root = tmp_path / "Videos"
    source = _create_processed_source(root)
    db = tmp_path / "queue.db"
    conn.migrate_upload_queue(db)
    monkeypatch.setattr(conn, "DATA_BASE_FILE", str(db))
    final = source.with_name("10s_" + source.name)
    conn.insert_upload_queue(str(final), db)
    with conn.connect(db) as connection:
        connection.execute("update upload_queue set status = ?", (status,))
    before = final.read_bytes()
    history = source.with_suffix(".mp4.task.json").read_bytes()
    with pytest.raises(wb.SegmentStateConflict):
        if action == "reburn":
            wb.reburn_segment_subtitles(root, "seg_keep")
        elif action == "range":
            wb.update_segment_range(root, "seg_keep", {"start_seconds": 12, "end_seconds": 22})
        else:
            wb.prepare_segment_finalize(root, "seg_keep", {})
    assert final.read_bytes() == before
    assert source.with_suffix(".mp4.task.json").read_bytes() == history


def test_staged_withdrawal_races_activation_atomically(tmp_path):
    db = tmp_path / "queue.db"
    conn.migrate_upload_queue(db)
    conn.stage_upload_queue("final.mp4", db)
    gate = Barrier(2)
    def activate():
        gate.wait()
        return conn.activate_staged_upload("final.mp4", db)
    def withdraw():
        gate.wait()
        return conn.withdraw_staged_upload("final.mp4", db)
    with ThreadPoolExecutor(2) as pool:
        active, removed = pool.submit(activate), pool.submit(withdraw)
        result, withdrawn = active.result(), removed.result()
    assert (withdrawn and result is None) or (not withdrawn and result["status"] == "queued")


def test_processing_source_is_not_requeued(tmp_path, monkeypatch):
    from src.dashboard import slice_control
    root = tmp_path / "Videos"
    source = _create_processed_source(root)
    source.with_suffix(".mp4.done").unlink()
    source.with_suffix(".mp4.processing").write_text("{}")
    monkeypatch.setattr(slice_control, "MIN_SOURCE_RECORDING_SIZE_MB", 0)
    result = slice_control.start_slice_scan(root, task_id=wb._task_id_for_source(source, root))
    assert result["status"] == "processing"
    assert result["queued"] == 0
    assert not source.with_suffix(".mp4.pending").exists()


def test_two_source_submissions_write_one_marker(tmp_path, monkeypatch):
    from src.dashboard import slice_control
    root = tmp_path / "Videos"
    source = _create_processed_source(root)
    source.with_suffix(".mp4.done").unlink()
    monkeypatch.setattr(slice_control, "MIN_SOURCE_RECORDING_SIZE_MB", 0)
    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(slice_control.start_slice_scan, root) for _ in range(2)]
        results = [future.result() for future in futures]
    assert sum(result["queued"] for result in results) == 1
    assert len(list(root.rglob("*.pending"))) == 1


@pytest.mark.anyio
async def test_identical_finalize_finds_original_job(tmp_path, dashboard_client):
    root = tmp_path / "Videos"
    source = _create_processed_source(root)
    async with dashboard_client(root, remote_worker_trigger=lambda _: {"status": "accepted"}) as client:
        first = await client.post("/api/segments/seg_keep/finalize", json={"title": "Reviewed"})
        history = source.with_suffix(".mp4.task.json").read_bytes()
        second = await client.post("/api/segments/seg_keep/finalize", json={"title": "Reviewed"})
    assert first.status_code == second.status_code == 200
    assert first.json()["job_id"] == second.json()["job_id"]
    assert second.json()["status"] == "already_pending"
    assert source.with_suffix(".mp4.task.json").read_bytes() == history


@pytest.mark.parametrize("bad", ["{", "[]", '{"job_id":"wrong"}'])
def test_corrupt_processing_is_preserved_and_other_jobs_drain(tmp_path, bad):
    normal = action_jobs.enqueue_action_job(tmp_path, action="render_segment", segment_id="normal")
    root = action_jobs.jobs_dir(tmp_path)
    broken = root / ("a" * 32 + ".processing.json")
    broken.write_text(bad)
    executed = []
    assert action_jobs.process_action_jobs(tmp_path, executor=lambda job: executed.append(job["job_id"]) or {}) == 1
    assert executed == [normal["job"]["job_id"]]
    assert (root / ("a" * 32 + ".invalid.json")).read_text() == bad
    with pytest.raises(action_jobs.SegmentActionConflict):
        action_jobs.find_active_segment_job(tmp_path, "unknown")


def test_partial_ffmpeg_output_is_not_success(tmp_path, monkeypatch):
    from src.autoslice import danmaku_slice
    output = tmp_path / "candidate.mp4"
    class Process:
        stdout = io.StringIO("")
        def wait(self):
            return 1
    def launch(command, **kwargs):
        Path(command[-1]).write_bytes(b"partial")
        kwargs["stderr"].write(b"disk unavailable")
        return Process()
    monkeypatch.setattr("subprocess.Popen", launch)
    with pytest.raises(RuntimeError, match="disk unavailable"):
        danmaku_slice.slice_video("source.mp4", output, 1.9, 2.9)
    assert not output.exists()


def test_upload_page_is_bounded_and_read_only(tmp_path):
    missing = tmp_path / "missing.db"
    with pytest.raises(Exception):
        conn.read_upload_page(db_path=missing)
    assert not missing.exists()
    db = tmp_path / "queue.db"
    conn.migrate_upload_queue(db)
    with conn.connect(db) as connection:
        connection.executemany("insert into upload_queue(video_path,status) values (?, 'queued')", [(f"{i}.mp4",) for i in range(1000)])
    items, total = conn.read_upload_page(limit=50, offset=50, db_path=db)
    assert len(items) == 50 and total == 1000
    assert items[0]["id"] > items[-1]["id"]


@pytest.mark.anyio
async def test_slow_worker_read_does_not_block_local_requests(tmp_path, dashboard_client):
    import threading
    entered, release = threading.Event(), threading.Event()
    def slow():
        entered.set()
        release.wait(10)
        return {"status": "unavailable"}
    async with dashboard_client(tmp_path, remote_worker_status_reader=slow) as client:
        pending = asyncio.create_task(client.get("/api/worker-trigger/status"))
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            local = await asyncio.wait_for(client.get("/api/source-recordings"), 1)
            assert local.status_code == 200
            assert not pending.done()
        finally:
            release.set()
            await pending


def test_partial_recycle_recovers_frozen_manifest(tmp_path):
    from src.dashboard import recording_trash, source_lifecycle
    from tests.test_recording_trash import _recording, _state
    source = _recording(tmp_path)
    task = _state(tmp_path, source)
    moved = []
    def move(paths):
        if len(moved) == 1:
            raise OSError("interrupted")
        moved.append(paths[0])
        paths[0].unlink()
    with pytest.raises(OSError):
        recording_trash.trash_recording(tmp_path, task, mover=move)
    frozen = source_lifecycle.read_recording_state(tmp_path, task)["trash_plan"]["files"]
    recording_trash.trash_recording(tmp_path, task, mover=lambda paths: (moved.append(paths[0]), paths[0].unlink()))
    assert len(moved) == len(frozen) == len(set(moved))
    assert source_lifecycle.read_recording_state(tmp_path, task)["trash_status"] == "done"


def test_recycle_missing_unrecorded_result_is_not_retried(tmp_path):
    from src.dashboard import recording_trash, source_lifecycle
    from tests.test_recording_trash import _recording, _state
    source = _recording(tmp_path)
    task = _state(tmp_path, source)
    def move_then_fail(paths):
        paths[0].unlink()
        raise OSError("outcome not recorded")
    with pytest.raises(OSError):
        recording_trash.trash_recording(tmp_path, task, mover=move_then_fail)
    with pytest.raises(source_lifecycle.RecordingTrashBlocked, match="未知"):
        recording_trash.trash_recording(tmp_path, task, mover=lambda _: pytest.fail("must not move unknown item"))


@pytest.mark.parametrize("start", [0.1, 0.9, 1.9])
def test_fractional_final_has_source_frames_audio_and_duration(tmp_path, start):
    import shutil
    import subprocess
    from array import array
    from src.autoslice.analysis_result import AnalysisResult, TranscriptSegment
    from src.burn.subtitle_burn import burn_subtitles_from_analysis
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("ffmpeg/ffprobe unavailable")
    source, final = tmp_path / "source.mp4", tmp_path / "final.mp4"
    def run(args):
        return subprocess.run(args, check=True, capture_output=True).stdout
    run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=30:duration=5",
         "-f", "lavfi", "-i", "sine=frequency=1000:sample_rate=48000:duration=5",
         "-c:v", "libx264", "-g", "90", "-pix_fmt", "yuv420p", "-c:a", "aac", str(source)])
    result = burn_subtitles_from_analysis(source, AnalysisResult(title="test", description="test", transcript_segments=[TranscriptSegment(start=0, end=1, text="test")]),
                                         output_path=final, source_range=(start, start + 2.9))
    assert result.burned, result.message
    duration = float(run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(final)]))
    assert abs(duration - 2.9) <= 1 / 30 + 0.01
    def frame(path, at):
        return run(["ffmpeg", "-v", "error", "-ss", str(at), "-i", str(path), "-frames:v", "1",
                    "-vf", "crop=160:40:0:0", "-pix_fmt", "gray", "-f", "rawvideo", "-"])
    expected, actual = frame(source, start), frame(final, 0)
    assert len(expected) == len(actual) == 6400
    assert sum(abs(a - b) for a, b in zip(expected, actual)) / len(actual) < 8
    audio = run(["ffmpeg", "-v", "error", "-i", str(final), "-vn", "-ac", "1", "-ar", "48000", "-f", "f32le", "-"])
    samples = array('f', audio)
    assert abs(len(samples) / 48000 - 2.9) < 0.05
    assert max(abs(x) for x in samples) > 0.05


def test_failed_slice_preserves_existing_media(tmp_path, monkeypatch):
    from src.autoslice import danmaku_slice
    output = tmp_path / "candidate.mp4"
    output.write_bytes(b"valid-before")
    class Process:
        stdout = io.StringIO("")
        def wait(self):
            return 1
    def launch(command, **kwargs):
        Path(command[-1]).write_bytes(b"partial")
        return Process()
    monkeypatch.setattr("subprocess.Popen", launch)
    with pytest.raises(RuntimeError):
        danmaku_slice.slice_video("source.mp4", output, 1.9, 2.9)
    assert output.read_bytes() == b"valid-before"


@pytest.mark.parametrize("stop_fails", [False, True])
def test_smb_recovery_budget_and_stop_boundary(tmp_path, stop_fails):
    import os
    import shutil
    import subprocess
    bash = "C:/Program Files/Git/bin/bash.exe" if os.name == "nt" else shutil.which("bash")
    if not bash or not Path(bash).is_file():
        pytest.skip("bash unavailable")
    log = tmp_path / "commands.log"
    driver = r'''probes=0
findmnt() { return 0; }
systemctl() { if [ "$FAIL_STOP" = 1 ] && [ "$1 $2" = "stop bilive-dashboard.service" ]; then return 1; fi; return 0; }
stat() { probes=$((probes + 1)); [ "$probes" -gt 1 ]; }
timeout() { printf '%s\n' "$*" >> "$CALL_LOG"; shift; if [ "$1" = bash ]; then return 0; fi; "$@"; }
umount() { return 0; }
source "$1"
'''
    env = {**os.environ, "CALL_LOG":log.as_posix(), "FAIL_STOP":str(int(stop_fails))}
    result = subprocess.run([bash, "--noprofile", "--norc", "-c", driver, "audit", Path("deploy/bilive-smb-recover.sh").resolve().as_posix()], env=env, capture_output=True, text=True)
    commands = log.read_text().splitlines()
    assert result.returncode == (1 if stop_fails else 0), result.stderr
    if stop_fails:
        assert not any("start mnt-win.mount" in line for line in commands)
    else:
        assert any("restart bilive-dashboard.service" in line for line in commands)
        budget = sum(int(line.split()[0]) for line in commands)
        assert budget < 150


@pytest.mark.parametrize("remote", ["", "already-on-cdn"])
def test_upload_retry_does_not_repeat_unknown_posting(tmp_path, monkeypatch, remote):
    db = tmp_path / "queue.db"
    conn.migrate_upload_queue(db)
    conn.insert_upload_queue("fixture.mp4", db)
    with conn.connect(db) as connection:
        connection.execute("update upload_queue set status = 'failed', remote_filename = ?", (remote,))
        item_id = connection.execute("select id from upload_queue").fetchone()[0]
    original_read = conn.connect_readonly
    original_retry = conn.requeue_failed_upload
    monkeypatch.setattr(conn, "connect_readonly", lambda: original_read(db))
    monkeypatch.setattr(conn, "requeue_failed_upload", lambda path: original_retry(path, db))
    job = {"action": "retry_upload", "execution_target": "windows", "payload": {"upload_id": item_id}}
    if remote:
        with pytest.raises(ValueError, match="人工核对"):
            action_jobs._execute_action_job(tmp_path, job)
    else:
        action_jobs._execute_action_job(tmp_path, job)
    with original_read(db) as connection:
        row = connection.execute("select status, remote_filename from upload_queue").fetchone()
    assert row[0] == ("failed" if remote else "queued")
    assert row[1] == remote
