"""DATA/actions.log: one line per user-triggered action (update, re-rate, profile and company changes, settings,
start-at-sign-in changes, restart), so "who did that, and when?" has an answer. Never put secrets in a line (no
access key, API key, resume text): only a short action name, the profile id and a few safe words.
Rotates at about 1 MB (the old file becomes actions.log.1; one old file is kept). Never raises."""
import os
import threading
import time

import paths

MAX_BYTES = 1_000_000
_lock = threading.Lock()


def _clean(s, n):
    return " ".join(str(s or "").split())[:n].replace("|", "/")


def log(action, profile=None, handler=None, detail=""):
    try:
        ip = ua = "-"
        if handler is not None:
            try:
                ip = handler.client_address[0]
                ua = _clean(handler.headers.get("User-Agent"), 60) or "-"
            except Exception:
                pass
        line = " | ".join([time.strftime("%Y-%m-%d %H:%M:%S"), _clean(action, 80) + (f" ({_clean(detail, 80)})" if detail else ""),
                           _clean(profile, 40) or "-", ip, ua]) + "\n"
        path = os.path.join(paths.DATA, "actions.log")
        with _lock:
            os.makedirs(paths.DATA, exist_ok=True)
            try:
                if os.path.getsize(path) + len(line) > MAX_BYTES:
                    os.replace(path, path + ".1")
            except OSError:
                pass
            with open(path, "a", encoding="utf-8") as f:
                f.write(line)
    except Exception:
        pass
