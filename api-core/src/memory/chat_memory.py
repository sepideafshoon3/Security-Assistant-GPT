from __future__ import annotations

import json
from pathlib import Path


class ChatMemory:
    """
    Very simple file-based chat memory, scoped per user.

    - One JSONL file per (user_id, conversation_id): base_dir/{user_id}/{conversation_id}.jsonl
    - Each line: {"role": "user"|"assistant", "content": "..."}
    - We only store user/assistant messages (no system prompts).
    """

    def __init__(self, base_dir: Path, max_messages: int = 50):
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.max_messages = max_messages

    def _conv_path(self, user_id: str, conversation_id: str) -> Path:
        user_dir = self.base_dir / user_id
        user_dir.mkdir(parents=True, exist_ok=True)
        return user_dir / f"{conversation_id}.jsonl"

    def conversation_exists(self, user_id: str, conversation_id: str) -> bool:
        return self._conv_path(user_id, conversation_id).exists()

    def load_history(self, user_id: str, conversation_id: str) -> list[dict[str, str]]:
        path = self._conv_path(user_id, conversation_id)
        if not path.exists():
            return []
        messages: list[dict[str, str]] = []
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

    def save_history(
        self, user_id: str, conversation_id: str, messages: list[dict[str, str]]
    ) -> None:
        """
        Overwrites the conversation file with the last max_messages messages.
        """
        trimmed = messages[-self.max_messages :]
        path = self._conv_path(user_id, conversation_id)
        with path.open("w", encoding="utf-8") as f:
            for m in trimmed:
                f.write(json.dumps(m, ensure_ascii=False) + "\n")

    def append_turn(
        self,
        user_id: str,
        conversation_id: str,
        user_msg: dict[str, str],
        assistant_msg: dict[str, str],
    ) -> list[dict[str, str]]:
        """
        Load history, append user+assistant, save, and return new history.
        """
        history = self.load_history(user_id, conversation_id)
        if user_msg:
            history.append({"role": "user", "content": user_msg["content"]})
        if assistant_msg:
            history.append({"role": "assistant", "content": assistant_msg["content"]})
        self.save_history(user_id, conversation_id, history)
        return history
