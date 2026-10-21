#!/usr/bin/env bash
# nusa-rg installer for Termux (AC-01, AC-40).
#
# One-liner install:
#   curl -fsSL https://raw.githubusercontent.com/padz24/Nusa-rg/main/install.sh | bash
#
# Requirements: Termux >= 0.118, ARM64. Target install time < 120s on a stable
# connection (AC-01).
set -euo pipefail

PACKAGE="termux-nusa-rg"
MIN_TERMUX="0.118"

# ------------------------------------------------------------------- terminal
# The installer draws the same emblem, the same colours and the same status
# wave as the `nusa-rg` command, so the two look like one program. The rules
# come from nusa_rg/ui.py: truecolor when COLORTERM advertises it, the
# 256-colour cube otherwise, and no colour at all when the output is not a
# terminal or NO_COLOR is set.

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  C_RESET=$'\033[0m'
  C_BOLD=$'\033[1m'
  C_DIM=$'\033[2m'
else
  C_RESET=""
  C_BOLD=""
  C_DIM=""
fi

# 256-colour cube index for an RGB triple, the way ui.py picks it.
_cube() {
  printf '%d' $(( 16 + 36 * (( $1 * 5 + 127 ) / 255) \
                    + 6 * (( $2 * 5 + 127 ) / 255) \
                    + (( $3 * 5 + 127 ) / 255) ))
}

fg() {  # r g b
  [ -n "$C_RESET" ] || return 0
  if [ "${COLORTERM:-}" = "truecolor" ] || [ "${COLORTERM:-}" = "24bit" ]; then
    printf '\033[38;2;%d;%d;%dm' "$1" "$2" "$3"
  else
    printf '\033[38;5;%dm' "$(_cube "$1" "$2" "$3")"
  fi
}

bg() {  # r g b
  [ -n "$C_RESET" ] || return 0
  if [ "${COLORTERM:-}" = "truecolor" ] || [ "${COLORTERM:-}" = "24bit" ]; then
    printf '\033[48;2;%d;%d;%dm' "$1" "$2" "$3"
  else
    printf '\033[48;5;%dm' "$(_cube "$1" "$2" "$3")"
  fi
}

# The palette of nusa_rg/ui.py, named for the places it is used.
TEAL="47 208 192"
DIM="108 125 134"
GREEN="74 222 128"
YELLOW="245 185 66"
PURPLE="139 140 246"
MODEL_TEXT="156 199 245"
SHINE="226 240 255"

teal() { fg $TEAL; }
dim() { fg $DIM; }
green() { fg $GREEN; }
yellow() { fg $YELLOW; }
purple() { fg $PURPLE; }

# Colour code plus text plus reset, for the places that need a whole run.
paint() {  # fg-triple  text
  fg $1
  printf '%s' "$2"
  printf '%s' "$C_RESET"
}

log() { printf '%s==>%s %s\n' "$(teal)" "$C_RESET" "$1"; }
ok() { printf '  %sok%s %s\n' "$(green)" "$C_RESET" "$1"; }
warn() { printf '  %s!!%s %s\n' "$(yellow)" "$C_RESET" "$1" >&2; }
die() { printf '%serror:%s %s\n' "$(fg 255 122 122)" "$C_RESET" "$1" >&2; exit 1; }

# --------------------------------------------------------------------- banner
# The emblem, the name and the tagline, in the order ui.py prints them.
banner() {
  local version="$1"
  local name="nusa-rg"
  [ -n "$version" ] && name="nusa-rg v$version"
  printf '\n'
  printf '  %s███%s    %s█%s\n' "$(fg 56 182 255)" "$C_RESET" "$(teal)" "$C_RESET"
  printf '  %s████%s   %s█%s  %s%s%s\n' "$(fg 58 165 240)" "$C_RESET" "$(teal)" \
    "$C_RESET" "$(teal)$C_BOLD" "$name" "$C_RESET"
  printf '  %s██%s %s██%s  %s█%s  %s%s%s\n' "$(fg 59 143 224)" "$C_RESET" \
    "$(fg 59 143 224)" "$C_RESET" "$(teal)" "$C_RESET" "$(fg 108 125 134)" \
    "installer for Termux" "$C_RESET"
  printf '  %s██%s  %s██%s %s█%s\n' "$(fg 47 111 208)" "$C_RESET" \
    "$(fg 47 111 208)" "$C_RESET" "$(teal)" "$C_RESET"
  printf '  %s██%s   %s████%s\n' "$(fg 34 80 176)" "$C_RESET" \
    "$(fg 59 143 224)" "$C_RESET"
  printf '\n'
}

# One chip, the way the banner draws them: a tinted background and a label.
chip() {  # label  fg-triple  bg-triple
  printf '%s%s%s%s%s' "$(bg $3)" "$C_BOLD" "$(fg $2)" "$1" "$C_RESET"
}

chip_row() {
  local python_version
  python_version="$(python -c 'import platform; print(platform.python_version())' 2>/dev/null || echo "?")"
  printf '  %s %s %s\n' \
    "$(chip "python $python_version" "$MODEL_TEXT" "23 58 99")" \
    "$(chip "termux ${TERMUX_VERSION:-unknown}" "$TEAL" "15 61 58")" \
    "$(chip "arm64" "$GREEN" "18 61 42")"
  printf '\n'
}

# -------------------------------------------------------------------- spinner
# The same eight-bar wave as the command's spinner, with the same drifting
# tint and a timer. The frames are the levels ui.py computes, precalculated so
# the shell does not have to do trigonometry 10 times a second.
WAVE_FRAMES=(
  43345565 55433444 66533233 77642112 77642001 77642000 66653100
  45543200 34443321 22233433 21123454 20013566 20002567 21002467
  32112467 33222456 44333345 35554434 35665433 35776532 25777531
  24677631 34567642 33455542 44344443 54322334 64311234 75310024
  75310013 65310013 55421013 44432223 23343333 11345544 00245665
  00146776 00136776 11135777 22234676 43334556 55443444 66653323
  67754211 67764200 57764200 46665210 45554310 33444322
)
WAVE_RAMP=$'▁▂▃▄▅▆▇█'
ASCII_RAMP='_.-~=+*#'

# Paint one wave frame: the gradient drifts one step every other tick.
wave_frame() {  # frame-index
  local frame="${WAVE_FRAMES[$(( $1 % ${#WAVE_FRAMES[@]} ))]}"
  local ramp="$WAVE_RAMP"
  [ -n "$C_RESET" ] || ramp="$ASCII_RAMP"
  local out="" column=0 level tint
  while [ "$column" -lt 8 ]; do
    level="${frame:$column:1}"
    tint=$(( (column * 2 + $1 / 2) % 4 ))
    case "$tint" in
      0) out+="$(teal)${ramp:$level:1}$C_RESET" ;;
      1) out+="$(fg 56 182 255)${ramp:$level:1}$C_RESET" ;;
      2) out+="$(fg 47 111 208)${ramp:$level:1}$C_RESET" ;;
      *) out+="$(purple)${ramp:$level:1}$C_RESET" ;;
    esac
    column=$((column + 1))
  done
  printf '%s' "$out"
}

# Run a command under the wave, the way the command runs a slow model call.
# RUN_STEP_QUIET=1 hides the command's own output, so it cannot fight the
# spinner for the same line.
run_step() {  # label  command...
  local label="$1"
  shift
  local quiet="${RUN_STEP_QUIET:-0}"
  if [ ! -t 1 ] || [ -n "${NO_COLOR:-}" ] || [ "${NUSA_RG_NO_SPINNER:-0}" = "1" ]; then
    if [ "$quiet" = "1" ]; then
      "$@" >/dev/null 2>&1
    else
      "$@"
    fi
    return $?
  fi

  if [ "$quiet" = "1" ]; then
    ( "$@" >/dev/null 2>&1 ) &
  else
    ( "$@" ) &
  fi
  local pid=$!
  local tick=0 started=$SECONDS elapsed
  printf '\033[?25l'
  while kill -0 "$pid" 2>/dev/null; do
    elapsed=$(( SECONDS - started ))
    printf '\r  %s %s %s\033[K' "$(wave_frame "$tick")" "$label" \
      "$(paint "$DIM" "${elapsed}s")"
    sleep 0.1
    tick=$((tick + 1))
  done
  wait "$pid"
  local status=$?
  printf '\r\033[K\033[?25h'
  return "$status"
}


# Where the source tree lives. Three ways to end up here, in order:
#
#   1. NUSA_RG_REPO_DIR -- an explicit override, always wins.
#   2. This script's own directory, when it holds a checkout. `nusa-rg
#      update` re-runs this script from the tree it just updated, and so does
#      anyone running `./install.sh` by hand. Without this, the script would
#      clone a *second* copy into $HOME/nusa-rg and install that instead,
#      silently leaving the updated tree unused.
#   3. $HOME/nusa-rg -- the one-liner `curl ... | bash` path, which has no
#      source tree of its own.
#
# Case 2 requires ${BASH_SOURCE[0]} to be a real file: under `curl | bash` it
# is "bash", and mistaking the user's current directory for a checkout would
# install whatever unrelated project they happened to be standing in.
resolve_repo_dir() {
  if [ -n "${NUSA_RG_REPO_DIR:-}" ]; then
    REPO_DIR="$NUSA_RG_REPO_DIR"
    return 0
  fi
  local self="${BASH_SOURCE[0]:-}"
  if [ -f "$self" ]; then
    local here; here="$(cd "$(dirname "$self")" && pwd)"
    if [ -d "$here/nusa_rg" ] && [ -f "$here/pyproject.toml" ]; then
      REPO_DIR="$here"
      return 0
    fi
  fi
  REPO_DIR="$HOME/nusa-rg"
}

REPO_DIR=""

# The version of the source tree, when we already have it. The one-liner
# install clones the source first, so the banner shows the name without a
# version and the closing line carries it.
read_version() {
  local init="$REPO_DIR/nusa_rg/__init__.py"
  [ -f "$init" ] || return 0
  sed -n 's/^__version__ = "\(.*\)"/\1/p' "$init" | head -n1
}

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
  TERMUX_VERSION="unknown"
  command -v termux-info >/dev/null 2>&1 || return 0
  local version
  version="$(termux-info 2>/dev/null | sed -n 's/.*Termux version: *\([0-9.]*\).*/\1/p' | head -n1)"
  [ -n "$version" ] || return 0
  if [ "$(printf '%s\n%s\n' "$MIN_TERMUX" "$version" | sort -V | head -n1)" != "$MIN_TERMUX" ]; then
    die "Termux $version found; $MIN_TERMUX or newer is required (NFR-01)"
  fi
  TERMUX_VERSION="$version"
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

  RUN_STEP_QUIET=1 run_step "installing $module" \
    python -m pip install --quiet "$module" \
    || return 1
}

install_deps() {
  log "installing runtime dependencies"

  # Prefer Termux's own packages: they ship prebuilt for Android/ARM64, which
  # avoids multi-minute source builds of PyYAML and cryptography.
  if command -v pkg >/dev/null 2>&1 && [ "$(id -u)" != "0" ]; then
    log "installing Termux packages (prebuilt, fast)"
    if ! RUN_STEP_QUIET=1 run_step "installing Termux packages" \
         pkg install -y python python-cryptography python-yaml; then
      warn "pkg install failed; falling back to pip"
    fi
  elif command -v pkg >/dev/null 2>&1; then
    warn "pkg refuses to run as root; using pip for dependencies"
  else
    warn "'pkg' not available; using pip for dependencies"
  fi

  RUN_STEP_QUIET=1 run_step "upgrading pip" \
    python -m pip install --quiet --upgrade pip || true

  local failed=()
  local module
  for module in click requests yaml cryptography markdown2; do
    install_module "$module" || failed+=("$module")
  done

  if [ "${#failed[@]}" -gt 0 ]; then
    die "could not install: ${failed[*]}
  On Termux, install the prebuilt packages instead:
      pkg install python-yaml python-cryptography
  nusa-rg will not run with an unencrypted keystore, so this is required."
  fi

  log "installing the nusa-rg package"
  RUN_STEP_QUIET=1 run_step "installing the nusa-rg package" \
    python -m pip install --quiet --no-deps -e "$REPO_DIR" \
    || die "pip install of the application package failed"

  ok "python dependencies installed"
}

fetch_source() {
  if [ -d "$REPO_DIR/nusa_rg" ]; then
    ok "using existing source tree at $REPO_DIR"
    return 0
  fi
  log "fetching source into $REPO_DIR"
  command -v git >/dev/null 2>&1 || die "git is required to fetch the source tree"
  RUN_STEP_QUIET=1 run_step "fetching source" \
    git clone --depth 1 https://github.com/padz24/Nusa-rg.git "$REPO_DIR" \
    || die "clone failed"
}

install_llama_cpp() {
  # Optional: the local execution path needs an ARM64 llama.cpp build (MS-02).
  if [ "${NUSA_RG_SKIP_LLAMA:-0}" = "1" ]; then
    warn "skipping llama.cpp build (NUSA_RG_SKIP_LLAMA=1)"
    return 0
  fi
  command -v llama-cli >/dev/null 2>&1 && { ok "llama-cli already installed"; return 0; }

  log "building llama.cpp (this is the slow step; set NUSA_RG_SKIP_LLAMA=1 to skip)"
  local dir="$HOME/llama.cpp"
  RUN_STEP_QUIET=1 run_step "cloning llama.cpp" \
    git clone --depth 1 https://github.com/ggerganov/llama.cpp "$dir" || {
    warn "llama.cpp clone failed; external API mode still works"
    return 0
  }
  RUN_STEP_QUIET=1 run_step "configuring llama.cpp" \
    cmake -S "$dir" -B "$dir/build" -DCMAKE_BUILD_TYPE=Release \
          -DGGML_NATIVE=OFF -DLLAMA_CURL=OFF || {
    warn "llama.cpp cmake configure failed"; return 0; }
  RUN_STEP_QUIET=1 run_step "building llama-cli" \
    cmake --build "$dir/build" --target llama-cli \
          -j"$(nproc 2>/dev/null || echo 4)" || {
    warn "llama.cpp build failed; external API mode still works"; return 0; }

  install -m 0755 "$dir/build/bin/llama-cli" \
    "${PREFIX:-/data/data/com.termux/files/usr}/bin/llama-cli" 2>/dev/null \
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
  if [ "${NUSA_RG_PRINT_REPO_DIR:-0}" = "1" ]; then
    printf '%s\n' "$REPO_DIR"
    return 0
  fi

  banner "$(read_version)"
  log "installing $PACKAGE"
  check_platform
  check_termux_version
  chip_row
  fetch_source
  verify_checksums
  install_deps
  install_llama_cpp

  log "securing the state directory"
  mkdir -p "$HOME/.nusa-rg/logs"
  chmod 700 "$HOME/.nusa-rg" "$HOME/.nusa-rg/logs"

  command -v nusa-rg >/dev/null 2>&1 \
    || warn "'nusa-rg' is not on PATH; add \$HOME/.local/bin to PATH"

  echo
  ok "$PACKAGE installed"
  cat <<'NEXT'

Next steps:
  1. Store a provider key:   nusa-rg config set api_key --secret
  2. Index your project:     nusa-rg index ~/projects/my-app
  3. Start chatting:         nusa-rg chat
  4. Verify the install:     nusa-rg doctor

Optional:
  - Browse the provider catalogue:  nusa-rg providers list
  - Trim command output with rtk:   https://github.com/rtk-ai/rtk
NEXT
}

main "$@"