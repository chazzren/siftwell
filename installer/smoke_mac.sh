#!/bin/bash
# Smoke test of a built Siftwell-<version>.dmg (Mac). The runner has no screen, so this covers everything except the window:
#   - the .dmg mounts, holds Siftwell.app and an Applications shortcut;
#   - the app copied out of it reports the right version and can load the window / menu-bar libraries (--check-imports);
#   - `Siftwell --server <port>` (scratch data folder, Claude blocked) answers /api/ping;
#   - `Siftwell --stop` stops it, using the pid file the way the launcher writes it.
#
#   installer/smoke_mac.sh <path to the .dmg> <expected version> [port]
set -euo pipefail
DMG="$1"; VERSION="$2"; PORT="${3:-8871}"
WORK="$(mktemp -d)"
MNT="$WORK/mnt"; mkdir -p "$MNT"
SERVER_PID=""
cleanup() {
  if [ -n "$SERVER_PID" ] && kill -0 "$SERVER_PID" 2>/dev/null; then kill "$SERVER_PID" 2>/dev/null || true; fi
  hdiutil detach "$MNT" -quiet 2>/dev/null || true
  rm -rf "$WORK"
}
trap cleanup EXIT

hdiutil attach -nobrowse -readonly -mountpoint "$MNT" "$DMG"
test -d "$MNT/Siftwell.app" || { echo "Siftwell.app is not in the .dmg" >&2; exit 1; }
test -L "$MNT/Applications" || { echo "the Applications shortcut is not in the .dmg" >&2; exit 1; }
ditto "$MNT/Siftwell.app" "$WORK/Siftwell.app"
hdiutil detach "$MNT" -quiet
APP="$WORK/Siftwell.app"
EXE="$APP/Contents/MacOS/Siftwell"
codesign --verify --deep --strict "$APP"

PLIST_V="$(/usr/libexec/PlistBuddy -c "Print :CFBundleShortVersionString" "$APP/Contents/Info.plist")"
[ "$PLIST_V" = "$VERSION" ] || { echo "Info.plist says '$PLIST_V', expected '$VERSION'" >&2; exit 1; }
OUT="$("$EXE" --version)"
echo "Siftwell --version -> '$OUT'"
[ "$OUT" = "$VERSION" ] || { echo "expected '$VERSION' from --version" >&2; exit 1; }
"$EXE" --check-imports

export JOBBOARD_DATA="$WORK/data" SIFTWELL_FORBID_CLAUDE=1 SIFTWELL_NO_SELFHEAL=1
mkdir -p "$JOBBOARD_DATA"
"$EXE" --server "$PORT" > "$WORK/server.out" 2>&1 &
SERVER_PID=$!
echo "$SERVER_PID" > "$JOBBOARD_DATA/server.pid"      # what the launcher records; --stop only ever stops this pid
UP=""
for i in $(seq 1 90); do
  if curl -fsS "http://127.0.0.1:$PORT/api/ping" > "$WORK/ping.json" 2>/dev/null; then UP=1; break; fi
  kill -0 "$SERVER_PID" 2>/dev/null || break
  sleep 1
done
if [ -z "$UP" ]; then
  echo "the server did not answer /api/ping" >&2
  cat "$WORK/server.out" || true
  cat "$JOBBOARD_DATA/server.log" 2>/dev/null || true
  exit 1
fi
echo "ping -> $(cat "$WORK/ping.json")"
grep -q '"siftwell"' "$WORK/ping.json" || { echo "unexpected ping answer" >&2; exit 1; }
curl -fsS "http://127.0.0.1:$PORT/" > /dev/null && echo "/ answers"

"$EXE" --stop
for i in $(seq 1 20); do
  kill -0 "$SERVER_PID" 2>/dev/null || break
  sleep 1
done
if kill -0 "$SERVER_PID" 2>/dev/null; then echo "--stop did not stop the server" >&2; exit 1; fi
if curl -fsS "http://127.0.0.1:$PORT/api/ping" > /dev/null 2>&1; then echo "the server still answers after --stop" >&2; exit 1; fi
SERVER_PID=""
echo "smoke test passed"
