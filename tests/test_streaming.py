"""Tests for real answer streaming (FR-18, AC-41, AC-43)."""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from nusa_rg.cli import main
from nusa_rg.engine import CoreEngine
from nusa_rg.llm.base import LLMError, LLMResponse, Usage
from nusa_rg.llm.failover import FailoverClient


class StreamingClient:
    """An LLM client whose only job is emitting preset deltas."""

    name = "stub-stream"

    def __init__(self, deltas, *, fail_after=None):
        self.deltas = deltas
        self.fail_after = fail_after
        self.prompts: list[str] = []

    def supports_stream(self) -> bool:
        return True

    def iter_stream(self, prompt, *, context="", system=""):
        self.prompts.append(prompt)
        for position, delta in enumerate(self.deltas):
            if self.fail_after is not None and position == self.fail_after:
                raise LLMError("stream broke")
            yield delta

    def generate(self, *args, **kwargs):  # pragma: no cover - must not run
        raise AssertionError("generate() must not be called when streaming")

    def health_check(self):
        return True, "ok"

    def close(self):
        pass


class WholeClient:
    """A client without incremental output, like the llama.cpp path."""

    name = "stub-whole"

    def supports_stream(self) -> bool:
        return False

    def generate(self, prompt, *, context="", system="", stream=False):
        return LLMResponse(text="one piece", usage=Usage(1, 2), provider="stub-whole")

    def health_check(self):
        return True, "ok"

    def close(self):
        pass


@pytest.fixture
def stub_client(monkeypatch):
    def install(client):
        monkeypatch.setattr("nusa_rg.engine.llm.build_client", lambda config: client)
        return client
    return install


# --------------------------------------------------------------------- engine
def test_engine_streams_deltas_in_order(stub_client):
    client = stub_client(StreamingClient(["Hello", ", ", "world"]))
    deltas: list[str] = []

    turn = CoreEngine().ask("hi", skip_retrieval=True, on_delta=deltas.append)

    assert deltas == ["Hello", ", ", "world"]
    assert turn.answer == "Hello, world"
    assert turn.response.provider == "stub-stream"
    assert client.prompts, "the composed prompt reached the client"


def test_engine_reports_retrieval_before_the_first_delta(stub_client, indexed):
    stub_client(StreamingClient(["answer"]))
    order: list[tuple] = []

    CoreEngine().ask(
        "how do we hash a password",
        on_retrieval=lambda result: order.append(("retrieval", len(result.snippets))),
        on_delta=lambda delta: order.append(("delta", delta)),
    )

    assert order[0][0] == "retrieval"
    assert order[0][1] >= 1
    assert order[1] == ("delta", "answer")


def test_engine_reports_an_empty_retrieval_too(stub_client):
    stub_client(StreamingClient(["x"]))
    seen: list = []

    CoreEngine().ask("hi", skip_retrieval=True, on_retrieval=seen.append,
                     on_delta=lambda delta: None)

    assert len(seen) == 1
    assert seen[0].snippets == []


def test_engine_without_stream_support_returns_the_whole_answer(stub_client):
    stub_client(WholeClient())
    deltas: list[str] = []

    turn = CoreEngine().ask("hi", skip_retrieval=True, on_delta=deltas.append)

    assert deltas == []
    assert turn.answer == "one piece"


# ------------------------------------------------------------------- failover
def test_failover_stream_skips_a_provider_that_fails_early():
    class Broken:
        name = "broken"

        def supports_stream(self):
            return True

        def iter_stream(self, prompt, *, context="", system=""):
            raise LLMError("down")
            yield  # pragma: no cover

        def generate(self, *args, **kwargs):  # pragma: no cover
            raise AssertionError

    client = FailoverClient([("broken", Broken()), ("good", StreamingClient(["ok"]))])

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


def test_failover_stream_is_unsupported_without_streaming_clients():
    client = FailoverClient([("whole", WholeClient())])

    assert client.supports_stream() is False


# ------------------------------------------------------------------------ CLI
def test_chat_stream_prints_deltas_as_they_arrive(runner, monkeypatch):
    def fake_iter(self, prompt, *, context="", system=""):
        yield "streamed "
        yield "answer"

    monkeypatch.setattr("nusa_rg.llm.api_client.ApiClient.iter_stream", fake_iter)
    monkeypatch.setattr("nusa_rg.llm.api_client.ApiClient.supports_stream",
                        lambda self: True)

    run(runner, ["config", "set", "api_key", "sk-stub", "--secret"])
    result = run(runner, ["chat", "hello", "--stream"])

    assert result.exit_code == 0, result.output
    assert result.output.count("streamed answer") == 1


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


@pytest.fixture
def runner():
    return CliRunner()


def run(runner, args, **kwargs):
    return runner.invoke(main, args, **kwargs)
