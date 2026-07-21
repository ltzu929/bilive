# Copyright (c) 2024 bilive.
"""Read-only self-evolution analytics (Windows side).

This package correlates slice-generation features with post-publish Bilibili
performance to produce *advisory-only* tuning reports. It never mutates the
live pipeline configuration and is only invoked from Windows analytics/worker
entrypoints (never from the read-only dashboard routes).
"""
