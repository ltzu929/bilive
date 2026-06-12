import importlib
import sqlite3
from pathlib import Path


def _module():
    path = Path("src/maintenance/runtime_cleanup.py")
    assert path.exists(), "runtime cleanup module is missing"
    return importlib.import_module("src.maintenance.runtime_cleanup")


def test_reset_upload_database_backs_up_legacy_queue_and_creates_empty_schema(
    tmp_path,
):
    maintenance = _module()
    database = tmp_path / "data.db"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "create table upload_queue ("
            "id integer primary key, video_path text, locked integer default 0)"
        )
        connection.execute(
            "insert into upload_queue(video_path, locked) values ('missing.mp4', 1)"
        )

    result = maintenance.reset_upload_database(
        database,
        backup_dir=tmp_path / "backups",
        timestamp="20260612-120000",
    )

    backup = Path(result["backup_path"])
    assert backup.exists()
    with sqlite3.connect(backup) as connection:
        assert connection.execute("select count(*) from upload_queue").fetchone()[0] == 1
    with sqlite3.connect(database) as connection:
        assert connection.execute("select count(*) from upload_queue").fetchone()[0] == 0
        indexes = connection.execute("pragma index_list(upload_queue)").fetchall()
    assert any(row[1] == "idx_video_path" and row[2] == 1 for row in indexes)


def test_recover_recording_keeps_valid_existing_mp4_and_deletes_flv(tmp_path):
    maintenance = _module()
    source = tmp_path / "room.flv"
    target = tmp_path / "room.mp4"
    source.write_bytes(b"x" * 2_000_000)
    target.write_bytes(b"valid")

    result = maintenance.recover_recording(
        source,
        execute=True,
        validator=lambda path: {
            "valid": path == target,
            "duration": 120.0,
            "streams": ["video", "audio"],
        },
        remuxer=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("remux should not run")
        ),
    )

    assert result["status"] == "kept_existing_mp4"
    assert not source.exists()
    assert target.exists()


def test_recover_recording_deletes_tiny_invalid_flv(tmp_path):
    maintenance = _module()
    source = tmp_path / "broken.flv"
    source.write_bytes(b"bad")

    result = maintenance.recover_recording(
        source,
        execute=True,
        delete_invalid=True,
        validator=lambda _path: {"valid": False, "error": "invalid"},
        remuxer=lambda *_args, **_kwargs: False,
    )

    assert result["status"] == "deleted_invalid"
    assert not source.exists()


def test_recover_recording_keeps_verified_remux_and_removes_source(tmp_path):
    maintenance = _module()
    source = tmp_path / "recoverable.flv"
    source.write_bytes(b"x" * 2_000_000)

    def remuxer(_source, output):
        assert output.name == "recoverable.partial.mp4"
        output.write_bytes(b"mp4")
        return True

    result = maintenance.recover_recording(
        source,
        execute=True,
        validator=lambda path: {
            "valid": path.name == "recoverable.partial.mp4",
            "duration": 90.0,
            "streams": ["video", "audio"],
        },
        remuxer=remuxer,
    )

    target = tmp_path / "recoverable.mp4"
    assert result["status"] == "recovered"
    assert target.exists()
    assert not source.exists()


def test_recover_recording_preserves_source_and_existing_target_on_remux_failure(
    tmp_path,
):
    maintenance = _module()
    source = tmp_path / "recoverable.flv"
    target = tmp_path / "recoverable.mp4"
    source.write_bytes(b"x" * 2_000_000)
    target.write_bytes(b"old-invalid-target")

    result = maintenance.recover_recording(
        source,
        execute=True,
        validator=lambda _path: {"valid": False, "error": "invalid"},
        remuxer=lambda _source, _output: False,
    )

    assert result["status"] == "recovery_failed_preserved"
    assert source.exists()
    assert target.read_bytes() == b"old-invalid-target"


def test_recover_recording_preserves_source_when_remux_validation_fails(tmp_path):
    maintenance = _module()
    source = tmp_path / "recoverable.flv"
    target = tmp_path / "recoverable.mp4"
    source.write_bytes(b"x" * 2_000_000)
    target.write_bytes(b"old-invalid-target")

    def remuxer(_source, output):
        output.write_bytes(b"invalid-remux")
        return True

    result = maintenance.recover_recording(
        source,
        execute=True,
        validator=lambda _path: {"valid": False, "error": "decode failed"},
        remuxer=remuxer,
    )

    assert result["status"] == "recovery_failed_preserved"
    assert source.exists()
    assert target.read_bytes() == b"old-invalid-target"
    assert not (tmp_path / "recoverable.partial.mp4").exists()


def test_recover_recording_reports_tiny_invalid_file_without_explicit_delete(
    tmp_path,
):
    maintenance = _module()
    source = tmp_path / "broken.flv"
    source.write_bytes(b"bad")

    result = maintenance.recover_recording(
        source,
        execute=True,
        validator=lambda _path: {"valid": False, "error": "invalid"},
        remuxer=lambda *_args, **_kwargs: False,
    )

    assert result["status"] == "invalid_preserved"
    assert source.exists()


def test_audit_mp4_recordings_preserves_invalid_files_by_default(tmp_path):
    maintenance = _module()
    valid = tmp_path / "valid.mp4"
    invalid = tmp_path / "invalid.mp4"
    valid.write_bytes(b"valid")
    invalid.write_bytes(b"invalid")

    report = maintenance.audit_mp4_recordings(
        tmp_path,
        validator=lambda path: {
            "valid": path == valid,
            "error": "" if path == valid else "decode failed",
        },
    )

    assert report["counts"] == {"valid": 1, "invalid_preserved": 1}
    assert invalid.exists()


def test_audit_mp4_recordings_deletes_only_confirmed_invalid_files(tmp_path):
    maintenance = _module()
    invalid = tmp_path / "invalid.mp4"
    invalid.write_bytes(b"invalid")

    report = maintenance.audit_mp4_recordings(
        tmp_path,
        delete_invalid=True,
        validator=lambda _path: {"valid": False, "error": "decode failed"},
    )

    assert report["counts"] == {"deleted_invalid": 1}
    assert not invalid.exists()
