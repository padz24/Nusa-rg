"""The privacy firewall: what may leave the device, and what may not.

Everything the assistant sends to a provider is project content the user
never agreed to publish. This module decides three things before a request
goes out:

* whether the text carries something that looks like a secret,
* whether the file it came from is local-only,
* and whether the request may proceed at all.

The rules are fail-closed. A secret that cannot be redacted stops the
request instead of being sent and hoping, and a file marked local-only never
reaches an external provider.
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Sequence

#: What a redacted secret looks like. The same mask the logs use.
MASK = "***MASKED***"

#: Patterns that look like credentials. Each entry is ``(kind, pattern)``.
SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("private-key", re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----")),
    ("openai-key", re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b")),
    ("groq-key", re.compile(r"\bgsk_[A-Za-z0-9]{20,}\b")),
    ("github-token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b")),
    ("github-pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    ("xai-key", re.compile(r"\bxai-[A-Za-z0-9]{16,}\b")),
    ("google-key", re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b")),
    ("aws-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("bearer-token", re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{12,}=*")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")),
    ("env-secret", re.compile(
        r"(?m)^\s*[A-Za-z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD)[A-Za-z0-9_]*"
        r"\s*=\s*[\"']?([^\s\"'#]{8,})")),
    ("assigned-secret", re.compile(
        r"(?i)\b(?:api[_-]?key|secret|token|password|passwd|private[_-]?key)\b"
        r"\s*[:=]\s*[\"']?([^\s\"',;]{8,})")),
)


@dataclass
class SecretMatch:
    """One thing that looks like a credential."""

    kind: str
    line: int
    excerpt: str


@dataclass
class ScreenResult:
    """The outcome of screening one piece of text."""

    ok: bool
    text: str
    matches: list[SecretMatch] = field(default_factory=list)
    reason: str = ""

    @property
    def redacted(self) -> bool:
        return bool(self.matches) and self.text != ""


class PrivacyPolicy:
    """What the configuration allows to leave the device."""

    def __init__(
        self,
        *,
        secret_detection: bool = True,
        redact_secrets: bool = True,
        local_only: Iterable[str] = (),
        confirm_sensitive_context: bool = True,
    ):
        self.secret_detection = bool(secret_detection)
        self.redact_secrets = bool(redact_secrets)
        self.local_only = tuple(str(item) for item in local_only or ())
        self.confirm_sensitive_context = bool(confirm_sensitive_context)

    @classmethod
    def from_config(cls, config) -> "PrivacyPolicy":
        """Read the policy from a :class:`~nusa_rg.config.Config`."""
        def flag(key: str, default: bool) -> bool:
            value = config.get(key, default)
            if isinstance(value, str):
                return value.strip().lower() in ("1", "true", "on", "yes")
            return bool(value)

        raw = config.get("privacy_local_only", []) or []
        if isinstance(raw, str):
            raw = [part.strip() for part in raw.split(",") if part.strip()]
        return cls(
            secret_detection=flag("privacy_secret_detection", True),
            redact_secrets=flag("privacy_redact_secrets", True),
            local_only=raw,
            confirm_sensitive_context=flag("privacy_confirm_sensitive_context", True),
        )

    # ------------------------------------------------------------- detection
    def scan(self, text: str) -> list[SecretMatch]:
        """Everything in ``text`` that looks like a credential."""
        if not text or not self.secret_detection:
            return []
        found: list[SecretMatch] = []
        seen: set[tuple[str, int]] = set()
        for kind, pattern in SECRET_PATTERNS:
            for match in pattern.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                key = (kind, line)
                if key in seen:
                    continue
                seen.add(key)
                found.append(SecretMatch(
                    kind=kind,
                    line=line,
                    excerpt=_excerpt(text, match),
                ))
        return found

    def redact(self, text: str) -> tuple[str, list[SecretMatch]]:
        """Replace every detected secret with the mask.

        Only the secret itself is replaced. A pattern that also matched the
        name of the setting keeps it, so ``API_KEY = "sk-..."`` becomes
        ``API_KEY = "***MASKED***"`` and not a broken line.
        """
        matches = self.scan(text)
        if not matches:
            return text, []
        cleaned = text
        for _kind, pattern in SECRET_PATTERNS:
            cleaned = _redact_pattern(pattern, cleaned)
        return cleaned, matches

    # ----------------------------------------------------------- local-only
    def is_local_only(self, path: str, root: str = "") -> bool:
        """True when a file may not be sent to an external provider."""
        if not self.local_only or not path:
            return False
        relative = path
        if root:
            try:
                relative = str(Path(path).resolve().relative_to(Path(root).resolve()))
            except (ValueError, OSError):
                relative = path
        relative = relative.replace("\\", "/").lstrip("./")
        name = relative.rsplit("/", 1)[-1]
        for pattern in self.local_only:
            cleaned = pattern.replace("\\", "/").lstrip("./")
            if fnmatch.fnmatch(relative, cleaned) or fnmatch.fnmatch(name, cleaned):
                return True
            if cleaned.endswith("/**") and relative.startswith(cleaned[:-3]):
                return True
        return False

    # -------------------------------------------------------------- the gate
    def screen(
        self,
        text: str,
        *,
        path: str = "",
        root: str = "",
        external: bool = True,
        confirm: Callable[[list[SecretMatch]], bool] | None = None,
    ) -> ScreenResult:
        """Decide whether ``text`` may be sent, and prepare it if it may.

        ``confirm`` is asked before a secret is passed on. Without it the
        answer is no: a non-interactive turn must not wait for a question it
        cannot ask.
        """
        if external and path and self.is_local_only(path, root):
            return ScreenResult(
                ok=False,
                text="",
                reason=(f"{path} is marked local-only; it is not sent to an "
                        "external provider"),
            )

        matches = self.scan(text)
        if not matches:
            return ScreenResult(ok=True, text=text)

        if self.redact_secrets:
            cleaned, _ = self.redact(text)
            if self.confirm_sensitive_context and confirm is not None:
                if not confirm(matches):
                    return ScreenResult(
                        ok=False,
                        text="",
                        matches=matches,
                        reason="the context holds a secret and was not confirmed",
                    )
            return ScreenResult(ok=True, text=cleaned, matches=matches)

        return ScreenResult(
            ok=False,
            text="",
            matches=matches,
            reason=("the context holds a secret and redaction is switched "
                    "off; refusing to send it"),
        )


def _redact_pattern(pattern: re.Pattern, text: str) -> str:
    """Replace the secret of every match, and nothing else.

    A pattern with a group holds the secret in its first group; the rest of
    the match is the setting around it and has to stay.
    """
    pieces: list[str] = []
    cursor = 0
    for match in pattern.finditer(text):
        start, end = match.span()
        if pattern.groups:
            group_start, group_end = match.span(1)
            if group_start >= 0:
                start, end = group_start, group_end
        if start < cursor:
            continue
        pieces.append(text[cursor:start])
        pieces.append(MASK)
        cursor = end
    pieces.append(text[cursor:])
    return "".join(pieces)


def _excerpt(text: str, match: re.Match) -> str:
    """A short, already-masked excerpt of a match."""
    start = max(0, match.start() - 8)
    end = min(len(text), match.end() + 8)
    fragment = text[start:end]
    fragment = re.sub(r"\s+", " ", fragment)
    return MASK if len(fragment) > 24 else fragment[:24]


__all__ = [
    "MASK", "SECRET_PATTERNS", "PrivacyPolicy", "ScreenResult", "SecretMatch",
]
