import subprocess
import sys


def test_slice_metadata_import_does_not_require_bilitool_dependencies():
    script = """
import builtins
import importlib

real_import = builtins.__import__

def guarded_import(name, *args, **kwargs):
    if name == "qrcode" or name.startswith("qrcode."):
        raise AssertionError("slice metadata import should not require qrcode")
    return real_import(name, *args, **kwargs)

builtins.__import__ = guarded_import
module = importlib.import_module("src.upload.slice_metadata")
assert hasattr(module, "write_slice_upload_metadata")
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
