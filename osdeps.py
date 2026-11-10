"""Small cross-platform helpers so Siftwell runs the same on macOS and Windows 11.

- finding the Claude Code / Codex command-line apps (Windows npm installs are .cmd wrappers that need cmd /c)
- finding a Chromium browser that can print HTML to PDF (Chrome or, on Windows, the built-in Edge)
- rendering PDF pages to PNG (pypdfium2, instead of macOS sips)
- keeping Windows awake while a long update or re-rate runs
- making Python read and write files as UTF-8 everywhere
"""
import os, shutil, sys

WINDOWS = os.name == "nt"
MAC = sys.platform == "darwin"


def _npmrc_prefix(home):
    """The `prefix=` line of ~/.npmrc (where `npm install -g` puts commands), read from the file instead of running npm."""
    try:
        with open(os.path.join(home, ".npmrc"), encoding="utf-8", errors="replace") as f:
            for line in f:
                k, _, v = line.partition("=")
                if k.strip() == "prefix" and v.strip():
                    return os.path.expanduser(os.path.expandvars(v.strip().strip('"')))
    except OSError:
        pass
    return ""


def _nvm_bins(home):
    """~/.nvm/versions/node/*/bin, newest Node version first."""
    import glob, re
    def ver(d):
        return tuple(int(x) for x in re.findall(r"\d+", os.path.basename(os.path.dirname(d)))[:3])
    return sorted(glob.glob(os.path.join(home, ".nvm", "versions", "node", "*", "bin")), key=ver, reverse=True)


def find_exe(name, extra=()):
    """Full path to a command-line app, or None. Besides PATH, it looks in a fixed list of usual install folders,
    because the desktop app (a Mac .app opened from Finder, Windows starting it at sign-in) gets a minimal PATH.
    No shell profiles are read and no login shell is started."""
    cands = [shutil.which(name)]
    home = os.path.expanduser("~")
    prefix = _npmrc_prefix(home)
    if WINDOWS:
        appdata, local = os.environ.get("APPDATA", ""), os.environ.get("LOCALAPPDATA", "")
        cands += [shutil.which(name + ".exe"), shutil.which(name + ".cmd"),
                  os.path.join(home, ".local", "bin", name + ".exe"),
                  os.path.join(home, ".claude", "local", name + ".exe"),
                  os.path.join(home, ".claude", "local", name + ".cmd"),
                  os.path.join(appdata, "npm", name + ".cmd") if appdata else "",
                  os.path.join(local, "Programs", name, name + ".exe") if local else "",
                  os.path.join(prefix, name + ".cmd") if prefix else ""]
    else:
        cands += [os.path.join(home, ".local", "bin", name),
                  os.path.join(home, ".claude", "local", name),
                  "/opt/homebrew/bin/" + name, "/usr/local/bin/" + name,
                  os.path.join(home, ".npm-global", "bin", name),
                  os.path.join(prefix, "bin", name) if prefix else "",
                  *[os.path.join(b, name) for b in _nvm_bins(home)],
                  os.path.join(home, ".volta", "bin", name)]
    cands += list(extra)
    for p in cands:
        if p and os.path.isfile(p):
            return p
    return None


def _hidden(kw):
    """On Windows, start child processes without a console window (Siftwell itself runs windowless, so every console
    program it starts, like `claude` or `codex`, would otherwise flash its own window)."""
    if WINDOWS and not kw.get("creationflags"):
        import subprocess
        kw["creationflags"] = subprocess.CREATE_NO_WINDOW
    return kw


def run_hidden(*args, **kw):
    """subprocess.run without a console window on Windows."""
    import subprocess
    return subprocess.run(*args, **_hidden(kw))


def popen_hidden(*args, **kw):
    """subprocess.Popen without a console window on Windows."""
    import subprocess
    return subprocess.Popen(*args, **_hidden(kw))


def cmd(path):
    """Command prefix for running an app found by find_exe (batch wrappers go through cmd /c on Windows)."""
    if WINDOWS and path and path.lower().endswith((".cmd", ".bat")):
        return ["cmd", "/c", path]
    return [path]


def chrome_path():
    """A Chromium browser that supports --headless --print-to-pdf."""
    if MAC:
        cands = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                 "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
                 "/Applications/Chromium.app/Contents/MacOS/Chromium"]
    elif WINDOWS:
        pf, pf86, local = os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), os.environ.get("LOCALAPPDATA", "")
        cands = [os.path.join(pf, r"Google\Chrome\Application\chrome.exe"), os.path.join(pf86, r"Google\Chrome\Application\chrome.exe"),
                 os.path.join(local, r"Google\Chrome\Application\chrome.exe"),
                 os.path.join(pf86, r"Microsoft\Edge\Application\msedge.exe"), os.path.join(pf, r"Microsoft\Edge\Application\msedge.exe")]
    else:
        cands = [shutil.which(n) for n in ("google-chrome", "chromium", "chromium-browser", "microsoft-edge")]
    for p in cands:
        if p and os.path.exists(p):
            return p
    return None


def file_url(path):
    """file:// URL for a local path (Windows paths need a leading slash and forward slashes)."""
    from pathlib import Path
    return Path(path).resolve().as_uri()


def pdf_to_pngs(pdf, outdir, max_pages=3, max_px=1600):
    """Render the first pages of a PDF to white-background PNGs. Returns (png paths, total page count)."""
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(pdf)
    n, out = len(doc), []
    for i in range(min(n, max_pages)):
        page = doc[i]
        w, h = page.get_size()
        scale = max_px / max(w, h)
        img = page.render(scale=scale, fill_color=(255, 255, 255, 255)).to_pil().convert("RGB")
        p = os.path.join(outdir, f"page{i + 1}.png")
        img.save(p)
        out.append(p)
    doc.close()
    return out, n


def keep_awake(on=True):
    """Stop Windows from sleeping while long work runs (no-op elsewhere)."""
    if not WINDOWS:
        return
    try:
        import ctypes
        ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if on else 0))
    except Exception:
        pass


def ensure_utf8():
    """Windows Python defaults to a legacy code page for files; the data is UTF-8. Restart in UTF-8 mode if needed,
    and make every child process (updates, re-rates) inherit it."""
    os.environ["PYTHONUTF8"] = "1"
    if WINDOWS and not sys.flags.utf8_mode and not getattr(sys, "frozen", False):  # (the installed exe is UTF-8 already)
        import subprocess
        sys.exit(subprocess.call([sys.executable, "-X", "utf8"] + sys.argv))
    # pythonw (no console window) has no stdout; send prints to a log instead of crashing
    if sys.stdout is None or sys.stderr is None:
        import paths
        log = open(paths.data("server.log"), "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stdout or log
        sys.stderr = sys.stderr or log
