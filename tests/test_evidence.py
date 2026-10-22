"""Proof-first answers: the evidence block and the labels it carries."""

from __future__ import annotations

from nusa_rg import evidence
from nusa_rg.rag.retriever import Snippet


def _snippet(path: str = "src/auth.py", score: float = 0.8) -> Snippet:
    return Snippet(
        path=path, start_line=3, end_line=9,
        content="def hash_password(password):\n    return sha256(password)\n",
        score=score,
    )


def test_the_evidence_carries_the_citation_and_the_score():
    items = evidence.build([_snippet()], None, "/proj")

    assert len(items) == 1
    assert items[0].citation == "src/auth.py:3-9"
    assert items[0].kind == evidence.FACT
    assert items[0].confidence == 0.8
    assert "[FACT]" in items[0].label()
    assert "confidence=0.80" in items[0].label()


def test_the_block_lists_the_evidence():
    block = evidence.format_block(evidence.build([_snippet()], None, "/proj"))

    assert block.startswith(evidence.EVIDENCE_OPEN)
    assert block.endswith(evidence.EVIDENCE_CLOSE)
    assert "src/auth.py:3-9" in block
    assert "sha256" in block


def test_without_evidence_the_block_says_so():
    block = evidence.format_block([])

    assert evidence.NO_EVIDENCE in block
    assert "UNKNOWN" in evidence.INSTRUCTIONS


def test_the_path_is_shortened_to_the_project():
    items = evidence.build([_snippet("/proj/src/auth.py")], None, "/proj")

    assert items[0].relpath == "src/auth.py"
    assert items[0].path == "/proj/src/auth.py"


def test_the_symbols_of_the_file_are_named():
    import sqlite3

    from nusa_rg import symbols

    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        "CREATE TABLE symbols (id INTEGER PRIMARY KEY, name TEXT, qualname TEXT,"
        " kind TEXT, path TEXT, relpath TEXT, start_line INTEGER,"
        " end_line INTEGER, parent TEXT, signature TEXT)")
    connection.execute(
        "INSERT INTO symbols(name, qualname, kind, path, relpath, start_line,"
        " end_line, parent, signature) VALUES(?,?,?,?,?,?,?,?,?)",
        ("hash_password", "hash_password", "function", "/proj/src/auth.py",
         "src/auth.py", 3, 9, "", "hash_password(password)"))
    connection.commit()

    items = evidence.build([_snippet("/proj/src/auth.py")], connection, "/proj")

    assert items[0].symbols == ["hash_password"]
    assert "symbol=hash_password" in items[0].label()
