"""Named chat sessions that survive across CLI invocations.

A session is a small JSON document under ``~/.nusa-rg/sessions`` containing the
visible user/assistant turns, the response style, and the project it was
started in. Retrieved snippets are deliberately *not* stored: they are rebuilt
from the index on every turn, so resuming an old session cannot replay stale
code.

The store is intentionally boring: one file per id, atomic replacement, 0600
permissions, and ids restricted to a filename-safe alphabet. Conversation text
is never written to the application log.
"""

from __future__ import annotations

import json
import os
import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import paths

#: Ids double as filenames, so keep them short and free of separators.
SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

#: Prompt history is capped by whole turns; the file itself keeps everything.
DEFAULT_HISTORY_TURNS = 10
MAX_HISTORY_CHARS = 24_000

FORMAT_VERSION = 1


class SessionError(ValueError):
    """Invalid id, missing session, or a malformed session document."""


def validate_id(session_id: str) -> str:
    """Return ``session_id`` stripped, or raise a user-facing error."""
    value = (session_id or "").strip()
    if not value:
        raise SessionError("session id cannot be empty")
    if not SESSION_ID_RE.match(value):
        raise SessionError(
            "session id must be 1-64 characters: letters, digits, '.', '_' or "
            "'-', and must start with a letter or digit"
        )
    return value


def new_id() -> str:
    """Generate a sortable, collision-resistant id without user input."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"{stamp}-{secrets.token_hex(2)}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _normalize_messages(raw: object) -> list[dict[str, str]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise SessionError("session messages must be a list")
    messages: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise SessionError("every session message must be an object")
        role = item.get("role")
        content = item.get("content")
        if role not in ("user", "assistant") or not isinstance(content, str):
            raise SessionError(
                "every session message needs role 'user'/'assistant' and text content"
            )
        messages.append({"role": role, "content": content})
    return messages


@dataclass
class Session:
    """One saved conversation and the settings that travel with it."""

    id: str
    messages: list[dict[str, str]] = field(default_factory=list)
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    style: str = ""
    project: str = ""
    path: Path | None = None

    @property
    def turns(self) -> int:
        """Number of user messages, i.e. completed questions."""
        return sum(1 for item in self.messages if item.get("role") == "user")

    @property
    def title(self) -> str:
        """First question, collapsed to one line and clipped for lists."""
        for item in self.messages:
            if item.get("role") == "user":
                text = " ".join(item["content"].split())
                return text[:80] + ("..." if len(text) > 80 else "")
        return "(empty)"

    def add_turn(self, question: str, answer: str) -> None:
        self.messages.append({"role": "user", "content": question})
        self.messages.append({"role": "assistant", "content": answer})
        self.updated_at = _now()

    def clear(self) -> None:
        self.messages.clear()
        self.updated_at = _now()

    def set_style(self, style: str) -> None:
        self.style = style or ""
        self.updated_at = _now()

    def history(self, *, max_turns: int = DEFAULT_HISTORY_TURNS,
                max_chars: int = MAX_HISTORY_CHARS) -> list[dict[str, str]]:
        """Return recent, whole turns ready for the chat-completions payload.

        Only user/assistant pairs are considered; a trailing incomplete pair is
        ignored. The newest turn is always kept even when it alone exceeds the
        character budget, because dropping it would silently forget the most
        relevant context.
        """
        if max_turns <= 0:
            return []

        pairs: list[list[dict[str, str]]] = []
        index = 0
        while index + 1 < len(self.messages):
            first, second = self.messages[index], self.messages[index + 1]
            if first.get("role") == "user" and second.get("role") == "assistant":
                pairs.append([first, second])
                index += 2
            else:
                index += 1

        selected = pairs[-max_turns:]
        while len(selected) > 1:
            total = sum(len(item["content"]) for pair in selected for item in pair)
            if total <= max_chars:
                break
            selected.pop(0)

        return [
            {"role": item["role"], "content": item["content"]}
            for pair in selected
            for item in pair
        ]

    def to_dict(self) -> dict:
        return {
            "version": FORMAT_VERSION,
            "id": self.id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "style": self.style,
            "project": self.project,
            "messages": [dict(item) for item in self.messages],
        }

    @classmethod
    def from_dict(cls, data: object, *, path: Path | None = None) -> "Session":
        if not isinstance(data, dict):
            raise SessionError("session file must contain a JSON object")
        session_id = data.get("id")
        if not isinstance(session_id, str) or not session_id:
            raise SessionError("session file is missing its id")
        created = data.get("created_at")
        updated = data.get("updated_at")
        style = data.get("style")
        project = data.get("project")
        return cls(
            id=validate_id(session_id),
            messages=_normalize_messages(data.get("messages")),
            created_at=created if isinstance(created, str) and created else _now(),
            updated_at=updated if isinstance(updated, str) and updated else _now(),
            style=style if isinstance(style, str) else "",
            project=project if isinstance(project, str) else "",
            path=path,
        )


class SessionStore:
    """Load, create, list, and delete sessions in one directory."""

    def __init__(self, directory: Path | None = None):
        self.directory = Path(directory) if directory is not None else paths.sessions_dir()

    # ---------------------------------------------------------------- paths
    def _ensure_directory(self) -> None:
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise SessionError(
                f"cannot create session directory {self.directory}: {exc}"
            ) from exc
        paths.restrict(self.directory, 0o700)

    def path(self, session_id: str) -> Path:
        return self.directory / f"{validate_id(session_id)}.json"

    def exists(self, session_id: str) -> bool:
        return self.path(session_id).is_file()

    # ---------------------------------------------------------------- write
    def _fresh_id(self) -> str:
        for _ in range(20):
            candidate = new_id()
            if not self.exists(candidate):
                return candidate
        raise SessionError("could not allocate a free session id")

    def create(self, session_id: str | None = None, *, project: str = "",
               style: str = "") -> Session:
        sid = validate_id(session_id) if session_id else self._fresh_id()
        if self.exists(sid):
            raise SessionError(f"session '{sid}' already exists")
        session = Session(id=sid, project=project, style=style)
        self.save(session)
        return session

    def open(self, session_id: str, *, project: str = "",
             style: str = "") -> Session:
        """Resume ``session_id``, creating it when it does not exist yet."""
        sid = validate_id(session_id)
        if self.exists(sid):
            return self.load(sid)
        return self.create(sid, project=project, style=style)

    def save(self, session: Session) -> None:
        self._ensure_directory()
        target = self.path(session.id)
        temporary = target.with_name(target.name + ".tmp")
        payload = json.dumps(session.to_dict(), ensure_ascii=False, indent=2)
        try:
            temporary.write_text(payload + "\n", encoding="utf-8")
            paths.restrict(temporary, 0o600)
            os.replace(temporary, target)
            paths.restrict(target, 0o600)
        except OSError as exc:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise SessionError(f"cannot write session '{session.id}': {exc}") from exc
        session.path = target
        session.updated_at = session.updated_at or _now()

    # ----------------------------------------------------------------- read
    def load(self, session_id: str) -> Session:
        sid = validate_id(session_id)
        target = self.path(sid)
        try:
            raw = target.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise SessionError(f"session '{sid}' not found") from exc
        except OSError as exc:
            raise SessionError(f"cannot read session '{sid}': {exc}") from exc
        try:
            data = json.loads(raw)
        except ValueError as exc:
            raise SessionError(f"session '{sid}' is not valid JSON") from exc
        session = Session.from_dict(data, path=target)
        if session.id != sid:
            raise SessionError(
                f"session file '{target.name}' contains id '{session.id}'"
            )
        return session

    def list(self) -> list[Session]:
        """Return sessions newest first, ignoring unreadable documents."""
        if not self.directory.is_dir():
            return []
        sessions: list[Session] = []
        for target in self.directory.glob("*.json"):
            try:
                sessions.append(self.load(target.stem))
            except SessionError:
                continue
        return sorted(sessions, key=lambda item: (item.updated_at, item.id),
                      reverse=True)

    # --------------------------------------------------------------- delete
    def delete(self, session_id: str) -> None:
        sid = validate_id(session_id)
        try:
            self.path(sid).unlink()
        except FileNotFoundError as exc:
            raise SessionError(f"session '{sid}' not found") from exc
        except OSError as exc:
            raise SessionError(f"cannot delete session '{sid}': {exc}") from exc


__all__ = [
    "DEFAULT_HISTORY_TURNS",
    "MAX_HISTORY_CHARS",
    "Session",
    "SessionError",
    "SessionStore",
    "new_id",
    "validate_id",
]
