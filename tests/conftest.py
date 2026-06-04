import pytest


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def videos_root(tmp_path):
    return tmp_path / "Videos"


@pytest.fixture
def dashboard_client():
    import httpx

    from src.dashboard.app import create_app

    def build(videos_root=None, **app_kwargs):
        app = create_app(videos_root=videos_root, **app_kwargs)
        transport = httpx.ASGITransport(app=app)
        return httpx.AsyncClient(transport=transport, base_url="http://test")

    return build


@pytest.fixture
def make_room(videos_root):
    def create(room_id="8792912"):
        room = videos_root / room_id
        room.mkdir(parents=True, exist_ok=True)
        return room

    return create


@pytest.fixture
def write_slice(make_room):
    def write(
        name="3100s_8792912_20260506-18-56-51.mp4",
        content=b"clip",
        room_id="8792912",
    ):
        path = make_room(room_id) / name
        path.write_bytes(content)
        return path

    return write


@pytest.fixture
def write_source_recording(make_room):
    def write(
        name="22384516_20260527-12-55-32.mp4",
        content=b"video",
        room_id="22384516",
        with_xml=True,
    ):
        source = make_room(room_id) / name
        source.write_bytes(content)
        if with_xml:
            source.with_suffix(".xml").write_text("<i></i>", encoding="utf-8")
        return source

    return write
