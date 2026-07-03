import json
import os
from pathlib import Path

import pytest
import toml

from src.db.conn import (
    get_upload_item,
    insert_upload_queue,
    list_upload_queue,
    migrate_upload_queue,
)
from src.upload.slice_metadata import write_slice_upload_metadata
from src.upload.upload import (
    BilibiliRuntimeClient,
    UploadAlreadyRunning,
    UploadProcessLock,
    UploadSettings,
    UploadWorker,
    main,
    parse_cookie_file,
    run_forever,
    settings_from_environment,
)


class FakeBilibiliClient:
    def __init__(
        self,
        *,
        logged_in=True,
        remote_filename="remote-file",
        submit_responses=None,
    ):
        self.logged_in = logged_in
        self.remote_filename = remote_filename
        self.submit_responses = list(
            submit_responses
            or [{"code": 0, "data": {"bvid": "BV1test"}, "message": "0"}]
        )
        self.login_calls = 0
        self.upload_calls = []
        self.submit_calls = []

    def check_login(self):
        self.login_calls += 1
        if self.logged_in:
            return {"isLogin": True, "uname": "test-user"}
        return None

    def upload_file(self, video_path, metadata):
        self.upload_calls.append((video_path, metadata))
        return self.remote_filename

    def submit_uploaded_video(self, remote_filename, metadata):
        self.submit_calls.append((remote_filename, metadata))
        return self.submit_responses.pop(0)


def make_settings(tmp_path, **overrides):
    values = {
        "db_path": tmp_path / "data.db",
        "cookie_file": tmp_path / "bilibili.cookie",
        "status_file": tmp_path / "upload-status.json",
        "lock_file": tmp_path / "upload.lock",
        "poll_interval_seconds": 1,
        "max_attempts": 3,
        "retry_base_seconds": 10,
        "auth_retry_seconds": 30,
        "delete_after_success": True,
        "upload_line": "auto",
        "tid": 138,
    }
    values.update(overrides)
    settings = UploadSettings(**values)
    migrate_upload_queue(settings.db_path)
    return settings


def queue_slice(tmp_path, settings, name="clip.mp4"):
    video_path = tmp_path / name
    video_path.write_bytes(b"video")
    sidecar = write_slice_upload_metadata(
        video_path,
        title="切片标题",
        desc="切片简介",
        tag=["直播切片", "高能"],
        source="https://live.bilibili.com/8792912",
    )
    assert insert_upload_queue(str(video_path), db_path=settings.db_path)
    return video_path, sidecar


def read_status(settings):
    return json.loads(settings.status_file.read_text(encoding="utf-8"))


def test_process_one_uploads_and_publishes_slice(tmp_path):
    settings = make_settings(tmp_path)
    video_path, sidecar = queue_slice(tmp_path, settings)
    client = FakeBilibiliClient()
    worker = UploadWorker(settings, client)

    result = worker.process_one(now=100)

    assert result.status == "published"
    assert result.bvid == "BV1test"
    assert [call[0] for call in client.upload_calls] == [str(video_path)]
    assert [call[0] for call in client.submit_calls] == ["remote-file"]
    row = get_upload_item(str(video_path), settings.db_path)
    assert row["status"] == "published"
    assert row["remote_filename"] == "remote-file"
    assert row["bvid"] == "BV1test"
    assert not video_path.exists()
    assert not sidecar.exists()
    assert read_status(settings)["last_successful_bvid"] == "BV1test"


def test_publish_retry_does_not_upload_video_twice(tmp_path):
    settings = make_settings(tmp_path)
    video_path, _ = queue_slice(tmp_path, settings)
    client = FakeBilibiliClient(
        submit_responses=[
            {"code": 21070, "message": "投稿服务繁忙"},
            {"code": 0, "data": {"bvid": "BV1retry"}, "message": "0"},
        ]
    )
    worker = UploadWorker(settings, client)

    first = worker.process_one(now=100)
    too_early = worker.process_one(now=109)
    second = worker.process_one(now=110)

    assert first.status == "retry"
    assert too_early.status == "idle"
    assert second.status == "published"
    assert [call[0] for call in client.upload_calls] == [str(video_path)]
    assert [call[0] for call in client.submit_calls] == [
        "remote-file",
        "remote-file",
    ]


def test_retryable_failure_stops_at_configured_limit(tmp_path):
    settings = make_settings(tmp_path, max_attempts=2)
    video_path, _ = queue_slice(tmp_path, settings)
    client = FakeBilibiliClient(
        submit_responses=[
            {"code": 21070, "message": "busy"},
            {"code": 21070, "message": "still busy"},
        ]
    )
    worker = UploadWorker(settings, client)

    worker.process_one(now=100)
    result = worker.process_one(now=110)

    assert result.status == "failed"
    row = get_upload_item(str(video_path), settings.db_path)
    assert row["status"] == "failed"
    assert row["attempts"] == 2
    assert row["locked"] == 1
    assert len(client.upload_calls) == 1
    assert len(client.submit_calls) == 2


def test_authentication_failure_does_not_claim_items(tmp_path):
    settings = make_settings(tmp_path)
    first, _ = queue_slice(tmp_path, settings, "first.mp4")
    second, _ = queue_slice(tmp_path, settings, "second.mp4")
    client = FakeBilibiliClient(logged_in=False)
    worker = UploadWorker(settings, client)

    result = worker.process_one(now=100)

    assert result.status == "paused_auth"
    assert [row["status"] for row in list_upload_queue(settings.db_path)] == [
        "queued",
        "queued",
    ]
    assert client.upload_calls == []
    assert client.submit_calls == []
    assert read_status(settings)["status"] == "paused_auth"
    assert first.exists()
    assert second.exists()


def test_missing_file_fails_without_bilibili_request(tmp_path):
    settings = make_settings(tmp_path)
    missing = tmp_path / "missing.mp4"
    insert_upload_queue(str(missing), db_path=settings.db_path)
    client = FakeBilibiliClient()
    worker = UploadWorker(settings, client)

    result = worker.process_one(now=100)

    assert result.status == "failed"
    assert client.login_calls == 0
    assert client.upload_calls == []
    assert get_upload_item(str(missing), settings.db_path)["status"] == "failed"


def test_malformed_metadata_fails_without_bilibili_request(tmp_path):
    settings = make_settings(tmp_path)
    video_path = tmp_path / "clip.mp4"
    video_path.write_bytes(b"video")
    video_path.with_suffix(".upload.json").write_text("{bad json", encoding="utf-8")
    insert_upload_queue(str(video_path), db_path=settings.db_path)
    client = FakeBilibiliClient()
    worker = UploadWorker(settings, client)

    result = worker.process_one(now=100)

    assert result.status == "failed"
    assert client.login_calls == 0
    assert client.upload_calls == []
    assert "metadata" in result.error.lower()


def test_success_can_keep_local_files(tmp_path):
    settings = make_settings(tmp_path, delete_after_success=False)
    video_path, sidecar = queue_slice(tmp_path, settings)
    worker = UploadWorker(settings, FakeBilibiliClient())

    result = worker.process_one(now=100)

    assert result.status == "published"
    assert video_path.exists()
    assert sidecar.exists()


def test_cleanup_failure_does_not_retry_published_submission(tmp_path, monkeypatch):
    settings = make_settings(tmp_path)
    video_path, _ = queue_slice(tmp_path, settings)
    client = FakeBilibiliClient()
    worker = UploadWorker(settings, client)
    monkeypatch.setattr(
        worker,
        "_cleanup",
        lambda *args: (_ for _ in ()).throw(OSError("file is in use")),
    )

    result = worker.process_one(now=100)

    assert result.status == "published"
    assert "file is in use" in result.error
    row = get_upload_item(str(video_path), settings.db_path)
    assert row["status"] == "published"
    assert row["attempts"] == 0
    assert len(client.submit_calls) == 1
    assert video_path.exists()


def test_auth_error_during_publish_preserves_remote_filename(tmp_path):
    settings = make_settings(tmp_path)
    video_path, _ = queue_slice(tmp_path, settings)
    client = FakeBilibiliClient(
        submit_responses=[{"code": -101, "message": "账号未登录"}]
    )
    worker = UploadWorker(settings, client)

    result = worker.process_one(now=100)

    assert result.status == "paused_auth"
    row = get_upload_item(str(video_path), settings.db_path)
    assert row["status"] == "uploaded"
    assert row["remote_filename"] == "remote-file"
    assert row["attempts"] == 0
    assert row["next_attempt_at"] == 130
    assert len(client.upload_calls) == 1


def test_runtime_client_uses_runtime_bilitool_config(tmp_path, monkeypatch):
    from src.upload.bilitool.bilitool.model import model as bilitool_model
    from src.upload.bilitool.bilitool.upload.bili_upload import BiliUploader

    monkeypatch.delenv("BILITOOL_CONFIG_PATH", raising=False)
    monkeypatch.setenv("BILIVE_LOG_DIR", str(tmp_path / "logs"))
    package_config = Path(bilitool_model.__file__).with_name("config.json")
    package_before = package_config.read_text(encoding="utf-8")
    expected_config = tmp_path / "logs" / "runtime" / "bilitool-config.json"
    seen_config_paths = []
    video_path = tmp_path / "clip.mp4"
    video_path.write_bytes(b"video")

    def fake_preupload(self, *, filename, filesize, cdn, probe_version):
        seen_config_paths.append(os.environ.get("BILITOOL_CONFIG_PATH"))
        return {
            "upos_uri": "upos://bucket/remote-file.m4s",
            "auth": "auth-token",
            "biz_id": 1,
            "chunk_size": 1024,
        }

    monkeypatch.setattr(BiliUploader, "preupload", fake_preupload)
    monkeypatch.setattr(
        BiliUploader,
        "get_upload_video_id",
        lambda self, *, upos_uri, auth, upos_url: {
            "upload_id": "upload-id",
            "key": "/remote-file.m4s",
        },
    )
    monkeypatch.setattr(
        BiliUploader,
        "upload_video_in_chunks",
        lambda self, **kwargs: None,
    )
    monkeypatch.setattr(
        BiliUploader,
        "finish_upload",
        lambda self, **kwargs: None,
    )
    client = BilibiliRuntimeClient(
        cookies={"SESSDATA": "session-value", "bili_jct": "csrf-value"},
        upload_line="qn",
    )

    remote_filename = client.upload_file(str(video_path), {})

    assert remote_filename == "remote-file"
    assert seen_config_paths == [str(expected_config)]
    assert os.environ.get("BILITOOL_CONFIG_PATH") is None
    runtime_config = json.loads(expected_config.read_text(encoding="utf-8"))
    assert runtime_config["upload"]["title"] == "clip"
    assert package_config.read_text(encoding="utf-8") == package_before

def test_process_lock_rejects_second_consumer(tmp_path):
    lock_path = tmp_path / "upload.lock"

    with UploadProcessLock(lock_path):
        with pytest.raises(UploadAlreadyRunning):
            with UploadProcessLock(lock_path):
                pass

    with UploadProcessLock(lock_path):
        assert lock_path.exists()

    assert not lock_path.exists()


def test_process_lock_recovers_stale_pid_file(tmp_path):
    lock_path = tmp_path / "upload.lock"
    lock_path.write_text("99999999", encoding="utf-8")

    with UploadProcessLock(lock_path):
        assert lock_path.read_text(encoding="utf-8") == str(os.getpid())

    assert not lock_path.exists()


def test_parse_cookie_file_requires_bilibili_session_values(tmp_path):
    cookie_file = tmp_path / "bilibili.cookie"
    cookie_file.write_text(
        "SESSDATA=session-value; bili_jct=csrf-value; DedeUserID=123",
        encoding="utf-8",
    )

    cookies = parse_cookie_file(cookie_file)

    assert cookies == {
        "SESSDATA": "session-value",
        "bili_jct": "csrf-value",
        "DedeUserID": "123",
    }

    cookie_file.write_text("SESSDATA=session-value", encoding="utf-8")
    with pytest.raises(ValueError, match="bili_jct"):
        parse_cookie_file(cookie_file)


def test_settings_from_environment_reads_upload_config(tmp_path, monkeypatch):
    config_path = tmp_path / "bilive-server.toml"
    config_path.write_text(
        """
[video]
tid = 171
upload_line = "bldsa"

[upload]
poll_interval_seconds = 7
max_attempts = 4
retry_base_seconds = 12
auth_retry_seconds = 90
delete_after_success = false
""".strip(),
        encoding="utf-8",
    )
    cookie_file = tmp_path / "bilibili.cookie"
    cookie_file.write_text(
        "SESSDATA=session-value; bili_jct=csrf-value",
        encoding="utf-8",
    )
    monkeypatch.setenv("BILIVE_DIR", str(tmp_path))
    monkeypatch.setenv("BILIVE_CONFIG", str(config_path))
    monkeypatch.setenv("BILIVE_COOKIE_FILE", str(cookie_file))
    monkeypatch.setenv("BILIVE_DB_PATH", str(tmp_path / "queue.db"))
    monkeypatch.setenv("BILIVE_LOG_DIR", str(tmp_path / "logs"))

    settings = settings_from_environment()

    assert settings.db_path == tmp_path / "queue.db"
    assert settings.cookie_file == cookie_file
    assert settings.status_file == tmp_path / "logs" / "runtime" / "upload-status.json"
    assert settings.lock_file == tmp_path / "logs" / "runtime" / "upload.lock"
    assert settings.poll_interval_seconds == 7
    assert settings.max_attempts == 4
    assert settings.retry_base_seconds == 12
    assert settings.auth_retry_seconds == 90
    assert settings.delete_after_success is False
    assert settings.upload_line == "bldsa"
    assert settings.tid == 171
    assert "session-value" in settings.sensitive_values
    assert "csrf-value" in settings.sensitive_values


def test_status_cli_does_not_load_credentials_or_network(
    tmp_path,
    monkeypatch,
    capsys,
):
    config_path = tmp_path / "bilive-server.toml"
    config_path.write_text(
        """
[video]
tid = 138
upload_line = "auto"

[upload]
poll_interval_seconds = 10
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("BILIVE_DIR", str(tmp_path))
    monkeypatch.setenv("BILIVE_CONFIG", str(config_path))
    monkeypatch.setenv("BILIVE_COOKIE_FILE", str(tmp_path / "missing.cookie"))
    monkeypatch.setenv("BILIVE_DB_PATH", str(tmp_path / "queue.db"))
    monkeypatch.setattr(
        "src.upload.upload.build_runtime_client",
        lambda settings: pytest.fail("status must not create a network client"),
    )

    exit_code = main(["--status"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["queue_counts"]["total"] == 0
    assert payload["database"] == "missing"
    assert not (tmp_path / "queue.db").exists()


def test_server_config_exports_upload_runtime_settings():
    from src.config import server_config

    assert server_config.UPLOAD_AUTO_START is True
    assert server_config.UPLOAD_POLL_INTERVAL_SECONDS == 10
    assert server_config.UPLOAD_MAX_ATTEMPTS == 3
    assert server_config.UPLOAD_RETRY_BASE_SECONDS == 30
    assert server_config.UPLOAD_AUTH_RETRY_SECONDS == 120
    assert server_config.UPLOAD_DELETE_AFTER_SUCCESS is True


def test_production_config_omits_legacy_gift_filter():
    from src.config import server_config

    config = toml.load("bilive-server.toml")

    assert "gift_price_filter" not in config["video"]
    assert not hasattr(server_config, "GIFT_PRICE_FILTER")


def test_run_forever_reloads_client_after_auth_configuration_recovers(tmp_path):
    settings = make_settings(tmp_path)
    video_path, _ = queue_slice(tmp_path, settings)
    working_client = FakeBilibiliClient()
    factory_calls = []
    sleeps = []

    def client_factory():
        factory_calls.append("build")
        if len(factory_calls) == 1:
            raise ValueError("cookie file missing")
        return working_client

    exit_code = run_forever(
        settings,
        client_factory=client_factory,
        sleep=lambda seconds: sleeps.append(seconds),
        max_cycles=2,
    )

    assert exit_code == 0
    assert factory_calls == ["build", "build"]
    assert sleeps == [settings.auth_retry_seconds]
    assert get_upload_item(str(video_path), settings.db_path)["status"] == "published"


def test_default_cli_defers_client_creation_to_run_loop(tmp_path, monkeypatch):
    settings = make_settings(tmp_path)
    calls = []
    monkeypatch.setattr(
        "src.upload.upload.settings_from_environment",
        lambda: settings,
    )
    monkeypatch.setattr(
        "src.upload.upload.build_runtime_client",
        lambda settings: pytest.fail("main must not eagerly build the client"),
    )
    monkeypatch.setattr(
        "src.upload.upload.run_forever",
        lambda received: calls.append(received) or 0,
    )

    exit_code = main([])

    assert exit_code == 0
    assert calls == [settings]
