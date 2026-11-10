"""One background job at a time per data folder: fetching, board rebuilds, re-rating and the per-job rating buttons
all write the same boards and rating caches, so they take turns through a lock file, DATA/job.lock.

The file holds JSON {pid, pid_ct, child, child_ct, kind, at, token}. `pid` is the process that took the lock; when the
server takes it on behalf of a jobfinder.py subprocess it passes JOBBOARD_JOB_LOCK=<token> to the child, which then
records its own pid as `child` instead of locking again (so a child left running after a server restart still counts
as the holder). `*_ct` is the process creation time, so a recycled pid is not mistaken for the holder.
A lock whose processes are all gone is stale and is taken over. While a lock is held, its file's modification time is
refreshed every HEARTBEAT seconds; a holder whose liveness can only be judged by pid (no creation time available) is
treated as dead after MAX_AGE without a heartbeat. A holder verified alive is never taken over, however long it runs.
A released lock is removed; if Windows won't let it be removed (a reader has it open), it is rewritten with
`released: true`, which every reader treats as free.

Windows note: open() doesn't share DELETE, so while anything (a polling waiter, antivirus) has job.lock open,
os.remove/os.replace on it fail with PermissionError. Every touch of the file therefore goes through _retry()."""
import atexit
import contextlib
import json
import os
import threading
import time

import paths

LOCK = os.path.join(paths.DATA, "job.lock")
ENV = "JOBBOARD_JOB_LOCK"
MAX_AGE = 12 * 3600   # no-heartbeat limit, used only when a recorded pid can't be verified by creation time
HEARTBEAT = 30.0      # seconds between heartbeat touches while holding
RELEASE_WAIT = 3.0    # how long release keeps retrying to remove the file before marking it released
LEFTOVER_AGE = 24 * 3600
_local = threading.local()
_held = {}            # token -> True for locks this process currently holds (released at exit if still held)
_leaked = set()       # tokens of ours whose release could neither remove nor mark the file: treated as stale
_swept = False


class Busy(Exception):
    pass


def _log(msg):
    try:
        print(f"joblock: {msg}", flush=True)
    except Exception:
        pass


def _retry(fn, tries=5, delay=0.08):
    """Call fn(), retrying on OSError (Windows PermissionError while another process has the file open).
    FileNotFoundError is final. The last OSError is re-raised."""
    for i in range(tries):
        try:
            return fn()
        except FileNotFoundError:
            raise
        except OSError:
            if i == tries - 1:
                raise
            time.sleep(delay)


# ---------------------------------------------------------------- process identity
_k32 = None


def _kernel32():
    global _k32
    if _k32 is None:
        import ctypes
        from ctypes import wintypes
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.OpenProcess.restype = wintypes.HANDLE
        k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        k.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        k.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
        _k32 = k
    return _k32


def _proc_info(pid):
    """(exists, creation_time) for a pid. creation_time is None when it can't be read (then only the pid is known)."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False, None
    if pid <= 0:
        return False, None
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        k = _kernel32()
        h = k.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return ctypes.get_last_error() == 5, None  # access denied: it exists
        try:
            code = wintypes.DWORD()
            if k.GetExitCodeProcess(h, ctypes.byref(code)) and code.value != 259:  # 259 = STILL_ACTIVE
                return False, None
            c, e, s, u = (wintypes.FILETIME() for _ in range(4))
            ct = None
            if k.GetProcessTimes(h, ctypes.byref(c), ctypes.byref(e), ctypes.byref(s), ctypes.byref(u)):
                ct = (c.dwHighDateTime << 32) | c.dwLowDateTime
            return True, ct
        finally:
            k.CloseHandle(h)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False, None
    except PermissionError:
        pass
    ct = None
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8", errors="replace") as f:
            ct = f.read().rsplit(")", 1)[1].split()[19]  # starttime, in clock ticks since boot
    except (OSError, IndexError):
        try:
            import subprocess
            out = subprocess.run(["ps", "-o", "lstart=", "-p", str(pid)], capture_output=True, text=True, timeout=3).stdout.strip()
            ct = out or None
        except Exception:
            ct = None
    return True, ct


def _ctime(pid):
    return _proc_info(pid)[1]


def _alive(pid, ct=None):
    """(alive, verified). verified=True means the answer rests on a matching/mismatching creation time (or the pid
    not existing at all); False means the pid exists but couldn't be checked against a recorded creation time."""
    if not pid:
        return False, True
    exists, cur = _proc_info(pid)
    if not exists:
        return False, True
    if ct is not None and cur is not None:
        return cur == ct, True
    return True, False


# ---------------------------------------------------------------- reading the lock
def _read():
    """(state, record): ("ok", dict) | ("missing", None) | ("busy", None) when the file can't be opened right now
    (Windows sharing violation, after retries) | ("unreadable", None) for a half-written or corrupt file."""
    def rd():
        with open(LOCK, encoding="utf-8") as f:
            return f.read()
    try:
        txt = _retry(rd)
    except FileNotFoundError:
        return "missing", None
    except OSError:
        return "busy", None
    try:
        rec = json.loads(txt)
    except ValueError:
        return "unreadable", None
    if not isinstance(rec, dict):
        return "unreadable", None
    return "ok", rec


def holder():
    """The current lock record, or None when free (released, missing or unreadable). When the file can't be read
    right now (busy), a placeholder {"kind": "job", "busy": True} is returned: it is held, we just can't see by whom.
    Never raises."""
    try:
        state, rec = _read()
    except Exception:
        return {"kind": "job", "busy": True}
    if state == "busy":
        return {"kind": "job", "busy": True}
    if state != "ok" or rec.get("released"):
        return None
    return rec


def info():
    """For status pages: None when no job holds the lock, else {kind, at (epoch seconds), pid, alive, mine}. alive says
    whether a process named in the lock is still running (False = an orphaned lock that will be taken over); mine says
    this very process holds it. A lock that can't be read right now is reported as alive with an unknown kind."""
    rec = holder()
    if not rec:
        return None
    if rec.get("busy"):
        return {"kind": "job", "at": None, "pid": None, "alive": True, "mine": False}
    alive = any(_alive(rec.get(k), rec.get(k + "_ct"))[0] for k in ("pid", "child"))
    return {"kind": str(rec.get("kind") or "job"), "at": rec.get("at"), "pid": rec.get("pid"), "alive": alive,
            "mine": rec.get("pid") == os.getpid()}


def _stale(rec, mtime=None):
    if rec is None or rec.get("released"):
        return True
    if rec.get("token") in _leaked:
        return True
    verified_alive = False
    unverified_alive = False
    for key in ("pid", "child"):
        a, v = _alive(rec.get(key), rec.get(key + "_ct"))
        if a and v:
            verified_alive = True
        elif a:
            unverified_alive = True
    if verified_alive:
        return False  # a holder we can positively identify is never taken over, however long it has run
    if not unverified_alive:
        return True
    beat = max(float(rec.get("at") or 0), mtime or 0)  # only a bare pid: it may be a recycled one
    return time.time() - beat > MAX_AGE


# ---------------------------------------------------------------- taking, breaking
def _try_take(kind, token):
    me = os.getpid()
    rec = {"pid": me, "pid_ct": _ctime(me), "child": None, "child_ct": None, "kind": kind, "at": time.time(), "token": token}
    try:
        fd = os.open(LOCK, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    except FileExistsError:
        return False
    except OSError:
        return False  # Windows: delete-pending or sharing violation; try again next poll
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(rec, f)
    except OSError:
        with contextlib.suppress(OSError):
            os.remove(LOCK)
        return False
    return True


def _drop(path):
    try:
        _retry(lambda: os.remove(path))
    except OSError:
        pass


def _break_if_stale():
    try:
        st = _retry(lambda: os.stat(LOCK))
    except OSError:
        return  # missing, or busy right now
    state, rec = _read()
    if state in ("missing", "busy"):
        return
    if state == "unreadable" and time.time() - st.st_mtime < 5:
        return  # being written right now
    if not _stale(rec, st.st_mtime):
        return
    aside = f"{LOCK}.stale-{os.getpid()}-{threading.get_ident()}"
    try:
        _retry(lambda: os.replace(LOCK, aside))  # atomic: only one waiter wins the takeover
    except OSError:
        return
    moved = None
    try:
        with open(aside, encoding="utf-8") as f:
            moved = json.load(f)
    except (OSError, ValueError):
        pass
    if rec is not None and (moved or {}).get("token") != rec.get("token"):
        # someone else took the lock between our check and the move: give it back
        try:
            os.rename(aside, LOCK)
        except OSError:
            # a third process acquired in the meantime: don't claim anything, leave their lock alone
            _log("takeover abandoned: the lock was re-acquired during the check")
            _drop(aside)
        return
    _log(f"took over a stale lock ({(rec or {}).get('kind')}, pid {(rec or {}).get('pid')})")
    _drop(aside)


# ---------------------------------------------------------------- releasing
def _mark_released(token, deadline):
    """Rewrite the lock record in place with released=true (works while readers have the file open)."""
    while True:
        state, rec = _read()
        if state == "missing" or (state == "ok" and rec.get("token") != token):
            return True
        if state == "ok":
            rec = dict(rec, released=True, released_at=time.time())
            try:
                with open(LOCK, "r+", encoding="utf-8") as f:
                    f.seek(0)
                    f.write(json.dumps(rec))
                    f.truncate()
                return True
            except FileNotFoundError:
                return True
            except OSError:
                pass
        if time.time() > deadline:
            return False
        time.sleep(0.1)


def _release(token):
    _held.pop(token, None)
    deadline = time.time() + RELEASE_WAIT
    while True:
        state, rec = _read()
        if state == "missing" or (state == "ok" and rec.get("token") != token):
            return  # gone, or no longer ours
        try:
            os.remove(LOCK)
            return
        except FileNotFoundError:
            return
        except OSError:
            pass
        if time.time() > deadline:
            break
        time.sleep(0.1)
    if _mark_released(token, time.time() + RELEASE_WAIT):
        _log("couldn't remove job.lock (in use by another process); marked it released instead")
        return
    _leaked.add(token)
    _log("couldn't remove or mark job.lock released; this process will treat its own lock as free")


@atexit.register
def _release_all():
    for token in list(_held):
        with contextlib.suppress(Exception):
            _release(token)


def _heartbeat(token, stop):
    while not stop.wait(HEARTBEAT):
        try:
            state, rec = _read()
            if state == "ok" and rec.get("token") == token:
                _retry(lambda: os.utime(LOCK))
        except Exception:
            pass


# ---------------------------------------------------------------- leftovers
def _sweep_old(folder, match):
    try:
        entries = list(os.scandir(folder))
    except OSError:
        return
    cutoff = time.time() - LEFTOVER_AGE
    for e in entries:
        try:
            if e.is_file(follow_symlinks=False) and match(e.name) and e.stat().st_mtime < cutoff:
                os.remove(e.path)
        except OSError:
            pass


def _sweep_asides():
    base = os.path.basename(LOCK) + ".stale-"
    _sweep_old(os.path.dirname(LOCK), lambda n: n.startswith(base))


def sweep_temp_files():
    """One-time (per process) cleanup of paths.write_atomic temp files (.<name>.*.tmp) left by a crash, older than a day:
    in DATA and in each DATA/people/<id>/."""
    global _swept
    if _swept:
        return
    _swept = True
    match = lambda n: n.startswith(".") and n.endswith(".tmp")
    _sweep_old(paths.DATA, match)
    try:
        for e in os.scandir(os.path.join(paths.DATA, "people")):
            if e.is_dir(follow_symlinks=False):
                _sweep_old(e.path, match)
    except OSError:
        pass


@contextlib.contextmanager
def hold(kind, wait=True, timeout=None, on_wait=None, poll=1.0, cancel=None):
    """Hold the data-folder job lock for a block. Waits (polling) while another job holds it; timeout=None waits
    without limit. Raises Busy if not waiting / timed out, or when `cancel` (a threading.Event) is set while waiting.
    Yields the lock token (pass it to child processes via child_env())."""
    if getattr(_local, "token", None):  # this thread already holds it
        yield _local.token
        return
    if os.environ.get(ENV):  # a parent process took it for us
        _adopt(os.environ[ENV])
        yield os.environ[ENV]
        return
    os.makedirs(paths.DATA, exist_ok=True)
    with contextlib.suppress(Exception):
        _sweep_asides()
        sweep_temp_files()
    token = f"{os.getpid()}-{threading.get_ident()}-{time.time():.3f}"
    t0, told = time.time(), False

    def attempt():
        if _try_take(kind, token):
            return True
        try:
            _break_if_stale()
        except Exception as e:  # never let a lock-file hiccup stop a job from starting or waiting
            _log(f"stale check failed ({e!r})")
        return _try_take(kind, token)

    while not attempt():
        if not wait or (timeout is not None and time.time() - t0 > timeout) or (cancel is not None and cancel.is_set()):
            raise Busy((holder() or {}).get("kind") or "another job")
        if on_wait and not told:
            on_wait((holder() or {}).get("kind") or "another job")
            told = True
        if cancel is not None:
            cancel.wait(poll)
        else:
            time.sleep(poll)
    _held[token] = True
    _local.token = token
    stop = threading.Event()
    try:
        threading.Thread(target=_heartbeat, args=(token, stop), daemon=True, name="joblock-heartbeat").start()
        yield token
    finally:
        stop.set()
        _local.token = None
        try:
            _release(token)
        except BaseException as e:
            _log(f"release failed ({e!r})")
            _leaked.add(token)
            raise


def _adopt(token):
    """In a child started under the parent's lock: record our pid as the child holder."""
    state, rec = _read()
    if state == "ok" and rec.get("token") == token and rec.get("child") != os.getpid() and not rec.get("released"):
        rec["child"] = os.getpid()
        rec["child_ct"] = _ctime(os.getpid())
        try:
            paths.dump_json_atomic(LOCK, rec)
        except OSError:
            pass


def child_env(token):
    """Environment for a subprocess that runs under a lock this process holds."""
    return {**os.environ, ENV: token}
