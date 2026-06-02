"""Tests for BurstEvent dataclass fields: baseline_density and local_density."""

from src.autoslice.burst_detector import BurstEvent, detect_bursts


def test_burst_event_has_baseline_and_local_density():
    """BurstEvent dataclass includes baseline_density and local_density fields."""
    event = BurstEvent(
        peak_time=100.0,
        start=40.0,
        end=160.0,
        duration=120.0,
        peak_density=5.0,
        burst_ratio=3.5,
        danmaku_count=200,
        baseline_density=1.43,
        local_density=5.0,
    )
    assert event.baseline_density == 1.43
    assert event.local_density == 5.0


def test_detect_bursts_populates_baseline_and_local_density():
    """detect_bursts fills baseline_density and local_density on returned events."""
    timestamps = [float(i) for i in range(100)] + [100.0] * 50
    events = detect_bursts(timestamps, video_duration=200.0, burst_ratio=2.0, context=30)

    assert len(events) > 0
    for event in events:
        assert event.baseline_density > 0
        assert event.local_density > 0