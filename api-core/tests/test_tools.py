from pathlib import Path
from src.tools.osv_runner import run_osv_scanner


def test_osv_runner_creates_output(tmp_path: Path):
    result = run_osv_scanner("/lab/repos/demo", tmp_path)
    assert result.success is True
    assert result.output_path is not None
    assert Path(result.output_path).exists()
