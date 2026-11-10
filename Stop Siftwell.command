#!/bin/bash
# Siftwell for Mac: double-click to stop the Siftwell started from this folder (no other programs are touched).
set -uo pipefail

APP="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
PID_FILE="$APP/.siftwell/server.pid"

pids=""
if [ -f "$PID_FILE" ]; then
    pid="$(tr -dc '0-9' < "$PID_FILE")"
    if [ -n "$pid" ]; then
        case "$(ps -p "$pid" -o command= 2>/dev/null)" in *"$APP/"*server.py*) pids="$pid" ;; esac
    fi
fi
while read -r pid cmd; do
    case "$cmd" in *"$APP/server.py"*) pids="$pids $pid" ;; esac
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
    echo "Siftwell has stopped. Double-click 'Start Siftwell' to start it again."
fi
rm -f "$PID_FILE"
echo "You can close this window."
