# NUSA-RG

![nusa-rg](docs/banner.png)

A coding assistant for the Termux terminal on Android. It indexes a project
with SQLite FTS5, puts the most relevant snippets in front of the model
together with your question, and answers through an OpenAI-compatible API or a
local llama.cpp model. Everything happens in the terminal: no server, no
browser, no GUI.

Real output, from a real index and a stubbed provider:

```
nusa-rg 1.3.0
session 20261021-023855-97a9 · 0 turn(s) · resume: nusa-rg chat --session 20261021-023855-97a9
retrieved 1 snippet(s) in 0.01s
context src/auth.py:1-13
    import hashlib
    import hmac
    import os
    ...
    def verify_password(password: str, salt: bytes, digest: bytes) -> bool:
        """Constant-time password check."""
    ... (+1 more lines)

The check lives in src/auth.py:12. verify_password() compares the digest with hmac.compare_digest.
```

The specification is [AGENS.md](AGENS.md), written in Indonesian. This file is
the English version, [README.id.md](README.id.md) the Indonesian one.

## Requirements

| | |
| :-- | :-- |
| Platform | Android with Termux 0.118 or newer, ARM64 |
| Python | 3.10 or newer |
| Index | SQLite with FTS5, bundled with CPython |
| Optional | `llama-cli` and a GGUF model, for answers without a network |
| Optional | [rtk](https://github.com/rtk-ai/rtk), to compress command output |

`nusa-rg doctor` checks the platform, the file permissions, the keystore, the
provider catalogue, the index, and the local model.

## Install

One line, no clone of your own:

```bash
curl -fsSL https://raw.githubusercontent.com/padz24/Nusa-rg/main/install.sh | bash
```

The script clones the source into `~/nusa-rg`, checks the architecture and
the Termux version, installs the two modules PyPI ships no Android wheel for
(`cryptography` and `PyYAML`), installs the package, and can build llama.cpp
for the local path. It prints the same emblem, colours and status wave as the
`nusa-rg` command, so a build that takes minutes shows progress instead of
silence.

To skip the optional llama.cpp build, which is the slow step:

```bash
curl -fsSL https://raw.githubusercontent.com/padz24/Nusa-rg/main/install.sh | NUSA_RG_SKIP_LLAMA=1 bash
```

`NUSA_RG_NO_SPINNER=1` turns the status wave off. `NUSA_RG_REPO_DIR=/path`
installs a tree you already have.

From a checkout, the same script runs in place:

```bash
git clone https://github.com/padz24/Nusa-rg.git ~/nusa-rg
cd ~/nusa-rg && ./install.sh
```

From a Termux repository, once it is published:

```bash
pkg install termux-nusa-rg
```

## Quick start

```bash
nusa-rg config set api_key --secret      # encrypted, never written to config.yaml
nusa-rg index ~/projects/my-app
nusa-rg chat
nusa-rg chat "explain this traceback"    # one question, then exit
```

## Commands

| Command | What it does |
| :-- | :-- |
| `nusa-rg chat` | Interactive session: `/exit`, `/clear`, `/session`, `/caveman`, `!command`, `/help` |
| `nusa-rg chat "msg"` | One question, then exit |
| `nusa-rg chat --session <id>` | Resume a saved conversation |
| `nusa-rg session list` | Saved conversations, newest first |
| `nusa-rg session show <id>` | Metadata and turns of one session |
| `nusa-rg session new [id]` | Create a session and print its id |
| `nusa-rg session delete <id> --yes` | Delete a session |
| `nusa-rg run <cmd>` | Run a command; `--ask "…"` answers with its output as context |
| `nusa-rg index <path>` | Scan and index a project |
| `nusa-rg providers list` | The bundled catalogue of 232 providers |
| `nusa-rg providers show <id>` | Endpoint, key variable, default model |
| `nusa-rg providers models <id>` | The models a provider hosts |
| `nusa-rg providers icon <id>` | Draw the logo of one provider |
| `nusa-rg providers refresh` | Fetch a fresh catalogue from models.dev |
| `nusa-rg config show` | The active configuration |
| `nusa-rg config set <key> <value>` | Change a setting (`--secret` for keys, `--provider <id>` per provider) |
| `nusa-rg config path` | Where the state files live |
| `nusa-rg status` | Provider, model, style, fallback chain, index, connectivity |
| `nusa-rg update` | Update a source checkout to the latest release |
| `nusa-rg doctor` | Installation and security checks |

Flags worth knowing: `--project/-p`, `--no-rag`, `--stream`/`--no-stream`,
`--session`/`--session-id`, `--caveman`, `--json` on `index`, `--force` on
`index`, `--reveal` on `config show`, `--raw` on `run`.

## Retrieval

1. The scanner walks the project and skips binaries, hidden directories,
   `node_modules`, `.venv`, and files over `max_file_bytes` (2 MB).
2. The index builder splits files into chunks of `chunk_lines` (60) with
   `chunk_overlap_lines` (10) of overlap, and writes them to SQLite FTS5 with
   the `unicode61 remove_diacritics 2` tokenizer. Unchanged files are skipped
   by mtime, so re-indexing is cheap.
3. The retriever queries FTS5, ranks with BM25, and keeps the top
   `max_context_snippets` (3).
4. The composer wraps the snippets in delimiters, labels each one with
   `path:line`, and appends the question.

The specification asks for retrieval in under two seconds on a 50 MB project
(AC-03). The retrieval step in the transcript above took 0.01s; the model call
is what takes time.

## Sessions

Every chat keeps a session. Without `--session`, `nusa-rg chat` starts one and
saves every turn as it happens. The file is written when the project is
indexed and the conversation says something, so a chat that ends without a
word leaves nothing behind. When the session ends, the id and the command
that brings the conversation back are printed:

```text
  session    20261021-010019-2144
  turns      0
  project    /home/user/projects/my-app
  stored     /home/user/.nusa-rg/sessions/20261021-010019-2144.json
resume with: nusa-rg chat --session 20261021-010019-2144
```

```bash
nusa-rg chat --session fix-auth
nusa-rg chat --session fix-auth "and why does that happen?"
nusa-rg run --session fix-auth --ask "what failed?" pytest -x
```

Inside the chat:

```
/session [show [id]]        show the active or a saved session
/session list               list saved sessions
/session new [id]           start a new session, the id is generated when omitted
/session use <id>           switch to a saved session
/session delete <id> --yes  delete one
```

Sessions live in `~/.nusa-rg/sessions/<id>.json`, mode 0600. Only the
conversation and the response style are stored; retrieved code is rebuilt from
the index on every turn. The prompt carries the last `session_history_turns`
turns (10 by default), while the file keeps the whole transcript. `/clear`
empties the saved history of the running session.

## Providers

The bundled catalogue is a trimmed snapshot of [models.dev](https://models.dev):
232 providers and 8,602 models, of which 209 speak the OpenAI chat-completions
protocol and are ready to use with nothing but a key.

```bash
nusa-rg providers list
nusa-rg providers list --search deep
nusa-rg providers show deepseek
nusa-rg providers models deepseek
nusa-rg providers icon deepseek
nusa-rg providers refresh
```

Each provider has a logo on the registry, and `providers list` draws it next
to the entry. A terminal cannot show SVG, so the file is rasterised into
Braille cells. Every entry gets a colour of its own, taken from the provider
id, and a blank line separates the entries:

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

The SVGs are fetched once and cached in `~/.nusa-rg/logos`. `providers list
--no-icons`, or the environment variable `NUSA_RG_NO_LOGOS=1`, keeps the
compact one-line table and never touches the network. The same happens when
models.dev cannot be reached.

Switching provider is a config change and takes effect on the next turn.
Setting a provider also picks its default model, which `config set api_model`
overrides:

```bash
nusa-rg config set provider deepseek
nusa-rg config set provider local
nusa-rg config set local_model_path ~/models/qwen2.5-coder-7b-q4_k_m.gguf
nusa-rg config set local_llama_bin ~/llama.cpp/build/bin/llama-cli
```

A key comes either from the environment variable models.dev lists for that
provider, or from the encrypted keystore, stored per provider:

```bash
export GROQ_API_KEY=...
nusa-rg config set api_key --provider groq --secret
```

The lookup order is the per-provider keystore entry, then the provider's
environment variable, then the shared `api_key` slot. `status` shows the key
state of the active provider, and `doctor` lists every per-provider
reference.

Anything OpenAI-compatible works with `api_base_url` set by hand. Ten
providers whose base URL models.dev leaves to its SDK (OpenAI, Groq, Mistral,
Perplexity, xAI, Cerebras, DeepInfra, Together, AIHubMix, Venice) have their
endpoint built in.

### Failover

`fallback_providers` is a list, and the chain is tried in order, so a rate
limit or an outage no longer ends the turn:

```bash
nusa-rg config set fallback_providers "groq, deepseek:deepseek-flash"
```

Entries are `id` or `id:model`. A fallback without a key, without a model, or
without an OpenAI-compatible endpoint is skipped, the reason is logged as
`llm.chain.skip`, and `doctor` reports it. When a fallback answers, the turn
names the provider that answered, and `status` prints the whole chain.

Two provider notes:

- Some models, Ollama's `beam` among them, spend the first part of the token
  budget reasoning and can return an empty answer when that budget runs out.
  `nusa-rg` reports that with the partial reasoning attached instead of
  showing a blank reply. Raise the ceiling with `nusa-rg config set
  max_tokens 4096`.
- Ollama Cloud is not in models.dev. Point at it with `nusa-rg config set
  api_base_url https://ollama.com/v1`.

## Running commands

`nusa-rg run` executes a command and, with `--ask`, answers a question using
its output as context:

```bash
nusa-rg run git status
nusa-rg run --ask "what broke?" pytest -x
nusa-rg run --raw npm install
```

Inside a chat, a line that starts with `!` does the same:

```
❯ !pytest -x
  $ pytest -x
  in /home/user/projects/my-app
  ... output ...
  exit 1 | 2.4s
❯ why did the second test fail?
```

The rules:

- A command runs only when you type it. An answer from a model can never
  start one.
- It runs in the project that is indexed, not in the directory the assistant
  was started in. The directory is printed above the output, and `--project`
  on `run` overrides it.
- Nothing goes through a shell. `;`, `|`, `&`, backticks, `$`, `<`, `>` and
  newlines are rejected with an explanation. Use a real terminal for
  pipelines.
- `command_timeout` (120 s) and `command_output_limit` (40,000 bytes) bound
  the run, and `--timeout` on `run` overrides the timeout for one invocation.
- `run` exits with the command's own exit code, so it composes with scripts.
  With `--ask`, a failing command turns into an explanation instead of a stack
  trace you have to describe later.

When [rtk](https://github.com/rtk-ai/rtk) (Rust Token Killer) is installed,
`nusa-rg run` executes the command as `rtk <command>` and RTK rewrites the
output before it can reach the model. The byte cap applies with or without
rtk, so one noisy command cannot blow up the context window. `nusa-rg doctor`
reports whether rtk is installed.

## Caveman

`response_style: caveman` appends terse rules to the system prompt: drop
articles, filler, pleasantries and hedging, lead with the answer, fragments
are fine. Code, paths, numbers, identifiers and error text stay exactly as
they are. It is a prompt-level style, so it works with every provider,
external or local, and needs no plugin runtime.

```bash
nusa-rg config set response_style caveman     # persistent
nusa-rg chat --caveman                        # this session
nusa-rg chat --caveman "explain this traceback"
nusa-rg run --caveman --ask "what changed?" git diff
```

Inside a session, `/caveman` toggles the style and `/caveman on|off` sets it.
`status` shows the active style.

## Configuration

`~/.nusa-rg/config.yaml`, created on first run. The defaults:

```yaml
model_provider: external        # external | local
api_provider: ''                # catalogue id behind api_base_url
api_base_url: https://api.openai.com/v1
api_model: gpt-4o-mini
api_key: ''                     # a keystore:// reference once stored
provider_keys: {}               # per-provider references
fallback_providers: []          # tried in order
local_model_path: ''
local_llama_bin: llama-cli
default_project_path: ''
response_style: default         # default | caveman
session_history_turns: 10
max_context_snippets: 3
chunk_lines: 60
chunk_overlap_lines: 10
max_file_bytes: 2097152
ignore_dirs: ['.git', 'node_modules', '__pycache__', '.venv', 'venv', 'build', 'dist', '.mypy_cache', '.pytest_cache']
ignore_globs: ['*.min.js', '*.lock', '*.so', '*.png', '*.jpg', '*.zip']
request_timeout: 60
max_tokens: null                # unset means the provider default
temperature: 0.2
command_timeout: 120
command_output_limit: 40000
command_use_rtk: true
update_remote: ''               # empty keeps the GitHub-only update guard
log_level: INFO
system_prompt: 'You are a concise programming assistant embedded in a Termux terminal...'
```

### Offline updates

`nusa-rg update` refuses any remote other than the official repository
(`https://github.com/padz24/Nusa-rg`), because an update runs `git reset
--hard` against `origin`. A checkout still pointing at the old
`PADZ-PRD/RAG-termux-cli` URL is accepted too. To update from a local mirror
or an offline bare repository, name it:

```bash
nusa-rg config set update_remote ~/RAG-termux-cli.git
```

That setting is the authorisation. Leaving it empty keeps the guard in place,
so a stray `origin` cannot satisfy it on its own. If the remote has no release
tags, the update compares the remote branch commit with the local `HEAD`.

## Updating

```bash
nusa-rg update --check     # report whether a newer version exists
nusa-rg update             # update, then re-run install.sh
nusa-rg update --force     # discard local commits first
```

`/update` inside a chat does the same. Config, credentials and the index live
in `~/.nusa-rg` and are never touched, so keys and history survive.

Two cases are reported rather than guessed:

- A copy installed from a Termux repository has no checkout to update. The
  command says so and points at `pkg upgrade termux-nusa-rg`.
- A checkout whose `origin` is not the official repository is refused, and a
  `.git` directory from another project is never mistaken for this one.

A dirty working tree or a diverged branch stops the update. `--force` discards
local commits deliberately.

## Security

| Guarantee | How |
| :-- | :-- |
| No plaintext credentials | Keys are sealed with AES-256-GCM in `~/.nusa-rg/keystore.bin`, and `config.yaml` holds a `keystore://` reference |
| Tamper evidence | The alias is the AEAD associated data, so a renamed or edited entry fails authentication |
| No query or code in the log | A log record is `timestamp \| level \| event \| sha256(query)` |
| No token leakage | Every log line passes a masking filter: `sk-…`, `Bearer …` and private keys become `***MASKED***` |
| Restricted files | `config.yaml`, `index.db`, `keystore.bin` and the logs are `0600`, and the state directories are `0700` |
| No shell injection | Nothing is passed through a shell, and arguments are filtered and executed as a list |
| Commands run only when typed | `run` and `!command` execute only the command lines you enter |
| Bounded command output | Output is capped in bytes with head and tail kept, and marked and sanitised as untrusted when it enters a prompt |
| Prompt-injection hardening | Role markers, our own delimiters and override phrasing in indexed files or command output are neutralised |

The specification names `termux-keystore` and `termux-crypto`, which are not
published Termux packages. This implementation uses the `cryptography` library
for AES-256-GCM and keeps the master key in a `0600` file inside the Android
app sandbox. A real keystore can replace it behind `nusa_rg/crypto.py` without
touching anything else.

State lives in one directory:

```
~/.nusa-rg/
├── config.yaml        # settings; keystore references only
├── keystore.bin       # AES-256-GCM sealed credentials
├── master.key         # 0600, scrypt-derives the keystore key
├── index.db           # SQLite FTS5 index
├── catalog.json       # optional: `providers refresh` snapshot (0600)
├── sessions/          # saved conversations
├── logos/             # provider SVGs from models.dev
└── logs/
    ├── app.log        # operational log, 10 MB x 5 rotations
    └── audit.log      # config changes and index operations
```

`NUSA_RG_HOME` relocates all of it.

## Markdown

Answers are rendered for the terminal: code blocks become syntax-coloured
panels, tables become bordered grids, and lists, task lists and footnotes get
their markers.

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

Markdown parsing is delegated to
[`markdown2`](https://github.com/trentm/python-markdown2) rather than
hand-rolled regex. A hand-written parser is a lot of subtly wrong code; during
development it mishandled intra-word underscores, unclosed fences and nested
blockquotes, each easy to miss. `markdown2` ships as a pure-Python universal
wheel, so it installs on Termux without a compiler, unlike `cryptography` or
`PyYAML`, and it is imported lazily, so `--help` and `status` never pay for
it.

This project owns what `markdown2` does not provide: the HTML-to-ANSI
renderer, table layout and truncation, syntax colouring, and the four
constructs markdown2 omits (subscript, superscript, `==highlight==` and emoji
shortcodes), applied outside code regions.

`nusa-rg chat --plain "..."` prints the raw Markdown instead.

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

The RAG module and the LLM clients meet only inside `CoreEngine`, so
replacing one never disturbs the other. That is what makes switching provider
a config change. The command runner stays outside `CoreEngine` on purpose:
commands run only from explicit user input, and the engine only ever receives
the resulting text as labelled, sanitised context.

## Development

```bash
pip install -e '.[dev]'
pytest                    # 613 tests
python -m nusa_rg         # run without installing
```

The suite needs no network access and no API key: HTTP calls are faked and the
llama.cpp path runs against a stub executable.

## Troubleshooting

| Symptom | Fix |
| :-- | :-- |
| `no API key configured` | `nusa-rg config set api_key --secret` |
| `no API key for provider 'x'` | `nusa-rg config set api_key --provider x --secret`, or export the provider's env var (`providers show x`) |
| `unknown provider` | Find the id with `nusa-rg providers list --search <text>` |
| Provider catalogue unreadable | `nusa-rg providers refresh` replaces the snapshot |
| `llama.cpp binary not found` | Build llama.cpp, or set `local_llama_bin` to its full path |
| `local model not found` | Check `local_model_path` points at the `.gguf` file |
| No snippets retrieved | Re-run `nusa-rg index <path>`, and check the files against `ignore_globs` and `ignore_dirs` |
| Retrieval feels slow | `nusa-rg index --force` rebuilds a stale index |
| Answers ignore your project | Set `default_project_path`, or pass `--project` |
| Shell operators rejected | `run` and `!command` decline `;`, `\|`, `&`, backticks, `$`, `<`, `>` and newlines by design |
| Command output truncated | Raise `command_output_limit`, or let rtk trim it first |
| Answers cost more than they should | `nusa-rg config set response_style caveman`, and install rtk |
| The answer came from another provider | `status` prints the fallback chain, and the turn names the provider that answered |

## License

MIT. See [LICENSE](LICENSE).
