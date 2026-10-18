"""Tests for the hybrid LLM paths and the provider factory.

No network access: the HTTP client is exercised against local fakes, and the
local path against a stub executable.
"""

from __future__ import annotations

import json
import stat

import pytest

from nusa_rg.config import Config
from nusa_rg.llm import build_client
from nusa_rg.llm.api_client import ApiClient
from nusa_rg.llm.base import (
    AuthenticationError,
    LocalModelError,
    ProviderUnavailableError,
    RateLimitError,
)
from nusa_rg.llm.local import LocalLLMRunner, estimate_tokens


class FakeResponse:
    """Stand-in for a ``requests`` response (status_code, no ``status``)."""

    def __init__(self, status=200, payload=None, body=None, lines=None):
        self.status_code = status
        self._payload = payload if payload is not None else {}
        self._body = body if body is not None else json.dumps(self._payload).encode()
        self._lines = lines

    def read(self):
        return self._body

    def json(self):
        return self._payload

    def iter_lines(self):
        return iter(self._lines or [])


class FakeRequestsResponse:
    """A faithful requests.Response stand-in: no read(), only .content/.text."""

    def __init__(self, status=200, payload=None, body=None):
        self.status_code = status
        self.ok = status < 400
        self._payload = payload if payload is not None else {}
        self.content = body if body is not None else json.dumps(self._payload).encode()
        self.text = self.content.decode()

    def json(self):
        return self._payload


class FakeUrllibResponse:
    """Stand-in for the urllib fallback (http.client status attributes)."""

    def __init__(self, status=200, payload=None, body=None):
        self.status = status
        self.code = status
        self._payload = payload if payload is not None else {}
        self._body = body if body is not None else json.dumps(self._payload).encode()

    def read(self):
        return self._body


def completion(content="hello", **usage):
    return {
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": usage.get("prompt_tokens", 10),
                  "completion_tokens": usage.get("completion_tokens", 5)},
    }


# ------------------------------------------------------------------ API client
def test_generate_returns_text_and_usage():
    client = ApiClient("https://api.openai.com/v1", "sk-test", "gpt-4o-mini")
    client._post = lambda payload, stream=False: FakeResponse(
        payload=completion("the answer", prompt_tokens=12, completion_tokens=6)
    )
    response = client.generate("question", system="be terse")

    assert response.text == "the answer"
    assert response.usage.prompt_tokens == 12
    assert response.usage.completion_tokens == 6
    assert response.as_dict()["usage"]["prompt_tokens"] == 12


def test_endpoint_matches_spec():
    """Section 9: POST /v1/chat/completions."""
    client = ApiClient("https://api.groq.com/openai/v1", "sk-test", "llama-3.1-8b")
    assert client.endpoint == "https://api.groq.com/openai/v1/chat/completions"


def test_authorization_header_is_bearer():
    client = ApiClient("https://api.openai.com/v1", "sk-abc", "gpt-4o-mini")
    assert client._headers()["Authorization"] == "Bearer sk-abc"


def test_status_reads_requests_attribute():
    """Regression: requests.Response has .status_code, not .status.

    Reading only ``.status`` made every HTTP error look like a 200.
    """
    from nusa_rg.llm.api_client import ApiClient as C

    assert C._status(FakeResponse(status=401)) == 401
    assert C._status(FakeResponse(status=404)) == 404


def test_status_reads_urllib_attribute():
    from nusa_rg.llm.api_client import ApiClient as C

    assert C._status(FakeUrllibResponse(status=500)) == 500


def test_status_defaults_to_zero_for_unknown_objects():
    from nusa_rg.llm.api_client import ApiClient as C

    assert C._status(object()) == 0


def test_401_raises_authentication_error():
    client = ApiClient("https://api.openai.com/v1", "sk-bad", "gpt-4o-mini")
    client._post = lambda payload, stream=False: FakeResponse(
        status=401, payload={"error": {"message": "invalid api key"}}
    )
    with pytest.raises(AuthenticationError) as exc:
        client.generate("hi")
    assert "rejected the API key" in str(exc.value)


def test_ollama_unauthorized_body_is_reported():
    """AC-10 against the real Ollama cloud response shape."""
    client = ApiClient("https://ollama.com/v1", "bogus", "beam")
    client._post = lambda payload, stream=False: FakeResponse(
        status=401, payload={"error": {"message": "Unauthorized", "type": "api_error"}}
    )
    with pytest.raises(AuthenticationError):
        client.generate("hi")


def test_ollama_model_not_found_body_is_reported():
    client = ApiClient("https://ollama.com/v1", "sk-valid", "no-such-model")
    client._post = lambda payload, stream=False: FakeResponse(
        status=404,
        payload={"error": {"message": 'model "no-such-model" not found.'}},
    )
    with pytest.raises(AuthenticationError) as exc:
        client.generate("hi")
    assert "does not know this model" in str(exc.value)
    assert "api_model" in str(exc.value), "should blame the model, not the URL"


def test_404_without_model_detail_blames_the_url():
    client = ApiClient("https://api.openai.com/v1", "sk-x", "m")
    client._post = lambda payload, stream=False: FakeResponse(status=404)
    with pytest.raises(AuthenticationError) as exc:
        client.generate("hi")
    assert "api_base_url" in str(exc.value)


def test_requests_style_response_error_detail_is_read():
    """Regression: requests.Response has no read(), only .content/.text.

    Calling read() raised AttributeError, which the broad handler swallowed,
    so every provider error message lost its detail under requests.
    """
    client = ApiClient("https://ollama.com/v1", "sk-valid", "m")
    client._post = lambda payload, stream=False: FakeRequestsResponse(
        status=404, payload={"error": {"message": 'model "m" not found'}})
    with pytest.raises(AuthenticationError) as exc:
        client.generate("hi")
    assert "not found" in str(exc.value)


def test_requests_style_response_success_path():
    client = ApiClient("https://ollama.com/v1", "sk-valid", "m")
    client._post = lambda payload, stream=False: FakeRequestsResponse(
        payload=completion("works"))
    assert client.generate("hi").text == "works"


def test_rate_limit_includes_provider_detail():
    client = ApiClient("https://ollama.com/v1", "sk-valid", "m")
    client._post = lambda payload, stream=False: FakeRequestsResponse(
        status=429, payload={"error": {"message": "slow down"}})
    with pytest.raises(RateLimitError) as exc:
        client.generate("hi")
    assert "slow down" in str(exc.value)


def test_server_error_includes_provider_detail():
    client = ApiClient("https://ollama.com/v1", "sk-valid", "m")
    client._post = lambda payload, stream=False: FakeRequestsResponse(
        status=500, payload={"error": {"message": "internal fault"}})
    with pytest.raises(ProviderUnavailableError) as exc:
        client.generate("hi")
    assert "internal fault" in str(exc.value)


def test_html_error_body_still_raises_on_status():
    client = ApiClient("https://ollama.com/v1", "sk-valid", "m")
    client._post = lambda payload, stream=False: FakeRequestsResponse(
        status=502, body=b"<html>Bad Gateway</html>")
    with pytest.raises(ProviderUnavailableError) as exc:
        client.generate("hi")
    assert "502" in str(exc.value)


def test_body_text_handles_both_transports():
    from nusa_rg.llm.api_client import ApiClient as C

    assert C._body_text(FakeRequestsResponse(payload={"a": 1})) == '{"a": 1}'
    assert C._body_text(FakeUrllibResponse(payload={"b": 2})) == '{"b": 2}'


def test_health_check_surfaces_http_error_status():
    client = ApiClient("https://api.openai.com/v1", "sk-bad", "m")
    client._post = lambda payload, stream=False: FakeResponse(
        status=401, payload={"error": {"message": "Unauthorized"}})
    ok, message = client.health_check()
    assert not ok
    assert "401" in message


def test_404_raises_with_hint():
    client = ApiClient("https://wrong.example/v1", "sk-x", "m")
    client._post = lambda payload, stream=False: FakeResponse(status=404)
    with pytest.raises(AuthenticationError) as exc:
        client.generate("hi")
    assert "api_base_url" in str(exc.value)


def test_429_raises_rate_limit():
    client = ApiClient("https://api.openai.com/v1", "sk-x", "m")
    client._post = lambda payload, stream=False: FakeResponse(status=429)
    with pytest.raises(RateLimitError):
        client.generate("hi")


def test_500_raises_provider_unavailable():
    client = ApiClient("https://api.openai.com/v1", "sk-x", "m")
    client._post = lambda payload, stream=False: FakeResponse(status=500)
    with pytest.raises(ProviderUnavailableError):
        client.generate("hi")


def test_non_json_response_is_handled():
    client = ApiClient("https://api.openai.com/v1", "sk-x", "m")
    client._post = lambda payload, stream=False: FakeResponse(body=b"<html>error</html>")
    with pytest.raises(ProviderUnavailableError):
        client.generate("hi")


def test_missing_choices_is_handled():
    client = ApiClient("https://api.openai.com/v1", "sk-x", "m")
    client._post = lambda payload, stream=False: FakeResponse(payload={"choices": []})
    with pytest.raises(ProviderUnavailableError):
        client.generate("hi")


# ------------------------------------------------- reasoning models (Ollama)
def reasoning_response(content="", reasoning="thinking...", finish="length"):
    return FakeResponse(payload={
        "choices": [{"message": {"role": "assistant", "content": content,
                                 "reasoning": reasoning},
                     "finish_reason": finish}],
        "usage": {"prompt_tokens": 20, "completion_tokens": 16},
    })


def test_reasoning_model_with_empty_content_is_explained():
    """Ollama's 'beam' returns empty content when it runs out of budget."""
    client = ApiClient("https://ollama.com/v1", "sk-x", "beam")
    client._post = lambda payload, stream=False: reasoning_response()
    response = client.generate("hi")

    assert "token budget" in response.text
    assert "max_tokens" in response.text, "the error must tell the user how to fix it"
    assert "thinking..." in response.text, "partial reasoning is shown"
    assert response.usage.prompt_tokens == 20


def test_reasoning_content_used_when_content_empty_and_complete():
    client = ApiClient("https://ollama.com/v1", "sk-x", "beam")
    client._post = lambda payload, stream=False: reasoning_response(
        content="", reasoning="final thought text", finish="stop")
    assert "final thought text" in client.generate("hi").text


def test_reasoning_content_field_alias():
    client = ApiClient("https://ollama.com/v1", "sk-x", "beam")
    body = {"choices": [{"message": {"content": "", "reasoning_content": "alt field"},
                         "finish_reason": "stop"}]}
    client._post = lambda payload, stream=False: FakeResponse(payload=body)
    assert "alt field" in client.generate("hi").text


def test_truncated_without_reasoning_mentions_length():
    client = ApiClient("https://ollama.com/v1", "sk-x", "beam")
    client._post = lambda payload, stream=False: reasoning_response(
        content="", reasoning="", finish="length")
    assert "cut off" in client.generate("hi").text


def test_completely_empty_response_is_reported():
    client = ApiClient("https://ollama.com/v1", "sk-x", "beam")
    client._post = lambda payload, stream=False: reasoning_response(
        content="", reasoning="", finish="stop")
    assert "empty response" in client.generate("hi").text


def test_max_tokens_is_sent_when_configured():
    client = ApiClient("https://ollama.com/v1", "sk-x", "beam", max_tokens=4096)
    captured = {}
    client._post = lambda payload, stream=False: (
        captured.update(payload), FakeResponse(payload=completion("ok")))[1]
    client.generate("hi")
    assert captured["max_tokens"] == 4096


def test_max_tokens_omitted_by_default():
    client = ApiClient("https://ollama.com/v1", "sk-x", "beam")
    captured = {}
    client._post = lambda payload, stream=False: (
        captured.update(payload), FakeResponse(payload=completion("ok")))[1]
    client.generate("hi")
    assert "max_tokens" not in captured, "provider default is used when unset"


def test_factory_wires_max_tokens():
    settings = Config()
    settings.update({"api_key": "sk-x", "max_tokens": 2048})
    assert build_client(settings).max_tokens == 2048

    settings.update({"max_tokens": None})
    assert build_client(settings).max_tokens is None

    settings.update({"max_tokens": "not-a-number"})
    assert build_client(settings).max_tokens is None


def test_health_check_without_key():
    client = ApiClient("https://api.openai.com/v1", "", "m")
    ok, message = client.health_check()
    assert not ok
    assert "api key" in message.lower()


def test_health_check_on_transport_error():
    client = ApiClient("https://api.openai.com/v1", "sk-x", "m")

    def boom(payload, stream=False):
        raise ProviderUnavailableError("cannot reach host")

    client._post = boom
    ok, message = client.health_check()
    assert not ok
    assert "cannot reach" in message


def test_health_check_success():
    client = ApiClient("https://api.openai.com/v1", "sk-x", "m")
    client._post = lambda payload, stream=False: FakeResponse(payload=completion())
    ok, message = client.health_check()
    assert ok and "reachable" in message


def test_network_failure_becomes_provider_unavailable():
    client = ApiClient("https://api.invalid.invalid/v1", "sk-x", "m", timeout=1)
    with pytest.raises(ProviderUnavailableError):
        client.generate("hi")


def test_context_is_prepended_to_prompt():
    client = ApiClient("https://api.openai.com/v1", "sk-x", "m")
    captured = {}

    def capture(payload, stream=False):
        captured.update(payload)
        return FakeResponse(payload=completion())

    client._post = capture
    client.generate("my question", context="RETRIEVED CODE", system="sys")
    user = captured["messages"][-1]["content"]
    assert "RETRIEVED CODE" in user
    assert "my question" in user


def test_system_message_precedes_user():
    client = ApiClient("https://api.openai.com/v1", "sk-x", "m")
    captured = {}
    client._post = lambda payload, stream=False: (
        captured.update(payload), FakeResponse(payload=completion())
    )[1]
    client.generate("q", system="be terse")
    assert captured["messages"][0] == {"role": "system", "content": "be terse"}


def test_sse_stream_is_parsed():
    client = ApiClient("https://api.openai.com/v1", "sk-x", "m")
    client._post = lambda payload, stream=False: FakeResponse(lines=[
        b'data: {"choices":[{"delta":{"content":"He"}}]}',
        b'data: {"choices":[{"delta":{"content":"llo"}}]}',
        b"data: [DONE]",
    ])
    response = client.generate("hi", stream=True)
    assert response.text == "Hello"


# ----------------------------------------------------------------- local model
@pytest.fixture
def fake_llama(tmp_path):
    """A stub that stands in for llama-cli and echoes its prompt."""
    script = tmp_path / "llama-cli"
    script.write_text(
        "#!/bin/sh\n"
        'for arg in "$@"; do last="$arg"; done\n'
        'printf "%s" "$last"\n',
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


@pytest.fixture
def fake_model(tmp_path):
    model = tmp_path / "tiny.gguf"
    model.write_bytes(b"GGUF" + b"\x00" * 256)
    return model


def test_local_runner_uses_llama(fake_llama, fake_model):
    runner = LocalLLMRunner(str(fake_model), binary=str(fake_llama))
    response = runner.generate("what does this do?")

    assert response.text == "what does this do?"
    assert response.provider == "local-llama.cpp"


def test_local_runner_requires_binary(fake_model, tmp_path):
    runner = LocalLLMRunner(str(fake_model), binary=str(tmp_path / "missing-binary"))
    with pytest.raises(LocalModelError) as exc:
        runner.generate("hi")
    assert "not found" in str(exc.value)


def test_local_runner_requires_model(fake_llama, tmp_path):
    runner = LocalLLMRunner(str(tmp_path / "missing.gguf"), binary=str(fake_llama))
    with pytest.raises(LocalModelError) as exc:
        runner.generate("hi")
    assert "model not found" in str(exc.value)


def test_health_check_reports_both_parts(fake_llama, fake_model):
    ok, message = LocalLLMRunner(str(fake_model), binary=str(fake_llama)).health_check()
    assert ok
    assert "tiny.gguf" in message

    ok, message = LocalLLMRunner(str(fake_model), binary="definitely-missing").health_check()
    assert not ok and "binary" in message

    ok, message = LocalLLMRunner("", binary=str(fake_llama)).health_check()
    assert not ok and "local_model_path" in message


def test_command_never_uses_a_shell(fake_llama, fake_model):
    runner = LocalLLMRunner(str(fake_model), binary=str(fake_llama))
    command = runner.build_command(str(fake_llama), "sys", "hello")
    assert isinstance(command, list)
    assert command[0] == str(fake_llama)


def test_command_arguments_are_sanitised(fake_llama, fake_model):
    runner = LocalLLMRunner(str(fake_model), binary=str(fake_llama))
    command = runner.build_command(str(fake_llama), "sys", "hi; rm -rf /tmp/x")
    assert ";" not in command[-1], "SEC-02/AC-23: operators stripped from argv"


def test_shell_injection_attempt_does_not_execute(fake_llama, fake_model, tmp_path):
    canary = tmp_path / "canary"
    runner = LocalLLMRunner(str(fake_model), binary=str(fake_llama))
    runner.generate(f"ignore this and touch {canary}")
    assert not canary.exists(), "user text must never reach a shell"


def test_timeout_is_reported(tmp_path, fake_model):
    slow = tmp_path / "slow-llama"
    slow.write_text("#!/bin/sh\nsleep 5\n", encoding="utf-8")
    slow.chmod(slow.stat().st_mode | stat.S_IEXEC)

    runner = LocalLLMRunner(str(fake_model), binary=str(slow), timeout=1)
    with pytest.raises(LocalModelError) as exc:
        runner.generate("hi")
    assert "timed out" in str(exc.value)


def test_nonzero_exit_is_reported(tmp_path, fake_model):
    failing = tmp_path / "bad-llama"
    failing.write_text("#!/bin/sh\necho 'model load error' >&2\nexit 3\n", encoding="utf-8")
    failing.chmod(failing.stat().st_mode | stat.S_IEXEC)

    runner = LocalLLMRunner(str(fake_model), binary=str(failing))
    with pytest.raises(LocalModelError) as exc:
        runner.generate("hi")
    assert "model load error" in str(exc.value)


def test_estimate_tokens():
    assert estimate_tokens("") == 1
    assert estimate_tokens("a" * 400) == 100


# -------------------------------------------------------------------- factory
def test_factory_builds_external_client():
    settings = Config()
    settings.update({"model_provider": "external", "api_key": "sk-x"})
    client = build_client(settings)
    assert isinstance(client, ApiClient)


def test_factory_builds_local_client(fake_llama, fake_model):
    """AC-30: switching provider changes the execution path."""
    settings = Config()
    settings.update({"model_provider": "local", "local_model_path": str(fake_model),
                     "local_llama_bin": str(fake_llama), "api_key": "sk-x"})
    assert isinstance(build_client(settings), LocalLLMRunner)

    settings.set_provider("external")
    assert isinstance(build_client(settings), ApiClient)


def test_factory_requires_key_for_external_mode():
    """FR-08/AC-10: no request is attempted without a credential."""
    from nusa_rg.llm.base import AuthenticationError

    settings = Config()
    settings.update({"model_provider": "external", "api_key": ""})
    with pytest.raises(AuthenticationError) as exc:
        build_client(settings)
    assert "config set api_key" in str(exc.value)


def test_local_without_model_path_is_actionable():
    from nusa_rg.llm.base import LLMError

    settings = Config()
    settings.set_provider("local")
    with pytest.raises(LLMError) as exc:
        build_client(settings)
    assert "local_model_path" in str(exc.value)


def test_config_provider_base_url_switching():
    settings = Config()
    settings.update({"api_base_url": "https://api.groq.com/openai/v1"})
    assert settings.provider_base_url() == "https://api.groq.com/openai/v1"

    settings.update({"api_base_url": ""})
    assert settings.provider_base_url().startswith("https://")


def test_engine_ask_does_not_touch_rag_when_llm_swapped(monkeypatch, sample_project):
    """AC-27: swapping the LLM client leaves retrieval untouched."""
    from nusa_rg.engine import CoreEngine

    engine = CoreEngine()
    engine.index_project(sample_project)
    engine.close()

    engine2 = CoreEngine()
    engine2.index_project(sample_project)
    calls = []
    monkeypatch.setattr(
        "nusa_rg.llm.build_client",
        lambda cfg: type("Stub", (), {
            "name": "stub",
            "generate": lambda self, p, **kw: calls.append(p) or type(
                "R", (), {"text": "stubbed", "usage": type("U", (), {
                    "prompt_tokens": 0, "completion_tokens": 0})()})(),
            "health_check": lambda self: (True, "ok"),
        })(),
    )
    turn = engine2.ask("how do we hash passwords")
    assert turn.answer == "stubbed"
    assert calls, "the stub client was invoked"
    assert turn.retrieval.snippets, "retrieval still works with a different LLM client"
    engine2.close()