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
  nusa-rg chat "explain this traceback" One-shot question, then exit
  nusa-rg providers list --search qwen  Browse 200+ provider entries
  nusa-rg config set provider deepseek  Switch provider in one command
  nusa-rg run --ask "why?" pytest -x    Run a command, ask about its output
  nusa-rg config show                    Print the current configuration
  nusa-rg config set provider local      Switch to the llama.cpp path
  nusa-rg status                         Show index and provider state

In chat, type /exit (or Ctrl+D) to quit, /clear to start a new topic,
/caveman to toggle terse answers, and !command to run a terminal command.
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
      NUSA_RG_HOME    Override the state directory (default ~/.nusa-rg)
      NO_COLOR        Set to disable ANSI colours
      NUSA_RG_NO_ANIM Set to skip the banner intro animation
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
    rows = [
        (("/exit", "bold"), "leave the session (Ctrl+D works too)"),
        (("/quit", "bold"), "alias for /exit"),
        (("/clear", "bold"), "forget the current topic and start over"),
        (("/caveman [on|off]", "bold"), "toggle terse answers that save output tokens"),
        (("!command", "bold"), "run a terminal command; its output becomes context"),
        (("/help", "bold"), "show this list"),
        (("/update", "bold"), "update a source checkout to the latest release"),
    ]
    ui.data_table(["command", "description"], rows, header=False)


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

    ui.key_values([
        ("installed", info.installed_version),
        ("latest", info.remote_version or "unknown"),
        ("checkout", info.source_dir),
    ], label_width=10)

    if info.remote_version is None:
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
            line = input(ui.paint("  ... > " if lines else "  > ", ui.DIM))
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


@main.command()
@click.argument("message", required=False)
@click.option("--project", "-p", default=None, help="Project directory to index first.")
@click.option("--no-rag", is_flag=True, help="Answer without retrieving project context.")
@click.option("--stream/--no-stream", default=None,
              help="Stream the answer as it arrives (default: on in an interactive terminal).")
@click.option("--markdown/--no-markdown", default=True,
              help="Render Markdown (code blocks, bold, lists). Enabled by default.")
@click.option("--plain", is_flag=True,
              help="Print the raw Markdown source with no formatting.")
@click.option("--index/--no-index", "do_index", default=True,
              help="Index the project automatically if it is missing or stale.")
@click.option("--caveman", is_flag=True,
              help="Answer in telegraphic style to cut output tokens (also /caveman).")
def chat(message: str | None, project: str | None, no_rag: bool,
          stream: bool | None, markdown: bool, plain: bool, do_index: bool,
          caveman: bool) -> None:
    """Start an interactive chat session, or answer a single message."""
    engine = CoreEngine()
    session_style = "caveman" if caveman else None

    target = project or engine.config.project_path()
    if target and do_index and not no_rag:
        _auto_index(engine, target)

    if message:
        _single_turn(engine, message, no_rag=no_rag, stream=stream,
                     plain=plain, markdown=markdown, style=session_style)
        return

    _interactive_loop(engine, no_rag=no_rag, stream=stream,
                      plain=plain, markdown=markdown, style=session_style)


def _auto_index(engine: CoreEngine, target: str) -> None:
    """Index the configured project when the index has never been built."""
    try:
        current = engine.index.project_root
    except Exception:  # noqa: BLE001 - a broken index must not block chat
        current = ""
    if current:
        return

    try:
        if ui.is_interactive():
            with ui.index_progress() as reporter:
                stats = engine.index_project(target, on_event=reporter.emit)
        else:
            ui.info(f"no index yet; indexing {target} ...")
            stats = engine.index_project(target)
        ui.success(stats.summary())
    except (OSError, ValueError) as exc:
        ui.warn(f"indexing skipped: {exc}")


def _emit(text: str, *, plain: bool, markdown: bool) -> None:
    """Print an answer, rendering Markdown unless disabled."""
    if plain or not markdown:
        print(text)
    else:
        print(render.render_markdown(text))


def _print_retrieval(result) -> None:
    if not result.snippets:
        return
    ui.info(f"retrieved {len(result.snippets)} snippet(s) in {result.duration:.2f}s")
    for snippet in result.snippets:
        if ui.is_interactive():
            _print_snippet(snippet)
        else:
            ui.highlight_snippet(snippet)


def _print_snippet(snippet, max_lines: int = 12) -> None:
    """A retrieved snippet as a syntax-highlighted panel (interactive only)."""
    lines = snippet.content.rstrip("\n").splitlines()
    body = "\n".join(lines[:max_lines])
    note = "" if len(lines) <= max_lines else \
        f"... (+{len(lines) - max_lines} more lines)"
    ui.snippet_panel(
        f"context {snippet.path}:{snippet.start_line}-{snippet.end_line}",
        render.highlight_code(body, render.language_for_path(snippet.path)),
        note=note,
    )


class _AnswerStream:
    """Prints an answer while it streams, blocking to paragraph boundaries.

    Markdown mode reuses ``render.MarkdownStream`` so a fragment is only shown
    once it renders cleanly; plain mode writes each delta straight through.
    """

    def __init__(self, *, plain: bool, markdown: bool, before_first=None) -> None:
        self._markdown = render.MarkdownStream() if markdown and not plain else None
        self._before_first = before_first
        self.emitted = False
        self._last = ""

    def _write(self, fragment: str) -> None:
        sys.stdout.write(fragment)
        self._last = fragment

    def feed(self, delta: str) -> None:
        if not self.emitted:
            self.emitted = True
            if self._before_first is not None:
                self._before_first()
        if self._markdown is None:
            self._write(delta)
        else:
            for fragment in self._markdown.feed(delta):
                self._write(fragment)
        sys.stdout.flush()

    def finish(self) -> None:
        if not self.emitted:
            return
        if self._markdown is not None:
            for fragment in self._markdown.close():
                self._write(fragment)
        if not self._last.endswith("\n"):
            sys.stdout.write("\n")
        sys.stdout.flush()


def _ask_turn(engine: CoreEngine, message: str, *, no_rag: bool,
              style: str | None, stream: bool | None, plain: bool,
              markdown: bool, command_output: str = "", before_first=None):
    """Run one turn, streaming the answer when that is appropriate.

    Returns ``(turn, streamer, retrieval_shown)``. ``streamer`` is ``None``
    for a whole-answer turn; otherwise ``streamer.emitted`` says whether text
    was shown (a provider without streaming support returns the answer whole).
    ``retrieval_shown`` reports whether snippets were already printed while
    generation was still pending.
    """
    streaming = stream if stream is not None else ui.is_interactive()
    if not streaming:
        with ui.thinking():
            turn = engine.ask(message, stream=False, skip_retrieval=no_rag,
                              style=style, command_output=command_output)
        return turn, None, False

    spinner = ui.Spinner().start()
    streamer = _AnswerStream(plain=plain, markdown=markdown,
                             before_first=before_first)
    shown = {"retrieval": False}

    def on_retrieval(result) -> None:
        if result.snippets:
            spinner.stop()
            _print_retrieval(result)
            shown["retrieval"] = True

    def on_delta(delta: str) -> None:
        spinner.stop()
        streamer.feed(delta)

    try:
        turn = engine.ask(message, stream=False, skip_retrieval=no_rag,
                          style=style, command_output=command_output,
                          on_retrieval=on_retrieval, on_delta=on_delta)
    finally:
        spinner.stop()
    return turn, streamer, shown["retrieval"]


def _single_turn(engine: CoreEngine, message: str, *, no_rag: bool, stream: bool | None,
                 plain: bool = False, markdown: bool = True,
                 style: str | None = None) -> None:
    ui.heading(f"nusa-rg {__version__}")
    try:
        turn, streamer, retrieval_shown = _ask_turn(
            engine, message, no_rag=no_rag, style=style, stream=stream,
            plain=plain, markdown=markdown, before_first=print,
        )
    except LLMError as exc:
        ui.error(str(exc))
        engine.close()
        return
    if streamer is not None and streamer.emitted:
        streamer.finish()
    else:
        if not retrieval_shown:
            _print_retrieval(turn.retrieval)
        print()
        _emit(turn.answer, plain=plain, markdown=markdown)
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


def _interactive_loop(engine: CoreEngine, *, no_rag: bool, stream: bool | None,
                      plain: bool = False, markdown: bool = True,
                      style: str | None = None) -> None:
    ui.banner()
    ui.heading(f"nusa-rg {__version__} - type /exit to quit, /help for commands")
    root = engine.config.project_path()
    provider = engine.config.get("model_provider", "external")
    ui.info(f"provider: {provider} | project: {root or '(none indexed)'}")
    try:
        files, chunks = engine.index.count()
        if files:
            ui.info(f"index: {files} file(s), {chunks} chunk(s)")
        elif not no_rag:
            ui.info("index: empty - run 'nusa-rg index <path>' "
                    "for context-aware answers")
    except Exception:  # noqa: BLE001 - a broken index must not block chat
        pass

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
            ui.info("context cleared")
            continue
        if command in HELP_COMMANDS:
            _print_chat_help()
            continue
        if command in UPDATE_COMMANDS:
            _run_update()
            continue
        words = command.split()
        if words and words[0] in STYLE_COMMANDS:
            session_style = _toggle_style(engine.config, command, session_style)
            continue
        if raw.startswith("!"):
            pending_command = _capture_command(engine.config, raw[1:].strip()) \
                or pending_command
            continue

        if raw.endswith("\\"):
            raw = raw[:-1] + "\n" + _read_multi_line()

        try:
            turn, streamer, retrieval_shown = _ask_turn(
                engine, raw, no_rag=no_rag, style=session_style, stream=stream,
                plain=plain, markdown=markdown, command_output=pending_command,
                before_first=lambda: print(ui.assistant_prompt()),
            )
        except LLMError as exc:
            ui.error(str(exc))
            continue
        except KeyboardInterrupt:
            print()
            ui.warn("cancelled")
            continue

        pending_command = ""
        if streamer is not None and streamer.emitted:
            streamer.finish()
        else:
            if not retrieval_shown:
                _print_retrieval(turn.retrieval)
            print(ui.assistant_prompt())
            _emit(turn.answer, plain=plain, markdown=markdown)
        if turn.response.used_fallback:
            ui.info(f"answered via fallback provider: {turn.response.provider}")
        usage = turn.response.usage
        if usage.prompt_tokens or usage.completion_tokens:
            ui.info(f"[{turn.retrieval.duration:.2f}s retrieval | "
                    f"{usage.prompt_tokens}+{usage.completion_tokens} tokens]")

    engine.close()


# ---------------------------------------------------------------------- run
@main.command("run")
@click.argument("command", nargs=-1, required=True)
@click.option("--ask", "-a", "question", default=None,
              help="Ask a question with the command output as context.")
@click.option("--raw", is_flag=True, help="Do not route the command through rtk.")
@click.option("--timeout", type=int, default=None,
              help="Seconds before the command is stopped (default: command_timeout).")
@click.option("--project", "-p", default=None, help="Project directory to index first.")
@click.option("--no-rag", is_flag=True, help="Answer without retrieving project context.")
@click.option("--stream/--no-stream", default=None,
              help="Stream the answer as it arrives (default: on in an interactive terminal).")
@click.option("--caveman", is_flag=True, help="Answer in telegraphic style.")
@click.option("--plain", is_flag=True, help="Print the raw Markdown answer.")
@click.option("--markdown/--no-markdown", default=True, help="Render Markdown.")
def run_cmd(command: tuple[str, ...], question: str | None, raw: bool,
            timeout: int | None, project: str | None, no_rag: bool,
            stream: bool | None, caveman: bool, plain: bool, markdown: bool) -> None:
    """Run a terminal command (through rtk when installed).

    \b
    Examples:
      nusa-rg run git status
      nusa-rg run --ask "what broke?" pytest -x
      nusa-rg run "git diff --stat"

    The exit code is the command's own, so it composes with scripts.
    """
    settings = Config()
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
    target = project or engine.config.project_path()
    if target and not no_rag:
        _auto_index(engine, target)
    try:
        turn, streamer, retrieval_shown = _ask_turn(
            engine, question, no_rag=no_rag,
            style="caveman" if caveman else None, stream=stream,
            plain=plain, markdown=markdown,
            command_output=result.for_prompt(), before_first=print,
        )
    except LLMError as exc:
        ui.error(str(exc))
        engine.close()
        sys.exit(1)
    if streamer is not None and streamer.emitted:
        streamer.finish()
    else:
        if not retrieval_shown:
            _print_retrieval(turn.retrieval)
        print()
        _emit(turn.answer, plain=plain, markdown=markdown)
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
        with ui.index_progress() as reporter:
            stats = engine.index_project(path, force=force, on_event=reporter.emit)
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

    ui.index_summary(stats)
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
    ui.key_values(
        [(key, data[key]) for key in sorted(data)],
        label_width=28,
        truncate=72,
    )
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
    ui.key_values([
        ("config", paths.config_path()),
        ("index", paths.index_db_path()),
        ("keystore", paths.keystore_path()),
        ("catalog", paths.catalog_path()),
        ("log", paths.app_log_path()),
        ("audit", paths.audit_log_path()),
    ], label_width=10)


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
def providers_list(search: str, show_all: bool, limit: int) -> None:
    """List providers; only ready-to-use ones by default."""
    catalogue = _load_catalog()
    total, models = catalogue.counts()
    ready = sum(1 for entry in catalogue.providers.values() if entry.selectable)
    ui.heading(f"Providers ({total} listed, {ready} ready to use)")
    ui.info(f"snapshot: {catalogue.fetched_at or 'bundled'} | "
            f"{models} models in total")
    rows = catalogue.search(search, compatible_only=not show_all)
    if ui.is_interactive():
        ui.data_table(["", "id", "name", "models"], [
            [
                ("●", "nusa.mint") if entry.selectable else ("○", "dim"),
                (entry.id, "bold"),
                entry.name,
                str(entry.model_count),
            ]
            for entry in rows[:limit]
        ])
    else:
        for entry in rows[:limit]:
            mark = ui.paint("ok", ui.GREEN) if entry.selectable else ui.paint("--", ui.GREY)
            print(f"  [{mark}] {ui.paint(f'{entry.id:<28}', ui.BOLD)}"
                  f"{entry.name[:30]:<32}{entry.model_count:>5} models")
    if len(rows) > limit:
        ui.info(f"... {len(rows) - limit} more; raise --limit or narrow --search")
    if not rows:
        ui.info("no provider matches; try: nusa-rg providers refresh")


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
    rows = [
        ("id", provider.id),
        ("endpoint", provider.api or "(not published - set api_base_url)"),
        ("key", ", ".join(provider.env) or "(none listed)"),
        ("models", provider.model_count),
        ("default", provider.default_model or "(none picked)"),
    ]
    if provider.doc:
        rows.append(("docs", provider.doc))
    rows.append(("compatible",
                 ("yes", "nusa.ok") if provider.selectable else ("no", "nusa.warn")))
    ui.key_values(rows, label_width=10)
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
    table_rows = []
    for model_id, model in rows[:limit]:
        context = model.get("context")
        context_text = f"{context // 1000}k" if isinstance(context, int) and context else "?"
        cost_in, cost_out = model.get("input"), model.get("output")
        if isinstance(cost_in, (int, float)) or isinstance(cost_out, (int, float)):
            left = cost_in if isinstance(cost_in, (int, float)) else "?"
            right = cost_out if isinstance(cost_out, (int, float)) else "?"
            cost_text = f"${left}/${right} per M tokens"
        else:
            cost_text = ""
        table_rows.append([(model_id, "bold"), context_text, (cost_text, "dim")])
    ui.data_table(["id", "context", "cost"], table_rows,
                  aligns=["left", "right", "left"],
                  no_wrap=[False, True, True],
                  overflow=["fold", "ellipsis", "ellipsis"])
    if len(rows) > limit:
        ui.info(f"... {len(rows) - limit} more; raise --limit or narrow --search")


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
    ui.key_values([
        ("installed", info.installed_version),
        ("latest", info.remote_version or "unknown"),
        ("checkout", info.source_dir),
        ("branch", info.branch or "unknown"),
    ], label_width=10)

    if info.remote_version is None:
        ui.error(info.detail or "could not reach the remote")
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
        ui.info(f"update {info.installed_version} -> {info.remote_version}?")
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
    key_state = "set" if settings.api_key_for(provider_id) else "not set"
    style = str(settings.get("response_style", "default") or "default")
    rows = [
        ("provider", f"{provider}" + (f" ({provider_id})" if provider_id else "")),
        ("model", settings.get("api_model")),
        ("base url", settings.provider_base_url()),
        ("api key", key_state +
         (" (keystore/encrypted)" if key_state == "set" else "")),
        ("style", style_mod.describe(style)),
    ]
    entries = settings.fallback_entries()
    if entries:
        chain = " -> ".join(pid + (f":{model}" if model else "") for pid, model in entries)
        rows.append(("fallback", f"{provider_id or provider} -> {chain}"))

    try:
        with ProjectIndex() as idx:
            root = idx.project_root
            files, chunks = idx.count()
        rows.append(("index", f"{files} file(s), {chunks} chunk(s)"))
        rows.append(("root", root or "(none)"))
    except Exception as exc:  # noqa: BLE001
        rows.append(("index", f"unavailable ({exc})"))
    ui.key_values(rows, label_width=10)

    engine = CoreEngine(settings)
    try:
        ok, message = engine.health_check()
    except LLMError as exc:
        ok, message = False, str(exc)
    engine.close()

    if ui.is_interactive():
        ui.key_values([("llm", (message, "nusa.ok" if ok else "nusa.warn"))],
                      label_width=10)
    else:
        (ui.success if ok else ui.warn)(f"  llm       {message}")
    log_event("status", level="INFO" if ok else "WARN", llm_ok=ok)


@main.command()
def doctor() -> None:
    """Run installation and security self-checks."""
    ui.heading("Diagnostics")
    import shutil
    import sqlite3

    ok = True
    rows: list[tuple[str, str, str, str]] = []

    def check(label: str, passed: bool, detail: str = "") -> None:
        nonlocal ok
        ok = ok and passed
        rows.append(("PASS" if passed else "FAIL",
                     "nusa.ok" if passed else "nusa.error", label, detail))

    def note(label: str, detail: str = "") -> None:
        rows.append(("INFO", "dim", label, detail))

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

    ui.check_rows(rows)

    ui.info("")
    ui.success("all checks passed") if ok else ui.warn("some checks failed")
    audit("doctor", "SUCCESS" if ok else "FAILED")
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()