"""CLI coverage: provider catalogue, per-provider keys, run, and chat toggles."""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from nusa_rg import catalog, paths
from nusa_rg.cli import main
from nusa_rg.config import Config, ConfigError


@pytest.fixture
def runner():
    return CliRunner()


def run(runner, args, **kwargs):
    return runner.invoke(main, args, **kwargs)


# ---------------------------------------------------------------- catalogue
def test_providers_list_searches(runner):
    result = run(runner, ["providers", "list", "--search", "deepseek"])
    assert result.exit_code == 0
    assert "deepseek" in result.output
    assert "ready to use" in result.output


def test_providers_show_details(runner):
    result = run(runner, ["providers", "show", "groq"])
    assert result.exit_code == 0
    assert "https://api.groq.com/openai/v1" in result.output
    assert "GROQ_API_KEY" in result.output


def test_providers_show_unknown_is_an_error(runner):
    result = run(runner, ["providers", "show", "definitely-not-a-provider"])
    assert result.exit_code == 1
    assert "unknown provider" in result.output


def test_providers_list_shows_the_icon_of_every_provider(runner):
    result = run(runner, ["providers", "list", "--search", "groq"])
    assert result.exit_code == 0
    assert "groq.svg" in result.output
    assert "models.dev/logos" in result.output


def test_providers_show_includes_the_logo_url(runner):
    result = run(runner, ["providers", "show", "groq"])
    assert result.exit_code == 0
    assert "https://models.dev/logos/groq.svg" in result.output


def test_providers_icon_prints_the_url(runner):
    result = run(runner, ["providers", "icon", "groq"])
    assert result.exit_code == 0
    assert "https://models.dev/logos/groq.svg" in result.output


def test_providers_icon_unknown_provider(runner):
    result = run(runner, ["providers", "icon", "skynet"])
    assert result.exit_code == 1
    assert "unknown provider" in result.output


def test_providers_icon_download_saves_the_svg(runner, monkeypatch):
    """The logo is cached on disk the first time it is drawn."""
    from nusa_rg import logos

    monkeypatch.delenv(logos.DISABLE_ENV, raising=False)
    monkeypatch.setattr(logos, "svg_text", lambda name, timeout=15: "<svg/>")

    result = run(runner, ["providers", "icon", "groq"])

    assert result.exit_code == 0
    assert "https://models.dev/logos/groq.svg" in result.output


def test_providers_models_lists_entries(runner):
    result = run(runner, ["providers", "models", "deepseek", "--limit", "5"])
    assert result.exit_code == 0
    assert "deepseek-flash" in result.output


def test_providers_refresh_stores_a_snapshot(runner, monkeypatch):
    import json

    synthetic = {
        "faux": {
            "name": "Faux",
            "api": "https://faux.example/v1",
            "env": ["FAUX_API_KEY"],
            "npm": "@ai-sdk/openai-compatible",
            "models": {
                "faux-1": {
                    "id": "faux-1", "name": "Faux 1",
                    "modalities": {"output": ["text"]},
                    "release_date": "2026-01-01",
                },
            },
        },
    }
    monkeypatch.setattr(catalog, "fetch_raw", lambda url, timeout=45: synthetic)
    catalog.clear_cache()
    try:
        result = run(runner, ["providers", "refresh"])
        assert result.exit_code == 0
        assert "1 providers" in result.output

        stored = json.loads(paths.catalog_path().read_text(encoding="utf-8"))
        assert "faux" in stored["providers"]
        assert paths.catalog_path().stat().st_mode & 0o077 == 0
    finally:
        catalog.clear_cache()


# ------------------------------------------------------------------- config
def test_config_set_provider_from_catalogue(runner):
    result = run(runner, ["config", "set", "provider", "deepseek"])
    assert result.exit_code == 0
    settings = Config()
    expected = catalog.load_catalog().get("deepseek").default_model
    assert settings.get("model_provider") == "external"
    assert settings.get("api_provider") == "deepseek"
    assert settings.get("api_base_url") == "https://api.deepseek.com"
    assert settings.get("api_model") == expected
    assert "model set to" in result.output


def test_config_set_provider_prefers_the_catalogue_over_legacy(runner):
    result = run(runner, ["config", "set", "provider", "local"])
    assert result.exit_code == 0
    assert Config().get("model_provider") == "local"


def test_config_set_provider_unknown(runner):
    result = run(runner, ["config", "set", "provider", "skynet"])
    assert result.exit_code == 2
    assert "unknown provider" in result.output


def test_config_set_provider_key_stays_encrypted(runner):
    result = run(runner, ["config", "set", "api_key", "--provider", "groq", "--secret"],
                 input="gsk-test-key\ngsk-test-key\n")
    assert result.exit_code == 0
    assert "encrypted" in result.output

    settings = Config()
    assert settings.api_key_for("groq") == "gsk-test-key"
    yaml_text = paths.config_path().read_text(encoding="utf-8")
    assert "gsk-test-key" not in yaml_text
    assert "credential/provider/groq" in yaml_text


def test_config_set_provider_key_removal(runner):
    Config().set_provider_key("groq", "gsk-temp")
    result = run(runner, ["config", "set", "api_key", "--provider", "groq"])
    assert result.exit_code == 0
    assert Config().api_key_for("groq") == ""


def test_plaintext_provider_key_in_yaml_is_rejected():
    paths.ensure_dirs()
    paths.config_path().write_text(
        "provider_keys:\n  groq: gsk-leaked-plaintext\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        Config()


def test_fallback_providers_round_trip(runner):
    result = run(runner, ["config", "set", "fallback_providers",
                          "groq,deepseek:deepseek-flash"])
    assert result.exit_code == 0
    assert Config().fallback_entries() == [
        ("groq", ""), ("deepseek", "deepseek-flash")]

    result = run(runner, ["config", "set", "fallback_providers", "skynet"])
    assert result.exit_code == 2
    assert "unknown provider" in result.output


def test_status_shows_style_and_provider(runner):
    run(runner, ["config", "set", "provider", "deepseek"])
    result = run(runner, ["status"])
    assert result.exit_code == 0
    assert "style" in result.output
    assert "deepseek" in result.output
    assert "https://models.dev/logos/deepseek.svg" in result.output


# ---------------------------------------------------------------------- run
def test_run_command_and_exit_code(runner):
    result = run(runner, ["run", "--raw", "echo", "hello-run"])
    assert result.exit_code == 0
    assert "hello-run" in result.output


def test_run_propagates_the_exit_code(runner):
    result = run(runner, ["run", "--raw", "--", "sh", "-c", "exit 5"])
    assert result.exit_code == 5


def test_run_rejects_shell_operators(runner):
    result = run(runner, ["run", "--raw", "ls | head"])
    assert result.exit_code == 2
    assert "shell operators" in result.output


def test_run_unknown_command_is_127(runner):
    result = run(runner, ["run", "--raw", "definitely-not-here-xyz"])
    assert result.exit_code == 127
    assert "not found" in result.output


# --------------------------------------------------------------------- chat
def test_chat_captures_a_command_as_context(runner):
    result = run(runner, ["chat"], input="!echo captured-here\n/exit\n")
    assert result.exit_code == 0
    assert "captured-here" in result.output
    assert "output kept" in result.output


def test_chat_caveman_toggle(runner):
    result = run(runner, ["chat"], input="/caveman\n/exit\n")
    assert result.exit_code == 0
    assert "response style: caveman" in result.output

    result = run(runner, ["chat"], input="/caveman on\n/caveman off\n/exit\n")
    assert "response style: caveman" in result.output
    assert "response style: default" in result.output


def test_chat_help_lists_new_commands(runner):
    result = run(runner, ["chat"], input="/help\n/exit\n")
    assert "/caveman" in result.output
    assert "!command" in result.output


def test_chat_caveman_flag_reaches_the_prompt(runner, monkeypatch):
    from nusa_rg.llm.api_client import ApiClient
    from nusa_rg.llm.base import LLMResponse, Usage

    captured = {}

    def fake_generate(self, prompt, **kwargs):
        captured["system"] = kwargs.get("system", "")
        return LLMResponse(text="ok", usage=Usage(), provider="stub")

    run(runner, ["config", "set", "api_key", "sk-stub", "--secret"])
    monkeypatch.setattr(ApiClient, "generate", fake_generate)
    result = run(runner, ["chat", "--caveman", "--no-rag", "hello"])
    assert result.exit_code == 0
    assert "telegraphic" in captured["system"]


def test_run_ask_uses_the_output_as_context(runner, monkeypatch):
    from nusa_rg.llm.api_client import ApiClient
    from nusa_rg.llm.base import LLMResponse, Usage

    captured = {}

    def fake_generate(self, prompt, **kwargs):
        captured["prompt"] = prompt
        return LLMResponse(text="answer-here", usage=Usage(), provider="stub")

    run(runner, ["config", "set", "api_key", "sk-stub", "--secret"])
    monkeypatch.setattr(ApiClient, "generate", fake_generate)
    result = run(runner, ["run", "--raw", "--ask", "why?", "echo", "hi-there"])
    assert result.exit_code == 0
    assert "answer-here" in result.output
    assert "hi-there" in captured["prompt"]
