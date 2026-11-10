#!/bin/bash
# Siftwell for Mac: double-click to stop the Siftwell started from this folder (no other programs are touched).
set -uo pipefail

APP="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
# The server's pid file lives in the data folder (same rules as paths.py and Start Siftwell.command).
abspath() {
    local p="$1"
    case "$p" in "~") p="$HOME" ;; "~/"*) p="$HOME/${p#\~/}" ;; esac
    case "$p" in /*) ;; *) p="$PWD/$p" ;; esac
    printf '%s' "${p%/}"
}
if [ -n "${JOBBOARD_DATA:-}" ]; then DATA="$(abspath "$JOBBOARD_DATA")"
elif [ "$(uname -s)" = "Darwin" ]; then DATA="$HOME/Library/Application Support/JobBoard"
else DATA="${XDG_DATA_HOME:-$HOME/.local/share}/jobboard"
fi
PID_FILE="$DATA/server.pid"
# The launcher's Python runtime (same rules as paths.py and Start Siftwell.command).
if [ -n "${SIFTWELL_RUNTIME:-}" ]; then RT="$(abspath "$SIFTWELL_RUNTIME")"
elif [ "$(uname -s)" = "Darwin" ]; then RT="$HOME/Library/Application Support/Siftwell/runtime"
else RT="${XDG_CACHE_HOME:-$HOME/.cache}/siftwell/runtime"
fi

# A Siftwell server from THIS folder, whichever Python runs it (also the start-at-sign-in entry).
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

pids=""
if [ -f "$PID_FILE" ]; then
    pid="$(tr -dc '0-9' < "$PID_FILE")"
    if [ -n "$pid" ] && own_cmd "$(ps -p "$pid" -o command= 2>/dev/null)"; then pids="$pid"; fi
fi
while read -r pid cmd; do
    if own_cmd "$cmd"; then pids="$pids $pid"; fi
done < <(ps -axo pid=,command= 2>/dev/null)

if [ -z "${pids// /}" ]; then
    echo "Siftwell isn't running (from this folder)."
else
    for pid in $pids; do
        pkill -TERM -P "$pid" 2>/dev/null   # anything it started, e.g. a running job update
        kill -TERM "$pid" 2>/dev/null
    done
    sleep 2
    for pid in $pids; do
        if kill -0 "$pid" 2>/dev/null; then pkill -KILL -P "$pid" 2>/dev/null; kill -KILL "$pid" 2>/dev/null; fi
    done
    rm -f "$PID_FILE"
    echo "Siftwell has stopped. Double-click 'Start Siftwell' to start it again."
fi
echo "You can close this window."
