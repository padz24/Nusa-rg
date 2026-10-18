"""Logging with mandatory secret masking and size-based rotation.

Implements SEC-03, SEC-06, SEC-07, SEC-08:

* every record is ``timestamp | level | event | sha256(query)`` -- never the
  query text, never an API key, never a code snippet (SEC-06, AC-32);
* a final mask pass runs on the formatted message so a stray ``sk-...`` token
  is replaced with ``***MASKED***`` even if a caller passes one in;
* the log file is chmod 600 (SEC-07, AC-33);
* rotation happens at 10 MB keeping 5 archives, so ``app.log.1`` appears the
  moment the cap is crossed (SEC-08, AC-34).
"""

from __future__ import annotations

import hashlib
import logging
import logging.handlers
import os
import re
import threading
from typing import Any

from . import paths

MAX_BYTES = 10 * 1024 * 1024
BACKUP_COUNT = 5
MASK = "***MASKED***"

# Patterns that must never survive into a log file (SEC-03).
_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}"),          # OpenAI-style
    re.compile(r"\bgsk_[A-Za-z0-9_\-]{8,}"),         # Groq
    re.compile(r"\bxai-[A-Za-z0-9_\-]{8,}"),         # xAI
    re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{8,}", re.IGNORECASE),
    re.compile(r"(?i)\b(api[_-]?key|authorization|password|secret|token)"
               r"\b\s*[:=]\s*\S+"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
)

_configured = False
_configured_root: str | None = None
_lock = threading.Lock()

LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARN": logging.WARNING,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
}

#: SEC-06 permits metadata only. Any keyword not on this list is logged as
#: "<redacted>" rather than its value, so a caller cannot accidentally write a
#: query, a snippet, or a credential into the log by passing an extra kwarg.
ALLOWED_FIELDS = frozenset({
    "context", "chunks", "changed", "duration", "files", "files_indexed",
    "files_unchanged", "hits", "key", "keys", "llm_ok", "model", "path",
    "provider", "reason", "root", "status",
})

MAX_FIELD_CHARS = 120


def fingerprint(value: str | bytes | None) -> str:
    """Stable SHA-256 of a query, used instead of the query itself (SEC-06).

    Lets support correlate a report with a session without retaining the text.
    """
    if value is None:
        return "-"
    if isinstance(value, str):
        value = value.encode("utf-8", errors="replace")
    return hashlib.sha256(value).hexdigest()[:16]


def mask(text: str) -> str:
    """Replace anything secret-shaped with ``***MASKED***``."""
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(MASK, text)
    return text


class _RedactingFormatter(logging.Formatter):
    """Last line of defence: strip secrets from whatever we are about to write."""

    def format(self, record: logging.LogRecord) -> str:
        return mask(super().format(record))


def configure(verbose: bool = False, force: bool = False) -> logging.Logger:
    """Install the rotating file handler and the stderr console handler.

    Re-runs automatically when the state directory changes (e.g. a new
    ``NUSA_RG_HOME``) so handlers never point at a stale location.
    """
    global _configured, _configured_root
    root = str(paths.base_dir())
    with _lock:
        if _configured and not force and _configured_root == root:
            return logging.getLogger("nusa_rg")

        paths.ensure_dirs()
        logger = logging.getLogger("nusa_rg")
        logger.setLevel(logging.DEBUG if verbose else logging.INFO)
        logger.propagate = False

        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()

        file_handler = logging.handlers.RotatingFileHandler(
            paths.app_log_path(),
            maxBytes=MAX_BYTES,
            backupCount=BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setFormatter(
            _RedactingFormatter("%(asctime)s | %(levelname)-5s | %(name)s | %(message)s")
        )
        logger.addHandler(file_handler)

        console = logging.StreamHandler()
        console.setLevel(logging.DEBUG if verbose else logging.WARNING)
        console.setFormatter(_RedactingFormatter("%(levelname)s: %(message)s"))
        logger.addHandler(console)

        # SEC-07: 0600 on the active file and on any rotated archives.
        paths.restrict(paths.app_log_path())
        paths.restrict(paths.audit_log_path())

        _configured = True
        _configured_root = root
        return logger


def get_logger(name: str | None = None) -> logging.Logger:
    # Reconfigure when unconfigured *or* when the state directory has moved.
    if not _configured or _configured_root != str(paths.base_dir()):
        configure()
    return logging.getLogger(f"nusa_rg.{name}" if name else "nusa_rg")


def _render_field(name: str, value: Any) -> str:
    """Render one metadata field under the SEC-06 allowlist rules.

    A field outside :data:`ALLOWED_FIELDS` is reduced to ``***MASKED***`` when
    its value looks credential-shaped (satisfying AC-24) and to ``<redacted>``
    otherwise, so snippets and query text never land in the log.
    """
    raw = str(value)
    if name not in ALLOWED_FIELDS:
        return f"{name}={MASK}" if mask(raw) != raw else f"{name}=<redacted>"
    text = mask(raw)
    # Keep one field on one line: newlines would forge extra log records.
    text = text.replace("\r", " ").replace("\n", " ")
    if len(text) > MAX_FIELD_CHARS:
        text = text[: MAX_FIELD_CHARS - 3] + "..."
    return f"{name}={text}"


def log_event(event: str, level: str = "INFO", query: str | None = None,
              **fields: Any) -> None:
    """Record a metadata-only event.

    Callers pass an event name plus optional keyword details. Query text is
    accepted only so it can be reduced to a hash -- the text itself is dropped.
    Fields outside :data:`ALLOWED_FIELDS` are redacted.
    """
    logger = get_logger()
    parts = [f"event={event}", f"query_hash={fingerprint(query)}"]
    parts += [_render_field(k, v) for k, v in sorted(fields.items())]
    logger.log(LEVELS.get(level.upper(), logging.INFO), " ".join(parts))


def audit(event: str, result: str = "SUCCESS", detail: str = "") -> None:
    """Append an audit entry for a state-changing operation (SEC-09, AC-35).

    Kept in a dedicated file so the trail stays readable independently of the
    operational log, while sharing the same masking rules and ISO-8601 stamps.
    """
    paths.ensure_dirs()
    logger = logging.getLogger("nusa_rg.audit")
    target = str(paths.audit_log_path())
    current = {
        os.path.abspath(handler.baseFilename)
        for handler in logger.handlers
        if isinstance(handler, logging.FileHandler)
    }
    # Re-point the handler whenever the state directory moves, otherwise entries
    # would be written to a stale (possibly deleted) path.
    if current != {target}:
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()
        handler = logging.FileHandler(target, encoding="utf-8")
        handler.setFormatter(
            _RedactingFormatter("%(asctime)s | %(levelname)-5s | %(message)s")
        )
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
        paths.restrict(paths.audit_log_path())

    entry = (f"event={event} result={result} "
             f"detail={mask(str(detail)).replace(chr(10), ' ').replace(chr(13), ' ')[:MAX_FIELD_CHARS] if detail else '-'}")
    logger.log(LEVELS.get(result.upper(), logging.INFO), entry)