"""Shrink command output the way rtk does, without the rtk binary.

rtk (Rust Token Killer) is a separate program. On Termux it is often
installed but cannot run, because the binary was built for another
platform, and a command that cannot start is a command that fails. This
module is the built-in fallback: it reads what a command printed and
returns a shorter version, keeping the lines that carry the result and
dropping the progress noise around them.

The rules are per tool family, because what matters depends on the tool. A
pip install ends in "Successfully installed", a test run ends in a summary
line, a build ends in "Finished". Output that matches no family goes
through the generic rules: progress lines go, repeated lines collapse, and
the rest stays.

Every compressed output starts with a note that says how much was dropped,
so the model never reads a summary as if it were the whole log.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Sequence

#: How many lines a compressed output may have.
MAX_LINES = 12

#: Progress lines, matched against the start of a line.
_PROGRESS = (
    re.compile(r"^\s*(downloading|collecting|resolving|fetching|unpacking|"
               r"extracting|setting up|processing triggers|reading package "
               r"lists|building wheel|replacing|creating|linking|updating|"
               r"installing|removing|adding|checking|verifying|waiting|"
               r"selecting|preparing|copying|moving)\b", re.IGNORECASE),
    re.compile(r"^\s*[\d.]+\s*[kKmM]?/[\d.]+\s*[kKmM]?"),
    re.compile(r"^\s*[\d.]+\s*%\s*$"),
    re.compile(r"^\s*\[[=>\s*\-.]*\]\s*$"),
)

#: Summary lines of the tool families we know.
_PIP_INSTALLED = re.compile(r"^Successfully installed\s+(.*)$")
_NPM_SUMMARY = re.compile(r"^(added|removed|changed|upgraded|audited|up to date)\b",
                          re.IGNORECASE)
_APT_SUMMARY = re.compile(r"^\d+ upgraded,")
_CARGO_COMPILE = re.compile(r"^\s*Compiling\s+(\S+)")
_CARGO_FINISHED = re.compile(r"^\s*Finished\b")
_PYTEST_SUMMARY = re.compile(r"=+ .*(passed|failed|error|no tests ran).* =+",
                             re.IGNORECASE)
_ESLINT_PROBLEM = re.compile(r"^\s*\S+\s+\d+:\d+\s+(error|warning)\b")
_ESLINT_SUMMARY = re.compile(r"^\s*\S?\s*\d+ problems?\b")
_GO_RESULT = re.compile(r"^(ok|FAIL|---|\?\?|panic:|#)")


def tool_name(argv: Sequence[str]) -> str:
    """The tool family of a command, as the rules are keyed."""
    if not argv:
        return ""
    parts = [str(part) for part in argv]
    first = parts[0]
    if Path(first).name.startswith("python"):
        if "-m" in parts:
            index = parts.index("-m")
            if index + 1 < len(parts):
                return parts[index + 1].lower()
        return "python"
    if first == "go" and len(parts) > 1:
        return f"go {parts[1]}"
    if first == "cargo" and len(parts) > 1:
        return f"cargo {parts[1]}"
    if first == "npm" and len(parts) > 1:
        return f"npm {parts[1]}"
    if first in ("pip", "pip3"):
        return "pip"
    return Path(first).name.lower()


def _keep_pip(lines: list[str]) -> list[str]:
    kept: list[str] = []
    for line in lines:
        match = _PIP_INSTALLED.match(line)
        if match:
            names = match.group(1).split()
            listed = ", ".join(names[:6]) + (", ..." if len(names) > 6 else "")
            kept.append(f"installed {len(names)} package(s): {listed}")
        elif line.startswith(("Successfully built", "ERROR", "error:")):
            kept.append(line)
    return kept


def _keep_npm(lines: list[str]) -> list[str]:
    return [line for line in lines
            if _NPM_SUMMARY.match(line.strip()) or "npm ERR!" in line]


def _keep_pkg(lines: list[str]) -> list[str]:
    kept = [line for line in lines
            if _APT_SUMMARY.match(line.strip()) or line.startswith(("E: ", "Err:"))]
    return kept


def _keep_cargo(lines: list[str]) -> list[str]:
    kept: list[str] = []
    crates: set[str] = set()
    for line in lines:
        match = _CARGO_COMPILE.match(line)
        if match:
            crates.add(match.group(1))
            continue
        if _CARGO_FINISHED.match(line) or line.startswith(("error", "warning:")):
            kept.append(line)
    if crates:
        kept.insert(0, f"compiled {len(crates)} crate(s)")
    return kept


def _keep_go(lines: list[str]) -> list[str]:
    return [line for line in lines if _GO_RESULT.match(line)]


def _keep_pytest(lines: list[str]) -> list[str]:
    return [line for line in lines
            if _PYTEST_SUMMARY.search(line)
            or line.startswith(("FAILED", "ERROR", "E   "))]


def _keep_jest(lines: list[str]) -> list[str]:
    return [line for line in lines
            if line.strip().startswith(("Tests:", "Test Suites:", "Snapshots:",
                                       "Time:"))]


def _keep_eslint(lines: list[str]) -> list[str]:
    return [line for line in lines
            if _ESLINT_PROBLEM.match(line) or _ESLINT_SUMMARY.match(line)]


def _keep_generic(lines: list[str]) -> list[str]:
    kept: list[str] = []
    for line in lines:
        text = line.rstrip()
        if not text.strip():
            continue
        if any(pattern.match(text) for pattern in _PROGRESS):
            continue
        if kept and kept[-1] == text:
            continue
        kept.append(text)
    return kept


#: Which rules to use for which tool.
_KEEPERS: dict[str, Callable[[list[str]], list[str]]] = {
    "pip": _keep_pip,
    "npm": _keep_npm,
    "npm install": _keep_npm,
    "npm ci": _keep_npm,
    "npm update": _keep_npm,
    "yarn": _keep_npm,
    "pnpm": _keep_npm,
    "apt": _keep_pkg,
    "apt-get": _keep_pkg,
    "apk": _keep_pkg,
    "pkg": _keep_pkg,
    "cargo build": _keep_cargo,
    "cargo test": _keep_cargo,
    "cargo check": _keep_cargo,
    "go test": _keep_go,
    "go build": _keep_go,
    "pytest": _keep_pytest,
    "python -m pytest": _keep_pytest,
    "jest": _keep_jest,
    "vitest": _keep_jest,
    "eslint": _keep_eslint,
}


def compress(output: str, argv: Sequence[str] = ()) -> str:
    """A shorter version of ``output``.

    The original text is returned when there is nothing worth cutting, so a
    short command output reaches the model exactly as it was printed.
    """
    if not output.strip():
        return output

    lines = output.splitlines()
    keeper = _KEEPERS.get(tool_name(argv), _keep_generic)
    kept = keeper(lines)
    if not kept:
        kept = _keep_generic(lines)
    if not kept:
        return output

    if len(kept) > MAX_LINES:
        head = kept[:MAX_LINES - 3]
        tail = kept[-3:]
        kept = head + [f"... ({len(kept) - len(head) - len(tail)} more lines)"] + tail

    body = "\n".join(kept)
    if body.strip() == output.strip():
        return output
    return f"[output compressed: {len(lines)} lines -> {len(kept)}]\n{body}"


__all__ = ["MAX_LINES", "compress", "tool_name"]
