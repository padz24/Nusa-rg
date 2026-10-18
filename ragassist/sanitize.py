"""Input hardening for shell-adjacent characters and prompt injection.

Two distinct threats are addressed (SEC-02):

* **Command injection** -- user input must never reach a shell. The assistant
  never builds shell command lines from user data; the checks below are a
  defence-in-depth layer for the one place that does touch ``subprocess``
  (the llama.cpp runner) and for anything a future maintainer might route
  through a shell.
* **Prompt injection** -- retrieved files and user text are untrusted. We
  neutralise the control sequences used to override a system prompt (role
  markers, delimiter escapes) so a ``README`` containing ``<|im_start|>system``
  cannot hijack the composed request.
"""

from __future__ import annotations

import re
import unicodedata

# Characters with meaning to a POSIX shell. These are stripped from text that
# could ever be interpolated into a command line (AC-23).
SHELL_METACHARACTERS = ";|&`$><\n\r"

# Chat input keeps a few of these because they are legitimate in code, so the
# chat path uses a narrower, escaping policy instead of outright removal.
_SHELL_CHAIN_RE = re.compile(r"(?:`|\$\(|&&|\|\||;)\s*(?:rm|cat|sh|bash|curl|wget|chmod|chown)\b")

# Chat-control sequences used by most model templates to forge a new role.
_ROLE_MARKER_RE = re.compile(
    r"<\|(?:im_start|im_end|endoftext|start_header_id|eot_id|system|user|assistant)\|>",
    re.IGNORECASE,
)
# Delimiters used by our own prompt composer; if untrusted text contains them it
# could forge the end of the context block. Both the opening and closing forms
# must be matched, since the composer emits "<|/RAG_CONTEXT|>".
_DELIMITER_RE = re.compile(
    r"<\|/?RAG_(?:CONTEXT|COMMAND|USER|END)\|>", re.IGNORECASE
)

# Instruction-override phrasing common to prompt-injection payloads.
_INJECTION_RE = re.compile(
    r"(?:ignore|disregard|forget)\s+(?:all\s+)?(?:previous|prior|above|preceding)\s+"
    r"(?:instruction|prompt|rule|direction)",
    re.IGNORECASE,
)

_CONTROL_CHARS = dict.fromkeys(
    code for code in range(32) if code not in (9, 10)
)


def contains_shell_metacharacters(text: str) -> bool:
    """True when ``text`` holds a character that a shell would interpret."""
    return any(ch in SHELL_METACHARACTERS for ch in text)


def sanitize_shell_arg(value: str) -> str:
    """Return ``value`` with shell metacharacters removed.

    Used for any argument destined for ``subprocess`` without ``shell=True``.
    """
    cleaned = unicodedata.normalize("NFKC", value)
    cleaned = "".join(ch for ch in cleaned if ch not in SHELL_METACHARACTERS)
    return cleaned.strip()


def sanitize_command_line(text: str) -> str:
    """Neutralise chained-shell payloads inside user chat input (AC-23).

    The result stays readable for the LLM -- we blank out the operator rather
    than dropping the whole line, so ``rm -rf`` in a pasted snippet is still
    explained rather than silently dropped.
    """
    cleaned = unicodedata.normalize("NFKC", text)
    cleaned = _SHELL_CHAIN_RE.sub("[blocked-shell-chain]", cleaned)
    # Remove any leftover backticks so no unpaired command-substitution
    # delimiter survives into the prompt.
    cleaned = cleaned.replace("`", "").replace("\x00", "")
    return cleaned


def sanitize_untrusted(text: str) -> str:
    """Harden text retrieved from disk before it enters a prompt.

    Applies to file chunks and project snippets, which an attacker could have
    written on purpose.
    """
    cleaned = unicodedata.normalize("NFKC", text)
    cleaned = cleaned.translate(_CONTROL_CHARS)
    cleaned = _ROLE_MARKER_RE.sub("[role-marker]", cleaned)
    cleaned = _DELIMITER_RE.sub("[delimiter]", cleaned)
    cleaned = _INJECTION_RE.sub("[override-attempt]", cleaned)
    return cleaned


def is_suspicious(text: str) -> bool:
    """True when the text looks like an injection attempt (for audit logs)."""
    return bool(
        _ROLE_MARKER_RE.search(text)
        or _DELIMITER_RE.search(text)
        or _INJECTION_RE.search(text)
        or _SHELL_CHAIN_RE.search(text)
    )