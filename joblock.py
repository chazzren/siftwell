"""One background job at a time per data folder: fetching, board rebuilds, re-rating and the per-job rating buttons
all write the same boards and rating caches, so they take turns through a lock file, DATA/job.lock.

The file holds JSON {pid, child, kind, at}. `pid` is the process that took the lock; when the server takes it on
behalf of a jobfinder.py subprocess it passes JOBBOARD_JOB_LOCK=<token> to the child, which then records its own pid
as `child` instead of locking again (so a child left running after a server restart still counts as the holder).
A lock whose processes are all gone is stale and is taken over; so is one older than MAX_AGE."""
import contextlib
import json
import os
import threading
import time

import paths

LOCK = os.path.join(paths.DATA, "job.lock")
ENV = "JOBBOARD_JOB_LOCK"
MAX_AGE = 12 * 3600  # longer than any real job (a full update with ratings runs a few hours at most)
_local = threading.local()


class Busy(Exception):
    pass


def _alive(pid):
    if not pid:
        return False
    if os.name == "nt":
        import ctypes
        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return ctypes.GetLastError() == 5  # access denied: it exists
        try:
            code = ctypes.c_ulong()
            if not k.GetExitCodeProcess(h, ctypes.byref(code)):
                return True
            return code.value == 259  # STILL_ACTIVE
        finally:
            k.CloseHandle(h)
    try:
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def holder():
    """The current lock record, or None when free (or unreadable)."""
    try:
        with open(LOCK, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return None


def _stale(rec):
    if rec is None:
        return True
    if time.time() - float(rec.get("at") or 0) > MAX_AGE:
        return True
    return not (_alive(rec.get("pid")) or _alive(rec.get("child")))


def _try_take(kind, token):
    rec = {"pid": os.getpid(), "child": None, "kind": kind, "at": time.time(), "token": token}
    try:
        fd = os.open(LOCK, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(rec, f)
    return True


def _break_if_stale():
    try:
        st = os.stat(LOCK)
    except FileNotFoundError:
        return
    rec = holder()
    if rec is None and time.time() - st.st_mtime < 5:
        return  # being written right now
    if _stale(rec):
        aside = f"{LOCK}.stale-{os.getpid()}-{threading.get_ident()}"
        try:
            os.replace(LOCK, aside)  # atomic: only one waiter wins the takeover
        except OSError:
            return
        try:
            with open(aside, encoding="utf-8") as f:
                moved = json.load(f)
        except (OSError, ValueError):
            moved = None
        if rec is not None and (moved or {}).get("token") != rec.get("token"):
            # someone else took the lock between our check and the move: give it back
            try:
                os.rename(aside, LOCK)
                return
            except OSError:
                pass
        print(f"joblock: took over a stale lock ({(rec or {}).get('kind')}, pid {(rec or {}).get('pid')})", flush=True)
        try:
            os.remove(aside)
        except OSError:
            pass


@contextlib.contextmanager
def hold(kind, wait=True, timeout=None, on_wait=None, poll=1.0):
    """Hold the data-folder job lock for a block. Waits (polling) while another job holds it; timeout=None waits
    without limit. Raises Busy if not waiting / timed out. Yields the lock token (pass it to child processes via
    child_env())."""
    if getattr(_local, "token", None):  # this thread already holds it
        yield _local.token
        return
    if os.environ.get(ENV):  # a parent process took it for us
        _adopt(os.environ[ENV])
        yield os.environ[ENV]
        return
    os.makedirs(paths.DATA, exist_ok=True)
    token = f"{os.getpid()}-{threading.get_ident()}-{time.time():.3f}"
    t0, told = time.time(), False
    while not _try_take(kind, token):
        _break_if_stale()
        if _try_take(kind, token):
            break
        if not wait or (timeout is not None and time.time() - t0 > timeout):
            raise Busy((holder() or {}).get("kind") or "another job")
        if on_wait and not told:
            on_wait((holder() or {}).get("kind") or "another job")
            told = True
        time.sleep(poll)
    _local.token = token
    try:
        yield token
    finally:
        _local.token = None
        rec = holder()
        if rec and rec.get("token") == token:
            try:
                os.remove(LOCK)
            except OSError:
                pass


def _adopt(token):
    """In a child started under the parent's lock: record our pid as the child holder."""
    rec = holder()
    if rec and rec.get("token") == token and rec.get("child") != os.getpid():
        rec["child"] = os.getpid()
        try:
            paths.dump_json_atomic(LOCK, rec)
        except OSError:
            pass


def child_env(token):
    """Environment for a subprocess that runs under a lock this process holds."""
    return {**os.environ, ENV: token}
