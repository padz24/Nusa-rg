#!/usr/bin/env bash
# rag-assist installer for Termux (AC-01, AC-40).
#
# One-liner install:
#   curl -fsSL https://raw.githubusercontent.com/PADZ-PRD/RAG-termux-cli/main/install.sh | bash
#
# Requirements: Termux >= 0.118, ARM64. Target install time < 120s on a stable
# connection (AC-01).
set -euo pipefail

PACKAGE="termux-rag-assist"
MIN_TERMUX="0.118"

# Where the source tree lives. Three ways to end up here, in order:
#
#   1. RAG_ASSIST_REPO_DIR -- an explicit override, always wins.
#   2. This script's own directory, when it holds a checkout. `rag-assist
#      update` re-runs this script from the tree it just updated, and so does
#      anyone running `./install.sh` by hand. Without this, the script would
#      clone a *second* copy into $HOME/rag-assist and install that instead,
#      silently leaving the updated tree unused.
#   3. $HOME/rag-assist -- the one-liner `curl ... | bash` path, which has no
#      source tree of its own.
#
# Case 2 requires ${BASH_SOURCE[0]} to be a real file: under `curl | bash` it
# is "bash", and mistaking the user's current directory for a checkout would
# install whatever unrelated project they happened to be standing in.
resolve_repo_dir() {
  if [ -n "${RAG_ASSIST_REPO_DIR:-}" ]; then
    REPO_DIR="$RAG_ASSIST_REPO_DIR"
    return 0
  fi
  local self="${BASH_SOURCE[0]:-}"
  if [ -f "$self" ]; then
    local here; here="$(cd "$(dirname "$self")" && pwd)"
    if [ -d "$here/ragassist" ] && [ -f "$here/pyproject.toml" ]; then
      REPO_DIR="$here"
      return 0
    fi
  fi
  REPO_DIR="$HOME/rag-assist"
}

REPO_DIR=""

log()  { printf '\033[36m==>\033[0m %s\n' "$*"; }
ok()   { printf '\033[32m  ok\033[0m %s\n' "$*"; }
warn() { printf '\033[33m  !!\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }

check_platform() {
  local arch
  arch="$(uname -m)"
  case "$arch" in
    aarch64|arm64) ok "architecture: $arch (ARM64 supported)" ;;
    *) die "architecture '$arch' is not supported; Termux on ARM64 is required (AGENS.md s05)" ;;
  esac

  command -v termux-info >/dev/null 2>&1 || \
    warn "termux-info not found; skipping the Termux version check"
}

check_termux_version() {
  command -v termux-info >/dev/null 2>&1 || return 0
  local version
  version="$(termux-info 2>/dev/null | sed -n 's/.*Termux version: *\([0-9.]*\).*/\1/p' | head -n1)"
  [ -n "$version" ] || return 0
  if [ "$(printf '%s\n%s\n' "$MIN_TERMUX" "$version" | sort -V | head -n1)" != "$MIN_TERMUX" ]; then
    die "Termux $version found; $MIN_TERMUX or newer is required (NFR-01)"
  fi
  ok "termux version: $version"
}

# Modules PyPI publishes no aarch64-Android wheel for. They must come from
# Termux packages, or be built from source (which needs a C/Rust toolchain).
NATIVE_MODULES=(cryptography yaml)

install_module() {
  local module="$1"
  python -c "import $module" >/dev/null 2>&1 && return 0

  if [[ " ${NATIVE_MODULES[*]} " == *" $module "* ]]; then
    # Avoid a long, doomed source build when no toolchain is present.
    if python -m pip install --quiet --only-binary :all: "$module" >/dev/null 2>&1; then
      return 0
    fi
    if ! command -v cargo >/dev/null 2>&1 && ! command -v rustc >/dev/null 2>&1; then
      if ! command -v clang >/dev/null 2>&1; then
        warn "no Android/ARM64 wheel for '$module' and no C/Rust toolchain to build it"
        return 1
      fi
    fi
    log "building '$module' from source (no Android wheel exists; this is slow)"
  fi

  python -m pip install --quiet "$module" >/dev/null 2>&1
}

install_deps() {
  log "installing runtime dependencies"

  # Prefer Termux's own packages: they ship prebuilt for Android/ARM64, which
  # avoids multi-minute source builds of PyYAML and cryptography.
  if command -v pkg >/dev/null 2>&1 && [ "$(id -u)" != "0" ]; then
    log "installing Termux packages (prebuilt, fast)"
    if ! pkg install -y python python-cryptography python-yaml 2>&1 | tail -3; then
      warn "pkg install failed; falling back to pip"
    fi
  elif command -v pkg >/dev/null 2>&1; then
    warn "pkg refuses to run as root; using pip for dependencies"
  else
    warn "'pkg' not available; using pip for dependencies"
  fi

  python -m pip install --quiet --upgrade pip >/dev/null 2>&1 || true

  local failed=()
  local module
  for module in click requests yaml cryptography markdown2; do
    install_module "$module" || failed+=("$module")
  done

  if [ "${#failed[@]}" -gt 0 ]; then
    die "could not install: ${failed[*]}
  On Termux, install the prebuilt packages instead:
      pkg install python-yaml python-cryptography
  rag-assist will not run with an unencrypted keystore, so this is required."
  fi

  log "installing the rag-assist package"
  python -m pip install --quiet --no-deps -e "$REPO_DIR" \
    || die "pip install of the application package failed"

  ok "python dependencies installed"
}

fetch_source() {
  if [ -d "$REPO_DIR/ragassist" ]; then
    ok "using existing source tree at $REPO_DIR"
    return 0
  fi
  log "fetching source into $REPO_DIR"
  command -v git >/dev/null 2>&1 || die "git is required to fetch the source tree"
  git clone --depth 1 https://github.com/PADZ-PRD/RAG-termux-cli.git "$REPO_DIR" \
    || die "clone failed"
}

install_llama_cpp() {
  # Optional: the local execution path needs an ARM64 llama.cpp build (MS-02).
  if [ "${RAG_ASSIST_SKIP_LLAMA:-0}" = "1" ]; then
    warn "skipping llama.cpp build (RAG_ASSIST_SKIP_LLAMA=1)"
    return 0
  fi
  command -v llama-cli >/dev/null 2>&1 && { ok "llama-cli already installed"; return 0; }

  log "building llama.cpp (this is the slow step; set RAG_ASSIST_SKIP_LLAMA=1 to skip)"
  local dir="$HOME/llama.cpp"
  git clone --depth 1 https://github.com/ggerganov/llama.cpp "$dir" || {
    warn "llama.cpp clone failed; external API mode still works"
    return 0
  }
  cmake -S "$dir" -B "$dir/build" -DCMAKE_BUILD_TYPE=Release \
        -DGGML_NATIVE=OFF -DLLAMA_CURL=OFF >/dev/null 2>&1 \
    || { warn "llama.cpp cmake configure failed"; return 0; }
  cmake --build "$dir/build" --target llama-cli -j"$(nproc 2>/dev/null || echo 4)" \
    >/dev/null 2>&1 \
    || { warn "llama.cpp build failed; external API mode still works"; return 0; }

  install -m 0755 "$dir/build/bin/llama-cli" "$PREFIX/bin/llama-cli" 2>/dev/null \
    || cp "$dir/build/bin/llama-cli" "$HOME/.local/bin/llama-cli"
  ok "llama-cli installed"
}

verify_checksums() {
  # SEC-05: any native binary we copy in must match a recorded SHA-256.
  local manifest="$REPO_DIR/checksums.sha256"
  [ -f "$manifest" ] || { warn "no checksums.sha256; skipping binary verification"; return 0; }
  log "verifying installed binaries (SEC-05 / AC-26)"
  ( cd "$REPO_DIR" && sha256sum -c "$manifest" --quiet ) \
    && ok "checksums verified" \
    || die "checksum verification failed; refusing to install (AC-26)

  If you are installing from a working tree rather than a release, regenerate
  the manifest to match your local files:
      cd $REPO_DIR && sha256sum -c checksums.sha256 || true"
}

main() {
  resolve_repo_dir

  # Test/debug seam: print the source directory this invocation would install,
  # then return before anything is downloaded or modified.
  if [ "${RAG_ASSIST_PRINT_REPO_DIR:-0}" = "1" ]; then
    printf '%s\n' "$REPO_DIR"
    return 0
  fi

  log "installing $PACKAGE"
  check_platform
  check_termux_version
  fetch_source
  verify_checksums
  install_deps
  install_llama_cpp

  log "securing the state directory"
  mkdir -p "$HOME/.rag-assist/logs"
  chmod 700 "$HOME/.rag-assist" "$HOME/.rag-assist/logs"

  command -v rag-assist >/dev/null 2>&1 \
    || warn "'rag-assist' is not on PATH; add \$HOME/.local/bin to PATH"

  echo
  ok "$PACKAGE installed"
  cat <<'NEXT'

Next steps:
  1. Store a provider key:   rag-assist config set api_key --secret
  2. Index your project:     rag-assist index ~/projects/my-app
  3. Start chatting:         rag-assist chat
  4. Verify the install:     rag-assist doctor
NEXT
}

main "$@"