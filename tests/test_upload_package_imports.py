import builtins
import importlib
import sys


def test_slice_metadata_import_does_not_require_bilitool_dependencies(monkeypatch):
    for name in list(sys.modules):
        if name == "src.upload" or name.startswith("src.upload."):
            sys.modules.pop(name)

    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "qrcode" or name.startswith("qrcode."):
            raise AssertionError("slice metadata import should not require qrcode")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    module = importlib.import_module("src.upload.slice_metadata")

    assert hasattr(module, "write_slice_upload_metadata")
