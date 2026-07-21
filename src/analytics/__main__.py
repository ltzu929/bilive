# Copyright (c) 2024 bilive.
"""CLI entrypoint for the periodic self-evolution analytics run (Windows side).

Run via ``python -m src.analytics``. It (1) refreshes published slice stats from
Bilibili into ``slice_performance``, (2) builds an advisory tuning report + a
few-shot pack, and (3) writes them to the runtime output directory. Nothing
here mutates the live pipeline configuration.

Intended to be scheduled by Windows Task Scheduler (see
``install_windows_worker_task.ps1`` for the analogous worker task), never on Pi.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from src.analytics.published_stats import refresh_published_stats
from src.analytics.recommender import build_recommendations, write_recommendations
from src.db.conn import get_slice_performance


def _current_config() -> dict[str, object]:
    from src.config import BURST_CONTEXT, BURST_LAG_SECONDS, BURST_RATIO

    return {
        "slice.burst.burst_lag_seconds": BURST_LAG_SECONDS,
        "slice.burst.burst_ratio": BURST_RATIO,
        "slice.burst.burst_context": BURST_CONTEXT,
    }


def _default_output_dir() -> Path:
    project_root = Path(
        os.environ.get("BILIVE_DIR", Path(__file__).resolve().parents[2])
    )
    return Path(
        os.environ.get("BILIVE_LOG_DIR", project_root / "logs")
    ) / "analytics"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="bilive self-evolution analytics run")
    parser.add_argument("--db-path", default=None, help="override the SQLite db path")
    parser.add_argument(
        "--output-dir",
        default=None,
        help="directory for recommendations.json / few_shot.json",
    )
    parser.add_argument(
        "--rate-limit-seconds",
        type=float,
        default=1.0,
        help="delay between Bilibili stat fetches",
    )
    parser.add_argument(
        "--min-samples",
        type=int,
        default=5,
        help="minimum published slices before advising",
    )
    parser.add_argument(
        "--skip-fetch",
        action="store_true",
        help="skip the Bilibili poll and only rebuild recommendations",
    )
    args = parser.parse_args(argv)

    output_dir = Path(args.output_dir) if args.output_dir else _default_output_dir()

    if not args.skip_fetch:
        summary = refresh_published_stats(
            db_path=args.db_path,
            rate_limit_seconds=args.rate_limit_seconds,
        )
        print(f"[analytics] stats refresh: {json.dumps(summary)}")

    rows = get_slice_performance(args.db_path)
    report = build_recommendations(
        rows,
        current_config=_current_config(),
        min_samples=args.min_samples,
    )
    paths = write_recommendations(report, output_dir)
    print(
        f"[analytics] sample_size={report['sample_size']} "
        f"insufficient_data={report['insufficient_data']} "
        f"report={paths['report']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
