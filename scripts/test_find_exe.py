"""Checks osdeps.find_exe's fixed list of install folders (the desktop app gets a minimal PATH, so an existing Claude Code
must be found without PATH). Each case puts a fake `claude` in one folder of a fake home and expects it to be found,
with PATH lookups switched off. Runs both the Windows and the macOS/Linux branches on any OS. Touches nothing real.

    python -X utf8 scripts/test_find_exe.py
"""
import os, shutil, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import osdeps

fails = 0


def check(label, ok):
    global fails
    print(("ok   " if ok else "FAIL ") + label)
    fails += 0 if ok else 1


def touch(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w").close()
    return path


def run(windows, rel, npmrc=None):
    home = tempfile.mkdtemp(prefix="sw_findexe_")
    env = {k: os.environ.get(k) for k in ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA")}
    saved = osdeps.WINDOWS, shutil.which
    try:
        os.environ.update(HOME=home, USERPROFILE=home, APPDATA=os.path.join(home, "AppData", "Roaming"),
                          LOCALAPPDATA=os.path.join(home, "AppData", "Local"))
        osdeps.WINDOWS = windows
        shutil.which = lambda *a, **k: None   # PATH finds nothing, as in a Finder-launched app
        if npmrc:
            with open(os.path.join(home, ".npmrc"), "w") as f:
                f.write("; comment\nprefix=" + npmrc.replace("{home}", home) + "\n")
        want = touch(os.path.join(home, *rel)) if rel else None
        got = osdeps.find_exe("claude")
        return want, got, home
    finally:
        osdeps.WINDOWS, shutil.which = saved
        for k, v in env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def case(windows, rel, label, npmrc=None):
    want, got, home = run(windows, rel, npmrc)
    check(f"{'win' if windows else 'mac'}: {label}", got is not None and want is not None and os.path.samefile(got, want))
    shutil.rmtree(home, ignore_errors=True)


# macOS / Linux
case(False, [".local", "bin", "claude"], "~/.local/bin/claude (native installer)")
case(False, [".claude", "local", "claude"], "~/.claude/local/claude (older local install)")
case(False, [".npm-global", "bin", "claude"], "~/.npm-global/bin/claude")
case(False, [".volta", "bin", "claude"], "~/.volta/bin/claude")
case(False, ["npmprefix", "bin", "claude"], "npm prefix from ~/.npmrc", npmrc="{home}/npmprefix")
case(False, [".nvm", "versions", "node", "v20.11.1", "bin", "claude"], "~/.nvm/versions/node/*/bin/claude")

# nvm: newest Node version wins
home = tempfile.mkdtemp(prefix="sw_findexe_")
old = touch(os.path.join(home, ".nvm", "versions", "node", "v9.9.9", "bin", "claude"))
new = touch(os.path.join(home, ".nvm", "versions", "node", "v18.2.0", "bin", "claude"))
saved_env = {k: os.environ.get(k) for k in ("HOME", "USERPROFILE")}
saved = osdeps.WINDOWS, shutil.which
os.environ.update(HOME=home, USERPROFILE=home)
osdeps.WINDOWS, shutil.which = False, (lambda *a, **k: None)
try:
    got = osdeps.find_exe("claude")
finally:
    osdeps.WINDOWS, shutil.which = saved
    for k, v in saved_env.items():
        os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
check("mac: nvm picks the newest Node version (v18 over v9)", got is not None and os.path.samefile(got, new))
shutil.rmtree(home, ignore_errors=True)

# Windows
case(True, [".local", "bin", "claude.exe"], r"%USERPROFILE%\.local\bin\claude.exe")
case(True, [".claude", "local", "claude.exe"], r"%USERPROFILE%\.claude\local\claude.exe")
case(True, ["AppData", "Roaming", "npm", "claude.cmd"], r"%APPDATA%\npm\claude.cmd")
case(True, ["AppData", "Local", "Programs", "claude", "claude.exe"], r"%LOCALAPPDATA%\Programs\claude\claude.exe")
case(True, ["nodeprefix", "claude.cmd"], "npm prefix from .npmrc", npmrc="{home}\\nodeprefix")

# nothing installed, and a folder named like the app doesn't count
want, got, home = run(False, None)
check("mac: nothing installed -> None", got is None or not got.startswith(home))  # (a real /opt/homebrew one may exist)
shutil.rmtree(home, ignore_errors=True)
home = tempfile.mkdtemp(prefix="sw_findexe_")
os.makedirs(os.path.join(home, ".local", "bin", "claude"))
saved_env = {k: os.environ.get(k) for k in ("HOME", "USERPROFILE")}
saved = osdeps.WINDOWS, shutil.which
os.environ.update(HOME=home, USERPROFILE=home)
osdeps.WINDOWS, shutil.which = False, (lambda *a, **k: None)
try:
    got = osdeps.find_exe("claude")
finally:
    osdeps.WINDOWS, shutil.which = saved
    for k, v in saved_env.items():
        os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
check("mac: a folder called claude is not the app", got is None)
shutil.rmtree(home, ignore_errors=True)

print("\nall passed" if not fails else f"\n{fails} failed")
sys.exit(1 if fails else 0)
