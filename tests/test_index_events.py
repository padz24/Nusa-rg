"""Tests for index progress events (FR-17)."""

from __future__ import annotations

from click.testing import CliRunner

from nusa_rg.cli import main
from nusa_rg.rag import ProjectIndex


def _project(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "a.py").write_text("print('a')\n", encoding="utf-8")
    (root / "b.py").write_text("print('b')\n", encoding="utf-8")
    return root


def test_index_emits_scan_planned_file_done(tmp_path):
    root = _project(tmp_path)
    events: list = []

    with ProjectIndex() as index:
        index.index(root, chunk_size=20, overlap=5, on_event=events.append)

    phases = [event.phase for event in events]
    assert phases[0] == "scan"
    assert events[0].detail == str(root.resolve())

    planned = events[phases.index("planned")]
    assert planned.total == 2

    files = [event for event in events if event.phase == "file"]
    assert sorted(event.detail for event in files) == ["a.py", "b.py"]
    assert [event.done for event in files] == [1, 2]

    assert phases[-1] == "done"


def test_index_without_a_callback_stays_silent(tmp_path, capsys):
    root = _project(tmp_path)

    with ProjectIndex() as index:
        index.index(root, chunk_size=20, overlap=5)

    assert capsys.readouterr().out == ""


def test_cli_index_plain_output_has_no_progress_or_escapes(tmp_path):
    root = _project(tmp_path)

    result = CliRunner().invoke(main, ["index", str(root)])

    assert result.exit_code == 0, result.output
    assert "Index complete" in result.output
    assert "scanning" not in result.output
    assert "\033[" not in result.output
