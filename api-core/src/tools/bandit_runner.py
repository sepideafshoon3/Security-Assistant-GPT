import subprocess
from pathlib import Path
from src.core.models import ToolResult


def run_bandit(repository_path: str, reports_dir: Path) -> ToolResult:
    reports_dir.mkdir(parents=True, exist_ok=True)
    output_path = reports_dir / "bandit.json"

    try:
        subprocess.run(
            [
                "bandit",
                "-r",
                repository_path,
                "-f",
                "json",
                "-o",
                str(output_path),
            ],
            check=True,
        )
        return ToolResult(
            action="run_bandit",
            success=True,
            output_path=str(output_path),
        )
    except Exception as exc:  # noqa: BLE001
        return ToolResult(
            action="run_bandit",
            success=False,
            errors=str(exc),
        )
