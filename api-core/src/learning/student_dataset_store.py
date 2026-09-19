from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass
class StudentLearningSample:
    ts: float
    event_type: str
    payload: dict[str, Any]
    feedback: dict[str, Any] | None = None


class StudentDatasetStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, sample: StudentLearningSample) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(sample), ensure_ascii=False) + "\n")
