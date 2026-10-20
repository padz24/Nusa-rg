"""Tests for live SSE streaming: engine hooks, failover, and the CLI path."""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from nusa_rg.cli import main
from nusa_rg.engine import CoreEngine
from nusa_rg.llm.base import LLMClient, LLMError, LLMResponse, Usage
from nusa_rg.llm.failover import FailoverClient
from nusa_rg.live import supports_live


class StreamingClient(LLMClient):
    """A client whose only job is emitting preset deltas."""

    name = "stub-stream"

    def __init__(self, deltas, *, fail_after=None, usage=None):
        self.deltas = deltas
        self.fail_after = fail_after
        self.usage = usage
        self.prompts: list[str] = []

    def supports_stream(self) -> bool:
        return True

    def iter_stream(self, prompt, *, context="", system="", on_usage=None):
        self.prompts.append(prompt)
        for position, delta in enumerate(self.deltas):
            if self.fail_after is not None and position == self.fail_after:
                raise LLMError("stream broke")
            yield delta
        if on_usage is not None and self.usage is not None:
            on_usage(self.usage)

    def generate(self, *args, **kwargs):  # pragma: no cover - must not run
        raise AssertionError("generate() must not be called when streaming")


class WholeClient(LLMClient):
    """A client without incremental output, like the llama.cpp path."""

    name = "stub-whole"

    def generate(self, prompt, *, context="", system="", stream=False):
        return LLMResponse(text="one piece", usage=Usage(1, 2), provider="stub-whole")


@pytest.fixture
def stub_client(monkeypatch):
    def install(client):
        monkeypatch.setattr("nusa_rg.engine.llm.build_client", lambda config: client)
        return client

    return install


@pytest.fixture
def runner():
    return CliRunner()


def run(runner, args, **kwargs):
    return runner.invoke(main, args, **kwargs)


# ------------------------------------------------------------------- contract
def test_engine_advertises_the_live_hooks():
    """live.supports_live() gates the whole SSE path in the CLI."""
    assert supports_live(CoreEngine()) is True


def test_api_client_supports_stream():
    from nusa_rg.llm.api_client import ApiClient

    client = ApiClient(base_url="http://localhost:9/v1", api_key="k")
    assert client.supports_stream() is True


# --------------------------------------------------------------------- engine
def test_engine_streams_deltas_in_order(stub_client):
    client = stub_client(StreamingClient(["Hello", ", ", "world"]))
    deltas: list[str] = []

    turn = CoreEngine().ask("hi", skip_retrieval=True, on_token=deltas.append)

    assert deltas == ["Hello", ", ", "world"]
    assert turn.answer == "Hello, world"
    assert turn.response.provider == "stub-stream"
    assert client.prompts, "the composed prompt reached the client"


def test_engine_records_usage_from_the_stream(stub_client):
    stub_client(StreamingClient(["Hi"], usage=Usage(9, 4)))

    turn = CoreEngine().ask("hi", skip_retrieval=True, on_token=lambda delta: None)

    assert turn.response.usage.prompt_tokens == 9
    assert turn.response.usage.completion_tokens == 4


def test_engine_reports_retrieval_before_the_first_delta(stub_client, indexed):
    stub_client(StreamingClient(["answer"]))
    order: list[tuple] = []

    CoreEngine().ask(
        "how do we hash a password",
        on_retrieval=lambda result: order.append(("retrieval", len(result.snippets))),
        on_token=lambda delta: order.append(("delta", delta)),
    )

    assert order[0][0] == "retrieval"
    assert order[0][1] >= 1
    assert order[1] == ("delta", "answer")


def test_engine_reports_an_empty_retrieval_too(stub_client):
    stub_client(StreamingClient(["x"]))
    seen: list = []

    CoreEngine().ask("hi", skip_retrieval=True, on_retrieval=seen.append,
                     on_token=lambda delta: None)

    assert len(seen) == 1
    assert seen[0].snippets == []


def test_engine_without_stream_support_returns_the_whole_answer(stub_client):
    stub_client(WholeClient())
    deltas: list[str] = []

    turn = CoreEngine().ask("hi", skip_retrieval=True, on_token=deltas.append)

    assert deltas == []
    assert turn.answer == "one piece"
    assert turn.response.usage.prompt_tokens == 1


# ------------------------------------------------------------------- failover
def test_failover_stream_skips_a_provider_that_fails_early():
    class Broken(StreamingClient):
        def iter_stream(self, prompt, *, context="", system="", on_usage=None):
            raise LLMError("down")
            yield  # pragma: no cover

    client = FailoverClient([("broken", Broken([])), ("good", StreamingClient(["ok"]))])

    assert list(client.iter_stream("hi")) == ["ok"]


def test_failover_stream_commits_once_text_started():
    client = FailoverClient([
        ("flaky", StreamingClient(["a", "b"], fail_after=1)),
        ("backup", StreamingClient(["b"])),
    ])
    chunks: list[str] = []

    with pytest.raises(LLMError):
        for delta in client.iter_stream("hi"):
            chunks.append(delta)

    # "a" was already shown, so the chain must not splice in the backup.
    assert chunks == ["a"]


def test_failover_reports_usage_from_the_provider_that_finishes():
    client = FailoverClient([
        ("broken", StreamingClient(["x"], fail_after=0)),
        ("good", StreamingClient(["ok"], usage=Usage(7, 3))),
    ])
    seen: list = []

    assert list(client.iter_stream("hi", on_usage=seen.append)) == ["ok"]
    assert seen == [Usage(7, 3)]


def test_failover_stream_is_unsupported_without_streaming_clients():
    client = FailoverClient([("whole", WholeClient())])

    assert client.supports_stream() is False


# ------------------------------------------------------------------------ CLI
def test_chat_stream_prints_deltas_as_they_arrive(runner, monkeypatch):
    def fake_iter(self, prompt, *, context="", system="", on_usage=None):
        yield "streamed "
        yield "answer"

    monkeypatch.setattr("nusa_rg.llm.api_client.ApiClient.iter_stream", fake_iter)
    monkeypatch.setattr("nusa_rg.llm.api_client.ApiClient.supports_stream",
                        lambda self: True)

    run(runner, ["config", "set", "api_key", "sk-stub", "--secret"])
    result = run(runner, ["chat", "hello", "--stream"])

    assert result.exit_code == 0, result.output
    assert result.output.count("streamed answer") == 1


def test_chat_footer_shows_streamed_token_usage(runner, monkeypatch):
    def fake_iter(self, prompt, *, context="", system="", on_usage=None):
        yield "streamed"
        if on_usage is not None:
            on_usage(Usage(9, 4))

    monkeypatch.setattr("nusa_rg.llm.api_client.ApiClient.iter_stream", fake_iter)
    monkeypatch.setattr("nusa_rg.llm.api_client.ApiClient.supports_stream",
                        lambda self: True)

    run(runner, ["config", "set", "api_key", "sk-stub", "--secret"])
    result = run(runner, ["chat", "--stream"], input="hello\n/exit\n")

    assert result.exit_code == 0, result.output
    assert "13 tok" in result.output


def test_chat_stream_flag_falls_back_to_the_whole_answer(runner, monkeypatch):
    monkeypatch.setattr("nusa_rg.llm.api_client.ApiClient.supports_stream",
                        lambda self: False)
    monkeypatch.setattr(
        "nusa_rg.llm.api_client.ApiClient.generate",
        lambda self, q, **kw: LLMResponse(text="whole answer", usage=Usage(),
                                          provider="stub"),
    )

    run(runner, ["config", "set", "api_key", "sk-stub", "--secret"])
    result = run(runner, ["chat", "hello", "--stream"])

    assert result.exit_code == 0, result.output
    assert result.output.count("whole answer") == 1


def test_chat_no_stream_waits_for_the_whole_answer(runner, monkeypatch):
    monkeypatch.setattr("nusa_rg.llm.api_client.ApiClient.supports_stream",
                        lambda self: True)
    monkeypatch.setattr(
        "nusa_rg.llm.api_client.ApiClient.generate",
        lambda self, q, **kw: LLMResponse(text="whole answer", usage=Usage(2, 3),
                                          provider="stub"),
    )

    run(runner, ["config", "set", "api_key", "sk-stub", "--secret"])
    result = run(runner, ["chat", "hello", "--no-stream"])

    assert result.exit_code == 0, result.output
    assert result.output.count("whole answer") == 1
