#!/bin/bash
# Siftwell for Mac: double-click (the first time: right-click -> Open) to start Siftwell and open its window.
# Siftwell opens in its own window (app_window.py: pywebview with the system WebKit). Closing that window stops Siftwell,
# unless "Keep Siftwell available to my phone when the window is closed" is on, or the window was opened on a server that
# was already running. If pywebview isn't usable it opens in the browser instead and says so. (Mac window: untested.)
# Nothing is written into this folder, so it can be deleted and replaced by a newer download at any time:
#   - Python runtime (uv, Python, package cache, virtualenv): ~/Library/Application Support/Siftwell/runtime
#     (Linux: ~/.cache/siftwell/runtime). Shared by every copy of the app folder, so a new download starts at once.
#   - Your data plus the remembered port and the server's pid: ~/Library/Application Support/JobBoard
#     (Linux: ~/.local/share/jobboard; JOBBOARD_DATA overrides it). These locations must match paths.py.
# No admin password is needed. An older install's .venv in this folder still works as a fallback.
#
# Optional environment variables (mainly for testing):
#   SIFTWELL_PORT=8790      use this port instead of the remembered one / 8766
#   SIFTWELL_RUNTIME=<dir>  keep the Python runtime here instead
#   SIFTWELL_NO_BROWSER=1   don't open the Siftwell window (or a browser)
set -euo pipefail

APP="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"

abspath() {  # like Python's os.path.abspath(os.path.expanduser(p))
    local p="$1"
    case "$p" in "~") p="$HOME" ;; "~/"*) p="$HOME/${p#\~/}" ;; esac
    case "$p" in /*) ;; *) p="$PWD/$p" ;; esac
    printf '%s' "${p%/}"
}
if [ "$(uname -s)" = "Darwin" ]; then
    DEF_DATA="$HOME/Library/Application Support/JobBoard"
    DEF_RT="$HOME/Library/Application Support/Siftwell/runtime"
else
    DEF_DATA="${XDG_DATA_HOME:-$HOME/.local/share}/jobboard"
    DEF_RT="${XDG_CACHE_HOME:-$HOME/.cache}/siftwell/runtime"
fi
if [ -n "${JOBBOARD_DATA:-}" ]; then DATA="$(abspath "$JOBBOARD_DATA")"; export JOBBOARD_DATA="$DATA"; else DATA="$DEF_DATA"; fi
if [ -n "${SIFTWELL_RUNTIME:-}" ]; then RT="$(abspath "$SIFTWELL_RUNTIME")"; else RT="$DEF_RT"; fi

UV_DIR="$RT/uv"
UV="$UV_DIR/uv"
VENV="$RT/venv"
PY="$VENV/bin/python"
REQ="$APP/requirements.txt"
STAMP="$RT/requirements.sha256"
SETUP_LOG="$RT/setup.log"
PORT_FILE="$DATA/port"
PID_FILE="$DATA/server.pid"
APP_WINDOW="$APP/app_window.py"
WINDOW_LOG="$DATA/window.log"
SERVER_LOG="$DATA/launcher.log"
LEGACY_PORT_FILE="$APP/.siftwell/port"   # older launchers kept the port here
LEGACY_PY="$APP/.venv/bin/python"        # older launchers' environment
DEFAULT_PORT=8766
FALLBACK_PORTS="8767 8768 8769 8770 8771 8772 8773 8774 8775"

# Keep uv and its downloads in the runtime folder.
export UV_INSTALL_DIR="$UV_DIR"
export UV_UNMANAGED_INSTALL="$UV_DIR"   # no install receipt in ~/.config, no shell profile changes
export UV_NO_MODIFY_PATH=1
export UV_PYTHON_INSTALL_DIR="$RT/python"
export UV_PYTHON_BIN_DIR="$RT/python-bin"
export UV_CACHE_DIR="$RT/cache"
export UV_NO_CONFIG=1
export PYTHONUTF8=1
export PYTHONPYCACHEPREFIX="$RT/pycache"   # compiled .pyc files stay out of the app folder
unset VIRTUAL_ENV || true

cd "$APP"

say()  { printf '%s\n' "$*"; }
step() { printf '  - %s\n' "$*"; }
fail() {
    printf '\n\033[31mSorry, Siftwell could not start.\n%s\033[0m\n' "$1"
    if [ -n "${2:-}" ]; then printf '\n\033[33m%s\033[0m\n' "$2"; fi
    printf '\nYou can close this window.\n'
    exit 1
}
log_tail() {
    if [ -f "$1" ]; then
        printf '\nLast lines of %s:\n' "$1"
        tail -n "${2:-8}" "$1" | sed 's/^/    /'
    fi
}

# Body of a page on the local server ("" if nothing answers).
fetch() { curl -fsSL --max-time 4 "http://127.0.0.1:$1$2" 2>/dev/null || true; }

is_siftwell() {
    local body
    body="$(fetch "$1" /api/status)"
    case "$body" in *'"schedule"'*'"recomputing"'*|*'"recomputing"'*'"schedule"'*) return 0 ;; esac
    body="$(fetch "$1" /)"
    case "$body" in *"Job Board"*|*Siftwell*) return 0 ;; esac
    return 1
}

port_free() {
    # Something listening on this port (any address)?
    if command -v lsof >/dev/null 2>&1; then
        ! lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1
    else
        ! (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null
    fi
}

# Is this command line a Siftwell server from THIS folder (whichever Python runs it)?
own_cmd() {
    local c="$1" prefix base
    case "$c" in
        "$RT/"*|"$APP/.venv/"*)   # a Python from the runtime folder or this app's .venv
            case "$c" in *"$APP/server.py"*|*"$APP/getting_started.py"*--serve*) return 0 ;; esac
            return 1 ;;
    esac
    # Any other Python: only the exact form "<python> [-X utf8] <app>/server.py [port]" or "... getting_started.py --serve".
    # An editor or `python -c "...server.py..."` that merely mentions the path never matches.
    if [[ "$c" =~ ^(.*)[[:space:]][0-9]+$ ]]; then c="${BASH_REMATCH[1]}"; fi
    case "$c" in
        *" $APP/server.py") prefix="${c% $APP/server.py}" ;;
        *" $APP/getting_started.py --serve") prefix="${c% $APP/getting_started.py --serve}" ;;
        *) return 1 ;;
    esac
    prefix="${prefix% -X utf8}"
    base="$(printf '%s' "${prefix##*/}" | tr 'A-Z' 'a-z')"
    case "$base" in python|python3|python3.*|pythonw) return 0 ;; esac
    return 1
}

# PIDs of the Siftwell server started from THIS folder (never other Python programs).
own_pids() {
    local pid cmd
    if [ -f "$PID_FILE" ]; then
        pid="$(tr -dc '0-9' < "$PID_FILE" || true)"
        if [ -n "$pid" ]; then
            cmd="$(ps -p "$pid" -o command= 2>/dev/null || true)"
            if own_cmd "$cmd"; then echo "$pid"; fi
        fi
    fi
    # Also catch servers started some other way from this folder.
    ps -axo pid=,command= 2>/dev/null | while read -r pid cmd; do
        if own_cmd "$cmd"; then echo "$pid"; fi
    done
}

read_port() {
    local p=""
    if [ -n "${SIFTWELL_PORT:-}" ]; then p="$SIFTWELL_PORT"
    elif [ -f "$PORT_FILE" ]; then p="$(tr -dc '0-9' < "$PORT_FILE" || true)"
    elif [ -f "$LEGACY_PORT_FILE" ]; then p="$(tr -dc '0-9' < "$LEGACY_PORT_FILE" || true)"
    fi
    case "$p" in ''|*[!0-9]*) p="$DEFAULT_PORT" ;; esac
    echo "$p"
}

# Runs a command fully detached from this Terminal window (own session, no controlling terminal), output to a log file.
detach() {  # detach <pid file> <log file> <command...>
    "$PY" - "$@" <<'PYEOF'
import os, sys
pid_file, log_file, argv = sys.argv[1], sys.argv[2], sys.argv[3:]
if os.fork():
    sys.exit(0)
os.setsid()
if os.fork():
    sys.exit(0)
fd_in = os.open(os.devnull, os.O_RDONLY)
fd_out = os.open(log_file, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
os.dup2(fd_in, 0); os.dup2(fd_out, 1); os.dup2(fd_out, 2)
with open(pid_file, "w") as f:
    f.write(str(os.getpid()))
os.execv(argv[0], argv)
PYEOF
}

# A Python (the runtime's, else an older install's .venv) that has the pywebview package; prints its path.
window_python() {
    local py
    for py in "$PY" "$LEGACY_PY"; do
        if [ -x "$py" ] && "$py" -c 'import importlib.util,sys; sys.exit(0 if importlib.util.find_spec("webview") else 1)' >/dev/null 2>&1; then
            printf '%s' "$py"; return 0
        fi
    done
    return 1
}

WINDOW_OPENED=0
# open_board <port> [owns]: the Siftwell window (closing it stops the server when "owns", i.e. we just started it for
# this window), else the browser, saying so.
open_board() {
    local url="http://127.0.0.1:$1/" wp args
    if [ -n "${SIFTWELL_NO_BROWSER:-}" ]; then say "Siftwell is running at $url"; return; fi
    if wp="$(window_python)"; then
        say "Opening the Siftwell window"
        args=(-X utf8 "$APP_WINDOW")
        [ "${2:-}" = "owns" ] && args+=(--owns-server)
        SIFTWELL_PORT="$1" detach /dev/null "$WINDOW_LOG" "$wp" "${args[@]}"
        WINDOW_OPENED=1
        return
    fi
    say "Siftwell's own window isn't available on this Mac (it needs the pywebview package),"
    say "so Siftwell opens in your web browser instead. It keeps running until you double-click 'Stop Siftwell'."
    if command -v open >/dev/null 2>&1; then say "Opening $url"; open "$url"
    else say "Opening $url"; xdg-open "$url" >/dev/null 2>&1 || say "Open $url in your browser."
    fi
}

done_msg() {
    say ""
    if [ "$WINDOW_OPENED" = 1 ]; then
        say "Siftwell's window is open. You can close this Terminal window."
        say "Closing the Siftwell window stops Siftwell (unless you turned on 'Keep Siftwell available to my phone"
        say "when the window is closed' in Settings -> Get started). 'Stop Siftwell' also stops it."
    else
        say "Siftwell is running. You can close this window; Siftwell keeps running."
        say "To stop it, double-click 'Stop Siftwell'."
    fi
}

# Runs a command with its output going to setup.log.
quiet() { { printf '\n> %s\n' "$*"; "$@"; } >>"$SETUP_LOG" 2>&1; }

py_ok()  { [ -x "$1" ] && "$1" -c 'import sys; sys.exit(0 if sys.version_info[:2] >= (3, 12) else 1)' >/dev/null 2>&1; }
uv_ok()  { [ -x "$UV" ] && "$UV" --version >/dev/null 2>&1; }
req_hash() {
    if command -v shasum >/dev/null 2>&1; then shasum -a 256 "$REQ" | awk '{print $1}'; else sha256sum "$REQ" | awk '{print $1}'; fi
}

printf '\033]0;Siftwell\007'
PORT="$(read_port)"

# One-time setup (or repair) of the runtime: uv, Python, packages (pywebview for the window included). Skipped when the
# runtime is already there and requirements.txt hasn't changed since it was set up (any copy of the app folder shares it).
mkdir -p "$RT" "$DATA"
NET_HINT="Please check that this Mac is connected to the internet, then double-click 'Start Siftwell' again.
Details are in: $SETUP_LOG"

setup_runtime() {
    # Prints nothing on success; on failure prints a short message (details in setup.log) and returns 1.
    local NEED_UV=0 NEED_VENV=0 NEED_PKGS=0 OLD_HASH="" HASH
    uv_ok || NEED_UV=1
    py_ok "$PY" || NEED_VENV=1
    HASH="$(req_hash)"
    [ -f "$STAMP" ] && OLD_HASH="$(cat "$STAMP")"
    { [ "$NEED_VENV" = 1 ] || [ "$HASH" != "$OLD_HASH" ]; } && NEED_PKGS=1
    if [ "$NEED_UV" = 1 ] || [ "$NEED_VENV" = 1 ]; then
        say "Setting up Siftwell. This happens once and takes a couple of minutes..." >&2
        say "" >&2
    elif [ "$NEED_PKGS" = 1 ]; then
        say "Updating Siftwell's components..." >&2
    fi
    if [ "$NEED_UV" = 1 ] || [ "$NEED_VENV" = 1 ] || [ "$NEED_PKGS" = 1 ]; then
        echo "Siftwell setup $(date) for $APP" > "$SETUP_LOG"
    fi
    if [ "$NEED_UV" = 1 ]; then
        step "Downloading the installer tool (uv)" >&2
        mkdir -p "$UV_DIR"
        if ! quiet sh -c 'curl -LsSf https://astral.sh/uv/install.sh | sh' || ! uv_ok; then echo "Downloading uv failed."; return 1; fi
    fi
    if [ "$NEED_VENV" = 1 ]; then
        step "Downloading Python 3.12 and creating Siftwell's private environment" >&2
        if ! quiet "$UV" venv --quiet --clear --managed-python --python 3.12 "$VENV" || ! py_ok "$PY"; then
            echo "Setting up Python failed."; return 1
        fi
        rm -f "$STAMP"
    fi
    if [ "$NEED_PKGS" = 1 ]; then
        step "Installing Siftwell's packages" >&2
        if ! quiet "$UV" pip install --quiet --python "$PY" -r "$REQ"; then echo "Installing packages failed."; return 1; fi
        echo "$HASH" > "$STAMP"
        step "Done" >&2
        say "" >&2
    fi
    return 0
}

# 1. Already running? Open its window.
if is_siftwell "$PORT"; then
    if ! PROBLEM="$(setup_runtime)"; then
        log_tail "$SETUP_LOG" 4; say ""; say "Couldn't finish updating Siftwell's components ($PROBLEM)."
    fi
    open_board "$PORT"; done_msg; exit 0
fi

# 1b. Started from this folder but not answering yet? Wait for it.
OWN="$( (own_pids || true) | head -n 1 || true)"
if [ -n "$OWN" ]; then
    p="$(ps -p "$OWN" -o command= 2>/dev/null | sed -n 's/.*server\.py[[:space:]]*\([0-9][0-9]*\).*/\1/p')"
    [ -n "$p" ] && PORT="$p"
    say "Siftwell is starting up..."
    for _ in $(seq 1 60); do
        if is_siftwell "$PORT"; then
            if ! PROBLEM="$(setup_runtime)"; then
                log_tail "$SETUP_LOG" 4; say ""; say "Couldn't finish updating Siftwell's components ($PROBLEM)."
            fi
            open_board "$PORT"; done_msg; exit 0
        fi
        sleep 1
    done
    fail "Siftwell is running but not answering on port $PORT." "Double-click 'Stop Siftwell', then 'Start Siftwell' again."
fi

# 2. Set up the runtime (fatal if it can't be done and there is no older environment to use).
if ! PROBLEM="$(setup_runtime)"; then
    if py_ok "$LEGACY_PY"; then
        # An older install's environment inside the app folder still works: use it this time.
        log_tail "$SETUP_LOG" 4
        say ""
        say "Couldn't finish setting up ($PROBLEM); using the older Python environment in this folder for now."
        PY="$LEGACY_PY"
    else
        log_tail "$SETUP_LOG"; fail "$PROBLEM" "$NET_HINT"
    fi
fi

# 3. Pick a port: the remembered one (default 8766), else the first free one in 8767-8775.
if ! port_free "$PORT"; then
    BUSY="$PORT"; PORT=""
    for p in $DEFAULT_PORT $FALLBACK_PORTS; do
        if [ "$p" != "$BUSY" ] && port_free "$p"; then PORT="$p"; break; fi
    done
    [ -n "$PORT" ] || fail "Ports $DEFAULT_PORT to 8775 are all in use by other programs." "Close some programs or restart the Mac, then try again."
    say "Port $BUSY is used by another program, so Siftwell will use port $PORT."
fi
[ -n "${SIFTWELL_PORT:-}" ] || echo "$PORT" > "$PORT_FILE"   # a one-off SIFTWELL_PORT is never remembered

# 4. Start the server in the background, detached from this Terminal window (its own session, no
#    controlling terminal), so closing the window doesn't stop it. The detached process writes its pid file.
#    The Siftwell window below owns it: closing that window stops it, unless "keep available to my phone" is on.
say "Starting Siftwell..."
rm -f "$PID_FILE"
detach "$PID_FILE" "$SERVER_LOG" "$PY" -X utf8 "$APP/server.py" "$PORT"

# 5. Wait until it answers, then open the Siftwell window.
for _ in $(seq 1 60); do
    if is_siftwell "$PORT"; then open_board "$PORT" owns; done_msg; exit 0; fi
    sleep 1
    if [ -f "$PID_FILE" ] && ! kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
        log_tail "$SERVER_LOG" 15
        rm -f "$PID_FILE"
        fail "Siftwell stopped right after starting." "The log above ($SERVER_LOG) may say why."
    fi
done
log_tail "$SERVER_LOG" 15
fail "Siftwell did not answer within a minute." "It may still be starting. Wait a moment and double-click 'Start Siftwell' again."
