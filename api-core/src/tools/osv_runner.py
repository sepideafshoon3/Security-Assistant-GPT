from pathlib import Path
from src.core.models import ToolResult


def run_osv_scanner(repository_path: str, reports_dir: Path) -> ToolResult:
    """
    Placeholder for running osv-scanner.
    In a real setup, call the osv-scanner binary with subprocess.
    """
    reports_dir.mkdir(parents=True, exist_ok=True)
    output_path = reports_dir / "osv-scanner.json"

    # Fake output to keep skeleton harmless and self-contained.
    output_path.write_text('{"status": "not-implemented", "repo": "%s"}' % repository_path)

    return ToolResult(
        action="run_osv_scanner",
        success=True,
        output_path=str(output_path),
    )
