"""Command-line interface (FR-05, FR-06, FR-13..FR-16).

Entry point: ``nusa-rg`` with sub-commands ``chat``, ``index``, ``config``,
plus ``status`` and ``doctor`` for diagnostics.
"""

from __future__ import annotations

import sys

import click

from . import __version__, crypto, paths, render, ui
from . import catalog as catalog_mod
from . import command as command_mod
from . import live as live_mod
from . import logos as logos_mod
from . import session as session_mod
from . import style as style_mod
from . import update as update_mod
from .command import CommandError
from .config import Config, ConfigError, PROVIDERS
from .engine import CoreEngine
from .llm.base import LLMError
from .logging_setup import audit, configure, log_event
from .rag import ProjectIndex

CONTEXT_SETTINGS = {
    "help_option_names": ["-h", "--help"],
    "max_content_width": 100,
}

EPILOG = """
Examples:
  nusa-rg index ~/projects/my-app       Index a project directory
  nusa-rg chat                          Start an interactive session
  nusa-rg chat --session fix-auth       Resume a saved session
  nusa-rg chat "explain this traceback" One-shot question, then exit
  nusa-rg providers list --search qwen  Browse 200+ provider entries
  nusa-rg config set provider deepseek  Switch provider in one command
  nusa-rg run --ask "why?" pytest -x    Run a command, ask about its output
  nusa-rg config show                    Print the current configuration
  nusa-rg config set provider local      Switch to the llama.cpp path
  nusa-rg status                         Show index and provider state

In chat, type /exit (or Ctrl+D) to quit, /clear to start a new topic,
/session to manage saved conversations, /caveman to toggle terse answers,
and !command to run a terminal command.
"""


@click.group(context_settings=CONTEXT_SETTINGS, epilog=EPILOG,
             invoke_without_command=True)
@click.version_option(__version__, "-V", "--version", prog_name="nusa-rg")
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging.")
@click.option("--no-colour", "--no-color", is_flag=True, help="Disable ANSI colours.")
@click.pass_context
def main(ctx: click.Context, verbose: bool, no_colour: bool) -> None:
    """Coding assistant for Termux with local-project RAG.

    \b
    Environment:
      NUSA_RG_HOME   Override the state directory (default ~/.nusa-rg)
      NO_COLOR       Set to disable ANSI colours
    """
    if no_colour:
        ui.set_colour(False)
    configure(verbose=verbose)
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose

    if ctx.invoked_subcommand is None:
        # Bare invocation: show the emblem above the command list. The exit
        # code stays 2, as click used for a no-arguments group.
        ui.banner()
        click.echo(ctx.get_help())
        ctx.exit(2)


# --------------------------------------------------------------------- chat
EXIT_COMMANDS = {"/exit", "/quit", "/q"}
CLEAR_COMMANDS = {"/clear", "/reset"}
HELP_COMMANDS = {"/help", "/?"}
UPDATE_COMMANDS = {"/update", "/upgrade"}
STYLE_COMMANDS = {"/caveman", "/style"}


def _print_chat_help() -> None:
    """List the session commands."""
    ui.heading("Chat commands")
    for command, description in (
        ("/exit", "leave the session (Ctrl+D works too)"),
        ("/quit", "alias for /exit"),
        ("/clear", "forget the current topic and clear saved history"),
        ("/session [show|list|new|use|delete]", "manage persistent chat sessions"),
        ("/caveman [on|off]", "toggle terse answers that save output tokens"),
        ("!command", "run a terminal command; its output becomes context"),
        ("/help", "show this list"),
        ("/update", "update a source checkout to the latest release"),
    ):
        print(f"  {ui.paint(command, ui.BOLD)}  {description}")


def _run_update(force: bool = False) -> None:
    """Update from inside a chat session (the ``/update`` command).

    Interactive sessions cannot answer a confirmation prompt reliably while a
    prompt is on screen, so this checks and reports, and only proceeds when the
    checkout is clean. Anything ambiguous is reported rather than guessed.
    """
    info = update_mod.check()

    if info.method != update_mod.METHOD_SOURCE:
        ui.warn(info.summary())
        if info.method == update_mod.METHOD_PACKAGE:
            ui.info("run: pkg upgrade termux-nusa-rg")
        return

    latest = info.remote_version
    if latest is None and info.remote_head:
        latest = f"commit {info.remote_head[:12]}"
    print(f"  installed  {info.installed_version}")
    print(f"  latest     {latest or 'unknown'}")
    print(f"  checkout   {info.source_dir}")

    if info.remote_version is None and info.available is None:
        ui.error(info.detail or "could not reach the remote")
        return
    if not info.available:
        ui.success("already up to date")
        return
    if info.dirty and not force:
        ui.error("the checkout has uncommitted changes; "
                 "commit them, or run 'nusa-rg update --force'")
        return

    ui.info("updating; this can take a few minutes ...")
    try:
        with ui.thinking("Updating"):
            result = update_mod.perform(info, force=force)
    except update_mod.UpdateError as exc:
        ui.error(str(exc))
        return

    for step in result.steps:
        print(ui.paint(f"  - {step}", ui.GREY))
    if not result.ok:
        ui.error(result.detail or "the update did not complete")
        return
    ui.success(f"updated {result.old_version} -> {result.new_version}"
               if result.changed else "already at the latest commit")
    ui.info("the running session continues; restart nusa-rg to pick up "
            "the new code")


def _read_multi_line() -> str:
    """Collect input until a blank line, supporting multi-line code (AC-37).

    A single-line prompt is accepted as soon as Enter is pressed on the first
    line; a blank line terminates an explicitly continued block. Completion
    stays active here too, so a file path can be completed mid-block.
    """
    print(ui.paint("  (enter a blank line to finish a multi-line block, /exit to quit)",
                   ui.DIM))
    lines: list[str] = []
    while True:
        try:
            line = input(ui.readline_safe(
                ui.paint("  ... > " if lines else "  > ", ui.DIM)))
        except EOFError:
            print()
            return "\n".join(lines)
        if not line.strip() and lines:
            break
        if not line.strip() and not lines:
            continue
        lines.append(line)
        # A trailing "\n" escape also closes the block.
        if line.endswith("\\n"):
            lines[-1] = line[:-2]
            break
    return "\n".join(lines)


def _session_id_callback(ctx, param, value):
    """Validate a session id at parse time so bad ids fail before any work."""
    if value is None:
        return None
    try:
        return session_mod.validate_id(value)
    except session_mod.SessionError as exc:
        raise click.BadParameter(str(exc)) from exc


def _history_turns(engine: CoreEngine) -> int:
    """Read the history window, tolerating an older config without the key."""
    try:
        return max(0, int(engine.config.get("session_history_turns", 10) or 0))
    except (TypeError, ValueError):
        return session_mod.DEFAULT_HISTORY_TURNS


def _session_history(engine: CoreEngine, session) -> list[dict[str, str]] | None:
    if session is None:
        return None
    return session.history(max_turns=_history_turns(engine))


def _save_session(store, session) -> bool:
    """Persist a session without turning a disk error into a traceback."""
    if store is None or session is None:
        return False
    try:
        store.save(session)
        return True
    except session_mod.SessionError as exc:
        ui.error(f"session not saved: {exc}")
        return False


def _format_stamp(value: str) -> str:
    """Render an ISO-8601 UTC timestamp compactly for the terminal."""
    return value.replace("T", " ").replace("Z", "")[:16] if value else "unknown"


def _print_session(session, *, show_messages: bool = False,
                   last: int | None = None) -> None:
    ui.heading(f"Session {session.id}")
    print(f"  created  {_format_stamp(session.created_at)}")
    print(f"  updated  {_format_stamp(session.updated_at)}")
    print(f"  turns    {session.turns}")
    print(f"  style    {session.style or 'configured default'}")
    print(f"  project  {session.project or '(current project)'}")
    print(f"  path     {session.path or session_mod.SessionStore().path(session.id)}")
    if not show_messages or not session.messages:
        return
    print()
    messages = session.messages if last is None else session.messages[-max(1, last):]
    for item in messages:
        label = "you" if item["role"] == "user" else "assistant"
        body = item["content"].strip()
        lines = body.splitlines() or [""]
        print(f"  {label}: {lines[0]}")
        for line in lines[1:]:
            print(f"  {' ' * len(label)}  {line}")


def _print_sessions(sessions) -> None:
    if not sessions:
        ui.info("no saved sessions")
        return
    ui.heading(f"Sessions ({len(sessions)})")
    for item in sessions:
        print(f"  {ui.paint(f'{item.id:<26}', ui.BOLD)}"
              f"{item.turns:>3} turn(s)  {_format_stamp(item.updated_at):<16}  "
              f"{item.title}")


@main.command()
@click.argument("message", required=False)
@click.option("--project", "-p", default=None, help="Project directory to index first.")
@click.option("--no-rag", is_flag=True, help="Answer without retrieving project context.")
@click.option("--stream", is_flag=True,
              help="Stream the answer live over SSE (the default in a terminal).")
@click.option("--no-stream", is_flag=True,
              help="Wait for the whole answer instead of streaming it.")
@click.option("--markdown/--no-markdown", default=True,
              help="Render Markdown (code blocks, bold, lists). Enabled by default.")
@click.option("--plain", is_flag=True,
              help="Print the raw Markdown source with no formatting.")
@click.option("--index/--no-index", "do_index", default=True,
              help="Index the project automatically if it is missing or stale.")
@click.option("--caveman", is_flag=True,
              help="Answer in telegraphic style to cut output tokens (also /caveman).")
@click.option("--session", "--session-id", "session_id", default=None,
              callback=_session_id_callback,
              help="Resume or create a named chat session.")
def chat(message: str | None, project: str | None, no_rag: bool,
          stream: bool, no_stream: bool, markdown: bool, plain: bool,
          do_index: bool, caveman: bool, session_id: str | None) -> None:
    """Start an interactive chat session, or answer a single message."""
    engine = CoreEngine()
    stream = _resolve_stream(engine, stream, no_stream)
    session_style = "caveman" if caveman else None

    store = None
    session = None
    target = project or engine.config.project_path()
    if session_id:
        store = session_mod.SessionStore()
        try:
            session = store.open(
                session_id,
                project=target or "",
                style=session_style or "",
            )
        except session_mod.SessionError as exc:
            ui.error(str(exc))
            engine.close()
            sys.exit(2)

        if project and session.project != target:
            session.project = target
            _save_session(store, session)
        if not target and session.project:
            target = session.project
        if session.messages:
            ui.info(f"resumed session {session.id} ({session.turns} turn(s))")
        else:
            ui.info(f"session {session.id}")
        session_style = session.style or session_style
        if session_style and session.style != session_style:
            session.set_style(session_style)
            _save_session(store, session)

    if target and do_index and not no_rag:
        _auto_index(engine, target)

    history = _session_history(engine, session)
    if message:
        turn = _single_turn(engine, message, no_rag=no_rag, stream=stream,
                            plain=plain, markdown=markdown, style=session_style,
                            history=history)
        if session is not None and store is not None and turn is not None:
            session.add_turn(message, turn.answer)
            _save_session(store, session)
        return

    _interactive_loop(engine, no_rag=no_rag, stream=stream,
                      plain=plain, markdown=markdown, style=session_style,
                      session=session, store=store, project=target or "")


def _auto_index(engine: CoreEngine, target: str) -> None:
    """Index the configured project when the index has never been built."""
    try:
        current = engine.index.project_root
    except Exception:  # noqa: BLE001 - a broken index must not block chat
        current = ""
    if current:
        return

    try:
        ui.info(f"no index yet; indexing {target} ...")
        stats = engine.index_project(target)
        ui.success(stats.summary())
    except (OSError, ValueError) as exc:
        ui.warn(f"indexing skipped: {exc}")


def _emit(text: str, *, plain: bool, markdown: bool, lead: str = "") -> None:
    """Print an answer, rendering Markdown unless disabled.

    ``lead`` (the assistant marker) shares the first line with the answer,
    except when the answer opens with a block element that needs its own line.
    """
    body = text if plain or not markdown else render.render_markdown(text)
    body = body.lstrip("\n")
    block_start = text.lstrip().startswith(("```", "|", "---", "#", ">"))
    if lead and body and not block_start:
        print(lead + body)
        return
    if lead:
        print(lead.rstrip())
    print(body)


def _print_retrieval(result) -> None:
    if not result.snippets:
        return
    ui.info(f"retrieved {len(result.snippets)} snippet(s) in {result.duration:.2f}s")
    for snippet in result.snippets:
        ui.highlight_snippet(snippet)


def _resolve_stream(engine: CoreEngine, stream: bool, no_stream: bool) -> bool:
    """Decide whether the answer streams.

    The flags win. Without one, a terminal streams as long as the engine can
    deliver tokens live (SSE); an engine without the hooks keeps its old path.
    """
    if no_stream:
        return False
    if stream:
        return True
    return sys.stdout.isatty() and live_mod.supports_live(engine)


def _run_turn(engine: CoreEngine, message: str, *, stream: bool, no_rag: bool,
              plain: bool, markdown: bool, style: str | None = None,
              command_output: str = "", history: list[dict[str, str]] | None = None,
              lead: str = "", gap: bool = False):
    """Ask the engine, print the context and the answer, and return the turn.

    With ``stream`` and an engine that has the live hooks, the answer is printed
    as the tokens arrive. Anything else takes the classic path: a spinner, then
    the whole answer. ``gap`` puts a blank line before the answer.
    """
    options: dict = {"stream": stream, "skip_retrieval": no_rag, "style": style}
    if command_output:
        options["command_output"] = command_output
    if history:
        options["history"] = history

    if stream and live_mod.supports_live(engine):
        live = live_mod.LiveTurn(show_retrieval=_print_retrieval, emit=_emit,
                                 plain=plain, markdown=markdown, lead=lead, gap=gap)
        try:
            with ui.thinking() as spinner:
                live.attach(spinner)
                turn = engine.ask(message, **options, **live.hooks(engine))
        except BaseException:
            live.abort()
            raise
        if live.finish(turn.answer):
            if not live.retrieval_shown:
                _print_retrieval(turn.retrieval)  # engine never called on_retrieval: late, not lost
            return turn
        # Nothing arrived token by token (a one-shot reply): print it the classic way.
        retrieval_shown = live.retrieval_shown
    else:
        with ui.thinking():
            turn = engine.ask(message, **options)
        retrieval_shown = False

    if not retrieval_shown:
        _print_retrieval(turn.retrieval)
    if gap:
        print()
    _emit(turn.answer, plain=plain, markdown=markdown, lead=lead)
    return turn


def _single_turn(engine: CoreEngine, message: str, *, no_rag: bool, stream: bool,
                 plain: bool = False, markdown: bool = True,
                 style: str | None = None,
                 history: list[dict[str, str]] | None = None):
    ui.heading(f"nusa-rg {__version__}")
    try:
        return _run_turn(engine, message, stream=stream, no_rag=no_rag,
                         plain=plain, markdown=markdown, style=style,
                         history=history, gap=True)
    except LLMError as exc:
        ui.error(str(exc))
        return None
    finally:
        engine.close()


def _run_terminal_command(text: str, settings: Config, *, use_rtk: bool | None = None):
    """Execute a ``!command`` line under the configured limits."""
    argv = command_mod.split_command(text)
    if use_rtk is None:
        use_rtk = bool(settings.get("command_use_rtk", True))
    return command_mod.run(
        argv,
        timeout=int(settings.get("command_timeout", command_mod.DEFAULT_TIMEOUT)
                    or command_mod.DEFAULT_TIMEOUT),
        limit=int(settings.get("command_output_limit", command_mod.DEFAULT_LIMIT)
                  or command_mod.DEFAULT_LIMIT),
        use_rtk=use_rtk,
    )


def _print_command(result) -> None:
    """Show a finished command exactly as the model will receive it."""
    ui.heading(f"$ {result.display}")
    if result.output:
        print(result.output)
    ui.info(result.summary())


def _capture_command(settings: Config, text: str) -> str:
    """Run one ``!command``, print it, and return its prompt block.

    Returns an empty string when nothing was run, so callers can keep any
    previously captured output.
    """
    if not text:
        ui.info("usage: !<command>   e.g. !git status")
        return ""
    try:
        with ui.thinking("Running command"):
            result = _run_terminal_command(text, settings)
    except CommandError as exc:
        ui.error(str(exc))
        return ""
    _print_command(result)
    ui.info("output kept - your next question will be answered with it")
    return result.for_prompt()


def _toggle_style(settings: Config, command: str, current: str | None) -> str:
    """Handle ``/caveman [on|off]`` and return the session style to use."""
    parts = command.split()
    requested = parts[1] if len(parts) > 1 else ""
    effective = current or str(settings.get("response_style", "default") or "default")
    if requested in ("on", "1"):
        chosen = "caveman"
    elif requested in ("off", "0"):
        chosen = "default"
    else:
        chosen = "default" if effective == "caveman" else "caveman"
    ui.info(f"response style: {style_mod.describe(chosen)}")
    return chosen


def _session_usage() -> None:
    ui.heading("Session commands")
    for command, description in (
        ("/session [show [id]]", "show the active or a saved session"),
        ("/session list", "list saved sessions"),
        ("/session new [id]", "start a new session (id is generated when omitted)"),
        ("/session use <id>", "switch to a saved session"),
        ("/session delete <id> --yes", "delete a saved session"),
    ):
        print(f"  {ui.paint(command, ui.BOLD)}  {description}")


def _session_command(args: list[str], session, store, style: str | None,
                     project: str):
    """Execute one ``/session`` subcommand and return the new state."""
    store = store or session_mod.SessionStore()
    action = args[0].lower() if args else "show"
    rest = args[1:]

    if action in ("help", "?"):
        _session_usage()
        return session, store, style

    if action == "list":
        _print_sessions(store.list())
        return session, store, style

    if action in ("show", "info"):
        target = session
        if rest:
            try:
                target = store.load(rest[0])
            except session_mod.SessionError as exc:
                ui.error(str(exc))
                return session, store, style
        if target is None:
            ui.info("no active session; start one with /session new [id]")
        else:
            _print_session(target)
        return session, store, style

    if action == "new":
        requested = rest[0] if rest else None
        try:
            new = store.create(requested, project=project, style=style or "")
        except session_mod.SessionError as exc:
            ui.error(str(exc))
            return session, store, style
        ui.success(f"session {new.id} created")
        return new, store, new.style or style

    if action in ("use", "open", "resume"):
        if not rest:
            ui.error("usage: /session use <id>")
            return session, store, style
        try:
            new = store.load(rest[0])
        except session_mod.SessionError as exc:
            ui.error(str(exc))
            return session, store, style
        effective_style = new.style or style
        if effective_style and new.style != effective_style:
            new.set_style(effective_style)
            _save_session(store, new)
        ui.success(f"session {new.id} ({new.turns} turn(s))")
        return new, store, effective_style

    if action in ("delete", "rm"):
        if not rest:
            ui.error("usage: /session delete <id> --yes")
            return session, store, style
        target_id = rest[0]
        if "--yes" not in rest[1:] and "-y" not in rest[1:]:
            ui.error(f"refusing to delete session '{target_id}' without --yes")
            return session, store, style
        try:
            store.delete(target_id)
        except session_mod.SessionError as exc:
            ui.error(str(exc))
            return session, store, style
        ui.success(f"deleted session {target_id}")
        if session is not None and session.id == target_id:
            session = None
        return session, store, style

    _session_usage()
    return session, store, style


def _interactive_loop(engine: CoreEngine, *, no_rag: bool, stream: bool,
                      plain: bool = False, markdown: bool = True,
                      style: str | None = None, session=None, store=None,
                      project: str = "") -> None:
    facts = ui.banner()
    ui.chat_hints(index_empty=not facts.index_ready and not no_rag)

    session_style = style
    pending_command = ""

    while True:
        try:
            raw = input("\n" + ui.user_prompt())
        except (EOFError, KeyboardInterrupt):
            print()
            ui.info("session ended")
            break

        raw = raw.strip()
        if not raw:
            continue

        command = raw.lower()
        if command in EXIT_COMMANDS:
            ui.info("session ended")
            break
        if command in CLEAR_COMMANDS:
            pending_command = ""
            if session is not None and store is not None:
                session.clear()
                _save_session(store, session)
                ui.info("context cleared (session history emptied)")
            else:
                ui.info("context cleared")
            continue
        if command in HELP_COMMANDS:
            _print_chat_help()
            continue
        if command in UPDATE_COMMANDS:
            _run_update()
            continue

        parts = raw.split()
        if parts and parts[0].lower() == "/session":
            session, store, session_style = _session_command(
                parts[1:], session, store, session_style, project)
            continue

        words = command.split()
        if words and words[0] in STYLE_COMMANDS:
            session_style = _toggle_style(engine.config, command, session_style)
            if session is not None and store is not None:
                session.set_style(session_style)
                _save_session(store, session)
            continue
        if raw.startswith("!"):
            pending_command = _capture_command(engine.config, raw[1:].strip()) \
                or pending_command
            continue

        if raw.endswith("\\"):
            raw = raw[:-1] + "\n" + _read_multi_line()

        try:
            turn = _run_turn(engine, raw, stream=stream, no_rag=no_rag,
                             plain=plain, markdown=markdown, style=session_style,
                             command_output=pending_command,
                             history=_session_history(engine, session),
                             lead=ui.assistant_prompt())
        except LLMError as exc:
            ui.error(str(exc))
            continue
        except KeyboardInterrupt:
            print()
            ui.warn("cancelled")
            continue

        pending_command = ""
        if session is not None and store is not None:
            session.add_turn(raw, turn.answer)
            _save_session(store, session)
        if turn.response.used_fallback:
            ui.info(f"answered via fallback provider: {turn.response.provider}")
        usage = turn.response.usage
        ui.footer(turn.retrieval.duration,
                  usage.prompt_tokens + usage.completion_tokens)

    engine.close()


# ------------------------------------------------------------------- session
@main.group()
def session() -> None:
    """Manage saved chat sessions."""


@session.command("list")
def session_list() -> None:
    """List saved sessions, newest first."""
    _print_sessions(session_mod.SessionStore().list())


@session.command("new")
@click.argument("session_id", required=False,
                callback=_session_id_callback)
@click.option("--project", "-p", default=None,
              help="Project path to remember with this session.")
def session_new(session_id: str | None, project: str | None) -> None:
    """Create an empty session and print its id."""
    try:
        created = session_mod.SessionStore().create(
            session_id, project=project or "")
    except session_mod.SessionError as exc:
        ui.error(str(exc))
        sys.exit(1)
    ui.success(f"session {created.id} created")
    print(f"  path  {created.path}")
    ui.info(f"resume with: nusa-rg chat --session {created.id}")


@session.command("show")
@click.argument("session_id", callback=_session_id_callback)
@click.option("--last", type=click.IntRange(min=1), default=None,
              help="Show only the last N messages (default: all).")
def session_show(session_id: str, last: int | None) -> None:
    """Print one session's metadata and recent turns."""
    try:
        saved = session_mod.SessionStore().load(session_id)
    except session_mod.SessionError as exc:
        ui.error(str(exc))
        sys.exit(1)
    _print_session(saved, show_messages=True, last=last)


@session.command("delete")
@click.argument("session_id", callback=_session_id_callback)
@click.option("--yes", is_flag=True,
              help="Confirm permanent deletion.")
def session_delete(session_id: str, yes: bool) -> None:
    """Delete a saved session."""
    if not yes:
        ui.error(f"refusing to delete session '{session_id}' without --yes")
        sys.exit(2)
    try:
        session_mod.SessionStore().delete(session_id)
    except session_mod.SessionError as exc:
        ui.error(str(exc))
        sys.exit(1)
    ui.success(f"deleted session {session_id}")


# ---------------------------------------------------------------------- run
@main.command("run")
@click.argument("command", nargs=-1, required=True)
@click.option("--ask", "-a", "question", default=None,
              help="Ask a question with the command output as context.")
@click.option("--session", "--session-id", "session_id", default=None,
              callback=_session_id_callback,
              help="Append this question to a named chat session (requires --ask).")
@click.option("--raw", is_flag=True, help="Do not route the command through rtk.")
@click.option("--timeout", type=int, default=None,
              help="Seconds before the command is stopped (default: command_timeout).")
@click.option("--project", "-p", default=None, help="Project directory to index first.")
@click.option("--no-rag", is_flag=True, help="Answer without retrieving project context.")
@click.option("--stream", is_flag=True,
              help="Stream the answer live over SSE (the default in a terminal).")
@click.option("--no-stream", is_flag=True,
              help="Wait for the whole answer instead of streaming it.")
@click.option("--caveman", is_flag=True, help="Answer in telegraphic style.")
@click.option("--plain", is_flag=True, help="Print the raw Markdown answer.")
@click.option("--markdown/--no-markdown", default=True, help="Render Markdown.")
def run_cmd(command: tuple[str, ...], question: str | None, raw: bool,
            timeout: int | None, project: str | None, no_rag: bool,
            stream: bool, no_stream: bool, caveman: bool, plain: bool,
            markdown: bool, session_id: str | None) -> None:
    """Run a terminal command (through rtk when installed).

    \b
    Examples:
      nusa-rg run git status
      nusa-rg run --ask "what broke?" pytest -x
      nusa-rg run --session debug --ask "what broke?" pytest -x
      nusa-rg run "git diff --stat"

    The exit code is the command's own, so it composes with scripts.
    """
    settings = Config()
    if session_id and not question:
        ui.error("--session requires --ask; a session stores question/answer turns")
        sys.exit(2)

    session_store = None
    chat_session = None
    if session_id:
        session_store = session_mod.SessionStore()
        try:
            chat_session = session_store.open(session_id,
                                              project=project or "")
        except session_mod.SessionError as exc:
            ui.error(str(exc))
            sys.exit(2)
    if len(command) == 1:
        # A single quoted argument may carry the whole command line.
        try:
            argv = command_mod.split_command(command[0])
        except CommandError as exc:
            ui.error(str(exc))
            sys.exit(2)
    else:
        argv = list(command)

    try:
        with ui.thinking("Running command"):
            result = command_mod.run(
                argv,
                timeout=timeout or int(
                    settings.get("command_timeout", command_mod.DEFAULT_TIMEOUT)
                    or command_mod.DEFAULT_TIMEOUT),
                limit=int(
                    settings.get("command_output_limit", command_mod.DEFAULT_LIMIT)
                    or command_mod.DEFAULT_LIMIT),
                use_rtk=not raw and bool(settings.get("command_use_rtk", True)),
            )
    except CommandError as exc:
        ui.error(str(exc))
        sys.exit(127)

    _print_command(result)

    if not question:
        sys.exit(result.exit_code)

    engine = CoreEngine(settings)
    stream = _resolve_stream(engine, stream, no_stream)
    target = project or engine.config.project_path()
    if not target and chat_session is not None:
        target = chat_session.project
    session_style = "caveman" if caveman else (
        chat_session.style if chat_session is not None else None)
    if chat_session is not None and session_style \
            and chat_session.style != session_style:
        chat_session.set_style(session_style)
        _save_session(session_store, chat_session)
    if target and not no_rag:
        _auto_index(engine, target)
    try:
        turn = _run_turn(
            engine, question, stream=stream, no_rag=no_rag, plain=plain,
            markdown=markdown, style=session_style,
            command_output=result.for_prompt(),
            history=_session_history(engine, chat_session), gap=True)
    except LLMError as exc:
        ui.error(str(exc))
        engine.close()
        sys.exit(1)
    if chat_session is not None and session_store is not None:
        chat_session.add_turn(question, turn.answer)
        _save_session(session_store, chat_session)
    engine.close()


# -------------------------------------------------------------------- index
@main.command()
@click.argument("path", required=False)
@click.option("--force", is_flag=True, help="Re-index every file, ignoring mtimes.")
@click.option("--set-default", is_flag=True,
              help="Also store this path as default_project_path.")
@click.option("--json", "as_json", is_flag=True, help="Emit statistics as JSON.")
def index(path: str | None, force: bool, set_default: bool, as_json: bool) -> None:
    """Scan and index a project directory into the local SQLite FTS5 store."""
    engine = CoreEngine()
    try:
        stats = engine.index_project(path, force=force)
    except FileNotFoundError as exc:
        ui.error(str(exc))
        sys.exit(1)
    except (ConfigError, ValueError) as exc:
        ui.error(str(exc))
        sys.exit(2)
    finally:
        if not set_default:
            engine.close()

    if as_json:
        import json as jsonlib

        click.echo(jsonlib.dumps({
            "root": stats.root,
            "files_scanned": stats.scanned,
            "files_indexed": stats.files_indexed,
            "files_unchanged": stats.files_unchanged,
            "files_skipped": stats.files_skipped,
            "files_removed": stats.files_removed,
            "chunks": stats.chunks,
            "duration_seconds": round(stats.duration, 3),
        }, indent=2))
        return

    ui.heading("Index complete")
    print(f"  root      {stats.root}")
    print(f"  scanned   {stats.scanned} file(s)")
    print(f"  indexed   {stats.files_indexed}")
    print(f"  unchanged {stats.files_unchanged}")
    print(f"  removed   {stats.files_removed}")
    print(f"  chunks    {stats.chunks}")
    print(f"  duration  {stats.duration:.2f}s")
    engine.close()


# ------------------------------------------------------------------- config
@main.group()
def config() -> None:
    """Manage the API key, provider, model, and project path."""
    pass


@config.command("show")
@click.option("--reveal", is_flag=True,
              help="Print the decrypted API key (handle the output carefully).")
def config_show(reveal: bool) -> None:
    """Print the active configuration."""
    settings = Config()
    data = settings.data
    if reveal:
        data["api_key"] = settings.get("api_key", "") or "(unset)"

    ui.heading(f"Configuration ({settings._path})")
    for key in sorted(data):
        value = data[key]
        if isinstance(value, str) and len(value) > 72:
            value = value[:69] + "..."
        print(f"  {ui.paint(key, ui.BOLD):<28} {value}")
    ui.info(f"state directory: {paths.base_dir()}")


@config.command("set")
@click.argument("key", required=False)
@click.argument("value", required=False)
@click.option("--secret", is_flag=True,
              help="Store the value encrypted in the keystore (use for api_key).")
@click.option("--provider", "provider_id", default=None,
              help="Store the key for one catalogue provider, not the default slot.")
def config_set(key: str | None, value: str | None, secret: bool,
               provider_id: str | None) -> None:
    """Set a configuration value.

    \b
    Examples:
      nusa-rg config set provider deepseek
      nusa-rg config set api_model deepseek-flash
      nusa-rg config set api_key --secret                    (default slot)
      nusa-rg config set api_key --provider groq --secret    (per provider)
      nusa-rg config set fallback_providers "groq, deepseek"
      nusa-rg config set response_style caveman
      nusa-rg config set system_prompt "You are terse."
    """
    settings = Config()

    if key is None:
        ui.error("missing KEY. Run 'nusa-rg config set --help' for usage.")
        sys.exit(2)

    if key == "provider":
        if value is None:
            ui.error("provider requires a value: external, local, or any "
                     "catalogue id (see 'nusa-rg providers list')")
            sys.exit(2)
        try:
            report = settings.set_provider(value)
        except ConfigError as exc:
            ui.error(str(exc))
            sys.exit(2)
        shown = report.get("name") or report["provider"]
        ui.success(f"provider set to '{report['provider']}'" +
                   (f" ({shown})" if shown != report["provider"] else ""))
        if report.get("model"):
            ui.info(f"model set to {report['model']} "
                    f"(change it with: nusa-rg config set api_model <id>)")
        if report.get("model_count"):
            ui.info(f"{report['model_count']} model(s) in the catalogue; "
                    f"browse with: nusa-rg providers models {report['provider']}")
        return

    if key == "api_key":
        if provider_id:
            if secret and value is None:
                value = click.prompt(f"API key for {provider_id}",
                                     hide_input=True, confirmation_prompt=True)
            value = value or ""
            try:
                settings.set_provider_key(provider_id, value)
            except (ConfigError, crypto.CredentialStoreError) as exc:
                ui.error(str(exc))
                sys.exit(1)
            if value:
                ui.success(f"API key for '{provider_id}' stored encrypted "
                           "(config.yaml keeps only a reference)")
            else:
                ui.success(f"API key for '{provider_id}' removed")
            return

        if secret and value is None:
            value = click.prompt("API key", hide_input=True, confirmation_prompt=True)
        if value is None:
            value = ""
        if not value:
            crypto.delete_secret("credential/api_key")
            settings.set("api_key", "", audit_event="config.clear_api_key")
            ui.success("API key removed from the keystore")
            return
        try:
            settings.set_api_key(value)
        except crypto.CredentialStoreError as exc:
            # The backend is missing or the keystore is damaged: refuse to
            # continue rather than risk writing the secret anywhere in clear.
            ui.error(str(exc))
            sys.exit(1)
        ui.success("API key stored encrypted (config.yaml keeps only a reference)")
        return

    if value is None:
        ui.error(f"'{key}' requires a value")
        sys.exit(2)

    if key == "fallback_providers":
        _validate_fallbacks(value)

    # Coerce numeric-looking values so YAML stores ints, not strings.
    coerced: object = value
    if value.lstrip("-").replace(".", "", 1).isdigit():
        coerced = float(value) if "." in value else int(value)
    try:
        settings.set(key, coerced, audit_event=f"config.set.{key}")
    except ConfigError as exc:
        ui.error(str(exc))
        sys.exit(2)
    if key == "fallback_providers":
        entries = settings.fallback_entries()
        shown = ", ".join(pid + (f":{model}" if model else "") for pid, model in entries)
        ui.success(f"fallback_providers = {shown or '(cleared)'}")
        if entries:
            ui.info("fallbacks are tried in order when the active provider "
                    "fails; keys come from each provider's own store or env var")
        return
    ui.success(f"{key} = {value}")


def _validate_fallbacks(value: str) -> None:
    """Reject fallback entries that name unknown providers."""
    entries = [part.strip() for part in value.split(",") if part.strip()]
    for entry in entries:
        provider_id = entry.partition(":")[0].strip().lower()
        known = provider_id in PROVIDERS
        if not known:
            try:
                known = catalog_mod.load_catalog().get(provider_id) is not None
            except catalog_mod.CatalogError:
                known = False
        if not known:
            ui.error(f"unknown provider '{provider_id}' in fallback_providers. "
                     "Find ids with: nusa-rg providers list --search <text>")
            sys.exit(2)


@config.command("path")
def config_path_cmd() -> None:
    """Print the resolved paths of the state directory."""
    ui.heading("Paths")
    for label, value in (
        ("config", paths.config_path()),
        ("index", paths.index_db_path()),
        ("sessions", paths.sessions_dir()),
        ("logos", paths.logos_dir()),
        ("keystore", paths.keystore_path()),
        ("catalog", paths.catalog_path()),
        ("log", paths.app_log_path()),
        ("audit", paths.audit_log_path()),
    ):
        print(f"  {ui.paint(label, ui.BOLD):<10} {value}")


# ----------------------------------------------------------------- providers
def _load_catalog() -> "catalog_mod.Catalog":
    try:
        return catalog_mod.load_catalog()
    except catalog_mod.CatalogError as exc:
        ui.error(str(exc))
        sys.exit(1)


@main.group()
def providers() -> None:
    """Browse the bundled catalogue of 200+ providers and their models."""


@providers.command("list")
@click.option("--search", "-s", default="", help="Filter by provider id or name.")
@click.option("--all", "show_all", is_flag=True,
              help="Include providers without an OpenAI-compatible endpoint.")
@click.option("--limit", type=int, default=40, show_default=True)
@click.option("--no-icons", is_flag=True,
              help="Skip the provider logos (no network access).")
def providers_list(search: str, show_all: bool, limit: int, no_icons: bool) -> None:
    """List providers; only ready-to-use ones by default."""
    catalogue = _load_catalog()
    total, models = catalogue.counts()
    ready = sum(1 for entry in catalogue.providers.values() if entry.selectable)
    ui.heading(f"Providers ({total} listed, {ready} ready to use)")
    ui.info(f"snapshot: {catalogue.fetched_at or 'bundled'} | "
            f"{models} models in total | logos: drawn from the registry")
    found = catalogue.search(search, compatible_only=not show_all)
    rows = found[:limit]

    drawings = {} if no_icons else logos_mod.icons([entry.id for entry in rows])
    if drawings:
        cards = [(entry, _provider_card_rows(entry, drawings.get(entry.id, [])))
                 for entry in rows]
        icon_width = max((ui.visible_width(left) for _, card in cards
                          for left, _ in card), default=8)
        for index, (entry, card) in enumerate(cards):
            _print_provider_card(entry, card, icon_width)
            if index < len(cards) - 1:
                print()
    else:
        for index, entry in enumerate(rows):
            _print_provider_row(entry)
            if index < len(rows) - 1:
                print()

    if len(found) > limit:
        ui.info(f"... {len(found) - limit} more; raise --limit or narrow --search")
    if not found:
        ui.info("no provider matches; try: nusa-rg providers refresh")


def _print_provider_row(entry) -> None:
    """One provider on a single line, in its own colour."""
    accent = ui.provider_accent(entry.id)
    mark = ui.paint("ok", ui.GREEN) if entry.selectable else ui.paint("--", ui.GREY)
    print(f"  [{mark}] {ui.paint(f'{entry.id:<28}', accent, ui.BOLD)}"
          f"{entry.name[:30]:<32}{entry.model_count:>5} models")


def _pad(text: str, width: int) -> str:
    """Pad ``text`` on the right, ignoring escape codes."""
    return text + " " * max(0, width - ui.visible_width(text))


def _provider_card_rows(entry, drawing: list[str]) -> list[tuple[str, str]]:
    """The (logo, text) pairs of one provider card, already coloured."""
    accent = ui.provider_accent(entry.id)
    mark = ui.paint("ok", ui.GREEN) if entry.selectable else ui.paint("--", ui.GREY)
    details = [
        f"[{mark}] {ui.paint(entry.id, accent, ui.BOLD)}",
        entry.name,
        f"{entry.model_count} models",
        f"key {', '.join(entry.env) or '(none listed)'}",
    ]

    rows: list[tuple[str, str]] = []
    for index in range(max(len(drawing), len(details))):
        left = drawing[index] if index < len(drawing) else ""
        if not drawing and index == 0:
            left = ui.paint("no logo", ui.DIM)
        elif left:
            left = ui.paint(left, accent)
        right = details[index] if index < len(details) else ""
        rows.append((left, right))
    return rows


def _print_provider_card(entry, rows: list[tuple[str, str]],
                         icon_width: int) -> None:
    """One provider, drawn in its own colour."""
    for left, right in rows:
        print("  " + _pad(left, icon_width) + "  " + right)


@providers.command("show")
@click.argument("provider_id")
def providers_show(provider_id: str) -> None:
    """Show one provider's endpoint, key variable, and default model."""
    catalogue = _load_catalog()
    provider = catalogue.get(provider_id)
    if provider is None:
        ui.error(f"unknown provider '{provider_id}'. "
                 "Try: nusa-rg providers list --search <text>")
        sys.exit(1)
    ui.heading(provider.name)
    drawing = logos_mod.icon(provider.id)
    accent = ui.provider_accent(provider.id)
    for line in drawing:
        print("  " + ui.paint(line, accent))
    print(f"  id          {provider.id}")
    print(f"  endpoint    {provider.api or '(not published - set api_base_url)'}")
    print(f"  key         {', '.join(provider.env) or '(none listed)'}")
    print(f"  models      {provider.model_count}")
    print(f"  default     {provider.default_model or '(none picked)'}")
    if provider.doc:
        print(f"  docs        {provider.doc}")
    ready = ui.paint("yes", ui.GREEN) if provider.selectable else ui.paint("no", ui.YELLOW)
    print(f"  compatible  {ready}")
    if not provider.selectable:
        ui.warn("this endpoint is not OpenAI chat-completions; nusa-rg "
                "cannot call it directly")
    else:
        ui.info(f"switch with: nusa-rg config set provider {provider.id}")


@providers.command("models")
@click.argument("provider_id")
@click.option("--search", "-s", default="", help="Filter by model id or name.")
@click.option("--limit", type=int, default=30, show_default=True)
def providers_models(provider_id: str, search: str, limit: int) -> None:
    """List the models a provider hosts, newest first."""
    catalogue = _load_catalog()
    provider = catalogue.get(provider_id)
    if provider is None:
        ui.error(f"unknown provider '{provider_id}'")
        sys.exit(1)
    rows = catalogue.models(provider_id, search)
    ui.heading(f"{provider.name} - {len(rows)} model(s)")
    for model_id, model in rows[:limit]:
        context = model.get("context")
        context_text = f"{context // 1000}k" if isinstance(context, int) and context else "?"
        cost_in, cost_out = model.get("input"), model.get("output")
        if isinstance(cost_in, (int, float)) or isinstance(cost_out, (int, float)):
            left = cost_in if isinstance(cost_in, (int, float)) else "?"
            right = cost_out if isinstance(cost_out, (int, float)) else "?"
            cost_text = f"${left}/{right} per M tokens"
        else:
            cost_text = ""
        print(f"  {ui.paint(f'{model_id:<46}', ui.BOLD)}{context_text:>8}  {cost_text}")
    if len(rows) > limit:
        ui.info(f"... {len(rows) - limit} more; raise --limit or narrow --search")


@providers.command("icon")
@click.argument("provider_id")
def providers_icon(provider_id: str) -> None:
    """Draw the logo of one provider (models.dev serves an SVG per id)."""
    catalogue = _load_catalog()
    provider = catalogue.get(provider_id)
    if provider is None:
        ui.error(f"unknown provider '{provider_id}'. "
                 "Try: nusa-rg providers list --search <text>")
        sys.exit(1)
    drawing = logos_mod.icon(provider.id)
    accent = ui.provider_accent(provider.id)
    if not drawing:
        ui.warn("the logo of this provider could not be drawn")
        return
    for line in drawing:
        print("  " + ui.paint(line, accent))


@providers.command("refresh")
@click.option("--url", default=catalog_mod.CATALOG_URL, show_default=False,
              help="Catalogue source (default: the models.dev registry).")
@click.option("--timeout", type=int, default=45, show_default=True)
def providers_refresh(url: str, timeout: int) -> None:
    """Fetch a fresh catalogue into the state directory."""
    try:
        with ui.thinking("Fetching catalogue"):
            catalogue = catalog_mod.refresh(url, timeout=timeout)
    except catalog_mod.CatalogError as exc:
        ui.error(str(exc))
        sys.exit(1)
    total, models = catalogue.counts()
    ui.success(f"catalogue updated: {total} providers, {models} models")
    print(f"  stored in {paths.catalog_path()}")


# ------------------------------------------------------------------- update
@main.command()
@click.option("--check", "check_only", is_flag=True,
              help="Only report whether a newer version exists.")
@click.option("--force", is_flag=True,
              help="Discard local changes in the checkout before updating.")
@click.option("--no-install", is_flag=True,
              help="Update the checkout but do not re-run install.sh.")
@click.option("--yes", is_flag=True, help="Do not ask for confirmation.")
def update(check_only: bool, force: bool, no_install: bool, yes: bool) -> None:
    """Update a source checkout to the latest release.

    \b
    Config, credentials and the index live in ~/.nusa-rg and are never
    touched. A checkout installed from a package manager cannot self-update;
    this command says so and points at `pkg upgrade`.
    """
    info = update_mod.check()

    if info.method != update_mod.METHOD_SOURCE:
        ui.warn(info.summary())
        if info.method == update_mod.METHOD_PACKAGE:
            ui.info("run: pkg upgrade termux-nusa-rg")
        audit("update.check", "SKIPPED", f"method={info.method}")
        sys.exit(1 if check_only else 0)

    # Advisory notes go to stdout so they interleave correctly with the rest of
    # this command's output; stderr is reserved for the final failure.
    if info.dirty:
        ui.info("note: the checkout has uncommitted changes")
    note = update_mod.environment_note()
    if note:
        ui.info(f"note: {note}")

    ui.heading("Check for updates")
    latest = info.remote_version
    if latest is None and info.remote_head:
        latest = f"commit {info.remote_head[:12]}"
    print(f"  installed  {info.installed_version}")
    print(f"  latest     {latest or 'unknown'}")
    print(f"  checkout   {info.source_dir}")
    print(f"  branch     {info.branch or 'unknown'}")

    if info.remote_version is None and info.available is None:
        ui.error(info.detail or "could not reach the remote")
        audit("update.check", "FAILED", "source; remote version unavailable")
        sys.exit(1)

    if check_only:
        if info.available:
            ui.info("an update is available; run: nusa-rg update")
        else:
            ui.success("already up to date")
        return

    if not info.available:
        ui.success("already up to date")
        return

    if info.dirty and not force:
        ui.error("uncommitted changes; commit them or re-run with --force")
        sys.exit(1)

    if not yes:
        target = info.remote_version or (
            info.remote_head[:12] if info.remote_head else "latest")
        ui.info(f"update {info.installed_version} -> {target}?")
        if not click.confirm("Proceed", default=True):
            ui.info("cancelled")
            return

    ui.info("updating; this can take a few minutes ...")
    try:
        with ui.thinking("Updating"):
            result = update_mod.perform(info, force=force, runner=not no_install)
    except update_mod.UpdateError as exc:
        ui.error(str(exc))
        audit("update", "FAILED", "update error")
        sys.exit(1)

    for step in result.steps:
        print(ui.paint(f"  - {step}", ui.GREY))

    if not result.ok:
        ui.error(result.detail or "the update did not complete")
        sys.exit(1)

    if result.changed:
        ui.success(f"updated {result.old_version} -> {result.new_version}")
    else:
        ui.success("already at the latest commit")
    if result.detail:
        ui.warn(result.detail)
    ui.info(f"state kept in {update_mod.state_directory()}")


# ------------------------------------------------------------------- status
@main.command()
def status() -> None:
    """Show the provider, index state, and an LLM health check."""
    settings = Config()
    ui.heading("Status")
    provider_id = str(settings.get("api_provider") or "")
    provider = settings.get("model_provider")
    print(f"  provider  {provider}" + (f" ({provider_id})" if provider_id else ""))
    print(f"  model     {settings.get('api_model')}")
    print(f"  base url  {settings.provider_base_url()}")
    key_state = "set" if settings.api_key_for(provider_id) else "not set"
    print(f"  api key   {key_state}" +
          (" (keystore/encrypted)" if key_state == "set" else ""))
    style = str(settings.get("response_style", "default") or "default")
    print(f"  style     {style_mod.describe(style)}")
    entries = settings.fallback_entries()
    if entries:
        chain = " -> ".join(pid + (f":{model}" if model else "") for pid, model in entries)
        print(f"  fallback  {provider_id or provider} -> {chain}")

    try:
        with ProjectIndex() as idx:
            root = idx.project_root
            files, chunks = idx.count()
        print(f"  index     {files} file(s), {chunks} chunk(s)")
        print(f"  root      {root or '(none)'}")
    except Exception as exc:  # noqa: BLE001
        print(f"  index     unavailable ({exc})")

    engine = CoreEngine(settings)
    try:
        ok, message = engine.health_check()
    except LLMError as exc:
        ok, message = False, str(exc)
    engine.close()

    (ui.success if ok else ui.warn)(f"  llm       {message}")
    log_event("status", level="INFO" if ok else "WARN", llm_ok=ok)


@main.command()
def doctor() -> None:
    """Run installation and security self-checks."""
    ui.heading("Diagnostics")
    import shutil
    import sqlite3

    ok = True

    def check(label: str, passed: bool, detail: str = "") -> None:
        nonlocal ok
        ok = ok and passed
        mark = ui.paint("PASS", ui.GREEN) if passed else ui.paint("FAIL", ui.RED)
        print(f"  [{mark}] {label}" + (f" - {detail}" if detail else ""))

    def note(label: str, detail: str = "") -> None:
        mark = ui.paint("INFO", ui.GREY)
        print(f"  [{mark}] {label}" + (f" - {detail}" if detail else ""))

    check("python >= 3.10", sys.version_info >= (3, 10), sys.version.split()[0])
    check("platform", True, f"{sys.platform}")

    with sqlite3.connect(":memory:") as probe:
        try:
            probe.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
            check("sqlite FTS5", True, sqlite3.sqlite_version)
        except sqlite3.OperationalError:
            check("sqlite FTS5", False, "built without FTS5")

    paths.ensure_dirs()
    check("state directory", paths.base_dir().is_dir(), str(paths.base_dir()))

    for label, path in (("config", paths.config_path()),
                        ("index", paths.index_db_path()),
                        ("log", paths.app_log_path())):
        if path.exists():
            mode = oct(path.stat().st_mode & 0o777)
            check(f"{label} permissions", path.stat().st_mode & 0o077 == 0, mode)
        else:
            check(f"{label} permissions", True, "not created yet")

    from . import crypto

    settings = Config()
    api_key = settings.data.get("api_key", "")
    check("no plaintext api key", not (api_key and not crypto.is_reference(api_key)),
          "keystore reference" if crypto.is_reference(api_key) else "none set")

    provider_keys = settings.data.get("provider_keys") or {}
    plaintext = [name for name, value in provider_keys.items()
                 if value and not crypto.is_reference(value)]
    check("no plaintext provider keys", not plaintext,
          ", ".join(plaintext) if plaintext else
          (f"{len(provider_keys)} reference(s)" if provider_keys else "none set"))

    binary = shutil.which(str(settings.get("local_llama_bin", "llama-cli")) or "")
    check("llama.cpp binary", bool(binary), binary or "not installed (local mode unavailable)")

    version = command_mod.rtk_version()
    if version is not None:
        check("rtk", True, f"{version} - command output filtered before it reaches the model")
    else:
        note("rtk", "not installed - optional; install from github.com/rtk-ai/rtk "
                    "to trim command output")

    try:
        catalogue = catalog_mod.load_catalog()
        providers, models = catalogue.counts()
        check("provider catalogue", providers > 0,
              f"{providers} providers, {models} models"
              + (f", snapshot {catalogue.fetched_at}" if catalogue.fetched_at else " (bundled)"))
    except catalog_mod.CatalogError as exc:
        check("provider catalogue", False, str(exc))

    entries = settings.fallback_entries()
    for provider_id, _ in entries:
        provider = None
        try:
            provider = catalog_mod.load_catalog().get(provider_id)
        except catalog_mod.CatalogError:
            provider = None
        if provider is None and provider_id not in PROVIDERS:
            note(f"fallback '{provider_id}'", "unknown provider id; it will be skipped")
        elif provider is not None and not provider.selectable:
            note(f"fallback '{provider_id}'", "not OpenAI-compatible; it will be skipped")
        elif not settings.api_key_for(provider_id):
            note(f"fallback '{provider_id}'", "no key stored and no env var set; "
                                              "it will be skipped")

    ui.info("")
    ui.success("all checks passed") if ok else ui.warn("some checks failed")
    audit("doctor", "SUCCESS" if ok else "FAILED")
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
