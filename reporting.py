from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any


def build_report(
    results: list[dict[str, Any]],
    started_at: datetime,
    finished_at: datetime,
    run_mode: str = "real",
) -> dict[str, Any]:
    passed = sum(1 for item in results if item["status"] == "passed")
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
    report_file = Path(report_path)
    if report_file.exists():
        archive_dir = report_file.parent / "reports_archive"
        archive_dir.mkdir(exist_ok=True)

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        archived_path = archive_dir / f"{report_file.stem}_{timestamp}{report_file.suffix}"
        report_file.rename(archived_path)
        print(f"Archived previous report to: {archived_path}")
