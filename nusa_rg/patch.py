"""Ghost Patch: a change that is read and tested before it touches anything.

A patch is a unified diff that lives in a staging copy of the project. The
user can read it, run the tests against it, and only then apply it to the
real tree. Nothing in this module writes to the project without an explicit
apply.

The diff comes from a model, so every path in it is checked before it is
used: it must be relative, it must stay inside the project, and it must not
reach out through a symbolic link. The hunks are also checked against the
file they claim to change, so a patch that no longer applies is refused
instead of writing something half-right.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from . import paths

#: Directories never copied into the staging tree.
SKIP_DIRS = frozenset({
    ".git", "node_modules", "__pycache__", ".venv", "venv", "build", "dist",
    ".mypy_cache", ".pytest_cache", ".nusa-rg",
})

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


class PatchError(RuntimeError):
    """A patch is unusable, unsafe, or no longer applies."""


@dataclass
class Hunk:
    """One block of a unified diff."""

    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: list[str] = field(default_factory=list)


@dataclass
class FilePatch:
    """The change to one file."""

    path: str
    hunks: list[Hunk] = field(default_factory=list)

    @property
    def added(self) -> int:
        return sum(1 for hunk in self.hunks for line in hunk.lines
                   if line.startswith("+"))

    @property
    def removed(self) -> int:
        return sum(1 for hunk in self.hunks for line in hunk.lines
                   if line.startswith("-"))


@dataclass
class Patch:
    """A staged change, ready to be reviewed."""

    id: str
    project: str
    request: str
    diff: str
    files: list[FilePatch] = field(default_factory=list)
    created_at: float = 0.0
    status: str = "staged"
    root: str = ""

    @property
    def added(self) -> int:
        return sum(item.added for item in self.files)

    @property
    def removed(self) -> int:
        return sum(item.removed for item in self.files)

    def summary(self) -> str:
        return (f"{self.id} · {len(self.files)} file(s) · "
                f"+{self.added} -{self.removed} · {self.status}")


def extract_diff(text: str) -> str:
    """Pull the unified diff out of a model answer.

    The model is asked for a diff, but it may wrap it in a code fence or add a
    sentence around it. Everything that is not a diff line is dropped.
    """
    wanted = ("--- ", "+++ ", "@@", "diff --git", "index ", "new file",
              "deleted file", "similarity index", "rename ", "---", "+++")
    lines: list[str] = []
    for line in (text or "").splitlines():
        if line.startswith("```"):
            continue
        if line.startswith(("---", "+++", "@@", "diff ", "index ", "new file",
                            "deleted file", "similarity index", "rename ")):
            lines.append(line)
        elif lines and (line.startswith(("+", "-", " ")) or line == ""):
            lines.append(line)
    return "\n".join(lines).strip() + "\n" if lines else ""


# ------------------------------------------------------------------- parsing

def _safe_path(raw: str) -> str:
    """Check one path from a diff and return it in project form."""
    path = (raw or "").strip()
    if path.startswith(("a/", "b/")):
        path = path[2:]
    if path.startswith("/") or re.match(r"^[A-Za-z]:[\\/]", path):
        raise PatchError(f"absolute path in the patch: {raw}")
    parts = Path(path).parts
    if not parts or any(part == ".." for part in parts):
        raise PatchError(f"path outside the project: {raw}")
    if path in ("", "/dev/null"):
        raise PatchError("the patch names no file")
    return path.replace("\\", "/")


def parse_diff(text: str) -> list[FilePatch]:
    """Read a unified diff into file patches.

    Raises :class:`PatchError` when the diff is malformed or names a path
    that leaves the project.
    """
    patches: list[FilePatch] = []
    current: FilePatch | None = None
    hunk: Hunk | None = None
    for line in (text or "").splitlines():
        if line.startswith("--- "):
            hunk = None
            continue
        if line.startswith("+++ "):
            if current is not None:
                patches.append(current)
            current = FilePatch(path=_safe_path(line[4:]))
            hunk = None
            continue
        if line.startswith("@@"):
            match = _HUNK.match(line)
            if not match:
                raise PatchError(f"cannot read the hunk header: {line}")
            if current is None:
                raise PatchError("a hunk without a file header")
            hunk = Hunk(
                old_start=int(match.group(1)),
                old_count=int(match.group(2) or 1),
                new_start=int(match.group(3)),
                new_count=int(match.group(4) or 1),
            )
            current.hunks.append(hunk)
            continue
        if hunk is None:
            continue
        if line.startswith(("+", "-", " ")):
            hunk.lines.append(line)
        elif line.startswith("\\"):
            continue
        elif line == "":
            hunk.lines.append(" ")
        else:
            hunk = None
    if current is not None:
        patches.append(current)
    if not patches:
        raise PatchError("the diff has no file to change")
    return patches


def apply_to_file(original: str, patch: FilePatch) -> str:
    """Apply one file patch to its text, or refuse."""
    lines = original.splitlines(keepends=True)
    result: list[str] = []
    cursor = 0
    for hunk in patch.hunks:
        start = max(0, hunk.old_start - 1)
        if start < cursor:
            raise PatchError(f"the hunks of {patch.path} overlap")
        result.extend(lines[cursor:start])
        cursor = start
        for entry in hunk.lines:
            marker, body = entry[0], entry[1:]
            if marker == " ":
                if cursor >= len(lines) or lines[cursor].rstrip("\n") != body:
                    raise PatchError(
                        f"{patch.path} no longer matches the patch")
                result.append(lines[cursor])
                cursor += 1
            elif marker == "-":
                if cursor >= len(lines) or lines[cursor].rstrip("\n") != body:
                    raise PatchError(
                        f"{patch.path} no longer matches the patch")
                cursor += 1
            elif marker == "+":
                result.append(body + "\n")
    result.extend(lines[cursor:])
    return "".join(result)


def apply_to_tree(patches: list[FilePatch], root: Path,
                  target: Path) -> list[str]:
    """Apply every file patch inside ``target``; return the paths written."""
    written: list[str] = []
    for patch in patches:
        source = root / patch.path
        destination = target / patch.path
        # A symbolic link in the path would let the patch write outside.
        if any((root / part).is_symlink() for part in Path(patch.path).parents
               if part != Path(".")):
            raise PatchError(f"{patch.path} goes through a symbolic link")
        original = ""
        if source.is_file():
            original = source.read_text(encoding="utf-8", errors="replace")
        elif not source.exists() and patch.added == 0:
            raise PatchError(f"{patch.path} does not exist")
        updated = apply_to_file(original, patch)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(updated, encoding="utf-8")
        written.append(patch.path)
    return written


# -------------------------------------------------------------------- storing

def _ignore(directory: str, names: list[str]) -> set[str]:
    return {name for name in names if name in SKIP_DIRS}


def copy_tree(root: Path, target: Path) -> None:
    """Copy the project into the staging area, minus the heavy parts."""
    target.mkdir(parents=True, exist_ok=True)
    for entry in root.iterdir():
        if entry.name in SKIP_DIRS:
            continue
        destination = target / entry.name
        if entry.is_symlink():
            continue
        if entry.is_dir():
            shutil.copytree(entry, destination, ignore=_ignore,
                            symlinks=False, dirs_exist_ok=True)
        elif entry.is_file() and entry.stat().st_size <= 2 * 1024 * 1024:
            shutil.copy2(entry, destination)


class PatchStore:
    """Where staged patches live."""

    def __init__(self, base: Path | None = None):
        self.base = Path(base) if base else paths.base_dir() / "patches"

    def project_dir(self, project: str) -> Path:
        return self.base / project

    def patch_dir(self, project: str, patch_id: str) -> Path:
        return self.project_dir(project) / patch_id

    def create(self, project: str, request: str, diff: str,
               patches: list[FilePatch], root: str = "") -> Patch:
        """Stage a patch: the diff, a copy of the tree, and the result."""
        patch_id = uuid.uuid4().hex[:8]
        directory = self.patch_dir(project, patch_id)
        if directory.exists():
            raise PatchError(f"patch {patch_id} already exists")
        directory.mkdir(parents=True)
        paths.restrict(directory, 0o700)
        tree = directory / "tree"
        source_root = Path(root) if root else Path(project)
        if source_root.is_dir():
            copy_tree(source_root, tree)
            apply_to_tree(patches, source_root, tree)
        patch = Patch(
            id=patch_id, project=project, request=request, diff=diff,
            files=patches, created_at=time.time(), root=str(source_root),
        )
        (directory / "patch.diff").write_text(diff, encoding="utf-8")
        (directory / "patch.json").write_text(
            json.dumps({
                "id": patch.id, "project": patch.project, "request": patch.request,
                "root": patch.root,
                "created_at": patch.created_at, "status": patch.status,
                "files": [{"path": item.path,
                           "added": item.added, "removed": item.removed}
                          for item in patch.files],
            }, indent=2), encoding="utf-8")
        paths.restrict(directory / "patch.diff")
        paths.restrict(directory / "patch.json")
        return patch

    def load(self, project: str, patch_id: str) -> Patch:
        directory = self.patch_dir(project, patch_id)
        meta = directory / "patch.json"
        if not meta.is_file():
            raise PatchError(f"no patch {patch_id} for this project")
        data = json.loads(meta.read_text(encoding="utf-8"))
        diff = (directory / "patch.diff").read_text(encoding="utf-8")
        return Patch(
            id=data["id"], project=data["project"], request=data["request"],
            diff=diff, files=parse_diff(diff), created_at=data["created_at"],
            status=data.get("status", "staged"), root=data.get("root", ""),
        )

    def list(self, project: str) -> list[Patch]:
        """Every patch of one project, newest first."""
        directory = self.project_dir(project)
        if not directory.is_dir():
            return []
        found = []
        for child in sorted(directory.iterdir(), reverse=True):
            if not (child / "patch.json").is_file():
                continue
            try:
                found.append(self.load(project, child.name))
            except (PatchError, ValueError, OSError):
                continue
        return found

    def tree(self, project: str, patch_id: str) -> Path:
        return self.patch_dir(project, patch_id) / "tree"

    def set_status(self, project: str, patch_id: str, status: str) -> None:
        meta = self.patch_dir(project, patch_id) / "patch.json"
        data = json.loads(meta.read_text(encoding="utf-8"))
        data["status"] = status
        meta.write_text(json.dumps(data, indent=2), encoding="utf-8")
        paths.restrict(meta)

    def discard(self, project: str, patch_id: str) -> bool:
        """Throw a staged patch away."""
        directory = self.patch_dir(project, patch_id)
        if not directory.is_dir():
            return False
        shutil.rmtree(directory, ignore_errors=True)
        return True


__all__ = [
    "FilePatch", "Hunk", "Patch", "PatchError", "PatchStore", "apply_to_file",
    "apply_to_tree", "copy_tree", "parse_diff",
]
