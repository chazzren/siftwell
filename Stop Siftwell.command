#!/bin/bash
# Siftwell for Mac: double-click to stop the Siftwell started from this folder (no other programs are touched).
# Only the processes recorded in this data folder's pid files (window.pid, tray.pid, server.pid) are stopped, and only
# after checking that each really is this folder's Siftwell and was not created after its pid file was written (a reused
# pid). Nothing is ever stopped because it listens on a port or has a similar command line.
set -uo pipefail

APP="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
# The pid files live in the data folder (same rules as paths.py and Start Siftwell.command).
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
HINT="If Siftwell was started some other way, restart your computer or sign out and back in."

# Does this command line run exactly "<python> [-X utf8] <APP>/<script> [arg]"? Relative paths, other folders, an editor or
# `python -c "...server.py..."` never match. $1 = command line, $2 = script name, $3 = required last argument ("" = a
# port number or nothing).
runs_script() {
    local c="$1" script="$APP/$2" flag="$3" prefix base
    case "$flag" in
        "") if [[ "$c" =~ ^(.*)[[:space:]][0-9]+$ ]]; then c="${BASH_REMATCH[1]}"; fi ;;
        *)  case "$c" in *" $flag") c="${c% $flag}" ;; *) return 1 ;; esac ;;
    esac
    case "$c" in
        *" $script") prefix="${c% $script}" ;;
        *) return 1 ;;
    esac
    prefix="${prefix% -X utf8}"
    base="$(printf '%s' "${prefix##*/}" | tr 'A-Z' 'a-z')"
    case "$base" in python|python3|python3.*|pythonw) return 0 ;; esac
    return 1
}

# Seconds since a process started (from ps's elapsed time, [[dd-]hh:]mm:ss), or empty if unknown.
proc_age() {
    local e d=0 h=0 m s
    e="$(ps -p "$1" -o etime= 2>/dev/null | tr -d ' ')"
    [ -n "$e" ] || return 0
    case "$e" in *-*) d="${e%%-*}"; e="${e#*-}" ;; esac
    IFS=: read -r a b c <<< "$e"
    if [ -n "${c:-}" ]; then h="$a"; m="$b"; s="$c"; else m="$a"; s="$b"; fi
    echo $(( ((10#$d * 24 + 10#$h) * 60 + 10#$m) * 60 + 10#$s ))
}

file_age() {   # seconds since the file was last written
    local t
    t="$(stat -f %m "$1" 2>/dev/null || stat -c %Y "$1" 2>/dev/null)"
    [ -n "$t" ] && echo $(( $(date +%s) - t ))
}

# stop_recorded <pid file> <script> <flag>: prints stopped / none / refused.
stop_recorded() {
    local pf="$1" pid pcmd page fage
    [ -f "$pf" ] || { echo none; return; }
    pid="$(tr -dc '0-9' < "$pf")"
    [ -n "$pid" ] || { echo none; return; }
    pcmd="$(ps -p "$pid" -o command= 2>/dev/null)"
    if [ -z "$pcmd" ]; then rm -f "$pf"; echo none; return; fi
    page="$(proc_age "$pid")"; fage="$(file_age "$pf")"
    # A process younger than its pid file was started after the file was written: a reused pid, not ours.
    if [ -n "$page" ] && [ -n "$fage" ] && [ "$page" -lt $(( fage - 2 )) ]; then echo refused; return; fi
    if ! runs_script "$pcmd" "$2" "$3"; then
        if [ "$2" = "server.py" ] && runs_script "$pcmd" "getting_started.py" "--serve"; then :; else echo refused; return; fi
    fi
    pkill -TERM -P "$pid" 2>/dev/null   # anything it started, e.g. a running job update
    kill -TERM "$pid" 2>/dev/null
    for _ in 1 2 3 4 5 6 7 8; do kill -0 "$pid" 2>/dev/null || break; sleep 0.25; done
    if kill -0 "$pid" 2>/dev/null; then pkill -KILL -P "$pid" 2>/dev/null; kill -KILL "$pid" 2>/dev/null; sleep 0.5; fi
    if kill -0 "$pid" 2>/dev/null; then echo stuck; return; fi
    rm -f "$pf"
    echo stopped
}

r_tray="$(stop_recorded "$DATA/tray.pid" tray.py "")"
r_win="$(stop_recorded "$DATA/window.pid" app_window.py "--owns-server")"
[ "$r_win" = "refused" ] && r_win="$(stop_recorded "$DATA/window.pid" app_window.py "")"
r_srv="$(stop_recorded "$PID_FILE" server.py "")"

if [ "$r_srv" = "stuck" ] || [ "$r_win" = "stuck" ] || [ "$r_tray" = "stuck" ]; then
    echo "Siftwell did not stop. Try again, or restart the computer."
elif [ "$r_srv" = "stopped" ]; then
    echo "Siftwell has stopped. Double-click 'Start Siftwell' to start it again."
elif [ "$r_srv" = "refused" ] || [ "$r_win" = "refused" ] || [ "$r_tray" = "refused" ]; then
    echo "The program recorded as Siftwell's isn't Siftwell, so it was left alone. $HINT"
elif [ "$r_win" = "stopped" ] || [ "$r_tray" = "stopped" ]; then
    echo "The Siftwell window was closed."
else
    echo "Siftwell isn't running (from this folder). $HINT"
fi
echo "You can close this window."
