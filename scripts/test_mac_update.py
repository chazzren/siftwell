#!/usr/bin/env python3
"""Test of the Mac app updater's pieces that can run anywhere (appupdate.py). Nothing real is mounted, copied or opened.

    python scripts/test_mac_update.py <scratch dir>

Checks: finding Siftwell.app from the running executable; the release summary picks up the .dmg asset (size, checksum);
and the swap helper (appupdate.MAC_HELPER, a /bin/sh script) run with stand-in `open` and `Siftwell` programs: it runs --stop
for the old app, replaces the old app with the staged one, opens the result, and when the swap can't be done puts the old
app back. Needs a POSIX `sh` (Git Bash on Windows, any Mac or Linux); that part is skipped without one.
The real hdiutil / ditto / codesign steps (appupdate._mac_prepare) only run on a Mac; the release workflow's macos job
covers building and mounting the .dmg.
"""
import os
import shutil
import subprocess
import sys

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP)
os.environ.setdefault("SIFTWELL_FORBID_CLAUDE", "1")

results = []


def check(name, ok, extra=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + (("  [" + str(extra)[:300] + "]") if extra and not ok else ""), flush=True)


def find_sh():
    for c in (shutil.which("sh"), r"C:\Program Files\Git\bin\sh.exe", r"C:\Program Files\Git\usr\bin\sh.exe", "/bin/sh"):
        if c and os.path.exists(c):
            return c
    return None


def norm(p):
    return (p or '').replace('\\', '/').split(':', 1)[-1]   # on Windows this test runs the same path logic with C:\\ paths


def fwd(p):
    return os.path.abspath(p).replace("\\", "/")


def run_helper(sh, scratch, name, break_swap):
    base = os.path.join(scratch, name)
    shutil.rmtree(base, ignore_errors=True)
    app = os.path.join(base, "Applications", "Siftwell.app")
    staged = os.path.join(base, "Applications", ".Siftwell-update.app")
    bindir = os.path.join(base, "bin")
    for d, label in ((app, "OLD"), (staged, "NEW")):
        os.makedirs(os.path.join(d, "Contents", "MacOS"))
        with open(os.path.join(d, "Contents", "label"), "w") as f:
            f.write(label)
    os.makedirs(bindir)
    log = os.path.join(base, "calls.log")
    # the old app's executable: records that --stop was run
    with open(os.path.join(app, "Contents", "MacOS", "Siftwell"), "w", newline="\n") as f:
        f.write(f'#!/bin/sh\necho "stop: $1" >> "{fwd(log)}"\n')
    os.chmod(os.path.join(app, "Contents", "MacOS", "Siftwell"), 0o755)
    with open(os.path.join(bindir, "open"), "w", newline="\n") as f:
        f.write(f'#!/bin/sh\necho "open: $1" >> "{fwd(log)}"\ncat "$1/Contents/label" >> "{fwd(log)}"\necho >> "{fwd(log)}"\n')
    os.chmod(os.path.join(bindir, "open"), 0o755)
    if break_swap:
        shutil.rmtree(staged)          # nothing to move into place
    from appupdate import MAC_HELPER
    script = os.path.join(base, "mac-update.sh")
    with open(script, "w", newline="\n") as f:
        f.write(MAC_HELPER)
    env = dict(os.environ, PATH=fwd(bindir) + os.pathsep + os.environ.get("PATH", ""))
    r = subprocess.run([sh, fwd(script), "2147483646", fwd(staged), fwd(app), fwd(os.path.join(base, "helper.log"))],
                       env=env, capture_output=True, text=True, timeout=60)
    calls = open(log).read() if os.path.exists(log) else ""
    label = open(os.path.join(app, "Contents", "label")).read() if os.path.exists(os.path.join(app, "Contents", "label")) else None
    return r, calls, label, base, app, staged


def main():
    scratch = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(APP, "..", "scratch-mac-update"))
    os.makedirs(scratch, exist_ok=True)
    import appupdate
    import frozen

    # ---- mac_app(): where is Siftwell.app?
    saved = (sys.platform, frozen.FROZEN, sys.executable)
    try:
        sys.platform, frozen.FROZEN = "darwin", True
        sys.executable = "/Applications/Siftwell.app/Contents/MacOS/Siftwell"
        check("mac_app finds the bundle from the executable", norm(appupdate.mac_app()) == "/Applications/Siftwell.app", appupdate.mac_app())
        sys.executable = "/Users/x y/My Apps/Siftwell.app/Contents/MacOS/Siftwell"
        check("mac_app copes with spaces in the path", norm(appupdate.mac_app()) == "/Users/x y/My Apps/Siftwell.app", appupdate.mac_app())
        sys.executable = "/usr/local/bin/python3"
        check("mac_app is None outside a .app", appupdate.mac_app() is None)
        sys.executable = "/Applications/Siftwell.app/Contents/MacOS/Siftwell"
        frozen.FROZEN = False
        check("mac_app is None for a source copy", appupdate.mac_app() is None)
        sys.platform, frozen.FROZEN = "win32", True
        check("mac_app is None on Windows", appupdate.mac_app() is None)
    finally:
        sys.platform, frozen.FROZEN, sys.executable = saved

    # ---- release summary: the .dmg asset
    ver = "9.9.9"
    sha = "a" * 64
    rel = {"tag_name": "v" + ver, "body": "x", "html_url": "https://github.com/x/y/releases/tag/v9.9.9", "prerelease": True,
           "assets": [{"name": f"Siftwell-{ver}.dmg", "size": 1234, "digest": "sha256:" + sha, "browser_download_url": "https://example.test/a.dmg"},
                      {"name": f"Siftwell-Setup-{ver}.exe", "size": 5, "browser_download_url": "https://example.test/a.exe"},
                      {"name": f"Siftwell-{ver}.zip", "size": 7, "browser_download_url": "https://example.test/a.zip"}]}
    s = appupdate._summary(rel)
    check("summary has the .dmg with size and checksum", s["dmg"] and s["dmg"]["size"] == 1234 and s["dmg"]["sha256"] == sha, s)
    check("summary still has the Windows installer", s["installer"] and s["installer"]["size"] == 5, s)
    rel["assets"] = rel["assets"][1:]
    check("summary without a .dmg says none", appupdate._summary(rel)["dmg"] is None)

    # ---- the swap helper
    sh = find_sh()
    if not sh:
        print("SKIP the swap helper tests (no sh found)")
    else:
        r, calls, label, base, app, staged = run_helper(sh, scratch, "ok", False)
        check("helper: exits 0", r.returncode == 0, (r.stdout, r.stderr))
        check("helper: runs --stop for the old app first", calls.startswith("stop: --stop"), calls)
        check("helper: the app is now the new one", label == "NEW", label)
        check("helper: staged copy and the old copy are gone", not os.path.exists(staged) and not os.path.exists(app + ".old-update"))
        check("helper: opens the app once, after the swap", calls.count("open:") == 1 and calls.rstrip().endswith("NEW"), calls)
        r, calls, label, base, app, staged = run_helper(sh, scratch, "broken", True)
        check("helper: when the new copy is missing the old app is put back and opened", label == "OLD" and calls.count("open:") == 1
              and not os.path.exists(app + ".old-update"), (label, calls))
    shutil.rmtree(scratch, ignore_errors=True)
    print(f"\n{sum(results)}/{len(results)} checks passed")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
