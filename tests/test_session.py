"""Persistent chat sessions: storage, resume wiring, and CLI commands."""

from __future__ import annotations

import json
import stat

import pytest
from click.testing import CliRunner

from nusa_rg.cli import main
from nusa_rg.engine import CoreEngine
from nusa_rg.llm.api_client import ApiClient
from nusa_rg.llm.base import LLMClient, LLMResponse, Usage
from nusa_rg.llm.failover import FailoverClient
from nusa_rg.session import Session, SessionError, SessionStore


@pytest.fixture
def runner():
    return CliRunner()


def run(runner, args, **kwargs):
    return runner.invoke(main, args, **kwargs)


def install_fake_api(monkeypatch, replies=("stub answer",)):
    """Replace the network call and record the history sent per turn."""
    calls: list[dict] = []

    def fake_generate(self, query, *, context="", system="", stream=False,
                      history=None):
        calls.append({"query": query, "history": history})
        answer = replies[min(len(calls) - 1, len(replies) - 1)]
        return LLMResponse(text=answer, usage=Usage(3, 2), provider="stub")

    monkeypatch.setattr("nusa_rg.llm.api_client.ApiClient.generate", fake_generate)
    return calls


def set_api_key(runner):
    result = run(runner, ["config", "set", "api_key", "sk-stub", "--secret"])
    assert result.exit_code == 0, result.output


# ------------------------------------------------------------------- storage
def test_store_round_trip_and_permissions(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    created = store.create("work", project="/tmp/project", style="caveman")
    created.add_turn("first question", "first answer")
    store.save(created)

    loaded = store.load("work")
    assert loaded.id == "work"
    assert loaded.project == "/tmp/project"
    assert loaded.style == "caveman"
    assert loaded.turns == 1
    assert loaded.messages[-1] == {"role": "assistant", "content": "first answer"}
    assert loaded.title == "first question"
    assert stat.S_IMODE(loaded.path.stat().st_mode) == 0o600
    assert stat.S_IMODE(store.directory.stat().st_mode) == 0o700


def test_store_lists_newest_first_and_deletes(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    older = store.create("older")
    newer = store.create("newer")
    older.updated_at = "2026-01-01T00:00:00Z"
    newer.updated_at = "2026-02-01T00:00:00Z"
    store.save(older)
    store.save(newer)

    assert [item.id for item in store.list()] == ["newer", "older"]
    store.delete("newer")
    assert not store.exists("newer")
    with pytest.raises(SessionError):
        store.load("newer")


@pytest.mark.parametrize("bad", ["", "../escape", "a/b", ".hidden", "x" * 65])
def test_invalid_session_ids_are_rejected(tmp_path, bad):
    store = SessionStore(tmp_path / "sessions")
    with pytest.raises(SessionError):
        store.path(bad)


def test_corrupt_session_is_skipped_by_list_but_not_by_load(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    store.create("good")
    (store.directory / "broken.json").write_text("{not json", encoding="utf-8")

    assert [item.id for item in store.list()] == ["good"]
    with pytest.raises(SessionError):
        store.load("broken")


def test_history_keeps_whole_recent_turns():
    session = Session(id="demo")
    for number in range(3):
        session.add_turn(f"q{number}", f"a{number}")

    history = session.history(max_turns=2, max_chars=10_000)
    assert [item["content"] for item in history] == [
        "q1", "a1", "q2", "a2"
    ]
    assert session.history(max_turns=0) == []


def test_history_character_budget_keeps_the_newest_turn():
    session = Session(id="demo")
    for number in range(3):
        session.add_turn(f"question {number}", f"answer {number}")

    history = session.history(max_turns=10, max_chars=1)
    assert [item["content"] for item in history] == ["question 2", "answer 2"]


# -------------------------------------------------------------------- resume
def test_chat_one_shot_resumes_and_saves_history(runner, monkeypatch):
    set_api_key(runner)
    calls = install_fake_api(monkeypatch, ("answer one", "answer two"))

    first = run(runner, ["chat", "first", "--session", "work", "--no-rag"])
    second = run(runner, ["chat", "second", "--session", "work", "--no-rag"])

    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    assert calls[0]["history"] is None
    assert calls[1]["history"] == [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "answer one"},
    ]
    assert "resumed session work" in second.output

    saved = SessionStore().load("work")
    assert saved.turns == 2
    assert saved.messages[0] == {"role": "user", "content": "first"}
    assert saved.messages[-1] == {"role": "assistant", "content": "answer two"}


def test_chat_interactive_session_appends_each_turn(runner, monkeypatch):
    set_api_key(runner)
    calls = install_fake_api(monkeypatch)

    first = run(runner, ["chat", "--session", "shell", "--no-rag"],
                input="hello\n/exit\n")
    assert first.exit_code == 0, first.output
    assert calls[0]["history"] is None
    assert SessionStore().load("shell").turns == 1

    second = run(runner, ["chat", "--session", "shell", "--no-rag"],
                 input="again\n/exit\n")
    assert second.exit_code == 0, second.output
    assert calls[1]["history"] == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "stub answer"},
    ]
    assert SessionStore().load("shell").turns == 2


def test_clear_empties_saved_session_history(runner, monkeypatch):
    set_api_key(runner)
    install_fake_api(monkeypatch)

    result = run(runner, ["chat", "--session", "clear-me", "--no-rag"],
                 input="hello\n/clear\n/exit\n")

    assert result.exit_code == 0, result.output
    assert "context cleared" in result.output
    assert SessionStore().load("clear-me").messages == []


def test_session_command_creates_and_switches(runner):
    result = run(runner, ["chat"], input=(
        "/session new demo\n"
        "/session list\n"
        "/session show\n"
        "/exit\n"
    ))

    assert result.exit_code == 0, result.output
    assert "session demo created" in result.output
    assert "Sessions (1)" in result.output
    assert "Session demo" in result.output
    assert SessionStore().load("demo").turns == 0


def test_session_use_reports_missing_id(runner):
    result = run(runner, ["chat"], input="/session use missing\n/exit\n")

    assert result.exit_code == 0
    assert "not found" in result.output


def test_invalid_session_flag_is_a_click_error(runner):
    result = run(runner, ["chat", "--session", "../nope", "hi"])

    assert result.exit_code != 0
    assert "session id" in result.output


# --------------------------------------------------------------- CLI surface
def test_session_cli_creates_lists_shows_and_deletes(runner):
    created = run(runner, ["session", "new", "demo", "--project", "/tmp/p"])
    assert created.exit_code == 0, created.output
    assert "session demo created" in created.output
    assert SessionStore().exists("demo")

    listed = run(runner, ["session", "list"])
    assert listed.exit_code == 0
    assert "Sessions (1)" in listed.output
    assert "demo" in listed.output
    assert "0 turn(s)" in listed.output

    shown = run(runner, ["session", "show", "demo"])
    assert shown.exit_code == 0
    assert "Session demo" in shown.output
    assert "/tmp/p" in shown.output

    refused = run(runner, ["session", "delete", "demo"])
    assert refused.exit_code == 2
    assert "--yes" in refused.output

    deleted = run(runner, ["session", "delete", "demo", "--yes"])
    assert deleted.exit_code == 0
    assert not SessionStore().exists("demo")


def test_session_cli_show_can_limit_messages(runner):
    store = SessionStore()
    saved = store.create("demo")
    for number in range(3):
        saved.add_turn(f"q{number}", f"a{number}")
    store.save(saved)

    result = run(runner, ["session", "show", "demo", "--last", "2"])

    assert result.exit_code == 0
    assert "q2" in result.output
    assert "a2" in result.output
    assert "q0" not in result.output


def test_session_cli_new_generates_an_id(runner):
    result = run(runner, ["session", "new"])

    assert result.exit_code == 0, result.output
    stored = SessionStore().list()
    assert len(stored) == 1
    assert stored[0].id in result.output
    assert stored[0].path.exists()


def test_run_session_requires_ask(runner):
    result = run(runner, ["run", "--session", "debug", "echo", "hi"])

    assert result.exit_code == 2
    assert "--ask" in result.output
    assert not SessionStore().exists("debug")


def test_run_ask_appends_to_session(runner, monkeypatch):
    set_api_key(runner)
    install_fake_api(monkeypatch)

    result = run(runner, [
        "run", "--session", "debug", "--ask", "what happened?",
        "echo", "hello",
    ])

    assert result.exit_code == 0, result.output
    saved = SessionStore().load("debug")
    assert saved.turns == 1
    assert saved.messages[0] == {"role": "user", "content": "what happened?"}
    assert saved.messages[1] == {"role": "assistant", "content": "stub answer"}


# ------------------------------------------------------------------- payload
class _FakeResponse:
    def __init__(self, payload=None, lines=None):
        self.status_code = 200
        self._payload = payload or {}
        self._lines = lines or []

    def read(self):
        return json.dumps(self._payload).encode()

    def json(self):
        return self._payload

    def iter_lines(self, chunk_size=512):
        return iter(self._lines)


HISTORY = [
    {"role": "user", "content": "old question"},
    {"role": "assistant", "content": "old answer"},
]


def test_api_client_puts_history_between_system_and_current_turn():
    captured: dict = {}
    client = ApiClient("https://example.test/v1", "sk", "model")

    def fake_post(payload, stream=False):
        captured.update(payload)
        return _FakeResponse(payload={
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        })

    client._post = fake_post
    client.generate("current", system="system prompt", history=HISTORY)

    assert captured["messages"] == [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "old question"},
        {"role": "assistant", "content": "old answer"},
        {"role": "user", "content": "current"},
    ]


def test_api_stream_also_sends_history():
    captured: dict = {}
    client = ApiClient("https://example.test/v1", "sk", "model")

    def fake_post(payload, stream=False):
        captured.update(payload)
        return _FakeResponse(lines=[
            'data: {"choices":[{"delta":{"content":"ok"}}]}',
            "data: [DONE]",
        ])

    client._post = fake_post
    assert list(client.iter_stream("current", history=HISTORY)) == ["ok"]
    assert captured["messages"] == [
        {"role": "user", "content": "old question"},
        {"role": "assistant", "content": "old answer"},
        {"role": "user", "content": "current"},
    ]


class _HistoryClient(LLMClient):
    name = "history"

    def __init__(self):
        self.history = None

    def generate(self, prompt, *, context="", system="", stream=False,
                 history=None):
        self.history = history
        return LLMResponse(text="ok", usage=Usage(), provider=self.name)


def test_engine_passes_history_to_the_client(monkeypatch):
    client = _HistoryClient()
    monkeypatch.setattr("nusa_rg.engine.llm.build_client", lambda config: client)

    CoreEngine().ask("current", skip_retrieval=True, history=HISTORY)

    assert client.history == HISTORY


def test_engine_streams_with_history(monkeypatch):
    class StreamingHistoryClient(_HistoryClient):
        def supports_stream(self):
            return True

        def iter_stream(self, prompt, *, context="", system="", history=None,
                        on_usage=None):
            self.history = history
            yield "ok"

    client = StreamingHistoryClient()
    monkeypatch.setattr("nusa_rg.engine.llm.build_client", lambda config: client)

    CoreEngine().ask("current", skip_retrieval=True, history=HISTORY,
                     on_token=lambda delta: None)

    assert client.history == HISTORY


def test_failover_forwards_history():
    client = _HistoryClient()
    FailoverClient([("one", client)]).generate("current", history=HISTORY)

    assert client.history == HISTORY


def test_local_runner_renders_history_into_the_prompt():
    from nusa_rg.llm.local import _with_history

    rendered = _with_history(HISTORY, "current")

    assert "old question" in rendered
    assert "Assistant: old answer" in rendered
    assert rendered.endswith("User: current\nAssistant:")
