"""The code genome: what the project defines, and what refers to it.

The chunk index answers "which text looks like the question". This module
answers the harder question: "which function is that, and what else touches
it". It reads Python files with :mod:`ast`, so nothing in the project is
executed, and stores the result next to the chunks in the same database.

Symbols are replaced per file, inside the same transaction as the chunks of
that file, so a crash never leaves a symbol pointing at code that is gone.
"""

from __future__ import annotations

import ast
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

#: Names that are never worth recording as a reference.
_BUILTINS = frozenset({
    "print", "len", "range", "str", "int", "float", "bool", "list", "dict",
    "set", "tuple", "open", "isinstance", "getattr", "setattr", "hasattr",
    "super", "type", "self", "cls", "if", "for", "while", "return", "yield",
    "try", "except", "with", "assert", "raise", "import", "from", "class",
    "def", "lambda", "not", "and", "or", "in", "is", "None", "True", "False",
})


@dataclass
class Symbol:
    """One definition found in the project."""

    name: str
    qualname: str
    kind: str
    path: str
    relpath: str
    start_line: int
    end_line: int
    parent: str = ""
    signature: str = ""


@dataclass
class Reference:
    """One use of a name somewhere in the project."""

    name: str
    path: str
    relpath: str
    line: int


class _Collector(ast.NodeVisitor):
    """Collect definitions and name uses from one parsed file."""

    def __init__(self, path: str, relpath: str):
        self.path = path
        self.relpath = relpath
        self.symbols: list[Symbol] = []
        self.references: list[Reference] = []
        self._stack: list[str] = []

    # ---------------------------------------------------------- definitions
    def _qualname(self, name: str) -> str:
        return ".".join([*self._stack, name])

    def _signature(self, node) -> str:
        args = node.args
        names = [arg.arg for arg in (*args.posonlyargs, *args.args)]
        if args.vararg:
            names.append("*" + args.vararg.arg)
        names.extend(arg.arg for arg in args.kwonlyargs)
        if args.kwarg:
            names.append("**" + args.kwarg.arg)
        return f"{node.name}({', '.join(names)})"

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        qualname = self._qualname(node.name)
        self.symbols.append(Symbol(
            name=node.name, qualname=qualname, kind="class",
            path=self.path, relpath=self.relpath,
            start_line=node.lineno, end_line=getattr(node, "end_lineno", node.lineno),
            parent=".".join(self._stack), signature=node.name,
        ))
        self._stack.append(node.name)
        self.generic_visit(node)
        self._stack.pop()

    def _visit_function(self, node) -> None:
        qualname = self._qualname(node.name)
        kind = "method" if self._stack else "function"
        self.symbols.append(Symbol(
            name=node.name, qualname=qualname, kind=kind,
            path=self.path, relpath=self.relpath,
            start_line=node.lineno, end_line=getattr(node, "end_lineno", node.lineno),
            parent=".".join(self._stack), signature=self._signature(node),
        ))
        self._stack.append(node.name)
        self.generic_visit(node)
        self._stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    # ------------------------------------------------------------ references
    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load) and node.id not in _BUILTINS:
            self.references.append(Reference(
                name=node.id, path=self.path, relpath=self.relpath,
                line=node.lineno))
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr not in _BUILTINS:
            self.references.append(Reference(
                name=node.attr, path=self.path, relpath=self.relpath,
                line=node.lineno))
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        # `from auth import verify` is a use of verify, and the only evidence
        # that another file depends on it.
        for alias in node.names:
            self.references.append(Reference(
                name=alias.name, path=self.path, relpath=self.relpath,
                line=node.lineno))
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.references.append(Reference(
                name=alias.name.rsplit(".", 1)[-1], path=self.path,
                relpath=self.relpath, line=node.lineno))
        self.generic_visit(node)


def extract(path: str, relpath: str = "", text: str | None = None) -> tuple[list[Symbol], list[Reference]]:
    """The definitions and references of one file.

    A file that does not parse yields nothing rather than an error: the
    index must survive a half-written file.
    """
    if text is None:
        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return [], []
    if not relpath:
        relpath = path
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return [], []
    collector = _Collector(path, relpath)
    collector.visit(tree)
    return collector.symbols, collector.references


# ------------------------------------------------------------------ storage

def replace_file_symbols(
    conn: sqlite3.Connection,
    path: str,
    relpath: str,
    symbols: Sequence[Symbol],
    references: Sequence[Reference],
) -> None:
    """Swap the symbols of one file for a fresh set."""
    conn.execute("DELETE FROM symbols WHERE path=?", (path,))
    conn.execute("DELETE FROM symbol_refs WHERE path=?", (path,))
    conn.executemany(
        "INSERT INTO symbols(name, qualname, kind, path, relpath, start_line,"
        " end_line, parent, signature) VALUES(?,?,?,?,?,?,?,?,?)",
        [(s.name, s.qualname, s.kind, s.path, s.relpath, s.start_line,
          s.end_line, s.parent, s.signature) for s in symbols],
    )
    conn.executemany(
        "INSERT INTO symbol_refs(name, path, relpath, line) VALUES(?,?,?,?)",
        [(r.name, r.path, r.relpath, r.line) for r in references],
    )


def remove_file_symbols(conn: sqlite3.Connection, path: str) -> None:
    """Forget the symbols of a file that is gone."""
    conn.execute("DELETE FROM symbols WHERE path=?", (path,))
    conn.execute("DELETE FROM symbol_refs WHERE path=?", (path,))


# ----------------------------------------------------------------- queries

def definitions(conn: sqlite3.Connection, name: str, limit: int = 20) -> list[sqlite3.Row]:
    """Every definition of ``name``, most precise first."""
    return list(conn.execute(
        "SELECT * FROM symbols WHERE name=? OR qualname=? "
        "ORDER BY LENGTH(qualname), relpath LIMIT ?",
        (name, name, limit),
    ))


def references(conn: sqlite3.Connection, name: str, limit: int = 50) -> list[sqlite3.Row]:
    """Every place that mentions ``name``."""
    return list(conn.execute(
        "SELECT * FROM symbol_refs WHERE name=? ORDER BY relpath, line LIMIT ?",
        (name, limit),
    ))


def symbols_in_file(conn: sqlite3.Connection, path: str) -> list[sqlite3.Row]:
    """Every definition in one file."""
    return list(conn.execute(
        "SELECT * FROM symbols WHERE path=? ORDER BY start_line", (path,)))


def files_matching(conn: sqlite3.Connection, relpath: str) -> list[sqlite3.Row]:
    """Definitions of a file, addressed by its relative path."""
    return list(conn.execute(
        "SELECT * FROM symbols WHERE relpath=? ORDER BY start_line", (relpath,)))


def summary(conn: sqlite3.Connection) -> dict:
    """Counts for the project map."""
    kinds = {row["kind"]: row["total"] for row in conn.execute(
        "SELECT kind, COUNT(*) AS total FROM symbols GROUP BY kind")}
    files = conn.execute("SELECT COUNT(DISTINCT path) AS total FROM symbols").fetchone()
    per_file = list(conn.execute(
        "SELECT relpath, COUNT(*) AS total FROM symbols "
        "GROUP BY relpath ORDER BY total DESC, relpath LIMIT 12"))
    return {
        "symbols": sum(kinds.values()),
        "files": files["total"] if files else 0,
        "kinds": kinds,
        "top_files": per_file,
    }


def _looks_like_test(relpath: str) -> bool:
    name = relpath.rsplit("/", 1)[-1]
    return (name.startswith("test_") or name.endswith("_test.py")
            or "/tests/" in f"/{relpath}" or "/test/" in f"/{relpath}")


def impact(conn: sqlite3.Connection, target: str) -> dict:
    """What a change to ``target`` could touch, with the evidence.

    ``target`` is a file path or a symbol name. The result names the symbols
    involved, the files that refer to them, and the test files among those.
    """
    rows = symbols_in_file(conn, target) or files_matching(conn, target)
    if not rows:
        rows = definitions(conn, target)
    if not rows:
        return {"target": target, "symbols": [], "affected": [], "tests": []}

    symbols = [dict(row) for row in rows]
    affected: dict[str, dict] = {}
    tests: dict[str, dict] = {}
    for row in symbols:
        for reference in references(conn, row["name"], limit=200):
            if reference["path"] == row["path"]:
                continue
            entry = affected.setdefault(reference["relpath"], {
                "relpath": reference["relpath"], "symbols": set(), "lines": []})
            entry["symbols"].add(row["name"])
            entry["lines"].append(reference["line"])
            if _looks_like_test(reference["relpath"]):
                tests.setdefault(reference["relpath"], entry)

    def finish(entries: dict) -> list[dict]:
        out = []
        for entry in entries.values():
            item = dict(entry)
            item["symbols"] = ", ".join(sorted(item["symbols"]))
            item["lines"] = sorted(set(item["lines"]))[:8]
            out.append(item)
        return out

    return {
        "target": target,
        "symbols": symbols,
        "affected": finish(affected),
        "tests": finish(tests),
    }


__all__ = [
    "Reference", "Symbol", "definitions", "extract", "files_matching",
    "impact", "references", "remove_file_symbols", "replace_file_symbols",
    "summary", "symbols_in_file",
]
