"""Shared lightweight dashboard-domain exceptions."""


class SegmentStateConflict(RuntimeError):
    """Requested edit conflicts with an active or irreversible segment state."""
