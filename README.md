# Termux RAG Assistant

A coding assistant that runs entirely in your Android terminal. It indexes your
local project with SQLite FTS5, retrieves the most relevant code snippets for
each question, and answers through either an external LLM API or a local
llama.cpp model.

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
| `rag-assist chat` | Interactive session (`/exit`, `/clear`, `/help`) |
| `rag-assist chat "msg"` | Single question, then exit |
| `rag-assist index <path>` | Scan and index a project |
| `rag-assist config show` | Print active configuration |
| `rag-assist config set <key> <value>` | Change a setting |
| `rag-assist config path` | Show where state files live |
| `rag-assist status` | Provider, index state, and connectivity check |
| `rag-assist update` | Update a source checkout to the latest release |
| `rag-assist doctor` | Installation and security self-checks |

Useful flags: `--json` on `index`, `--no-rag` on `chat`, `--project/-p`,
`--stream`, `--force` on `index`, `--reveal` on `config show`.

## Providers

Switching is a config change and takes effect on the next turn — no reinstall,
no terminal restart.

```bash
# External: OpenAI
rag-assist config set api_key --secret
rag-assist config set provider openai
rag-assist config set api_model gpt-4o-mini

# External: Groq
rag-assist config set provider groq
rag-assist config set api_model llama-3.1-8b-instant

# External: Ollama Cloud (OpenAI-compatible)
rag-assist config set api_base_url https://ollama.com/v1
rag-assist config set api_model beam
rag-assist config set api_key --secret

# Local: llama.cpp, fully offline
rag-assist config set provider local
rag-assist config set local_model_path ~/models/qwen2.5-coder-7b-q4_k_m.gguf
rag-assist config set local_llama_bin ~/llama.cpp/build/bin/llama-cli
```

Any OpenAI-compatible endpoint works — set `api_base_url` directly.

> **Reasoning models.** Some models (including Ollama's `beam`) spend the first
> part of the token budget reasoning and can return an empty answer when that
> budget runs out. `rag-assist` detects this and reports it with the partial
> reasoning attached, rather than showing a blank reply. Raise the ceiling with
> `rag-assist config set max_tokens 4096`.

## Configuration

`~/.rag-assist/config.yaml`, created automatically on first run.

```yaml
model_provider: external        # external | local
api_base_url: https://api.openai.com/v1
api_model: gpt-4o-mini
api_key: 'keystore://credential/api_key'   # a reference, never the secret
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
| Prompt-injection hardening | Chat-control markers, our own delimiters, and override phrasing in indexed files are neutralised |
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
└── logs/
    ├── app.log        # operational log, 10 MB × 5 rotation
    └── audit.log      # config changes and index operations
```

Set `RAG_ASSIST_HOME` to relocate everything.

## Architecture

```
CLI (click)
  └── CoreEngine ──────────────────┐
        ├── RAG Module            │
        │     scanner → index → retriever → composer
        └── LLM Client (swappable)
              ├── ApiClient      → OpenAI / Groq / any compatible endpoint
              └── LocalLLMRunner → llama.cpp + GGUF
```

The RAG module and the LLM clients only meet inside `CoreEngine`, so replacing
one never disturbs the other. That separation is what makes provider switching a
config change.

## Development

```bash
pip install -e '.[dev]'
pytest                    # 440 tests
python -m ragassist       # run without installing
```

The suite needs no network access and no API key: HTTP calls are faked and the
llama.cpp path runs against a stub executable.

## Troubleshooting

| Symptom | Fix |
| :-- | :-- |
| `no API key configured` | `rag-assist config set api_key --secret` |
| `llama.cpp binary not found` | Build llama.cpp, or set `local_llama_bin` to its full path |
| `local model not found` | Check `local_model_path` points at the `.gguf` file |
| No snippets retrieved | Re-run `rag-assist index <path>`; confirm the files match `ignore_globs` |
| Retrieval feels slow | Run `rag-assist index --force` to rebuild a stale index |
| Answers ignore your project | Confirm `default_project_path` is set, or pass `--project` |

## License

MIT