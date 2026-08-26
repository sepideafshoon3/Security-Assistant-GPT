from __future__ import annotations

from pathlib import Path
from typing import List, Dict
import json


class ChatMemory:
    """
    Very simple file-based chat memory.

    - One JSONL file per conversation_id.
    - Each line: {"role": "user"|"assistant", "content": "..."}
    - We only store user/assistant messages (no system prompts).
    """

    def __init__(self, base_dir: Path, max_messages: int = 50):
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.max_messages = max_messages

    def _conv_path(self, conversation_id: str) -> Path:
        return self.base_dir / f"{conversation_id}.jsonl"

    def load_history(self, conversation_id: str) -> List[Dict[str, str]]:
        path = self._conv_path(conversation_id)
        if not path.exists():
            return []
        messages: List[Dict[str, str]] = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if "role" in obj and "content" in obj:
                        messages.append(
                            {"role": str(obj["role"]), "content": str(obj["content"])}
                        )
                except json.JSONDecodeError:
                    continue
        return messages

    def save_history(self, conversation_id: str, messages: List[Dict[str, str]]) -> None:
        """
        Overwrites the conversation file with the last max_messages messages.
        """
        trimmed = messages[-self.max_messages :]
        path = self._conv_path(conversation_id)
        with path.open("w", encoding="utf-8") as f:
            for m in trimmed:
                f.write(json.dumps(m, ensure_ascii=False) + "\n")

    def append_turn(
        self,
        conversation_id: str,
        user_msg: Dict[str, str],
        assistant_msg: Dict[str, str],
    ) -> List[Dict[str, str]]:
        """
        Load history, append user+assistant, save, and return new history.
        """
        history = self.load_history(conversation_id)
        if user_msg:
            history.append({"role": "user", "content": user_msg["content"]})
        if assistant_msg:
            history.append({"role": "assistant", "content": assistant_msg["content"]})
        self.save_history(conversation_id, history)
        return history
