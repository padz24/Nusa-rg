"""Command-line interface (FR-05, FR-06, FR-13..FR-16).

Entry point: ``rag-assist`` with sub-commands ``chat``, ``index``, ``config``,
plus ``status`` and ``doctor`` for diagnostics.
"""

from __future__ import annotations

import sys

import click

from . import __version__, crypto, paths, render, ui
from . import update as update_mod
from .config import Config, ConfigError
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
  rag-assist index ~/projects/my-app       Index a project directory
  rag-assist chat                          Start an interactive session
  rag-assist chat "explain this traceback" One-shot question, then exit
  rag-assist config show                    Print the current configuration
  rag-assist config set provider local      Switch to the llama.cpp path
  rag-assist status                         Show index and provider state

In chat, type /exit (or Ctrl+D) to quit, and /clear to start a new topic.
"""


@click.group(context_settings=CONTEXT_SETTINGS, epilog=EPILOG)
@click.version_option(__version__, "-V", "--version", prog_name="rag-assist")
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging.")
@click.option("--no-colour", "--no-color", is_flag=True, help="Disable ANSI colours.")
@click.pass_context
def main(ctx: click.Context, verbose: bool, no_colour: bool) -> None:
    """Coding assistant for Termux with local-project RAG.

    \b
    Environment:
      RAG_ASSIST_HOME   Override the state directory (default ~/.rag-assist)
      NO_COLOR          Set to disable ANSI colours
    """
    if no_colour:
        ui.set_colour(False)
    configure(verbose=verbose)
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose


# --------------------------------------------------------------------- chat
EXIT_COMMANDS = {"/exit", "/quit", "/q"}
CLEAR_COMMANDS = {"/clear", "/reset"}
HELP_COMMANDS = {"/help", "/?"}
UPDATE_COMMANDS = {"/update", "/upgrade"}


def _print_chat_help() -> None:
    """List the session commands."""
    ui.heading("Chat commands")
    for command, description in (
        ("/exit", "leave the session (Ctrl+D works too)"),
        ("/quit", "alias for /exit"),
        ("/clear", "forget the current topic and start over"),
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
            ui.info("run: pkg upgrade termux-rag-assist")
        return

    print(f"  installed  {info.installed_version}")
    print(f"  latest     {info.remote_version or 'unknown'}")
    print(f"  checkout   {info.source_dir}")

    if info.remote_version is None:
        ui.error(info.detail or "could not reach the remote")
        return
    if not info.available:
        ui.success("already up to date")
        return
    if info.dirty and not force:
        ui.error("the checkout has uncommitted changes; "
                 "commit them, or run 'rag-assist update --force'")
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
    ui.info("the running session continues; restart rag-assist to pick up "
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
@click.option("--stream", is_flag=True, help="Stream the API response as it arrives.")
@click.option("--markdown/--no-markdown", default=True,
              help="Render Markdown (code blocks, bold, lists). Enabled by default.")
@click.option("--plain", is_flag=True,
              help="Print the raw Markdown source with no formatting.")
@click.option("--index/--no-index", "do_index", default=True,
              help="Index the project automatically if it is missing or stale.")
def chat(message: str | None, project: str | None, no_rag: bool,
          stream: bool, markdown: bool, plain: bool, do_index: bool) -> None:
    """Start an interactive chat session, or answer a single message."""
    engine = CoreEngine()

    target = project or engine.config.project_path()
    if target and do_index and not no_rag:
        _auto_index(engine, target)

    if message:
        _single_turn(engine, message, no_rag=no_rag, stream=stream,
                     plain=plain, markdown=markdown)
        return

    _interactive_loop(engine, no_rag=no_rag, stream=stream,
                      plain=plain, markdown=markdown)


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
        ui.highlight_snippet(snippet)


def _single_turn(engine: CoreEngine, message: str, *, no_rag: bool, stream: bool,
                 plain: bool = False, markdown: bool = True) -> None:
    ui.heading(f"rag-assist {__version__}")
    try:
        with ui.thinking():
            turn = engine.ask(message, stream=stream, skip_retrieval=no_rag)
    except LLMError as exc:
        ui.error(str(exc))
        return
    _print_retrieval(turn.retrieval)
    print()
    _emit(turn.answer, plain=plain, markdown=markdown)
    engine.close()


def _interactive_loop(engine: CoreEngine, *, no_rag: bool, stream: bool,
                      plain: bool = False, markdown: bool = True) -> None:
    ui.heading(f"rag-assist {__version__} - type /exit to quit, /help for commands")
    root = engine.config.project_path()
    provider = engine.config.get("model_provider", "external")
    ui.info(f"provider: {provider} | project: {root or '(none indexed)'}")
    try:
        files, chunks = engine.index.count()
        if files:
            ui.info(f"index: {files} file(s), {chunks} chunk(s)")
        elif not no_rag:
            ui.info("index: empty - run 'rag-assist index <path>' "
                    "for context-aware answers")
    except Exception:  # noqa: BLE001 - a broken index must not block chat
        pass

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
            ui.info("context cleared")
            continue
        if command in HELP_COMMANDS:
            _print_chat_help()
            continue
        if command in UPDATE_COMMANDS:
            _run_update()
            continue

        if raw.endswith("\\"):
            raw = raw[:-1] + "\n" + _read_multi_line()

        try:
            with ui.thinking():
                turn = engine.ask(raw, stream=stream, skip_retrieval=no_rag)
        except LLMError as exc:
            ui.error(str(exc))
            continue
        except KeyboardInterrupt:
            print()
            ui.warn("cancelled")
            continue

        _print_retrieval(turn.retrieval)
        print(ui.assistant_prompt())
        _emit(turn.answer, plain=plain, markdown=markdown)
        usage = turn.response.usage
        if usage.prompt_tokens or usage.completion_tokens:
            ui.info(f"[{turn.retrieval.duration:.2f}s retrieval | "
                    f"{usage.prompt_tokens}+{usage.completion_tokens} tokens]")

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
def config_set(key: str | None, value: str | None, secret: bool) -> None:
    """Set a configuration value.

    \b
    Examples:
      rag-assist config set provider local
      rag-assist config set api_model llama-3.1-8b-instant
      rag-assist config set default_project_path ~/projects/app
      rag-assist config set api_key --secret          (prompts without echo)
      rag-assist config set system_prompt "You are terse."
    """
    settings = Config()

    if key is None:
        ui.error("missing KEY. Run 'rag-assist config set --help' for usage.")
        sys.exit(2)

    if key == "provider":
        if value is None:
            ui.error("provider requires a value: external, local, openai, or groq")
            sys.exit(2)
        try:
            settings.set_provider(value)
        except ConfigError as exc:
            ui.error(str(exc))
            sys.exit(2)
        ui.success(f"provider set to '{value}'")
        return

    if key == "api_key":
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

    # Coerce numeric-looking values so YAML stores ints, not strings.
    coerced: object = value
    if value.lstrip("-").replace(".", "", 1).isdigit():
        coerced = float(value) if "." in value else int(value)
    settings.set(key, coerced, audit_event=f"config.set.{key}")
    ui.success(f"{key} = {value}")


@config.command("path")
def config_path_cmd() -> None:
    """Print the resolved paths of the state directory."""
    ui.heading("Paths")
    for label, value in (
        ("config", paths.config_path()),
        ("index", paths.index_db_path()),
        ("keystore", paths.keystore_path()),
        ("log", paths.app_log_path()),
        ("audit", paths.audit_log_path()),
    ):
        print(f"  {ui.paint(label, ui.BOLD):<10} {value}")


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
    Config, credentials and the index live in ~/.rag-assist and are never
    touched. A checkout installed from a package manager cannot self-update;
    this command says so and points at `pkg upgrade`.
    """
    info = update_mod.check()

    if info.method != update_mod.METHOD_SOURCE:
        ui.warn(info.summary())
        if info.method == update_mod.METHOD_PACKAGE:
            ui.info("run: pkg upgrade termux-rag-assist")
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
    print(f"  installed  {info.installed_version}")
    print(f"  latest     {info.remote_version or 'unknown'}")
    print(f"  checkout   {info.source_dir}")
    print(f"  branch     {info.branch or 'unknown'}")

    if info.remote_version is None:
        ui.error(info.detail or "could not reach the remote")
        sys.exit(1)

    if check_only:
        if info.available:
            ui.info("an update is available; run: rag-assist update")
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
    print(f"  provider  {settings.get('model_provider')}")
    print(f"  model     {settings.get('api_model')}")
    print(f"  base url  {settings.provider_base_url()}")
    print(f"  api key   {'set (encrypted)' if settings.has_api_key() else 'not set'}")

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

    binary = shutil.which(str(settings.get("local_llama_bin", "llama-cli")) or "")
    check("llama.cpp binary", bool(binary), binary or "not installed (local mode unavailable)")

    ui.info("")
    ui.success("all checks passed") if ok else ui.warn("some checks failed")
    audit("doctor", "SUCCESS" if ok else "FAILED")
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()