#!/usr/bin/env bash
# nusa-rg installer for Termux (AC-01, AC-40).
#
# One-liner install:
#   curl -fsSL https://raw.githubusercontent.com/padz24/Nusa-rg/main/install.sh | bash
#
# Requirements: Termux >= 0.118, ARM64. Target install time < 120s on a stable
# connection (AC-01).

# The colour helpers expand their r g b triples unquoted on purpose.
# shellcheck disable=SC2086
set -euo pipefail

PACKAGE="termux-nusa-rg"
MIN_TERMUX="0.118"

# ------------------------------------------------------------------- terminal
# The installer draws the same emblem, the same colours, the same status chips
# and the same status wave as the `nusa-rg` command, so the two look like one
# program. The rules are those of nusa_rg/ui.py:
#
#   colour   off when NO_COLOR is set, on when NUSA_RG_FORCE_COLOR is set,
#            otherwise on for a real terminal that is not TERM=dumb
#   depth    truecolor when COLORTERM says truecolor or 24bit, else the
#            256-colour cube
#   glyphs   the blocks and the wave need UTF-8; any other locale gets '#' for
#            the blocks and "_.-~=+*#" for the wave
#   layout   emblem, identity and chips; below 40 columns only the name and the
#            chips; without colour plain lines and no emblem
#   wave     animates only on a colour terminal, never draws wider than the
#            terminal, and always gives the cursor back

COLOUR=0
if [ -n "${NO_COLOR:-}" ]; then
  COLOUR=0
elif [ -n "${NUSA_RG_FORCE_COLOR:-}" ]; then
  COLOUR=1
elif [ -t 1 ] && [ -n "${TERM:-}" ] && [ "${TERM:-}" != "dumb" ]; then
  COLOUR=1
fi

_colorterm="${COLORTERM:-}"
case "${_colorterm,,}" in
  truecolor|24bit) TRUECOLOUR=1 ;;
  *) TRUECOLOUR=0 ;;
esac

# An unset or C/POSIX locale counts as UTF-8: that is what Python's stdout does
# there, and so what the command draws.
_locale="${LC_ALL:-${LC_CTYPE:-${LANG:-}}}"
case "$_locale" in
  ""|C|POSIX|*[Uu][Tt][Ff]-8*|*[Uu][Tt][Ff]8*) UTF8=1 ;;
  *) UTF8=0 ;;
esac

if [ "$COLOUR" = 1 ]; then
  C_RESET=$'\033[0m'
  C_BOLD=$'\033[1m'
else
  C_RESET=""
  C_BOLD=""
fi

# SGR code for an RGB colour, left in REPLY so the wave loop needs no subshell:
# 24-bit where advertised, else the 256-colour cube, picked the way ui.py picks
# it.
sgr() {  # fg|bg  r g b
  local layer=38 cube
  if [ "$1" = bg ]; then layer=48; fi
  if [ "$TRUECOLOUR" = 1 ]; then
    printf -v REPLY '\033[%d;2;%d;%d;%dm' "$layer" "$2" "$3" "$4"
  else
    cube=$(( 16 + 36 * (( $2 * 5 + 127 ) / 255) + 6 * (( $3 * 5 + 127 ) / 255) + (( $4 * 5 + 127 ) / 255) ))
    printf -v REPLY '\033[%d;5;%dm' "$layer" "$cube"
  fi
}

fg() {  # r g b
  [ "$COLOUR" = 1 ] || return 0
  sgr fg "$1" "$2" "$3"
  printf '%s' "$REPLY"
}

bg() {  # r g b
  [ "$COLOUR" = 1 ] || return 0
  sgr bg "$1" "$2" "$3"
  printf '%s' "$REPLY"
}

# The palette of nusa_rg/ui.py, named for the places it is used.
TEAL="47 208 192"
DIM="108 125 134"
GREEN="74 222 128"
YELLOW="245 185 66"
PURPLE="139 140 246"
MODEL_TEXT="156 199 245"
SHINE="226 240 255"
BLUE_0="56 182 255"
BLUE_1="58 165 240"
BLUE_2="59 143 224"
BLUE_3="47 111 208"
BLUE_4="34 80 176"
CHIP_MODEL_BG="23 58 99"
CHIP_RTK_BG="15 61 58"
CHIP_INDEX_BG="18 61 42"

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

# The tint that drifts along the wave: ui.py blends teal, the light blue, the
# deep blue and the purple back to teal in five steps each, twenty colours in
# all. Generated from ui._gradient, not written by hand.
GRADIENT=(
  "47 208 192" "49 203 205" "51 198 217" "52 192 230"
  "54 187 242" "56 182 255" "54 168 246" "52 154 236"
  "51 139 227" "49 125 217" "47 111 208" "65 117 216"
  "84 123 223" "102 128 231" "121 134 238" "139 140 246"
  "121 154 235" "102 167 224" "84 181 214" "65 194 203"
)

# One loop of the wave, a frame per entry and a bar level (0-7) per digit. The
# wave of ui.py never repeats; these are its first 101 frames, the loop length
# whose seam is quietest, so the last frame flows into the first as smoothly as
# any two neighbours. Generated from the same formula, checked against
# Spinner._wave.
WAVE_FRAMES=(
  43345565 55433444 66533233 77642112 77642001 77642000 66653100 45543200
  34443321 22233433 21123454 20013566 20002567 21002467 32112467 33222456
  44333345 35554434 35665433 35776532 25777531 24677631 34567642 33455542
  44344443 54322334 64311234 75310024 75310013 65310013 55421013 44432223
  23343333 11345544 00245665 00146776 00136776 11135777 22234676 43334556
  55443444 66653323 67754211 67764200 57764200 46665210 45554310 33444322
  32223433 32112345 41001356 42000256 42100246 43111246 43322245 34433334
  23555444 13566543 13577653 12577753 12467763 23456764 33445554 54434444
  65432233 76421123 77531012 77531001 66531001 55542101 34443222 22334333
  11134554 00024566 10024677 10013677 21113577 32223567 44333456 45544344
  46665332 46775321 46776420 35776420 35666420 34555431 43344432 53222343
  53211234 64100135 64200135 64200025 54311124 44332224 23443333 12455544
  01356654 01357764 01357775 11246775 22345665
)

# Escape codes the draw loops use, built once; all empty without colour.
init_palette() {
  S_TEAL="" S_DIM="" S_SHINE="" S_B0="" S_B1="" S_B2="" S_B3="" S_B4=""
  TINT=()
  [ "$COLOUR" = 1 ] || return 0
  local triple
  sgr fg $TEAL;   S_TEAL=$REPLY
  sgr fg $DIM;    S_DIM=$REPLY
  sgr fg $SHINE;  S_SHINE=$REPLY
  sgr fg $BLUE_0; S_B0=$REPLY
  sgr fg $BLUE_1; S_B1=$REPLY
  sgr fg $BLUE_2; S_B2=$REPLY
  sgr fg $BLUE_3; S_B3=$REPLY
  sgr fg $BLUE_4; S_B4=$REPLY
  for triple in "${GRADIENT[@]}"; do
    sgr fg $triple
    TINT+=("$REPLY")
  done
}
init_palette

# Terminal width, the way ui.py asks: COLUMNS wins, then the tty, then 80.
term_columns() {
  local cols="${COLUMNS:-}" size
  if ! [[ "$cols" =~ ^[0-9]+$ ]] || [ "$cols" -lt 1 ]; then
    size="$(stty size <&1 2>/dev/null || true)"
    cols="${size##* }"
    if ! [[ "$cols" =~ ^[0-9]+$ ]] || [ "$cols" -lt 1 ]; then
      cols=80
    fi
  fi
  printf '%s' "$cols"
}

# --------------------------------------------------------------------- banner
# What ui.banner() prints, row for row: the emblem with the name, the tagline
# and the project line beside it, a blank row, then the status chips. The chips
# need facts that take a moment to collect (termux-info is slow), so the banner
# comes in two halves with the wave running in between: banner() draws
# everything above the chips, chip_row() draws the chips.

if [ "$UTF8" = 1 ]; then
  BLOCK="█"; MIDDOT="·"; ELLIPSIS="…"
else
  BLOCK="#"; MIDDOT="*"; ELLIPSIS="~"
fi
BLOCK2="$BLOCK$BLOCK"
BLOCK3="$BLOCK2$BLOCK"
BLOCK4="$BLOCK3$BLOCK"

# The N emblem: the rows, glyphs and colours of _LOGO in ui.py.
LOGO_ROWS=(
  "${S_B0}${BLOCK3}${C_RESET}    ${S_TEAL}${BLOCK2}${C_RESET}"
  "${S_B1}${BLOCK4}${C_RESET}   ${S_TEAL}${BLOCK2}${C_RESET}"
  "${S_B2}${BLOCK2}${C_RESET} ${S_B2}${BLOCK2}${C_RESET}  ${S_TEAL}${BLOCK2}${C_RESET}"
  "${S_B3}${BLOCK2}${C_RESET}  ${S_B3}${BLOCK2}${C_RESET} ${S_TEAL}${BLOCK2}${C_RESET}"
  "${S_B4}${BLOCK2}${C_RESET}   ${S_B2}${BLOCK4}${C_RESET}"
)

BANNER_MODE=logo
FACT_PY="?"
FACT_ARCH="?"
FACT_TERMUX="unknown"

# ui._fit: middle-truncate a text to a width. The result is left in REPLY.
fit_text() {  # text  width
  local text="$1" width="$2" keep head
  if [ "${#text}" -le "$width" ]; then
    REPLY="$text"
  elif [ "$width" -lt 3 ]; then
    REPLY="${text:0:width}"
  else
    keep=$(( width - 1 ))
    head=$(( (keep + 1) / 2 ))
    REPLY="${text:0:head}${ELLIPSIS}${text:$(( ${#text} - (keep - head) ))}"
  fi
}

# One banner row: indented two columns, trailing blanks dropped, as ui.banner().
emit_row() {
  local row="  $1"
  row="${row%"${row##*[![:space:]]}"}"
  printf '%s\n' "$row"
}

banner() {  # version (empty until the source tree is cloned)
  local version="${1:-}" columns project name i
  columns="$(term_columns)"

  name="${S_TEAL}${C_BOLD}nusa-rg${C_RESET}"
  [ -z "$version" ] || name+="${S_DIM} v${version}${C_RESET}"

  # The separator is a one-byte stand-in while the line is measured, so the
  # width comes out right even where bash counts bytes, not characters.
  project="${REPO_DIR/#"$HOME"/\~} "$'\001'" installer"

  if [ "$columns" -lt 40 ]; then
    # Too narrow for the emblem: just the name, then the chips.
    BANNER_MODE=compact
    emit_row "$name"
  elif [ "$COLOUR" != 1 ]; then
    # Piped output or NO_COLOR: plain identity lines, no emblem.
    BANNER_MODE=plain
    fit_text "$project" $(( columns - 2 )); project="${REPLY//$'\001'/$MIDDOT}"
    emit_row "$name"
    emit_row "ask your codebase"
    emit_row "$project"
    emit_row ""
  else
    BANNER_MODE=logo
    fit_text "$project" $(( columns - 13 )); project="${REPLY//$'\001'/$MIDDOT}"
    local right=("" "$name" "${S_DIM}ask your codebase${C_RESET}" "${S_DIM}${project}${C_RESET}" "")
    for i in 0 1 2 3 4; do
      emit_row "${LOGO_ROWS[i]}  ${right[i]}"
    done
  fi
}

# The status chips, wrapped to the terminal like ui._chip_rows: a tinted
# background and a padded label, one space apart, whole chips only.
chip_row() {
  local columns budget gap row="" used=0 spec label fgc bgc piece
  columns="$(term_columns)"
  budget=$(( columns - 2 ))
  [ "$budget" -ge 10 ] || budget=10
  if [ "$COLOUR" = 1 ]; then gap=1; else gap=2; fi
  [ "$BANNER_MODE" != logo ] || printf '\n'   # the blank row above the chips

  for spec in \
    "python ${FACT_PY}|${MODEL_TEXT}|${CHIP_MODEL_BG}" \
    "termux ${FACT_TERMUX}|${TEAL}|${CHIP_RTK_BG}" \
    "${FACT_ARCH}|${GREEN}|${CHIP_INDEX_BG}"; do
    IFS='|' read -r label fgc bgc <<<"$spec"
    if [ "$COLOUR" = 1 ]; then piece=" ${label} "; else piece="$label"; fi
    if [ -n "$row" ] && [ $(( used + gap + ${#piece} )) -gt "$budget" ]; then
      emit_row "$row"
      row=""
      used=0
    fi
    if [ -n "$row" ]; then
      row+="$(printf '%*s' "$gap" '')"
      used=$(( used + gap ))
    fi
    if [ "$COLOUR" = 1 ]; then
      row+="$(fg $fgc)$(bg $bgc)${piece}${C_RESET}"
    else
      row+="$piece"
    fi
    used=$(( used + ${#piece} ))
  done
  emit_row "$row"
  printf '\n'
}

# The three facts behind the chips: Python, the CPU and Termux, one per line.
# termux-info is slow, which is why this runs under the wave, right below the
# emblem.
probe_facts() {
  local py="" arch="" termux=""
  py="$(python -c 'import platform; print(platform.python_version())' 2>/dev/null || true)"
  arch="$(uname -m 2>/dev/null || true)"
  if command -v termux-info >/dev/null 2>&1; then
    termux="$(termux-info 2>/dev/null | sed -n 's/.*Termux version: *\([0-9.]*\).*/\1/p' | head -n1 || true)"
  fi
  printf '%s\n%s\n%s\n' "$py" "$arch" "$termux"
}

probe_facts_to() { probe_facts > "$1"; }  # a step the wave can run

load_facts() {  # the text probe_facts printed
  local py="" arch="" termux=""
  { IFS= read -r py || true; IFS= read -r arch || true; IFS= read -r termux || true; } <<<"$1"
  FACT_PY="${py:-?}"
  case "$arch" in
    aarch64|arm64) FACT_ARCH="arm64" ;;
    "") FACT_ARCH="?" ;;
    *) FACT_ARCH="$arch" ;;
  esac
  TERMUX_RAW="$termux"
  FACT_TERMUX="${termux:-unknown}"
}

# -------------------------------------------------------------------- spinner
# The Spinner of ui.py, frame for frame: eight bars of two blended sine waves,
# tinted by a gradient that drifts one step every other frame; the label in
# dim ink with a bright band sweeping across it; the timer to a tenth of a
# second. A frame is built from tables and builtins, with no subshell, so
# twelve of them a second cost next to nothing even on a phone.
WAVE_WIDTH=8
WAVE_SLEEP="0.08"        # seconds between frames
WAVE_INTERVAL_US=80000   # the same, in microseconds
SHIMMER_PAUSE=10         # idle frames between two shimmer sweeps
WAVE_RAMP=(▁ ▂ ▃ ▄ ▅ ▆ ▇ █)
ASCII_RAMP=(_ . - '~' '=' + '*' '#')
SPIN_PID=""
SPIN_COLS_STALE=1

# One status line, byte for byte what Spinner._frame draws: two spaces, the
# wave, the label with its shimmer, the timer. The result is left in REPLY.
spinner_frame() {  # label  frame-number  elapsed-microseconds  columns
  local label="$1" tick="$2" elapsed_us="$3" columns="$4"
  local frames=${#WAVE_FRAMES[@]} tints=${#TINT[@]}
  local frame="${WAVE_FRAMES[tick % frames]}"
  local wave="" glyph level column tint
  local tenths timer room width text padding cycle centre shimmer="" i gap

  for (( column = 0; column < WAVE_WIDTH; column++ )); do
    level="${frame:column:1}"
    if [ "$UTF8" = 1 ]; then glyph="${WAVE_RAMP[level]}"; else glyph="${ASCII_RAMP[level]}"; fi
    tint=$(( (column * 2 + tick / 2) % tints ))
    wave+="${TINT[tint]}${glyph}${C_RESET}"
  done

  tenths=$(( (elapsed_us + 50000) / 100000 ))
  printf -v timer '%4s' "$(( tenths / 10 )).$(( tenths % 10 ))"
  timer+="s"

  # Never wider than the terminal, so a redraw cannot wrap.
  room=$(( columns - (2 + WAVE_WIDTH + 1 + 1 + ${#timer}) - 1 ))
  width=${#label}
  [ "$width" -le "$room" ] || width=$room
  [ "$width" -ge 1 ] || width=1
  text="${label:0:width}"
  printf -v padding '%*s' $(( width - ${#text} )) ''

  cycle=$(( ${#text} + SHIMMER_PAUSE ))
  centre=$(( (elapsed_us / WAVE_INTERVAL_US) % cycle - 2 ))
  for (( i = 0; i < ${#text}; i++ )); do
    gap=$(( i > centre ? i - centre : centre - i ))
    case "$gap" in
      0) shimmer+="${S_SHINE}${C_BOLD}${text:i:1}${C_RESET}" ;;
      1) shimmer+="${S_TEAL}${text:i:1}${C_RESET}" ;;
      *) shimmer+="${S_DIM}${text:i:1}${C_RESET}" ;;
    esac
  done

  REPLY="  ${wave} ${shimmer}${padding} ${S_DIM}${timer}${C_RESET}"
}

# Ctrl+C or a kill during a step: stop the step, give the cursor back, leave.
_spin_abort() {
  if [ -n "$SPIN_PID" ]; then kill "$SPIN_PID" 2>/dev/null || true; fi
  printf '\r\033[K\033[?25h'
  exit 130
}

# Run a command under the wave, the way the command runs a slow model call.
# RUN_STEP_QUIET=1 hides the command's own output, so it cannot fight the
# spinner for the same line.
run_step() {  # label  command...
  local label="$1"
  shift
  local quiet="${RUN_STEP_QUIET:-0}"

  # Like Spinner.start(): animate only on a colour terminal.
  if [ "$COLOUR" != 1 ] || [ ! -t 1 ] || [ "${NUSA_RG_NO_SPINNER:-0}" = "1" ]; then
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
  SPIN_PID=$!

  local tick=0 started elapsed_us=0 columns=80 status
  if [ -n "${EPOCHREALTIME:-}" ]; then started="${EPOCHREALTIME//[!0-9]/}"; else started=$SECONDS; fi
  SPIN_COLS_STALE=1
  trap '_spin_abort' INT TERM
  trap 'SPIN_COLS_STALE=1' WINCH

  printf '\033[?25l'
  while kill -0 "$SPIN_PID" 2>/dev/null; do
    if [ "$SPIN_COLS_STALE" = 1 ]; then
      columns="$(term_columns)"
      SPIN_COLS_STALE=0
    fi
    if [ -n "${EPOCHREALTIME:-}" ]; then
      elapsed_us=$(( ${EPOCHREALTIME//[!0-9]/} - started ))
    else
      elapsed_us=$(( (SECONDS - started) * 1000000 ))   # no clock finer than a second
    fi
    spinner_frame "$label" "$tick" "$elapsed_us" "$columns"
    printf '\r%s\033[K' "$REPLY"
    sleep "$WAVE_SLEEP"
    tick=$(( tick + 1 ))
  done
  if wait "$SPIN_PID"; then status=0; else status=$?; fi
  trap - INT TERM WINCH
  SPIN_PID=""
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
  if [ -z "${TERMUX_RAW+x}" ]; then
    load_facts "$(probe_facts)"   # called on its own: collect the facts now
  fi
  local version="$TERMUX_RAW"
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

  # The chips need facts that take a moment to collect, so the wave runs right
  # below the emblem while they are gathered.
  local facts_file facts_text
  if facts_file="$(mktemp 2>/dev/null)"; then
    RUN_STEP_QUIET=1 run_step "checking your device" probe_facts_to "$facts_file" || true
    facts_text="$(cat "$facts_file" 2>/dev/null || true)"
    rm -f "$facts_file"
  else
    facts_text="$(probe_facts)"
  fi
  load_facts "$facts_text"
  chip_row

  log "installing $PACKAGE"
  check_platform
  check_termux_version
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

