"""Compatibility helpers used by the locally patched blrec runtime."""

import math
from typing import Any


DEFAULT_FRAME_RATE = 30.0


def normalize_frame_rate(value: Any, default: float = DEFAULT_FRAME_RATE) -> float:
    """Return a finite positive frame rate, falling back to the recorder default."""
    try:
        frame_rate = float(value)
    except (TypeError, ValueError):
        return default

    if not math.isfinite(frame_rate) or frame_rate <= 0:
        return default
    return frame_rate
