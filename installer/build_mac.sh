#!/bin/bash
# Build Siftwell.app (PyInstaller) and Siftwell-<version>.dmg on a Mac (the release workflow runs it on macos-14, Apple silicon).
#
#   installer/build_mac.sh [outdir]        default outdir: installer-out   (needs requirements + pyinstaller installed)
#
# The .dmg holds Siftwell.app and an "Applications" shortcut, so installing is "drag Siftwell onto Applications".
# Not signed or notarized (yet): the first start needs the Gatekeeper steps in docs/GUIDE.md.
set -euo pipefail
cd "$(dirname "$0")/.."
VERSION="$(tr -d '[:space:]' < VERSION)"
OUT="${1:-installer-out}"
mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"

rm -rf dist build
python -m PyInstaller --noconfirm --clean --distpath dist --workpath build installer/siftwell-mac.spec
APP="dist/Siftwell.app"
test -x "$APP/Contents/MacOS/Siftwell" || { echo "Siftwell.app was not built" >&2; exit 1; }
/usr/libexec/PlistBuddy -c "Print :CFBundleShortVersionString" "$APP/Contents/Info.plist"

# PyInstaller already ad-hoc signs the binaries; sign the finished bundle the same way so its seal covers the Info.plist
# and resources (an unsealed bundle makes macOS report it as damaged on some versions).
codesign --force --deep --sign - "$APP"
codesign --verify --deep --strict "$APP"

STAGE="$(mktemp -d)"
ditto "$APP" "$STAGE/Siftwell.app"
ln -s /Applications "$STAGE/Applications"
DMG="$OUT/Siftwell-$VERSION.dmg"
rm -f "$DMG"
hdiutil create -volname "Siftwell" -srcfolder "$STAGE" -ov -format UDZO "$DMG"
rm -rf "$STAGE"
ls -l "$DMG"
du -sh "$APP"
echo "$DMG"
