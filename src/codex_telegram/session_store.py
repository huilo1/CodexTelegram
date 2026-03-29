from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class ChatSession:
    chat_id: int
    cwd: str
    thread_id: str | None = None
    last_prompt: str | None = None


class SessionStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self, chat_id: int, default_cwd: Path) -> ChatSession:
        data = self._read_all()
        raw = data.get(str(chat_id))
        if raw is None:
            return ChatSession(chat_id=chat_id, cwd=str(default_cwd))
        return ChatSession(
            chat_id=chat_id,
            cwd=raw.get("cwd", str(default_cwd)),
            thread_id=raw.get("thread_id"),
            last_prompt=raw.get("last_prompt"),
        )

    def save(self, session: ChatSession) -> None:
        data = self._read_all()
        data[str(session.chat_id)] = asdict(session)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(data, ensure_ascii=True, indent=2) + "\n",
            encoding="utf-8",
        )

    def reset(self, chat_id: int, default_cwd: Path) -> ChatSession:
        session = ChatSession(chat_id=chat_id, cwd=str(default_cwd))
        self.save(session)
        return session

    def _read_all(self) -> dict[str, dict[str, object]]:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))
