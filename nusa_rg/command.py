"""Run a shell command and keep its output small enough for a prompt.

Two layers of compression, on purpose:

* **RTK** (Rust Token Killer, https://github.com/rtk-ai/rtk). When the ``rtk``
  binary is on ``PATH`` the command runs as ``rtk <command>``, and RTK rewrites
  the output -- a 47-line ``npm install`` becomes a four-line summary -- before
  it can reach the model.
* **A hard byte cap** applied here, because RTK is optional and a single noisy
  command should never be able to blow up the context window.

Nothing here ever goes through a shell: the command line is split with
``shlex`` and executed as an argument list (SEC-02). Shell operators are
rejected with an explanation instead of being silently reinterpreted, which
also keeps ``nusa-rg run`` predictable next to a real terminal.
"""

from __future__ import annotations

import re
import shlex
import shutil
import subprocess
import time
from dataclasses import dataclass, field

from . import compress as compressor
from . import sanitize

RTK_BINARY = "rtk"
DEFAULT_TIMEOUT = 120
DEFAULT_LIMIT = 40000
DEFAULT_PROMPT_BUDGET = 8000

#: Arguments matching this need no quoting when shown ("git status", "pytest -x").
_PLAIN_ARG = re.compile(r"[\w@%+=:,./-]+")


class CommandError(RuntimeError):
    """The command line is unusable, or the command failed to start."""


@dataclass
class CommandResult:
    """What a finished command produced."""

    argv: list[str]
    display: str
    exit_code: int
    output: str
    duration: float
    used_rtk: bool = False
    truncated: bool = False
    compressed: bool = False

    @property
    def ok(self) -> bool:
        return self.exit_code == 0

    def summary(self) -> str:
        """One grey line describing the run."""
        parts = [f"exit {self.exit_code}", f"{self.duration:.1f}s"]
        if self.used_rtk:
            parts.append("output filtered by rtk")
        elif self.compressed:
            parts.append("output compressed")
        if self.truncated:
            parts.append("output truncated")
        return " | ".join(parts)

    def for_prompt(self, max_chars: int = DEFAULT_PROMPT_BUDGET) -> str:
        """Render the run as a prompt-ready block.

        The cap is separate from the capture cap: everything the user saw stays
        in the terminal, while the model receives the head and tail with the
        middle elided.
        """
        body = self.output
        if len(body) > max_chars:
            keep = max_chars // 2
            body = (body[:keep] + "\n... [output trimmed for the prompt] ...\n"
                    + body[-keep:])
        status = "exit 0" if self.ok else f"exit {self.exit_code}"
        return f"$ {self.display}\n{body}\n[{status}]"


def rtk_path() -> str | None:
    """Location of the RTK binary, or ``None`` when it is not installed."""
    return shutil.which(RTK_BINARY)


def rtk_version(timeout: int = 5) -> str | None:
    """First line of ``rtk --version`` for the doctor screen."""
    path = rtk_path()
    if path is None:
        return None
    try:
        completed = subprocess.run(
            [path, "--version"], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    text = ((completed.stdout or "") + (completed.stderr or "")).strip()
    return text.splitlines()[0] if text else "unknown"


def rtk_usable(timeout: int = 5) -> bool:
    """True when the rtk binary is there and can actually start.

    rtk is often installed on Termux but built for another platform, and a
    binary that cannot start is worse than no binary at all: the command
    would fail before it ever ran. When it does not work, the built-in
    compressor takes its place.
    """
    path = rtk_path()
    if path is None:
        return False
    try:
        completed = subprocess.run(
            [path, "--version"], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


def split_command(text: str) -> list[str]:
    """Turn a typed command line into an argv list.

    Rejects shell operators up front, because the alternative -- passing them
    to a shell -- is exactly what this project promises never to do.
    """
    text = text.strip()
    if not text:
        raise CommandError("no command given")
    if sanitize.contains_shell_metacharacters(text):
        raise CommandError(
            "shell operators (one of ;|&`$><>) are not supported here. "
            "Run the plain command, or use a real terminal for pipelines."
        )
    try:
        argv = shlex.split(text)
    except ValueError as exc:
        raise CommandError(f"cannot parse the command line: {exc}") from exc
    if not argv:
        raise CommandError("no command given")
    return argv


def run(
    argv: list[str],
    *,
    timeout: int = DEFAULT_TIMEOUT,
    limit: int = DEFAULT_LIMIT,
    use_rtk: bool = True,
    cwd: str | None = None,
    compress: bool = True,
) -> CommandResult:
    """Execute ``argv``, optionally through RTK, and return its output.

    When rtk is missing or cannot start, the command runs on its own and the
    built-in compressor shortens its output, so a broken rtk never stops a
    command from working.
    """
    if not argv:
        raise CommandError("no command given")

    rtk = rtk_path() if use_rtk else None
    if rtk is not None and not rtk_usable():
        rtk = None
    executable = [rtk, *argv] if rtk else list(argv)
    display = _display(argv)

    started = time.monotonic()
    try:
        completed = subprocess.run(
            executable,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            cwd=cwd,
        )
    except subprocess.TimeoutExpired as exc:
        raise CommandError(
            f"the command did not finish within {timeout}s. "
            "Raise it with: nusa-rg config set command_timeout <seconds>"
        ) from exc
    except FileNotFoundError as exc:
        raise CommandError(f"command not found: {argv[0]}") from exc
    except OSError as exc:
        raise CommandError(f"cannot run '{argv[0]}': {exc}") from exc

    output, truncated = _combine(completed.stdout or "", completed.stderr or "", limit)
    compressed = False
    if rtk is None and compress:
        shorter = compressor.compress(output, argv)
        if shorter != output:
            output = shorter
            compressed = True
    return CommandResult(
        argv=list(argv),
        display=display,
        exit_code=completed.returncode,
        output=output,
        duration=time.monotonic() - started,
        used_rtk=rtk is not None,
        truncated=truncated,
        compressed=compressed,
    )


def _display(argv: list[str]) -> str:
    """Render a command for display, quoting only when it matters."""
    if all(_PLAIN_ARG.fullmatch(part) for part in argv):
        return " ".join(argv)
    return shlex.join(argv)


def _combine(stdout: str, stderr: str, limit: int) -> tuple[str, bool]:
    """Merge both streams under a byte budget, keeping head and tail."""
    sections = []
    if stdout.strip():
        sections.append(stdout.rstrip("\n"))
    if stderr.strip():
        sections.append("[stderr]\n" + stderr.rstrip("\n"))
    text = "\n".join(sections)

    if len(text.encode("utf-8", errors="replace")) <= limit:
        return text, False
    keep = max(1, limit // 2)
    head = _clip(text, keep, from_end=False)
    tail = _clip(text, keep, from_end=True)
    return f"{head}\n... [output truncated] ...\n{tail}", True


def _clip(text: str, size: int, *, from_end: bool) -> str:
    data = text.encode("utf-8", errors="replace")
    part = data[-size:] if from_end else data[:size]
    return part.decode("utf-8", errors="replace")


__all__ = [
    "CommandError", "CommandResult", "run", "rtk_path", "rtk_version",
    "split_command",
]
