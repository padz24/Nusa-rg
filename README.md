# Termux RAG Assistant

A coding assistant that runs entirely in your Android terminal. It indexes your
local project with SQLite FTS5, retrieves the most relevant code snippets for
each question, and answers through either an external LLM API or a local
llama.cpp model. External answers can come from any of 200+ OpenAI-compatible
providers, with optional failover between them, and two token-saving modes keep
the bill down: rtk-compressed command output, and telegraphic "caveman"
answers.

Built to the specification in [`AGENS.md`](AGENS.md).

```
you > how is the password verified?
  context: src/auth.py:1-14
    def verify_password(password: str, salt: str, digest: str) -> bool:
        """Constant-time password check."""
        return hmac.compare_digest(hash_password(password, salt), digest)
assistant >
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
rag-assist doctor
```

## Install

```bash
git clone https://github.com/PADZ-PRD/RAG-termux-cli.git ~/rag-assist
cd ~/rag-assist && ./install.sh
```

Or, once published to a Termux repository:

```bash
pkg install termux-rag-assist
```

## Quick start

```bash
# 1. Store a provider key (encrypted, never written to config.yaml)
rag-assist config set api_key --secret

# 2. Point it at a project
rag-assist index ~/projects/my-app

# 3. Ask questions
rag-assist chat
rag-assist chat "explain this traceback"     # one-shot
```

## Commands

| Command | Purpose |
| :-- | :-- |
| `rag-assist chat` | Interactive session (`/exit`, `/clear`, `/caveman`, `!command`, `/help`) |
| `rag-assist chat "msg"` | Single question, then exit |
| `rag-assist run <cmd>` | Run a command (through rtk when installed); `--ask "…"` answers with its output as context |
| `rag-assist index <path>` | Scan and index a project |
| `rag-assist providers list` | Browse the bundled catalogue of 200+ providers |
| `rag-assist providers show <id>` | Endpoint, key variable, and default model for one provider |
| `rag-assist providers models <id>` | The models a provider hosts, newest first |
| `rag-assist providers refresh` | Fetch a fresh catalogue from models.dev |
| `rag-assist config show` | Print active configuration |
| `rag-assist config set <key> <value>` | Change a setting (`--secret` for keys, `--provider <id>` for per-provider keys) |
| `rag-assist config path` | Show where state files live |
| `rag-assist status` | Provider, model, style, fallback chain, index state, connectivity |
| `rag-assist update` | Update a source checkout to the latest release |
| `rag-assist doctor` | Installation and security self-checks |

Useful flags: `--json` on `index`, `--no-rag` on `chat`, `--project/-p`,
`--stream`, `--force` on `index`, `--reveal` on `config show`, `--caveman` on
`chat` and `run`, `--raw` on `run`.

## Providers

`rag-assist` bundles a catalogue of **232 providers and 8,600+ models**, a
trimmed snapshot of [models.dev](https://models.dev), so browsing works
offline. 209 of those providers speak the OpenAI chat-completions protocol and
are ready to use with nothing more than an API key.

```bash
rag-assist providers list                      # ready-to-use providers
rag-assist providers list --search deep            # filter by id or name
rag-assist providers show deepseek             # endpoint, key variable, default model
rag-assist providers models deepseek           # its models, newest first
rag-assist providers refresh                   # replace the snapshot with a fresh copy
```

Switching is a config change and takes effect on the next turn — no reinstall,
no terminal restart. Setting a provider also picks its default model, which
`config set api_model` can override.

```bash
rag-assist config set provider deepseek
rag-assist config set provider groq
rag-assist config set provider local
rag-assist config set local_model_path ~/models/qwen2.5-coder-7b-q4_k_m.gguf
rag-assist config set local_llama_bin ~/llama.cpp/build/bin/llama-cli
```

Each provider's key can come from the environment variable models.dev lists for
it, or from the encrypted keystore — stored per provider:

```bash
export GROQ_API_KEY=...                                   # env var path
rag-assist config set api_key --provider groq --secret    # keystore path
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

Name one or more fallback providers and `rag-assist` moves down the chain when
the active one fails, so a rate limit or an outage no longer ends the session:

```bash
rag-assist config set fallback_providers "groq, deepseek:deepseek-flash"
```

Entries are `id` or `id:model`; use the model form to pick a specific model on
that provider. Fallbacks use each provider's own key (keystore or environment
variable); one without a key is skipped, with the reason recorded in the log
and reported by `doctor`. When a fallback answers, the turn says so, and
`status` prints the whole chain.

> **Reasoning models.** Some models (including Ollama's `beam`) spend the first
> part of the token budget reasoning and can return an empty answer when that
> budget runs out. `rag-assist` detects this and reports it with the partial
> reasoning attached, rather than showing a blank reply. Raise the ceiling with
> `rag-assist config set max_tokens 4096`.

> **Ollama Cloud** is not in models.dev; point at it directly with
> `rag-assist config set api_base_url https://ollama.com/v1`.

## Saving tokens: rtk and Caveman

Two independent levers, one on each side of the bill.

### rtk — compress command output before it reaches the model

When [rtk](https://github.com/rtk-ai/rtk) (Rust Token Killer) is installed,
`rag-assist run` executes commands as `rtk <command>` and RTK rewrites the
output first — a 47-line `npm install` becomes a four-line summary. A hard byte
cap applies with or without rtk, so one noisy command can never blow up the
context window.

```bash
rag-assist run git status
rag-assist run --ask "what broke?" pytest -x    # answer with the output as context
rag-assist run --raw npm install                # bypass rtk for this run
```

Inside a chat session, a line starting with `!` runs the command the same way;
you see the output, and the next question is answered with it attached:

```
you > !pytest -x
  $ pytest -x
  ... output, filtered by rtk ...
  exit 1 | 2.4s | output filtered by rtk
you > why did the second test fail?
```

The details:

* Commands run **only when you type them** — an answer from a model can never
  trigger one.
* Nothing goes through a shell: `;`, `|`, `&`, backticks, `$`, `<`, `>` and
  newlines are rejected with an explanation. Run the plain command, or use a
  real terminal for pipelines.
* `command_timeout` (120 s), `command_output_limit` (40,000 bytes) and
  `command_use_rtk` (true) bound the behaviour; `--timeout` on `run` overrides
  the timeout for one invocation.
* `run` exits with the command's own exit code, so it composes with scripts.
  `--ask` turns a failure into an immediate explanation instead of a stack
  trace you have to describe later.
* `rag-assist doctor` reports whether rtk is installed.

### Caveman — telegraphic answers, every fact kept

Native Caveman mode (after [caveman](https://github.com/JuliusBrussee/caveman))
appends terse rules to the system prompt: drop articles, filler, pleasantries,
and hedging; lead with the answer; fragments are fine. Code, paths, numbers,
identifiers, and error text stay exactly as they are — brevity never trades
accuracy. It is a prompt-level style, so it works with every provider,
external or local, and needs no plugin runtime.

```bash
rag-assist config set response_style caveman     # persistent
rag-assist chat --caveman                        # this session (or one question)
rag-assist chat --caveman "explain this traceback"
rag-assist run --caveman --ask "what changed?" git diff
```

Inside a session, `/caveman` toggles the style and `/caveman on|off` sets it
explicitly. `status` shows which style is active.

## Configuration

`~/.rag-assist/config.yaml`, created automatically on first run.

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

`rag-assist update` refuses any remote other than
`https://github.com/PADZ-PRD/RAG-termux-cli`, because an update runs
`git reset --hard` against `origin`. To update from a local mirror or an
offline bare repository, name it explicitly:

```bash
rag-assist config set update_remote ~/RAG-termux-cli.git
```

That setting is the authorisation. It is not a default that a stray `origin`
can satisfy on its own — leaving it empty keeps the GitHub-only guard in place.

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
rag-assist chat --plain "..."        # or --no-markdown
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
rag-assist update --check     # only report whether a newer version exists
rag-assist update             # update, then re-run install.sh
rag-assist update --force     # discard local commits first
```

The same is available inside a chat session as `/update`.

Config, credentials and the index live in `~/.rag-assist` and are never touched
by an update, so keys and history survive.

Two cases are reported rather than guessed at:

* **Installed from a package.** A copy installed from a Termux repository has no
  checkout to update; the command says so and points at `pkg upgrade
  termux-rag-assist`.
* **Not this repository.** The checkout's `origin` must resolve to
  `github.com/PADZ-PRD/RAG-termux-cli`. A `.git` directory belonging to some
  other project is refused outright.

A dirty working tree or a diverged branch stops the update and says so; pass
`--force` to discard local commits deliberately.

## Security

| Guarantee | How |
| :-- | :-- |
| No plaintext credentials | API keys sealed with AES-256-GCM in `~/.rag-assist/keystore.bin`; `config.yaml` holds only a `keystore://` reference |
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
> guarantee. Swap in a real keystore behind `ragassist/crypto.py` if one becomes
> available — nothing else needs to change.

State lives in one directory:

```
~/.rag-assist/
├── config.yaml        # settings; keystore references only
├── keystore.bin       # AES-256-GCM sealed credentials
├── master.key         # 0600, scrypt-derives the keystore key
├── index.db           # SQLite FTS5 index
├── catalog.json       # optional: `providers refresh` snapshot (0600), overrides the bundled one
└── logs/
    ├── app.log        # operational log, 10 MB × 5 rotation
    └── audit.log      # config changes and index operations
```

Set `RAG_ASSIST_HOME` to relocate everything.

## Architecture

```
CLI (click)
  ├── Command runner ──────→ rtk (optional) → process, never a shell
  ├── Catalogue (models.dev snapshot) → provider browser, failover wiring
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
pytest                    # 493 tests
python -m ragassist       # run without installing
```

The suite needs no network access and no API key: HTTP calls are faked and the
llama.cpp path runs against a stub executable.

## Troubleshooting

| Symptom | Fix |
| :-- | :-- |
| `no API key configured` | `rag-assist config set api_key --secret` |
| `no API key for provider 'x'` | `rag-assist config set api_key --provider x --secret`, or export the provider's env var (`providers show x`) |
| `unknown provider` | Find the id with `rag-assist providers list --search <text>` |
| Provider catalogue unreadable | `rag-assist providers refresh` to replace the snapshot |
| `llama.cpp binary not found` | Build llama.cpp, or set `local_llama_bin` to its full path |
| `local model not found` | Check `local_model_path` points at the `.gguf` file |
| No snippets retrieved | Re-run `rag-assist index <path>`; confirm the files match `ignore_globs` |
| Retrieval feels slow | Run `rag-assist index --force` to rebuild a stale index |
| Answers ignore your project | Confirm `default_project_path` is set, or pass `--project` |
| Shell operators rejected | `run` and `!command` decline `;`, `\|`, `&`, backticks, `$`, `<`, `>` and newlines by design; use a real terminal for pipelines |
| Command output truncated | Raise `command_output_limit`, or let rtk trim it first |
| Answers cost more than they should | `rag-assist config set response_style caveman` and install [rtk](https://github.com/rtk-ai/rtk) |
| Answers came from the wrong provider | `status` shows the fallback chain; that turn said which provider answered |

## License

MIT