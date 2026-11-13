"""Running Siftwell as the installed program (PyInstaller bundle, `Siftwell.exe`) as well as from source.

Everything that starts another Siftwell process (the server, the jobfinder run, the tray helper, the window, the
restart helper, the start-at-sign-in entry, the updater) builds its command line here, so the installed program and a
source checkout behave the same:

    from source   python [-X utf8] <app folder>/<script>.py <args>        (exactly what each caller did before)
    installed     Siftwell.exe --<mode> <args>                            (one exe; dispatch() picks the entry point)
    installed Mac Siftwell.app/Contents/MacOS/Siftwell --<mode> <args>   (the same exe inside the .app bundle)

Modes of Siftwell.exe (dispatch()): no argument = open the window (app_window.main); --server [port] = the windowless
server; --jobfinder <jobfinder args> = a fetch / recompute / re-rate run; --dirbuild <args> = "Build my own
directory" reading job sites (localdir.py / index_build/local.py); --tray <port>; --update = the headless
updater (siftwell_update.py, when present); --stop = stop this data folder's Siftwell (the installer runs it before
upgrading or uninstalling); --waiter = the restart helper; --version; --check-imports = load the window / tray
libraries and say so (the release build runs it as a smoke test, since the build machine has no screen).

Nothing here writes into the app folder.
"""
import os
import sys

FROZEN = bool(getattr(sys, "frozen", False))
APP = (getattr(sys, "_MEIPASS", None) if FROZEN else None) or os.path.dirname(os.path.abspath(__file__))
WINDOWS = sys.platform == "win32"

SCRIPTS = {"server": "server.py", "jobfinder": "jobfinder.py", "tray": "tray.py", "window": "app_window.py",
           "update": "siftwell_update.py", "dirbuild": "localdir.py"}


def interpreter(windowed=False):
    """sys.executable; from source on Windows with windowed=True the pythonw.exe next to it (no console window)."""
    exe = sys.executable
    if windowed and WINDOWS and not FROZEN:
        d, n = os.path.split(exe)
        if n.lower() == "python.exe" and os.path.exists(os.path.join(d, "pythonw.exe")):
            return os.path.join(d, "pythonw.exe")
    return exe


def command(mode, *args, utf8=False, windowed=False):
    """argv that starts a new Siftwell process in `mode` (a key of SCRIPTS). utf8: add `-X utf8` (source only; the
    installed program always runs in UTF-8 mode)."""
    args = [str(a) for a in args]
    if FROZEN:
        return [sys.executable, "--" + mode, *args]
    return [interpreter(windowed), *(["-X", "utf8"] if utf8 else []), os.path.join(APP, SCRIPTS[mode]), *args]


def serve_command():
    """The start-at-sign-in entry: [program, args...] that runs the server on the remembered port (installed program
    only; from source the entry runs `getting_started.py --serve`)."""
    return [sys.executable, "--server"]


def code_mtime(path):
    """When the code in `path` last changed. In the installed program the .py files are inside the bundle, so use the
    program itself: every release is a fresh build, so this moves forward on every upgrade."""
    return os.path.getmtime(sys.executable if FROZEN else path)


# ---------------------------------------------------------------- Siftwell.exe entry points
def _streams():
    """A windowed exe has no stdout/stderr unless the parent redirected them; give prints somewhere to go."""
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")


def _stop():
    """Stop this data folder's installed Siftwell: tray helper, window, then the server and what it started.
    Deliberately narrow: only the processes named in THIS data folder's pid files (tray.pid, window.pid, server.pid),
    only when they are running this same Siftwell.exe and weren't created after their pid file was written (a reused
    pid). It never goes looking for "whoever listens on the port" (that could be another install, or something else
    entirely). With no pid file there is nothing to do."""
    import app_window as aw
    for kind in ("tray", "window", "server"):
        r = aw.stop_recorded(kind)
        aw.log(f"--stop: {kind}: {r}")
    return 0


def _check_imports():
    """Import what the window and the tray need (the Mac build needs PyObjC's AppKit and WebKit as well). Prints one
    line; exit code 0 only when everything loads."""
    import importlib
    names = ["webview", "pystray", "PIL.Image"] + (["AppKit", "WebKit", "Foundation"] if sys.platform == "darwin" else [])
    bad = []
    for n in names:
        try:
            importlib.import_module(n)
        except Exception as e:
            bad.append(f"{n}: {type(e).__name__}: {e}")
    if sys.platform == "darwin":
        try:
            importlib.import_module("pystray._darwin")
        except Exception as e:
            bad.append(f"pystray._darwin: {type(e).__name__}: {e}")
    try:   # every job-system reader must load from inside the bundle (an installed build has no .py files on disk)
        import jobfinder
        jobfinder.load_extra()
        if len(jobfinder.FETCHERS) < 30:
            bad.append(f"job readers: only {len(jobfinder.FETCHERS)} loaded")
        names.append(f"{len(jobfinder.FETCHERS)} job readers")
    except Exception as e:
        bad.append(f"job readers: {type(e).__name__}: {e}")
    bad += directory_builder_problems()
    names.append("directory builder")
    print("imports ok: " + ", ".join(names) if not bad else "imports FAILED: " + "; ".join(bad))
    return 1 if bad else 0


DIRECTORY_BUILDER = ("index_build", "index_build.build", "index_build.local", "index_build.seed", "index_build.net",
                     "index_build.readers", "index_build.systems", "index_build.cc", "index_build.ct", "index_build.gov",
                     "index_build.postings", "index_build.resolve", "localdir")


def directory_builder_problems():
    """"Build my own directory" must work from inside the bundle: the builder package imports by name (an installed
    build has no .py files on disk) and the seed list it starts from is there and readable. [] when all is well."""
    import importlib
    bad = []
    for n in DIRECTORY_BUILDER:
        try:
            importlib.import_module(n)
        except Exception as e:
            bad.append(f"{n}: {type(e).__name__}: {e}")
    if not bad:
        try:
            import localdir
            from index_build import seed
            s = seed.read(localdir.SEED_ASSET)
            n = sum(len(g.get("t") or []) for g in (s or {}).get("groups") or [])
            if n < 1000:
                bad.append(f"seed list: only {n} job sites in {localdir.SEED_ASSET}")
        except Exception as e:
            bad.append(f"seed list: {type(e).__name__}: {e}")
    return bad


def _run_server(rest):
    import paths
    import runpy
    bad = paths.data_problem()
    if bad:
        print(bad, file=sys.stderr)
        return 1
    port = rest[0] if rest and rest[0].isdigit() else str(paths.read_port())
    sys.argv = [os.path.join(APP, "server.py"), port]
    os.chdir(APP)
    runpy.run_module("server", run_name="__main__", alter_sys=True)
    return 0


def dispatch(argv=None):
    """Frozen only. Handles the --mode arguments and returns an exit code, or returns None when there is nothing to
    do here (no argument or --window: open the window)."""
    if not FROZEN:
        return None
    argv = list(sys.argv[1:] if argv is None else argv)
    argv = [a for a in argv if not a.startswith("-psn_")]     # old macOS passes a process serial number when Finder opens an app
    if not argv or argv[0] in ("--window", "--owns-server"):
        return None
    mode, rest = argv[0], argv[1:]
    _streams()
    os.environ["PYTHONUTF8"] = "1"          # children (and the helper scripts) read and write UTF-8
    if APP not in sys.path:
        sys.path.insert(0, APP)
    if mode == "--version":
        import getting_started
        print(getting_started.VERSION)
        return 0
    if mode == "--stop":
        return _stop()
    if mode == "--check-imports":
        return _check_imports()
    if mode == "--server":
        return _run_server(rest)
    if mode == "--jobfinder":
        import jobfinder
        sys.argv = [os.path.join(APP, "jobfinder.py"), *rest]
        return jobfinder.main() or 0
    if mode == "--dirbuild":
        import localdir
        return localdir.main(rest) or 0
    if mode == "--tray":
        import paths
        import app_window as aw
        import tray
        aw._no_std_streams()
        return tray.main(int(rest[0]) if rest else paths.read_port())
    if mode == "--update":
        try:
            import siftwell_update
        except ImportError:
            # TODO: the headless updater (siftwell_update.py) is being built separately; it is picked up here
            # automatically once the file exists (the spec bundles every top-level .py).
            print("This build has no headless updater.", file=sys.stderr)
            return 2
        sys.argv = [os.path.join(APP, "siftwell_update.py"), *rest]
        return siftwell_update.main() or 0
    if mode == "--waiter":
        import getting_started
        sys.argv = ["waiter", *rest]
        exec(compile(getting_started._WAITER, "waiter", "exec"), {"__name__": "__waiter__"})
        return 0
    print(f"Siftwell: unknown option {mode}", file=sys.stderr)
    return 2
