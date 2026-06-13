# Copyright (c) 2024 bilive.

__all__ = ["UploadController", "FeedController"]


def __getattr__(name):
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    from .bilitool.bilitool import UploadController, FeedController

    controllers = {
        "UploadController": UploadController,
        "FeedController": FeedController,
    }
    return controllers[name]
