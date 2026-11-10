#!/bin/bash
# Siftwell for Mac: double-click (the first time: right-click -> Open) to start Siftwell and open it in your browser.
# The first run sets everything up inside this folder (.siftwell and .venv); nothing goes into your user profile
# and no admin password is needed. Your own data stays in ~/Library/Application Support/JobBoard.
#
# Optional environment variables (mainly for testing):
#   SIFTWELL_PORT=8790      use this port instead of the remembered one / 8766
#   SIFTWELL_NO_BROWSER=1   don't open a browser window
set -euo pipefail

APP="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
SIFT="$APP/.siftwell"
UV_DIR="$SIFT/uv"
UV="$UV_DIR/uv"
VENV="$APP/.venv"
PY="$VENV/bin/python"
REQ="$APP/requirements.txt"
STAMP="$SIFT/requirements.sha256"
PORT_FILE="$SIFT/port"
PID_FILE="$SIFT/server.pid"
SETUP_LOG="$SIFT/setup.log"
SERVER_LOG="$SIFT/launcher.log"
DEFAULT_PORT=8766
FALLBACK_PORTS="8767 8768 8769 8770 8771 8772 8773 8774 8775"

# Keep uv and its downloads inside the app folder.
export UV_INSTALL_DIR="$UV_DIR"
export UV_UNMANAGED_INSTALL="$UV_DIR"   # no install receipt in ~/.config, no shell profile changes
export UV_NO_MODIFY_PATH=1
export UV_PYTHON_INSTALL_DIR="$SIFT/python"
export UV_PYTHON_BIN_DIR="$SIFT/python-bin"
export UV_CACHE_DIR="$SIFT/cache"
export UV_NO_CONFIG=1
export PYTHONUTF8=1
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

# PIDs of the Siftwell server started from THIS folder (never other Python programs).
own_pids() {
    local pid cmd
    if [ -f "$PID_FILE" ]; then
        pid="$(tr -dc '0-9' < "$PID_FILE" || true)"
        if [ -n "$pid" ]; then
            cmd="$(ps -p "$pid" -o command= 2>/dev/null || true)"
            case "$cmd" in *"$APP/"*server.py*) echo "$pid" ;; esac
        fi
    fi
    # Also catch servers started some other way from this folder.
    ps -axo pid=,command= 2>/dev/null | while read -r pid cmd; do
        case "$cmd" in *"$APP/server.py"*) echo "$pid" ;; esac
    done
}

read_port() {
    local p=""
    if [ -n "${SIFTWELL_PORT:-}" ]; then p="$SIFTWELL_PORT"
    elif [ -f "$PORT_FILE" ]; then p="$(tr -dc '0-9' < "$PORT_FILE" || true)"
    fi
    case "$p" in ''|*[!0-9]*) p="$DEFAULT_PORT" ;; esac
    echo "$p"
}

open_board() {
    local url="http://127.0.0.1:$1/"
    if [ -n "${SIFTWELL_NO_BROWSER:-}" ]; then say "Siftwell is running at $url"; else say "Opening $url"; open "$url"; fi
}

done_msg() {
    say ""
    say "Siftwell is running. You can close this window; Siftwell keeps running."
    say "To stop it, double-click 'Stop Siftwell'."
}

# Runs a command with its output going to setup.log.
quiet() { { printf '\n> %s\n' "$*"; "$@"; } >>"$SETUP_LOG" 2>&1; }

venv_ok() { [ -x "$PY" ] && "$PY" -c 'import sys; sys.exit(0 if sys.version_info[:2] >= (3, 12) else 1)' >/dev/null 2>&1; }
uv_ok()   { [ -x "$UV" ] && "$UV" --version >/dev/null 2>&1; }
req_hash() { shasum -a 256 "$REQ" | awk '{print $1}'; }

printf '\033]0;Siftwell\007'
PORT="$(read_port)"

# 1. Already running? Just open it.
if is_siftwell "$PORT"; then
    open_board "$PORT"; done_msg; exit 0
fi

# 1b. Started from this folder but not answering yet? Wait for it.
OWN="$( (own_pids || true) | head -n 1 || true)"
if [ -n "$OWN" ]; then
    p="$(ps -p "$OWN" -o command= 2>/dev/null | sed -n 's/.*server\.py[[:space:]]*\([0-9][0-9]*\).*/\1/p')"
    [ -n "$p" ] && PORT="$p"
    say "Siftwell is starting up..."
    for _ in $(seq 1 60); do
        if is_siftwell "$PORT"; then open_board "$PORT"; done_msg; exit 0; fi
        sleep 1
    done
    fail "Siftwell is running but not answering on port $PORT." "Double-click 'Stop Siftwell', then 'Start Siftwell' again."
fi

# 2. One-time setup (or repair): uv, Python, packages.
mkdir -p "$SIFT"
NEED_UV=0; uv_ok || NEED_UV=1
NEED_VENV=0; venv_ok || NEED_VENV=1
HASH="$(req_hash)"
OLD_HASH=""; [ -f "$STAMP" ] && OLD_HASH="$(cat "$STAMP")"
NEED_PKGS=0; { [ "$NEED_VENV" = 1 ] || [ "$HASH" != "$OLD_HASH" ]; } && NEED_PKGS=1
NET_HINT="Please check that this Mac is connected to the internet, then double-click 'Start Siftwell' again.
Details are in: $SETUP_LOG"

if [ "$NEED_UV" = 1 ] || [ "$NEED_VENV" = 1 ]; then
    say "Setting up Siftwell. This happens once and takes a couple of minutes..."
    say ""
elif [ "$NEED_PKGS" = 1 ]; then
    say "Updating Siftwell's components..."
fi
if [ "$NEED_UV" = 1 ] || [ "$NEED_VENV" = 1 ] || [ "$NEED_PKGS" = 1 ]; then
    echo "Siftwell setup $(date)" > "$SETUP_LOG"
fi

if [ "$NEED_UV" = 1 ]; then
    step "Downloading the installer tool (uv)"
    mkdir -p "$UV_DIR"
    if ! quiet sh -c 'curl -LsSf https://astral.sh/uv/install.sh | sh' || ! uv_ok; then
        log_tail "$SETUP_LOG"; fail "Downloading uv failed." "$NET_HINT"
    fi
fi

if [ "$NEED_VENV" = 1 ]; then
    step "Downloading Python 3.12 and creating Siftwell's private environment"
    if ! quiet "$UV" venv --quiet --clear --managed-python --python 3.12 "$VENV" || ! venv_ok; then
        log_tail "$SETUP_LOG"; fail "Setting up Python failed." "$NET_HINT"
    fi
    rm -f "$STAMP"
fi

if [ "$NEED_PKGS" = 1 ]; then
    step "Installing Siftwell's packages"
    if ! quiet "$UV" pip install --quiet --python "$PY" -r "$REQ"; then
        log_tail "$SETUP_LOG"; fail "Installing packages failed." "$NET_HINT"
    fi
    echo "$HASH" > "$STAMP"
    step "Done"
    say ""
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
echo "$PORT" > "$PORT_FILE"

# 4. Start the server in the background, detached from this Terminal window (its own session, no
#    controlling terminal), so closing the window doesn't stop it. The detached process writes its pid file.
say "Starting Siftwell..."
rm -f "$PID_FILE"
"$PY" - "$PID_FILE" "$SERVER_LOG" "$PY" "-X" "utf8" "$APP/server.py" "$PORT" <<'PYEOF'
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

# 5. Wait until it answers, then open the browser.
for _ in $(seq 1 60); do
    if is_siftwell "$PORT"; then open_board "$PORT"; done_msg; exit 0; fi
    sleep 1
    if [ -f "$PID_FILE" ] && ! kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
        log_tail "$SERVER_LOG" 15
        rm -f "$PID_FILE"
        fail "Siftwell stopped right after starting." "The log above ($SERVER_LOG) may say why."
    fi
done
log_tail "$SERVER_LOG" 15
fail "Siftwell did not answer within a minute." "It may still be starting. Wait a moment and double-click 'Start Siftwell' again."
