"""The memory of failure: notes, fingerprints, and the prompt block."""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from nusa_rg import memory
from nusa_rg.cli import main
from nusa_rg.rag import ProjectIndex


@pytest.fixture
def runner():
    return CliRunner()


def run(runner, args, **kwargs):
    return runner.invoke(main, args, **kwargs)


def _connection():
    import sqlite3

    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        "CREATE TABLE memory_notes (id TEXT PRIMARY KEY, project TEXT NOT NULL,"
        " status TEXT NOT NULL, fingerprint TEXT NOT NULL, summary TEXT NOT NULL,"
        " detail TEXT NOT NULL DEFAULT '', subject TEXT NOT NULL DEFAULT '',"
        " attempts INTEGER NOT NULL DEFAULT 1, created_at REAL NOT NULL,"
        " updated_at REAL NOT NULL)")
    connection.execute(
        "CREATE TABLE memory_attempts (id INTEGER PRIMARY KEY,"
        " note_id TEXT NOT NULL, attempt INTEGER NOT NULL, status TEXT NOT NULL,"
        " note TEXT NOT NULL DEFAULT '', at REAL NOT NULL)")
    return connection


# ----------------------------------------------------------------- identity
def test_the_project_key_is_not_an_absolute_path():
    key = memory.project_key("/home/user/projects/my-app")

    assert "/" not in key
    assert "my-app" in key


def test_two_projects_with_the_same_name_stay_apart(tmp_path):
    first = memory.project_key(str(tmp_path / "a" / "project"))
    second = memory.project_key(str(tmp_path / "b" / "project"))

    assert first != second


def test_the_fingerprint_ignores_the_noise():
    first = memory.fingerprint("Error at line 42: cannot open /tmp/abc123")
    second = memory.fingerprint("Error at line 7: cannot open /tmp/zzz999")

    assert first == second


def test_different_errors_have_different_fingerprints():
    first = memory.fingerprint("cannot open the file")
    second = memory.fingerprint("the token expired")

    assert first != second


# ------------------------------------------------------------------- notes
def test_a_failure_is_written_down():
    connection = _connection()

    note = memory.record(connection, "proj", "pytest exited with 1",
                         "FAILED test_a.py", subject="pytest -q")

    assert note.status == "investigating"
    assert note.attempts == 1
    assert memory.get(connection, note.id) is not None


def test_the_same_failure_counts_another_attempt():
    connection = _connection()
    memory.record(connection, "proj", "pytest exited with 1", subject="pytest -q")
    again = memory.record(connection, "proj", "pytest exited with 1",
                          subject="pytest -q")

    assert again.attempts == 2
    assert again.status == "attempted"


def test_a_command_that_works_closes_its_notes():
    connection = _connection()
    memory.record(connection, "proj", "pytest exited with 1", subject="pytest -q")

    closed = memory.resolve_subject(connection, "proj", "pytest -q")

    assert closed == 1
    assert memory.list_notes(connection, "proj")[0].status == "resolved"


def test_a_secret_never_reaches_a_note():
    connection = _connection()

    note = memory.record(connection, "proj", 'the key sk-abcdefghijklmnop1234 failed')

    assert "sk-abcdefghijklmnop1234" not in note.summary
    assert "sk-abcdefghijklmnop1234" not in note.detail


def test_notes_of_another_project_are_not_shown():
    connection = _connection()
    memory.record(connection, "one", "failed here")
    memory.record(connection, "two", "failed there")

    assert [note.summary for note in memory.list_notes(connection, "one")] == [
        "failed here"]


def test_a_note_is_found_by_its_text_and_by_its_fingerprint():
    connection = _connection()
    memory.record(connection, "proj", "pytest exited with 1")

    assert memory.search(connection, "proj", "pytest")
    assert memory.search(connection, "proj",
                         "pytest exited with 42")  # same shape


def test_a_note_is_deleted():
    connection = _connection()
    note = memory.record(connection, "proj", "failed here")

    assert memory.delete(connection, note.id) is True
    assert memory.get(connection, note.id) is None
    assert memory.delete(connection, note.id) is False


def test_a_project_can_be_purged():
    connection = _connection()
    memory.record(connection, "proj", "failed here")
    memory.record(connection, "other", "failed there")

    assert memory.purge(connection, "proj") == 1
    assert memory.list_notes(connection, "proj") == []
    assert memory.list_notes(connection, "other")


def test_the_prompt_block_is_labelled():
    connection = _connection()
    memory.record(connection, "proj", "pytest exited with 1", "the import broke")

    block = memory.format_block(memory.for_prompt(connection, "proj", "pytest"))

    assert memory.MEMORY_OPEN in block
    assert memory.LABEL in block
    assert "the import broke" in block


def test_a_resolved_note_is_not_pushed_in_front_of_the_model():
    connection = _connection()
    memory.record(connection, "proj", "pytest exited with 1", subject="pytest -q")
    memory.resolve_subject(connection, "proj", "pytest -q")

    assert memory.for_prompt(connection, "proj", "pytest") == []


# ---------------------------------------------------------------------- CLI
def test_memory_list_is_empty_at_first(runner, sample_project):
    run(runner, ["index", str(sample_project)])

    result = run(runner, ["memory", "list"])

    assert result.exit_code == 0
    assert "no failure notes" in result.output


def test_memory_show_and_delete(runner, sample_project):
    run(runner, ["index", str(sample_project)])
    with ProjectIndex() as index:
        key = memory.project_key(index.project_root)
        note = memory.record(index.conn, key, "pytest exited with 1",
                             "FAILED test_a.py")

    listed = run(runner, ["memory", "list"])
    assert note.id in listed.output

    shown = run(runner, ["memory", "show", note.id])
    assert shown.exit_code == 0
    assert "pytest exited with 1" in shown.output

    deleted = run(runner, ["memory", "delete", note.id, "--yes"])
    assert deleted.exit_code == 0
    assert "deleted note" in deleted.output


def test_memory_search_finds_a_note(runner, sample_project):
    run(runner, ["index", str(sample_project)])
    with ProjectIndex() as index:
        key = memory.project_key(index.project_root)
        memory.record(index.conn, key, "pytest exited with 1")

    result = run(runner, ["memory", "search", "pytest"])

    assert result.exit_code == 0
    assert "pytest exited with 1" in result.output
