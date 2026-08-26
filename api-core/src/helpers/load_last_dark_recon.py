from pathlib import Path
from glob import glob
import json
import os


def load_latest_dark_recon_summary(
    data_root: Path,
    prefix: str = "recon_",
) -> str:
    """
    آخرین dark_recon_summary.json را زیر data_root پیدا می‌کند.

    انتظار:
      data_root / recon_<domain>_<ts> / dark_recon_summary.json
    """
    pattern = str(data_root / f"{prefix}*" / "dark_recon_summary.json")
    files = glob(pattern)
    if not files:
        return ""

    latest = max(files, key=os.path.getmtime)
    try:
        with open(latest, "r", encoding="utf-8") as f:
            data = json.load(f)

        slim = {
            "domain": data.get("domain"),
            "ts": data.get("ts"),
            "counts": data.get("counts"),
            "focus_hosts": data.get("focus_hosts", []),
            "sample_httpx": data.get("samples", {}).get("httpx", [])[:40],
            "sample_nmap_fast": data.get("samples", {}).get("nmap_fast", [])[:80],
        }
        return json.dumps(slim, ensure_ascii=False, indent=2)
    except Exception:
        return ""
