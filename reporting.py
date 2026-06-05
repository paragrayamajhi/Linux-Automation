from __future__ import annotations

"""Build and store run reports.

If you are reading this for the first time, this file does two simple things:
1) Take all host results and create one final JSON object (`build_report`).
2) Move old report files into an archive folder so new runs do not overwrite
    history (`archive_report`).

Quick glossary:
- summary: Top-level counts (passed/failed/total).
- host result: Status and task details for one host.
- archive: Move old file aside instead of deleting it.
"""

from datetime import datetime
from pathlib import Path
from typing import Any


def build_report(
    results: list[dict[str, Any]],
    started_at: datetime,
    finished_at: datetime,
    run_mode: str = "real",
) -> dict[str, Any]:
    """Build normalized report payload from host results.

    `run_mode` tells readers if this was a real run or an emulated test run.
    The returned dictionary is written directly to JSON by the orchestrator.
    """
    # Count hosts where the *overall* host status is passed.
    passed = sum(1 for item in results if item["status"] == "passed")
    # Everything not marked passed is counted as failed at host-summary level.
    failed = sum(1 for item in results if item["status"] != "passed")
    return {
        "summary": {
            "total_hosts": len(results),
            "passed": passed,
            "failed": failed,
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "run_mode": run_mode,
        },
        "hosts": results,
    }


def archive_report(report_path: str) -> None:
    """Move existing report to reports_archive with timestamped filename.

    Why this exists:
    - Without this, each run would replace the previous report.
    - With this, every historical run remains available for troubleshooting.
    """
    report_file = Path(report_path)
    if report_file.exists():
        # Create archive folder next to the report if it does not exist yet.
        archive_dir = report_file.parent / "reports_archive"
        archive_dir.mkdir(exist_ok=True)

        # Timestamp format keeps archived files naturally sorted by time.
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        archived_path = archive_dir / f"{report_file.stem}_{timestamp}{report_file.suffix}"
        report_file.rename(archived_path)
        print(f"Archived previous report to: {archived_path}")
