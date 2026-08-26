from __future__ import annotations
import json
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass
class StudentLearningSample:
    ts: float
    event_type: str
    payload: Dict[str, Any]
    feedback: Optional[Dict[str, Any]] = None


class StudentDatasetStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, sample: StudentLearningSample) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(sample), ensure_ascii=False) + "\n")
