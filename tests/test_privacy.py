"""The privacy firewall: secrets, local-only files, and the fail-closed gate."""

from __future__ import annotations

import pytest

from nusa_rg import privacy
from nusa_rg.config import Config
from nusa_rg.llm.base import LLMError

SECRET_TEXT = (
    'API_KEY = "sk-abcdefghijklmnop1234"\n'
    "export GROQ_API_KEY=gsk_ABCDEFGHIJKLMNOPQRSTUVWX\n"
    "password: hunter2xyz\n"
)


# --------------------------------------------------------------- detection
def test_secrets_are_found():
    policy = privacy.PrivacyPolicy()
    kinds = {match.kind for match in policy.scan(SECRET_TEXT)}

    assert "openai-key" in kinds
    assert "groq-key" in kinds
    assert "assigned-secret" in kinds


def test_clean_text_is_left_alone():
    policy = privacy.PrivacyPolicy()
    text = "def add(a, b):\n    return a + b\n"

    assert policy.scan(text) == []
    assert policy.redact(text)[0] == text


def test_redaction_keeps_the_setting_around_the_secret():
    policy = privacy.PrivacyPolicy()
    cleaned, matches = policy.redact(SECRET_TEXT)

    assert matches
    assert "sk-abcdefghijklmnop1234" not in cleaned
    assert "gsk_ABCDEFGHIJKLMNOPQRSTUVWX" not in cleaned
    assert "API_KEY = " in cleaned
    assert privacy.MASK in cleaned


def test_detection_can_be_switched_off():
    policy = privacy.PrivacyPolicy(secret_detection=False)

    assert policy.scan(SECRET_TEXT) == []


# -------------------------------------------------------------- local only
def test_local_only_patterns_match():
    policy = privacy.PrivacyPolicy(local_only=[".env", "private/**", "secrets/**"])

    assert policy.is_local_only("/proj/.env", "/proj")
    assert policy.is_local_only("/proj/private/keys.py", "/proj")
    assert policy.is_local_only("/proj/secrets/a/b.txt", "/proj")
    assert not policy.is_local_only("/proj/src/app.py", "/proj")


def test_a_local_only_file_is_not_sent_to_an_external_provider():
    policy = privacy.PrivacyPolicy(local_only=[".env"])
    result = policy.screen("TOKEN=x", path="/proj/.env", root="/proj", external=True)

    assert not result.ok
    assert "local-only" in result.reason


def test_a_local_only_file_may_go_to_the_local_model():
    policy = privacy.PrivacyPolicy(local_only=[".env"])
    result = policy.screen("TOKEN=x", path="/proj/.env", root="/proj", external=False)

    assert result.ok


# ------------------------------------------------------------------- gate
def test_the_gate_refuses_when_redaction_is_off():
    policy = privacy.PrivacyPolicy(redact_secrets=False)
    result = policy.screen(SECRET_TEXT, external=True)

    assert not result.ok
    assert "secret" in result.reason


def test_the_gate_asks_before_a_redacted_context_is_sent():
    policy = privacy.PrivacyPolicy(confirm_sensitive_context=True)
    asked = []

    def confirm(matches):
        asked.append(matches)
        return False

    result = policy.screen(SECRET_TEXT, external=True, confirm=confirm)

    assert asked, "the user was asked"
    assert not result.ok


def test_a_confirmed_context_is_sent_masked():
    policy = privacy.PrivacyPolicy(confirm_sensitive_context=True)
    result = policy.screen(SECRET_TEXT, external=True, confirm=lambda m: True)

    assert result.ok
    assert "sk-abcdefghijklmnop1234" not in result.text


# ------------------------------------------------------------------ config
def test_the_policy_is_read_from_the_configuration():
    settings = Config()
    settings.set("privacy_secret_detection", "off")
    settings.set("privacy_redact_secrets", "off")
    settings.set("privacy_local_only", [".env", "secrets/**"])
    settings.set("privacy_confirm_sensitive_context", "off")

    policy = privacy.PrivacyPolicy.from_config(settings)

    assert policy.secret_detection is False
    assert policy.redact_secrets is False
    assert policy.local_only == (".env", "secrets/**")
    assert policy.confirm_sensitive_context is False


# ------------------------------------------------------------------ engine
def test_the_engine_masks_a_secret_before_the_request(monkeypatch, sample_project):
    from nusa_rg.engine import CoreEngine

    engine = CoreEngine()
    engine.index_project(sample_project)
    secret = sample_project / "config.py"
    secret.write_text('API_KEY = "sk-abcdefghijklmnop1234"\n', encoding="utf-8")
    engine.index_project(sample_project, force=True)

    sent = []

    class Stub:
        name = "stub"

        def generate(self, prompt, **kwargs):
            sent.append(prompt)
            return type("R", (), {"text": "ok", "usage": None})()

        def health_check(self):
            return True, "ok"

    monkeypatch.setattr("nusa_rg.llm.build_client",
                        lambda config, **kwargs: Stub())
    turn = engine.ask("what is the api key")
    engine.close()

    assert sent
    assert "sk-abcdefghijklmnop1234" not in sent[0]
    assert privacy.MASK in sent[0]
    assert any("secret" in note for note in turn.privacy_notes)


def test_a_local_only_file_never_reaches_the_prompt(monkeypatch, sample_project):
    from nusa_rg.engine import CoreEngine

    settings = Config()
    settings.set("privacy_local_only", ["secret.py"])
    engine = CoreEngine(settings)
    engine.index_project(sample_project)
    (sample_project / "secret.py").write_text("TOKEN = 'abc123xyz'\n",
                                              encoding="utf-8")
    engine.index_project(sample_project, force=True)

    sent = []

    class Stub:
        name = "stub"

        def generate(self, prompt, **kwargs):
            sent.append(prompt)
            return type("R", (), {"text": "ok", "usage": None})()

        def health_check(self):
            return True, "ok"

    monkeypatch.setattr("nusa_rg.llm.build_client",
                        lambda config, **kwargs: Stub())
    engine.ask("what is the token")
    engine.close()

    assert sent
    assert "abc123xyz" not in sent[0]


def test_the_firewall_refuses_the_whole_turn_when_it_cannot_mask(monkeypatch,
                                                                 sample_project):
    from nusa_rg.engine import CoreEngine

    settings = Config()
    settings.set("privacy_redact_secrets", "off")
    engine = CoreEngine(settings)
    engine.index_project(sample_project)
    (sample_project / "secret.py").write_text('KEY = "sk-abcdefghijklmnop1234"\n',
                                              encoding="utf-8")
    engine.index_project(sample_project, force=True)

    monkeypatch.setattr("nusa_rg.llm.build_client",
                        lambda config, **kwargs: pytest.fail("must not send"))
    with pytest.raises(LLMError):
        engine.ask("what is the key")
    engine.close()
