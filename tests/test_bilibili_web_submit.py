from src.upload.bilibili_web import BilibiliWebClient


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


def test_submit_uploaded_video_uses_web_add_v3_json():
    session = FakeSession(
        FakeResponse({"code": 0, "data": {"bvid": "BV1test"}, "message": "0"})
    )
    client = BilibiliWebClient(
        session=session,
        csrf="csrf-token",
        now_ms=lambda: 1710000000123,
    )

    response = client.submit_uploaded_video(
        "remote-filename",
        {
            "title": "clip title",
            "desc": "clip description",
            "tid": 138,
            "tag": "直播切片,高能",
            "source": "https://live.bilibili.com/8792912",
            "cover": "",
            "dynamic": "dynamic text",
        },
    )

    assert response["data"]["bvid"] == "BV1test"
    assert len(session.calls) == 1
    url, request = session.calls[0]
    assert url == "https://member.bilibili.com/x/vu/web/add/v3"
    assert request["params"] == {
        "t": "1710000000123",
        "csrf": "csrf-token",
    }
    assert request["timeout"] == 60
    assert request["json"]["videos"] == [
        {
            "filename": "remote-filename",
            "title": "clip title",
            "desc": "clip description",
        }
    ]
    assert request["json"]["copyright"] == 2
    assert request["json"]["source"] == "https://live.bilibili.com/8792912"
    assert request["json"]["subtitle"] == {"open": 0, "lan": ""}


def test_submit_uploaded_video_returns_nonzero_api_response_for_worker():
    session = FakeSession(FakeResponse({"code": -101, "message": "账号未登录"}))
    client = BilibiliWebClient(
        session=session,
        csrf="csrf-token",
        now_ms=lambda: 1710000000123,
    )

    response = client.submit_uploaded_video(
        "remote-filename",
        {
            "title": "clip title",
            "desc": "",
            "tid": 138,
            "tag": "直播切片",
            "source": "https://live.bilibili.com/8792912",
        },
    )

    assert response == {"code": -101, "message": "账号未登录"}
