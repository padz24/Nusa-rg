# NUSA-RG

A coding assistant that runs entirely in your Android terminal. It indexes your
local project with SQLite FTS5, retrieves the most relevant code snippets for
each question, and answers through either an external LLM API or a local
llama.cpp model. External answers can come from any of 200+ OpenAI-compatible
providers, with optional failover between them, and two token-saving modes keep
the bill down: rtk-compressed command output, and telegraphic "caveman"
answers.

Built to the specification in [`AGENS.md`](AGENS.md).

```
❯ how is the password verified?
  context: src/auth.py:1-14
    def verify_password(password: str, salt: str, digest: str) -> bool:
        """Constant-time password check."""
        return hmac.compare_digest(hash_password(password, salt), digest)
◆
  Use verify_password() at src/auth.py:12; it compares the digest with
  hmac.compare_digest, which avoids leaking timing information.
```

## Why

A general-purpose chatbot cannot see the files in your Termux home directory, so
its answers are generic and you end up pasting code by hand. This tool reads your
project directly and grounds its answers in the actual source.

## Requirements

| | |
| :-- | :-- |
| OS | Android 11+ with Termux 0.118+ (ARM64) |
| Python | 3.10+ |
| Index engine | SQLite compiled with FTS5 (bundled with CPython) |
| Optional | `llama-cli` + a GGUF model, for fully offline use |
| Optional | [`rtk`](https://github.com/rtk-ai/rtk), to compress command output before the model sees it |

Check your environment at any time:

```bash
nusa-rg doctor
```

## Install

```bash
git clone https://github.com/padz24/Nusa-rg.git ~/nusa-rg
cd ~/nusa-rg && ./install.sh
```

Or, once published to a Termux repository:

```bash
pkg install termux-nusa-rg
```

## Quick start

```bash
# 1. Store a provider key (encrypted, never written to config.yaml)
nusa-rg config set api_key --secret

# 2. Point it at a project
nusa-rg index ~/projects/my-app

# 3. Ask questions
nusa-rg chat
nusa-rg chat "explain this traceback"     # one-shot
```

## Commands

| Command | Purpose |
| :-- | :-- |
| `nusa-rg chat` | Interactive session (`/exit`, `/clear`, `/session`, `/caveman`, `!command`, `/help`) |
| `nusa-rg chat "msg"` | Single question, then exit |
| `nusa-rg chat --session <id>` | Resume or create a saved conversation |
| `nusa-rg session list` | List saved conversations, newest first |
| `nusa-rg session show <id>` | Show a session's metadata and turns |
| `nusa-rg session delete <id> --yes` | Delete a saved conversation |
| `nusa-rg run <cmd>` | Run a command (through rtk when installed); `--ask "…"` answers with its output as context |
| `nusa-rg index <path>` | Scan and index a project |
| `nusa-rg providers list` | Browse the bundled catalogue of 200+ providers |
| `nusa-rg providers show <id>` | Endpoint, key variable, and default model for one provider |
| `nusa-rg providers models <id>` | The models a provider hosts, newest first |
| `nusa-rg providers icon <id>` | Draw the logo of one provider and print its address |
| `nusa-rg providers refresh` | Fetch a fresh catalogue from models.dev |
| `nusa-rg config show` | Print active configuration |
| `nusa-rg config set <key> <value>` | Change a setting (`--secret` for keys, `--provider <id>` for per-provider keys) |
| `nusa-rg config path` | Show where state files live |
| `nusa-rg status` | Provider, model, style, fallback chain, index state, connectivity |
| `nusa-rg update` | Update a source checkout to the latest release |
| `nusa-rg doctor` | Installation and security self-checks |

Useful flags: `--json` on `index`, `--no-rag` on `chat`, `--project/-p`,
`--stream`, `--session/--session-id` on `chat` and `run --ask`, `--force` on
`index`, `--reveal` on `config show`, `--caveman` on `chat` and `run`, `--raw`
on `run`.

## Sessions

Every chat keeps a session. `nusa-rg chat` starts one automatically, shows
which one it is, and saves each turn as it happens:

```text
  session    20261021-010019-2144
  turns      0
  project    /home/user/projects/my-app
  stored     /home/user/.nusa-rg/sessions/20261021-010019-2144.json
resume with: nusa-rg chat --session 20261021-010019-2144
```

The same block is printed again when the session ends, so the id and the
command that brings the conversation back are at hand when you leave.

Give it an id to pick a conversation back up:

```bash
nusa-rg chat --session fix-auth
nusa-rg chat --session fix-auth "and why does that happen?"
nusa-rg run --session fix-auth --ask "what failed?" pytest -x
```

Inside the chat, manage sessions without leaving the prompt:

```
/session [show [id]]        show the active or a saved session
/session list               list saved sessions
/session new [id]           start a new session (id is generated when omitted)
/session use <id>           switch to a saved session
/session delete <id> --yes  delete one
```

The CLI equivalent is `nusa-rg session list|show|delete`; `session new [id]`
creates an empty session and prints its id. Stored sessions live in
`~/.nusa-rg/sessions/<id>.json` with owner-only permissions. Only the
conversation text is persisted; retrieved code is rebuilt from the index on
each turn. Prompt history is capped by `session_history_turns` (default 10
turns), while the file keeps the full transcript.

`/clear` empties the saved history of the running session as well.

## Providers

`nusa-rg` bundles a catalogue of **232 providers and 8,600+ models**, a
trimmed snapshot of [models.dev](https://models.dev), so browsing works
offline. 209 of those providers speak the OpenAI chat-completions protocol and
are ready to use with nothing more than an API key.

```bash
nusa-rg providers list                      # ready-to-use providers
nusa-rg providers list --search deep            # filter by id or name
nusa-rg providers show deepseek             # endpoint, key variable, default model
nusa-rg providers models deepseek           # its models, newest first
nusa-rg providers icon deepseek             # draw one provider's logo
nusa-rg providers refresh                   # replace the snapshot with a fresh copy
```

### Provider icons

Every provider has a logo on the registry: `https://models.dev/logos/<id>.svg`.
`nusa-rg` fetches those SVGs once, caches them in `~/.nusa-rg/logos`, and
draws each one next to its provider — a terminal cannot show SVG, so the file
is rasterised into Braille cells.

Every entry carries its own colour, picked from a palette by the provider id,
and the entries are separated by a blank line so they never run together:

```text
  ⢀⣴⣾⣿⣿⣶⣄⠀  [ok] 302ai
  ⣾⣿⣿⣿⣿⣿⣿⣧  302.AI
  ⢻⣿⣿⣿⣿⣿⣿⡿  122 models
  ⠀⠙⠿⣿⣿⡿⠟⠁  key 302AI_API_KEY

  ⠀⢀⠀⡄⢠⠀⡀⠀  [ok] abacus
  ⠀⠸⠀⠆⢸⠀⣃⠀  Abacus
  ⠀⢙⠀⡇⠰⠀⡅⠀  103 models
  ⠀⠈⠀⠃⠘⠀⠁⠀  key ABACUS_API_KEY
```

```bash
nusa-rg providers list          # every provider, in its own colour
nusa-rg providers list --limit 40
nusa-rg providers show deepseek # the logo of one provider
nusa-rg providers icon deepseek # just the logo
```

`providers list --no-icons` (or `NUSA_RG_NO_LOGOS=1`) keeps the compact
one-line table and never touches the network; the same happens when the
registry cannot be reached.

Switching is a config change and takes effect on the next turn — no reinstall,
no terminal restart. Setting a provider also picks its default model, which
`config set api_model` can override.

```bash
nusa-rg config set provider deepseek
nusa-rg config set provider groq
nusa-rg config set provider local
nusa-rg config set local_model_path ~/models/qwen2.5-coder-7b-q4_k_m.gguf
nusa-rg config set local_llama_bin ~/llama.cpp/build/bin/llama-cli
```

Each provider's key can come from the environment variable models.dev lists for
it, or from the encrypted keystore — stored per provider:

```bash
export GROQ_API_KEY=...                                   # env var path
nusa-rg config set api_key --provider groq --secret    # keystore path
```

Lookup order is: per-provider keystore entry → provider environment variable →
the legacy shared `api_key` slot. `status` shows the key state for the active
provider; `doctor` lists every per-provider reference.

Anything OpenAI-compatible still works with `api_base_url` set by hand — the
catalogue's key variable and docs are there to help wire it up. Ten providers
whose base URL models.dev leaves to its SDK (OpenAI, Groq, Mistral, Perplexity,
xAI, Cerebras, DeepInfra, Together, AIHubMix, Venice) have known endpoints
built in.

### Failover

Name one or more fallback providers and `nusa-rg` moves down the chain when
the active one fails, so a rate limit or an outage no longer ends the session:

```bash
nusa-rg config set fallback_providers "groq, deepseek:deepseek-flash"
```

Entries are `id` or `id:model`; use the model form to pick a specific model on
that provider. Fallbacks use each provider's own key (keystore or environment
variable); one without a key is skipped, with the reason recorded in the log
and reported by `doctor`. When a fallback answers, the turn says so, and
`status` prints the whole chain.

> **Reasoning models.** Some models (including Ollama's `beam`) spend the first
> part of the token budget reasoning and can return an empty answer when that
> budget runs out. `nusa-rg` detects this and reports it with the partial
> reasoning attached, rather than showing a blank reply. Raise the ceiling with
> `nusa-rg config set max_tokens 4096`.

> **Ollama Cloud** is not in models.dev; point at it directly with
> `nusa-rg config set api_base_url https://ollama.com/v1`.

## Saving tokens: rtk and Caveman

Two independent levers, one on each side of the bill.

### rtk — compress command output before it reaches the model

When [rtk](https://github.com/rtk-ai/rtk) (Rust Token Killer) is installed,
`nusa-rg run` executes commands as `rtk <command>` and RTK rewrites the
output first — a 47-line `npm install` becomes a four-line summary. A hard byte
cap applies with or without rtk, so one noisy command can never blow up the
context window.

```bash
nusa-rg run git status
nusa-rg run --ask "what broke?" pytest -x    # answer with the output as context
nusa-rg run --raw npm install                # bypass rtk for this run
```

Inside a chat session, a line starting with `!` runs the command the same way;
you see the output, and the next question is answered with it attached:

```
❯ !pytest -x
  $ pytest -x
  in /home/user/projects/my-app
  ... output, filtered by rtk ...
  exit 1 | 2.4s | output filtered by rtk
❯ why did the second test fail?
```

The details:

* Commands run **only when you type them** — an answer from a model can never
  trigger one.
* They run **in the project that is indexed**, not in the directory the
  assistant was started in: `ls` there lists the project, not your home. The
  directory is printed above the output, and `--project` on `run` overrides it.
* Nothing goes through a shell: `;`, `|`, `&`, backticks, `$`, `<`, `>` and
  newlines are rejected with an explanation. Run the plain command, or use a
  real terminal for pipelines.
* `command_timeout` (120 s), `command_output_limit` (40,000 bytes) and
  `command_use_rtk` (true) bound the behaviour; `--timeout` on `run` overrides
  the timeout for one invocation.
* `run` exits with the command's own exit code, so it composes with scripts.
  `--ask` turns a failure into an immediate explanation instead of a stack
  trace you have to describe later.
* `nusa-rg doctor` reports whether rtk is installed.

### Caveman — telegraphic answers, every fact kept

Native Caveman mode (after [caveman](https://github.com/JuliusBrussee/caveman))
appends terse rules to the system prompt: drop articles, filler, pleasantries,
and hedging; lead with the answer; fragments are fine. Code, paths, numbers,
identifiers, and error text stay exactly as they are — brevity never trades
accuracy. It is a prompt-level style, so it works with every provider,
external or local, and needs no plugin runtime.

```bash
nusa-rg config set response_style caveman     # persistent
nusa-rg chat --caveman                        # this session (or one question)
nusa-rg chat --caveman "explain this traceback"
nusa-rg run --caveman --ask "what changed?" git diff
```

Inside a session, `/caveman` toggles the style and `/caveman on|off` sets it
explicitly. `status` shows which style is active.

## Configuration

`~/.nusa-rg/config.yaml`, created automatically on first run.

```yaml
model_provider: external        # external | local
api_provider: deepseek          # catalogue id backing api_base_url
api_base_url: https://api.deepseek.com
api_model: deepseek-flash
api_key: 'keystore://credential/api_key'   # a reference, never the secret
provider_keys:                  # per-provider references, never the secrets
  groq: 'keystore://credential/provider/groq'
fallback_providers: ['groq', 'deepseek:deepseek-flash']   # tried in order
response_style: default         # default | caveman
session_history_turns: 10       # previous turns sent when resuming a session
command_timeout: 120            # seconds a `run`/`!command` may run
command_output_limit: 40000     # bytes of command output kept for context
command_use_rtk: true           # route commands through rtk when installed
local_model_path: ''
default_project_path: /home/user/projects/my-app
system_prompt: 'You are a concise programming assistant...'
max_context_snippets: 3
chunk_lines: 60
chunk_overlap_lines: 10
ignore_dirs: ['.git', 'node_modules', '__pycache__', ...]
update_remote: ''                # empty = the official GitHub repository only
```

### Offline updates

`nusa-rg update` refuses any remote other than the official repository
(`https://github.com/padz24/Nusa-rg`), because an update runs `git reset
--hard` against `origin`. Checkouts still pointing at the legacy
`PADZ-PRD/RAG-termux-cli` URL are accepted too. To update from a local mirror
or an offline bare repository, name it explicitly:

```bash
nusa-rg config set update_remote ~/RAG-termux-cli.git
```

That setting is the authorisation. It is not a default that a stray `origin`
can satisfy on its own — leaving it empty keeps the GitHub-only guard in place.
If the remote has no release tags, `nusa-rg update` compares the remote branch
commit with the local `HEAD` instead of guessing a version.

## How retrieval works

1. **File scanner** — walks the project, skipping binaries, hidden directories,
   `node_modules`/`.venv`, and files over `max_file_bytes`.
2. **Index builder** — splits files into overlapping chunks and writes them to
   SQLite FTS5 (`unicode61` tokenizer). Unchanged files are skipped via mtime,
   so re-indexing is cheap.
3. **Retriever** — queries FTS5 with BM25 ranking and returns the top 3 chunks.
4. **Prompt composer** — wraps the snippets in explicit delimiters, cites them as
   `path:line`, and appends your question.

Typical retrieval latency is single-digit milliseconds, well inside the 2-second
budget from the spec. Indexing 120 files takes well under a second.

## Markdown rendering

Answers are rendered for the terminal by default: code blocks become labelled,
syntax-coloured panels, tables become bordered grids, and lists, task lists and
footnotes get proper markers.

Input:
```
# Password Hashing

| Approach | Speed | Memory |
|:---------|:-----:|-------:|
| PBKDF2   |  slow |   low  |

- [x] Use a random salt per user
- [ ] Never store plaintext
```

Output:
```
Password Hashing
════════════════

┌───────────┬────────┬────────┐
│ Approach  │ Speed  │ Memory │
├───────────┼────────┼────────┤
│ PBKDF2    │  slow  │   low  │
└───────────┴────────┴────────┘

☑ Use a random salt per user
☐ Never store plaintext
```

Coverage follows the [Markdown Guide](https://www.markdownguide.org/cheat-sheet/):
headings (ATX and setext), bold/italic/bold-italic, strikethrough, inline code,
fenced and indented code blocks with syntax highlighting, ordered/unordered/nested
lists, task lists, blockquotes, horizontal rules, links (inline, reference and
autolink), images, escaping, line breaks, tables with alignment, footnotes,
`==highlight==`, subscript, superscript, and emoji shortcodes.

To see the raw Markdown instead:

```bash
nusa-rg chat --plain "..."        # or --no-markdown
```

### Why markdown2

Markdown parsing is delegated to [`markdown2`](https://github.com/trentm/python-markdown2)
rather than hand-rolled regex. A hand-written parser is a large amount of subtly
wrong code; during development it mishandled intra-word underscores, unclosed
fences, and nested blockquotes, each easy to miss. `markdown2` ships as a
pure-Python universal wheel, so it installs instantly on Termux without compiling,
unlike `cryptography` or `PyYAML`. It is also imported lazily, so `--help` and
`status` never pay for it.

This project still owns what `markdown2` does not provide: the HTML-to-ANSI
renderer, table layout and truncation, syntax colouring, and the four constructs
markdown2 omits (subscript, superscript, `==highlight==`, emoji shortcodes),
applied only outside code regions.

## Updating

```bash
nusa-rg update --check     # only report whether a newer version exists
nusa-rg update             # update, then re-run install.sh
nusa-rg update --force     # discard local commits first
```

The same is available inside a chat session as `/update`.

Config, credentials and the index live in `~/.nusa-rg` and are never touched
by an update, so keys and history survive.

Two cases are reported rather than guessed at:

* **Installed from a package.** A copy installed from a Termux repository has no
  checkout to update; the command says so and points at `pkg upgrade
  termux-nusa-rg`.
* **Not this repository.** The checkout's `origin` must resolve to
  `github.com/padz24/Nusa-rg` (or the legacy
  `github.com/PADZ-PRD/RAG-termux-cli`). A `.git` directory belonging to some
  other project is refused outright.

A dirty working tree or a diverged branch stops the update and says so; pass
`--force` to discard local commits deliberately.

## Security

| Guarantee | How |
| :-- | :-- |
| No plaintext credentials | API keys sealed with AES-256-GCM in `~/.nusa-rg/keystore.bin`; `config.yaml` holds only a `keystore://` reference |
| No query or code in logs | Logs record timestamp, level, event, and a SHA-256 fingerprint of the query |
| No token leakage | Every log line passes a masking filter (`sk-…`, Bearer headers, private keys → `***MASKED***`) |
| Restricted files | `config.yaml`, `index.db`, and logs are `0600`; state directories are `0700` |
| No shell injection | Nothing is ever passed through a shell; arguments are filtered and invoked as a list |
| Commands run only when typed | `run` and `!command` execute only command lines you enter — an answer can never start one |
| Bounded command output | Output is capped in bytes (head and tail kept), and marked, delimited, and sanitised as untrusted when it enters a prompt |
| Prompt-injection hardening | Chat-control markers, our own delimiters, and override phrasing in indexed files or command output are neutralised |
| Tamper evidence | Keystore entries are authenticated (AES-GCM AAD), so edits are detected rather than silently accepted |

> **Note on `termux-keystore`.** The spec names `termux-keystore` and
> `termux-crypto`, which are not published Termux packages. This implementation
> uses the `cryptography` library for AES-256-GCM and keeps the master key in a
> `0600` file inside the Android app sandbox, which provides the same
> guarantee. Swap in a real keystore behind `nusa_rg/crypto.py` if one becomes
> available — nothing else needs to change.

State lives in one directory:

```
~/.nusa-rg/
├── config.yaml        # settings; keystore references only
├── keystore.bin       # AES-256-GCM sealed credentials
├── master.key         # 0600, scrypt-derives the keystore key
├── index.db           # SQLite FTS5 index
├── catalog.json       # optional: `providers refresh` snapshot (0600), overrides the bundled one
├── logos/             # provider SVGs fetched from models.dev, drawn in the terminal
└── logs/
    ├── app.log        # operational log, 10 MB × 5 rotation
    └── audit.log      # config changes and index operations
```

Set `NUSA_RG_HOME` to relocate everything.

## Architecture

```
CLI (click)
  ├── Command runner ──────→ rtk (optional) → process, never a shell
  ├── Catalogue (models.dev snapshot) → provider browser, failover wiring
  ├── Logo renderer (models.dev SVG → Braille cells) → provider browser
  └── CoreEngine ──────────────────┐
        ├── RAG Module            │
        │     scanner → index → retriever → composer
        └── LLM Client (swappable)
              ├── FailoverClient  → ordered chain of providers
              │     └── ApiClient → any OpenAI-compatible endpoint
              └── LocalLLMRunner → llama.cpp + GGUF
```

The RAG module and the LLM clients only meet inside `CoreEngine`, so replacing
one never disturbs the other. That separation is what makes provider switching a
config change. The command runner is deliberately outside `CoreEngine`: commands
run only from explicit user input, and the engine only ever receives the
resulting text as labelled, sanitised context.

## Development

```bash
pip install -e '.[dev]'
pytest                    # 613 tests
python -m nusa_rg       # run without installing
```

The suite needs no network access and no API key: HTTP calls are faked and the
llama.cpp path runs against a stub executable.

## Troubleshooting

| Symptom | Fix |
| :-- | :-- |
| `no API key configured` | `nusa-rg config set api_key --secret` |
| `no API key for provider 'x'` | `nusa-rg config set api_key --provider x --secret`, or export the provider's env var (`providers show x`) |
| `unknown provider` | Find the id with `nusa-rg providers list --search <text>` |
| Provider catalogue unreadable | `nusa-rg providers refresh` to replace the snapshot |
| `llama.cpp binary not found` | Build llama.cpp, or set `local_llama_bin` to its full path |
| `local model not found` | Check `local_model_path` points at the `.gguf` file |
| No snippets retrieved | Re-run `nusa-rg index <path>`; confirm the files match `ignore_globs` |
| Retrieval feels slow | Run `nusa-rg index --force` to rebuild a stale index |
| Answers ignore your project | Confirm `default_project_path` is set, or pass `--project` |
| Shell operators rejected | `run` and `!command` decline `;`, `\|`, `&`, backticks, `$`, `<`, `>` and newlines by design; use a real terminal for pipelines |
| Command output truncated | Raise `command_output_limit`, or let rtk trim it first |
| Answers cost more than they should | `nusa-rg config set response_style caveman` and install [rtk](https://github.com/rtk-ai/rtk) |
| Answers came from the wrong provider | `status` shows the fallback chain; that turn said which provider answered |

## License

MIT