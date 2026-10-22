"""The code genome: symbols, references, and the impact of a change."""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from nusa_rg import symbols
from nusa_rg.cli import main
from nusa_rg.rag import ProjectIndex

SOURCE = '''"""A small module."""

import hmac


def hash_password(password: str) -> bytes:
    """Hash a password."""
    return hmac.new(b"key", password.encode(), "sha256").digest()


class Account:
    """One account."""

    def verify(self, password: str, digest: bytes) -> bool:
        """Constant-time check."""
        return hmac.compare_digest(hash_password(password), digest)

    def check(self, password: str, digest: bytes) -> bool:
        return self.verify(password, digest)
'''

TEST_SOURCE = '''from account import Account


def test_verify():
    assert Account().verify("x", b"y")
'''


@pytest.fixture
def runner():
    return CliRunner()


def run(runner, args, **kwargs):
    return runner.invoke(main, args, **kwargs)


# ---------------------------------------------------------------- extraction
def test_definitions_and_references_are_found():
    found, used = symbols.extract("/proj/account.py", "account.py", SOURCE)

    names = {item.qualname for item in found}
    assert "hash_password" in names
    assert "Account" in names
    assert "Account.verify" in names
    kinds = {item.qualname: item.kind for item in found}
    assert kinds["Account"] == "class"
    assert kinds["Account.verify"] == "method"
    assert kinds["hash_password"] == "function"
    assert "verify" in {item.name for item in used}


def test_a_file_that_does_not_parse_yields_nothing():
    found, used = symbols.extract("/proj/broken.py", "broken.py", "def (:\n")

    assert found == []
    assert used == []


# ------------------------------------------------------------------- storage
def test_the_index_stores_the_symbols(sample_project):
    from nusa_rg.engine import CoreEngine

    engine = CoreEngine()
    engine.index_project(sample_project)
    with ProjectIndex() as index:
        found = symbols.definitions(index.conn, "hash_password")
    engine.close()

    assert found, "the symbol is in the index"
    assert found[0]["relpath"].endswith("auth.py")


def test_reindexing_replaces_the_symbols_of_a_file(sample_project):
    from nusa_rg.engine import CoreEngine

    engine = CoreEngine()
    engine.index_project(sample_project)
    with ProjectIndex() as index:
        before = len(symbols.definitions(index.conn, "hash_password"))
    engine.index_project(sample_project, force=True)
    with ProjectIndex() as index:
        after = len(symbols.definitions(index.conn, "hash_password"))
    engine.close()

    assert before == after, "a second index must not duplicate a symbol"


# -------------------------------------------------------------------- impact
def test_the_impact_names_the_files_that_refer_to_a_symbol(sample_project):
    from nusa_rg.engine import CoreEngine

    (sample_project / "tests").mkdir(exist_ok=True)
    (sample_project / "tests" / "test_auth.py").write_text(
        "from src.auth import hash_password\n\n\n"
        "def test_hash():\n    assert hash_password('x')\n",
        encoding="utf-8")

    engine = CoreEngine()
    engine.index_project(sample_project)
    with ProjectIndex() as index:
        result = symbols.impact(index.conn, "src/auth.py")
    engine.close()

    assert result["symbols"]
    assert result["symbols"][0]["name"] == "hash_password"
    assert result["affected"], "the test file refers to it"
    assert result["tests"], "the test file is recognised as a test"


# ----------------------------------------------------------------------- CLI
def test_map_shows_the_structure(runner, sample_project):
    indexed = run(runner, ["index", str(sample_project)])
    assert indexed.exit_code == 0

    result = run(runner, ["map"])

    assert result.exit_code == 0
    assert "Project map" in result.output
    assert "symbols" in result.output


def test_map_finds_one_symbol(runner, sample_project):
    run(runner, ["index", str(sample_project)])

    result = run(runner, ["map", "--symbol", "hash_password"])

    assert result.exit_code == 0
    assert "hash_password" in result.output
    assert "Referenced by" in result.output


def test_map_without_an_index_is_an_error(runner):
    result = run(runner, ["map"])

    assert result.exit_code == 1
    assert "no project is indexed" in result.output


def test_impact_reports_the_dependants(runner, sample_project):
    (sample_project / "tests").mkdir(exist_ok=True)
    (sample_project / "tests" / "test_auth.py").write_text(
        "from src.auth import hash_password\n", encoding="utf-8")
    run(runner, ["index", str(sample_project)])

    result = run(runner, ["impact", "src/auth.py"])

    assert result.exit_code == 0
    assert "Impact of src/auth.py" in result.output
    assert "Referenced by" in result.output


def test_impact_of_something_unknown_is_an_error(runner, sample_project):
    run(runner, ["index", str(sample_project)])

    result = run(runner, ["impact", "nothing/here.py"])

    assert result.exit_code == 1
    assert "nothing known" in result.output
