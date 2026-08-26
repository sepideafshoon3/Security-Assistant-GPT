import subprocess
from pathlib import Path
from typing import Optional
from src.core.models import ToolResult


def run_semgrep(repository_path: str, reports_dir: Path) -> ToolResult:
    reports_dir.mkdir(parents=True, exist_ok=True)
    output_path = reports_dir / "semgrep.json"

    try:
        subprocess.run(
            [
                "semgrep",
                "--config",
                "p/ci",
                "--json",
                "--output",
                str(output_path),
                repository_path,
            ],
            check=True,
        )
        return ToolResult(
            action="run_semgrep",
            success=True,
            output_path=str(output_path),
        )
    except Exception as exc:  # noqa: BLE001
        return ToolResult(
            action="run_semgrep",
            success=False,
            errors=str(exc),
        )
