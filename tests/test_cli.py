"""Tests for the click CLI surface (FR-05, FR-06, FR-13..FR-16)."""

from __future__ import annotations

import json
import stat

import pytest
from click.testing import CliRunner

from ragassist.cli import main


@pytest.fixture
def runner():
    return CliRunner()


def run(runner, args, **kwargs):
    return runner.invoke(main, args, **kwargs)


# ---------------------------------------------------------------------- help
def test_help_lists_all_commands(runner):
    """AC-07 / AC-36."""
    result = run(runner, ["--help"])
    assert result.exit_code == 0
    for command in ("chat", "index", "config"):
        assert command in result.output


def test_help_includes_examples(runner):
    """AC-39."""
    result = run(runner, ["--help"])
    assert "Examples:" in result.output
    assert "rag-assist index" in result.output


def test_short_help_flag(runner):
    assert run(runner, ["-h"]).exit_code == 0


def test_version(runner):
    result = run(runner, ["--version"])
    assert result.exit_code == 0
    assert "1.0.0" in result.output


def test_unknown_command_fails(runner):
    assert run(runner, ["frobnicate"]).exit_code != 0


# --------------------------------------------------------------------- index
def test_index_creates_the_database(runner, sample_project):
    """FR-09 / AC-11."""
    result = run(runner, ["index", str(sample_project)])
    assert result.exit_code == 0, result.output
    assert "Index complete" in result.output

    from ragassist.rag import ProjectIndex

    with ProjectIndex() as index:
        assert index.count()[0] == 3


def test_index_sets_default_project_path(runner, sample_project):
    """AC-16 / AC-30."""
    run(runner, ["index", str(sample_project)])
    from ragassist.config import Config

    assert Config().project_path() == str(sample_project.resolve())


def test_index_missing_path_exits_1(runner, tmp_path):
    result = run(runner, ["index", str(tmp_path / "nope")])
    assert result.exit_code == 1
    assert "does not exist" in result.output


def test_index_without_argument_is_actionable(runner):
    result = run(runner, ["index"])
    assert result.exit_code == 2
    assert "project path" in result.output


def test_index_json_output(runner, sample_project):
    result = run(runner, ["index", str(sample_project), "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["files_indexed"] == 3
    assert payload["root"] == str(sample_project.resolve())
    assert payload["duration_seconds"] >= 0


def test_index_reports_timing(runner, sample_project):
    result = run(runner, ["index", str(sample_project)])
    assert "duration" in result.output


def test_index_is_fast_enough_for_100_files(runner, tmp_path):
    """AC-28: 100+ files in under 30 seconds."""
    project = tmp_path / "big"
    for i in range(120):
        (project / f"mod_{i}.py").parent.mkdir(parents=True, exist_ok=True)
        (project / f"mod_{i}.py").write_text(
            f"def function_{i}():\n    return {i}\n", encoding="utf-8"
        )

    result = run(runner, ["index", str(project), "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["files_indexed"] == 120
    assert payload["duration_seconds"] < 30, "AC-28 budget"


# -------------------------------------------------------------------- config
def test_config_show(runner):
    result = run(runner, ["config", "show"])
    assert result.exit_code == 0
    assert "model_provider" in result.output
    assert "system_prompt" in result.output


def test_config_show_hides_key_by_default(runner):
    from ragassist.config import Config

    Config().set_api_key("sk-should-not-appear")
    result = run(runner, ["config", "show"])
    assert "sk-should-not-appear" not in result.output


def test_config_show_reveal(runner):
    from ragassist.config import Config

    Config().set_api_key("sk-visible-when-asked")
    result = run(runner, ["config", "show", "--reveal"])
    assert "sk-visible-when-asked" in result.output


def test_config_set_provider(runner):
    """AC-30."""
    from ragassist.config import Config

    assert run(runner, ["config", "set", "provider", "local"]).exit_code == 0
    assert Config().get("model_provider") == "local"

    assert run(runner, ["config", "set", "provider", "external"]).exit_code == 0
    assert Config().get("model_provider") == "external"


def test_config_set_provider_rejects_unknown(runner):
    result = run(runner, ["config", "set", "provider", "skynet"])
    assert result.exit_code == 2
    assert "unknown provider" in result.output


def test_config_set_requires_value(runner):
    assert run(runner, ["config", "set", "system_prompt"]).exit_code == 2


def test_config_set_missing_key(runner):
    result = run(runner, ["config", "set"])
    assert result.exit_code == 2
    assert "missing KEY" in result.output


def test_config_set_api_key_prompts_secret(runner):
    """SEC-01: the value is never echoed or written to YAML."""
    result = run(runner, ["config", "set", "api_key", "--secret"],
                 input="sk-prompted-secret\nsk-prompted-secret\n")
    assert result.exit_code == 0
    assert "encrypted" in result.output

    from ragassist import paths
    from ragassist.config import Config

    assert "sk-prompted-secret" not in paths.config_path().read_text()
    assert Config().get("api_key") == "sk-prompted-secret"


def test_config_set_api_key_arg_form(runner):
    assert run(runner, ["config", "set", "api_key", "sk-inline", "--secret"]).exit_code == 0
    from ragassist.config import Config

    assert Config().get("api_key") == "sk-inline"


def test_config_clear_api_key(runner):
    from ragassist.config import Config

    run(runner, ["config", "set", "api_key", "sk-to-remove", "--secret"])
    result = run(runner, ["config", "set", "api_key", ""])
    assert result.exit_code == 0
    assert Config().get("api_key", "") == ""


def test_config_path_command(runner):
    result = run(runner, ["config", "path"])
    assert result.exit_code == 0
    for label in ("config", "index", "keystore", "log"):
        assert label in result.output


def test_config_change_is_audited(runner):
    """AC-35."""
    from ragassist import paths

    run(runner, ["config", "set", "provider", "local"])
    assert "config.set.model_provider" in paths.audit_log_path().read_text()


# ---------------------------------------------------------------------- chat
def test_chat_single_message_reports_llm_error(runner):
    """FR-08 / AC-10: a clear message when the provider is unusable."""
    result = run(runner, ["chat", "hello there"])
    assert result.exit_code == 0, "the CLI must not crash on an LLM error"
    assert "error:" in result.output.lower()


def test_chat_without_api_key_explains_fix(runner):
    result = run(runner, ["chat", "hi"])
    assert "api key" in result.output.lower()


def test_chat_exits_on_eof(runner):
    """AC-37 / Ctrl+D."""
    result = run(runner, ["chat"], input="\x04")
    assert result.exit_code == 0
    assert "session ended" in result.output


def test_chat_exit_command(runner):
    result = run(runner, ["chat"], input="/exit\n")
    assert result.exit_code == 0
    assert "session ended" in result.output


def test_chat_help_command(runner):
    result = run(runner, ["chat"], input="/help\n/exit\n")
    assert "Chat commands" in result.output


def test_chat_clear_command(runner):
    result = run(runner, ["chat"], input="/clear\n/exit\n")
    assert "context cleared" in result.output


def test_chat_reports_retrieved_snippets(runner, sample_project, monkeypatch):
    """FR-15: snippets are highlighted before the answer."""
    from ragassist.llm.base import LLMResponse, Usage

    def fake_generate(self, query, *, context="", system="", stream=False):
        return LLMResponse(text="stub answer", usage=Usage(), provider="stub")

    monkeypatch.setattr("ragassist.llm.api_client.ApiClient.generate", fake_generate)

    run(runner, ["config", "set", "api_key", "sk-stub", "--secret"])
    run(runner, ["index", str(sample_project)])
    result = run(runner, ["chat", "how do we hash a password"])
    assert result.exit_code == 0, result.output
    assert "stub answer" in result.output
    assert "context" in result.output
    assert "auth.py" in result.output


def test_chat_multiline_block(runner, sample_project, monkeypatch):
    """AC-37: three code lines sent as one message."""
    from ragassist.llm.base import LLMResponse, Usage

    seen = {}

    def capture(self, query, *, context="", system="", stream=False):
        seen["user"] = query + context
        return LLMResponse(text="ok", usage=Usage(), provider="stub")

    monkeypatch.setattr("ragassist.llm.api_client.ApiClient.generate", capture)

    run(runner, ["config", "set", "api_key", "sk-stub", "--secret"])
    run(runner, ["index", str(sample_project)])
    run(runner, ["chat", "line one\nline two\nline three\n\n"])

    assert "line one" in seen.get("user", "")
    assert "line three" in seen.get("user", "")


def test_chat_no_rag_skips_retrieval(runner, sample_project, monkeypatch):
    from ragassist.llm.base import LLMResponse, Usage

    monkeypatch.setattr(
        "ragassist.llm.api_client.ApiClient.generate",
        lambda self, q, **kw: LLMResponse(text="plain", usage=Usage(), provider="stub"),
    )
    run(runner, ["config", "set", "api_key", "sk-stub", "--secret"])
    run(runner, ["index", str(sample_project)])
    result = run(runner, ["chat", "no context please", "--no-rag"])
    assert "context:" not in result.output


# ------------------------------------------------------------ status/doctor
def test_status_command(runner, sample_project):
    run(runner, ["index", str(sample_project)])
    result = run(runner, ["status"])
    assert result.exit_code == 0
    assert "provider" in result.output
    assert "index" in result.output


def test_doctor_runs_all_checks(runner):
    result = run(runner, ["doctor"])
    assert "Diagnostics" in result.output
    assert "sqlite FTS5" in result.output
    assert "PASS" in result.output


def test_doctor_reports_missing_llama_but_passes_others(runner):
    result = run(runner, ["doctor"])
    assert "llama.cpp binary" in result.output


# ---------------------------------------------------------------------- module
def test_module_entry_point(sample_project):
    import subprocess
    import sys

    completed = subprocess.run(
        [sys.executable, "-m", "ragassist", "--help"],
        capture_output=True, text=True, timeout=30,
    )
    assert completed.returncode == 0
    assert "chat" in completed.stdout


def test_security_state_files_are_owner_only_after_commands(runner, sample_project):
    from ragassist import paths

    run(runner, ["index", str(sample_project)])
    run(runner, ["chat", "/exit"], input="")

    for path in (paths.config_path(), paths.app_log_path(), paths.index_db_path()):
        if path.exists():
            assert stat.S_IMODE(path.stat().st_mode) == 0o600, f"{path}"