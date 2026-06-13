import importlib
import math
import zipfile
from pathlib import Path

import pytest

WHEEL = Path("wheel/blrec-2.0.0b4-py3-none-any.whl")


def _load_modules():
    expected = [
        Path("src/blrec_compat.py"),
        Path("src/blrec_patch.py"),
        Path("src/blrec_settings.py"),
    ]
    assert all(path.exists() for path in expected), "blrec hardening modules are missing"
    return (
        importlib.import_module("src.blrec_compat"),
        importlib.import_module("src.blrec_patch"),
        importlib.import_module("src.blrec_settings"),
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (float("inf"), 30.0),
        (float("-inf"), 30.0),
        (float("nan"), 30.0),
        (0, 30.0),
        (-1, 30.0),
        ("not-a-number", 30.0),
        (None, 30.0),
        ("29.97", 29.97),
        (60, 60.0),
    ],
)
def test_normalize_frame_rate_rejects_non_finite_and_non_positive_values(
    value,
    expected,
):
    compat, _, _ = _load_modules()
    assert compat.normalize_frame_rate(value) == expected


def test_patch_blrec_source_is_hash_guarded_and_idempotent(tmp_path):
    _, patcher, _ = _load_modules()
    with zipfile.ZipFile(WHEEL) as archive:
        original = archive.read("blrec/flv/operators/fix.py")

    target = tmp_path / "fix.py"
    target.write_bytes(original)

    assert patcher.patch_blrec_source(target, patcher.EXPECTED_BLREC_VERSION) is True
    patched = target.read_text(encoding="utf-8")
    assert "from src.blrec_compat import normalize_frame_rate" in patched
    assert "frame_rate = normalize_frame_rate(fps)" in patched
    assert "math.ceil(1000 / frame_rate)" in patched

    assert patcher.patch_blrec_source(target, patcher.EXPECTED_BLREC_VERSION) is False


def test_patch_blrec_source_refuses_unknown_version_or_source(tmp_path):
    _, patcher, _ = _load_modules()
    target = tmp_path / "fix.py"
    target.write_text("unknown source", encoding="utf-8")

    with pytest.raises(patcher.PatchError, match="version"):
        patcher.patch_blrec_source(target, "9.9.9")

    with pytest.raises(patcher.PatchError, match="hash"):
        patcher.patch_blrec_source(target, patcher.EXPECTED_BLREC_VERSION)


def test_keep_source_flv_updates_only_postprocessing_setting(tmp_path):
    _, _, settings_module = _load_modules()
    settings = tmp_path / "settings.toml"
    settings.write_text(
        '\n'.join(
            [
                '[recorder]',
                'stream_format = "flv"',
                '',
                '[postprocessing]',
                'remux_to_mp4 = true',
                'delete_source = "auto"',
                '',
            ]
        ),
        encoding="utf-8",
    )

    assert settings_module.keep_source_flv(settings) is True
    assert 'delete_source = "never"' in settings.read_text(encoding="utf-8")
    assert settings.with_suffix(".toml.before-bilive-hardening").exists()
    assert settings_module.keep_source_flv(settings) is False


def test_keep_source_flv_refuses_settings_without_postprocessing_key(tmp_path):
    _, _, settings_module = _load_modules()
    settings = tmp_path / "settings.toml"
    settings.write_text('[recorder]\nstream_format = "flv"\n', encoding="utf-8")

    with pytest.raises(ValueError, match="postprocessing"):
        settings_module.keep_source_flv(settings)
