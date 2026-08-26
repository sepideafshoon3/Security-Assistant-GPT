from pathlib import Path
from typing import Optional


class FileStore:
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def save_text(self, key: str, content: str) -> Path:
        path = self.base_dir / f"{key}.txt"
        path.write_text(content)
        return path

    def load_text(self, key: str) -> Optional[str]:
        path = self.base_dir / f"{key}.txt"
        if not path.exists():
            return None
        return path.read_text()
