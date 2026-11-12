"""Backup & move: export everything the household owns to one zip, and restore such a zip (on this or another computer).

Export  POST /api/backup/export {include_removed}   builds DATA -> Siftwell-backup-YYYY-MM-DD.zip in DATA/_backup_tmp (background)
        GET  /api/backup/download                   streams the finished zip
Import  POST /api/backup/upload   (raw body, Content-Length)   streamed to DATA/_backup_tmp/upload.zip, validated, preview returned
        POST /api/backup/restore {confirm: true}    background: stage -> set current data aside -> swap in -> migrate -> reload
        POST /api/backup/discard                    forget the uploaded file
        GET  /api/backup/status                     {job, has_data, version}

What is backed up: people/ (profiles, resumes, marks, tailored resumes, settings, boards), people.json, catalog.db (copied with
SQLite's online backup API so it is consistent while the server runs), ai_scores.json, pivot_scores.json, company_facts*,
company_research/, companies.json, config.json, schedule.json, network.json, access_key, market.json, plus manifest.json.
Left out: logs, _archive, people_removed (unless asked), runtime files (pid, lock, port), jsonld_cache, claude_work, secrets.json
(the Anthropic API key is a credential: enter it again on the other computer), temp files.

The routes are wired in server.py through configure(); this module never imports server.py. The pane and the welcome-page
widget share one script (JS) and stylesheet (CSS)."""
import datetime as dt
import json
import os
import re
import shutil
import sqlite3
import threading
import time
import zipfile

import joblock
import paths

FORMAT = 1                       # bump only when the zip layout changes incompatibly
MAX_UPLOAD = 12 * 1024 ** 3      # bytes in the zip itself
MAX_UNCOMPRESSED = 24 * 1024 ** 3
MAX_ENTRIES = 400_000
MAX_RATIO = 400                  # one entry may not expand more than this much (zip-bomb guard), above 1 MB
CHUNK = 1024 * 1024

TMP = os.path.join(paths.DATA, "_backup_tmp")
UPLOAD = os.path.join(TMP, "upload.zip")
# "directory": the employer directory's memory per person (which employers were offered, removed or pruned, so a
# removed one stays off and the weekly additions keep coming) and its cached files; "claude_usage.jsonl": the Claude
# usage history behind Settings, Claude usage.
TOP_NAMES = {"people.json", "catalog.db", "ai_scores.json", "pivot_scores.json", "config.json", "schedule.json",
             "network.json", "access_key", "market.json", "companies.json", "people", "company_research", "manifest.json",
             "directory", "claude_usage.jsonl"}
SIDECARS = ("catalog.db-wal", "catalog.db-shm", "catalog.db-journal")   # never exported; set aside with catalog.db on restore
SKIP_SUFFIX = (".tmp", ".lock", ".pid", ".part")

_L = threading.Lock()
JOB = {"state": "idle"}          # kind export|restore, state idle|running|done|error, msg, pct, ...
CFG = {"lock": None, "busy": lambda: "", "after": lambda: None}


def configure(lock, busy, after):
    """lock: the server's jobs_file_lock; busy(): reason string while something a restore would disturb runs;
    after(): re-read everything in the server process once a restore has swapped the data in."""
    CFG.update(lock=lock, busy=busy, after=after)


class BackupError(Exception):
    """A problem worth showing the user in plain words."""


# ---------------------------------------------------------------- small helpers
def app_version():
    try:
        return open(os.path.join(paths.APP, "VERSION"), encoding="utf-8").read().strip() or "dev"
    except OSError:
        return "dev"


def _vtuple(v):
    m = re.match(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?", str(v or ""))
    return tuple(int(x or 0) for x in m.groups()) if m else None


def human(n):
    for u in ("bytes", "KB", "MB", "GB"):
        if n < 1024 or u == "GB":
            return f"{n:,.0f} {u}" if u == "bytes" else (f"{n:,.0f} {u}" if n >= 100 else f"{n:,.1f} {u}")
        n /= 1024


def is_user_name(name, include_removed=False):
    """Is this top-level name in DATA part of the user's data (as opposed to logs, runtime files, caches)?"""
    if name in TOP_NAMES or name.startswith("company_facts"):
        return True
    return include_removed and name == "people_removed"


def _skip_file(name):
    return name.endswith(SKIP_SUFFIX) or name.startswith("~$") or name == "__pycache__"


def _free(path):
    try:
        return shutil.disk_usage(path).free
    except OSError:
        return 1 << 62


def _set(**kw):
    with _L:
        JOB.update(kw)


def sweep_tmp(keep_upload=True):
    """Remove stale export files, half-written parts and staging folders (never while a job runs)."""
    if JOB.get("state") == "running" or not os.path.isdir(TMP):
        return
    now = time.time()
    for n in os.listdir(TMP):
        p = os.path.join(TMP, n)
        try:
            age = now - os.path.getmtime(p)
            if n == "upload.zip" and keep_upload and age < 6 * 3600:
                continue
            if n.startswith("export-") and n.endswith(".zip") and JOB.get("file") == p and age < 3600:
                continue
            if os.path.isdir(p):
                shutil.rmtree(p, ignore_errors=True)
            else:
                os.remove(p)
        except OSError:
            pass


# ---------------------------------------------------------------- export
def _walk_user_files(include_removed):
    """[(abs path, arcname, size)] for everything to back up, except catalog.db (snapshotted separately)."""
    out = []
    D = paths.DATA
    for name in sorted(os.listdir(D)):
        if name == "catalog.db" or not is_user_name(name, include_removed):
            continue
        p = os.path.join(D, name)
        if os.path.isfile(p):
            if not _skip_file(name):
                out.append((p, name, os.path.getsize(p)))
        elif os.path.isdir(p):
            for root, dirs, files in os.walk(p):
                dirs[:] = [d for d in dirs if d != "__pycache__"]
                for f in files:
                    if _skip_file(f):
                        continue
                    fp = os.path.join(root, f)
                    try:
                        sz = os.path.getsize(fp)
                    except OSError:
                        continue
                    out.append((fp, os.path.relpath(fp, D).replace(os.sep, "/"), sz))
    return out


def _json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _person_counts(pid, name):
    d = os.path.join(paths.DATA, "people", pid)
    board = _json(os.path.join(d, "jobs.json"), {}) or {}
    marks = _json(os.path.join(d, "marks.json"), {}) or {}
    tdir = os.path.join(d, "tailored")
    tailored = len([f for f in os.listdir(tdir) if f.endswith(".json")]) if os.path.isdir(tdir) else 0
    rdir = os.path.join(d, "resumes")
    resumes = len([f for f in os.listdir(rdir) if os.path.isfile(os.path.join(rdir, f))]) if os.path.isdir(rdir) else 0
    return {"id": pid, "name": name, "jobs": len(board.get("jobs") or []), "ratings": int(board.get("ai_scored") or 0),
            "marks": len(marks) if isinstance(marks, dict) else 0, "tailored": tailored, "resumes": resumes}


def _snapshot_catalog(dest):
    """Consistent copy of catalog.db while the server may be using it (SQLite online backup); returns its counts."""
    src_path = os.path.join(paths.DATA, "catalog.db")
    if not os.path.exists(src_path):
        return None
    src = sqlite3.connect(src_path, timeout=60)
    try:
        dst = sqlite3.connect(dest)
        try:
            src.backup(dst)
            dst.execute("PRAGMA journal_mode=DELETE")   # one self-contained file, no -wal/-shm needed
            dst.commit()
            cnt = {}
            for k, q in (("companies", "SELECT COUNT(*) FROM companies"),
                         ("open_listings", "SELECT COUNT(*) FROM listings WHERE closed_at IS NULL AND partial=0"),
                         ("closed_listings", "SELECT COUNT(*) FROM listings WHERE closed_at IS NOT NULL")):
                try:
                    cnt[k] = dst.execute(q).fetchone()[0]
                except sqlite3.Error:
                    cnt[k] = 0
            return cnt
        finally:
            dst.close()
    finally:
        src.close()


def _build_export(include_removed):
    os.makedirs(TMP, exist_ok=True)
    sweep_tmp()
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    snap = os.path.join(TMP, f"catalog-{stamp}.snapshot")
    part = os.path.join(TMP, f"export-{stamp}.zip.part")
    final = os.path.join(TMP, f"export-{stamp}.zip")
    try:
        _set(msg="Waiting for a quiet moment…", pct=0)
        try:
            lock_ctx = joblock.hold("backup", wait=False)
            lock_ctx.__enter__()
        except joblock.Busy as e:
            raise BackupError(f"Siftwell is busy right now ({e}). Try again when it finishes.")
        try:
            with CFG["lock"]:
                _set(msg="Copying the catalog…", pct=2)
                files = _walk_user_files(include_removed)
                cat_counts = _snapshot_catalog(snap)
                if cat_counts is not None:
                    files.append((snap, "catalog.db", os.path.getsize(snap)))
                total = sum(f[2] for f in files) or 1
                if _free(TMP) < total + 50 * 1024 ** 2:
                    raise BackupError(f"There isn't enough free disk space to make the backup (about {human(total)} needed).")
                idx = _json(os.path.join(paths.DATA, "people.json"), []) or []
                names = {p.get("id"): p.get("name") for p in idx if isinstance(p, dict)}
                ppl = [_person_counts(pid, names.get(pid) or pid) for pid in names if pid]
                removed = []
                rd = os.path.join(paths.DATA, "people_removed")
                if include_removed and os.path.isdir(rd):
                    removed = sorted(os.listdir(rd))
                manifest = {"app": "siftwell", "format": FORMAT, "version": app_version(),
                            "exported_at": dt.datetime.now().isoformat(timespec="seconds"),
                            "people": ppl, "catalog": cat_counts or {}, "include_removed": bool(include_removed),
                            "removed_profiles": removed, "files": len(files)}
                done = 0
                with zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED, compresslevel=3, allowZip64=True) as zf:
                    zf.writestr("manifest.json", json.dumps(manifest, indent=1))
                    for abs_p, arc, sz in files:
                        try:
                            zf.write(abs_p, arc)
                        except FileNotFoundError:
                            continue          # a temp file vanished mid-walk
                        done += sz
                        _set(msg="Packing your data…", pct=min(98, 5 + int(done * 93 / total)))
        finally:
            lock_ctx.__exit__(None, None, None)
        os.replace(part, final)
        size = os.path.getsize(final)
        name = f"Siftwell-backup-{dt.date.today().isoformat()}.zip"
        _set(state="done", msg="Backup ready.", pct=100, file=final, name=name, size=size, size_h=human(size), manifest=manifest)
    except BackupError as e:
        _set(state="error", msg=str(e))
    except Exception as e:
        _set(state="error", msg=f"The backup didn't finish ({type(e).__name__}: {str(e)[:160]}). Nothing was changed.")
    finally:
        for p in (snap, part):
            try:
                os.remove(p)
            except OSError:
                pass


def start_export(include_removed):
    with _L:
        if JOB.get("state") == "running":
            raise BackupError("A backup or restore is already in progress.")
        JOB.clear()
        JOB.update(kind="export", state="running", msg="Starting…", pct=0)
    threading.Thread(target=_build_export, args=(bool(include_removed),), daemon=True).start()


# ---------------------------------------------------------------- validating a backup zip
def _clean_member(name):
    """The member's path parts, or raise BackupError when it could escape the data folder."""
    n = name.replace("\\", "/")
    if "\x00" in n or n.startswith("/") or re.match(r"^[A-Za-z]:", n) or n.startswith("//"):
        raise BackupError("This file isn't a safe Siftwell backup (it contains absolute paths), so it was not opened.")
    parts = [p for p in n.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise BackupError("This file isn't a safe Siftwell backup (it contains paths that point outside the data folder), so it was not opened.")
    if any(re.match(r"^[A-Za-z]:", p) for p in parts):
        raise BackupError("This file isn't a safe Siftwell backup (it contains unusual file names), so it was not opened.")
    return parts


def inspect(path):
    """Validate a backup zip and describe it. Raises BackupError (friendly text) when it must be refused.
    Returns {manifest, warnings, size, entries: [(info, parts)], unknown, total, has_removed}."""
    try:
        zf = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError):
        raise BackupError("That doesn't look like a Siftwell backup. It isn't a zip file, or it didn't finish copying.")
    with zf:
        infos = zf.infolist()
        if len(infos) > MAX_ENTRIES:
            raise BackupError("This backup has far more files than Siftwell would ever make, so it was not opened.")
        entries, unknown, total, has_removed, names = [], 0, 0, False, set()
        for zi in infos:
            parts = _clean_member(zi.filename)
            if not parts:
                continue
            if (zi.external_attr >> 16) & 0o170000 == 0o120000:
                raise BackupError("This file isn't a safe Siftwell backup (it contains shortcuts), so it was not opened.")
            if zi.flag_bits & 0x1:
                raise BackupError("This backup is password protected. Siftwell backups aren't; was it made by something else?")
            top = parts[0]
            if zi.is_dir():
                continue
            if zi.file_size > 1024 ** 2 and zi.compress_size and zi.file_size / zi.compress_size > MAX_RATIO:
                raise BackupError("This file has an unusually compressed entry, so it was not opened.")
            names.add("/".join(parts))
            if top == "people_removed" and len(parts) > 1:
                has_removed = True
            elif not (top in TOP_NAMES or top.startswith("company_facts")):
                unknown += 1
                continue
            if top == "manifest.json" and len(parts) != 1:
                unknown += 1
                continue
            total += zi.file_size
            entries.append((zi, parts))
        if total > MAX_UNCOMPRESSED:
            raise BackupError("This backup is larger than Siftwell can restore.")
        if "manifest.json" not in names:
            raise BackupError("That zip isn't a Siftwell backup (it has no manifest.json). Choose a file named Siftwell-backup-….zip made by Export everything.")
        try:
            man = json.loads(zf.read("manifest.json").decode("utf-8"))
            if not isinstance(man, dict) or man.get("app") != "siftwell":
                raise ValueError
            fmt = int(man.get("format"))
        except (ValueError, TypeError, KeyError, UnicodeDecodeError, zipfile.BadZipFile):
            raise BackupError("That zip isn't a Siftwell backup (its manifest couldn't be read).")
        if fmt > FORMAT:
            raise BackupError("This backup was made by a newer Siftwell whose backup layout this version can't read. Update Siftwell, then try again.")
        if "people.json" not in names and "catalog.db" not in names:
            raise BackupError("This backup has no profiles and no job catalog in it, so there is nothing to restore.")
        try:
            pj = json.loads(zf.read("people.json").decode("utf-8")) if "people.json" in names else []
            if not isinstance(pj, list) or any(not isinstance(p, dict) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", str(p.get("id", ""))) for p in pj):
                raise ValueError
        except (ValueError, UnicodeDecodeError):
            raise BackupError("The list of people in this backup is damaged, so it was not restored.")
    warnings = []
    theirs, mine = _vtuple(man.get("version")), _vtuple(app_version())
    if theirs and mine and theirs > mine:
        warnings.append(f"This backup was made by a newer Siftwell ({man.get('version')}); this one is {app_version()}. "
                        "It should restore fine, but update Siftwell when you can.")
    if unknown:
        warnings.append(f"{unknown} file{'s' if unknown != 1 else ''} in the backup that this Siftwell doesn't use will be skipped.")
    return {"manifest": man, "warnings": warnings, "size": os.path.getsize(path), "entries": entries, "total": total,
            "has_removed": has_removed or bool(man.get("include_removed")), "unknown": unknown}


def _preview(info):
    m = info["manifest"]
    return {"version": m.get("version"), "exported_at": m.get("exported_at"), "people": m.get("people") or [],
            "catalog": m.get("catalog") or {}, "size": info["size"], "size_h": human(info["size"]),
            "unpacked_h": human(info["total"]), "warnings": info["warnings"], "has_removed": info["has_removed"],
            "my_version": app_version()}


def has_data():
    try:
        return bool(_json(os.path.join(paths.DATA, "people.json"), []))
    except Exception:
        return False


# ---------------------------------------------------------------- restore
def _move(src, dst, tries=40):
    for i in range(tries):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if i == tries - 1:
                raise
            time.sleep(0.25)


def _extract(path, info, stage):
    done, total = 0, info["total"] or 1
    root = os.path.realpath(stage)
    with zipfile.ZipFile(path) as zf:
        for zi, parts in info["entries"]:
            if parts == ["manifest.json"]:
                continue
            dest = os.path.join(stage, *parts)
            if not os.path.realpath(dest).startswith(root + os.sep):
                raise BackupError("This file isn't a safe Siftwell backup, so nothing was restored.")
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            n = 0
            with zf.open(zi) as src, open(dest, "wb") as out:
                while True:
                    b = src.read(CHUNK)
                    if not b:
                        break
                    n += len(b)
                    if n > zi.file_size + 16:
                        raise BackupError("This backup is damaged (a file is bigger than it says), so nothing was restored.")
                    out.write(b)
            done += n
            _set(msg="Unpacking the backup…", pct=min(80, int(done * 80 / total)))


def _do_restore():
    D = paths.DATA
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    stage = os.path.join(TMP, f"stage-{stamp}")
    aside = os.path.join(D, "_archive", f"before-restore-{stamp}")
    moved_aside, placed = [], []
    try:
        if not os.path.exists(UPLOAD):
            raise BackupError("The backup file is no longer there. Choose it again.")
        info = inspect(UPLOAD)
        if _free(TMP) < info["total"] + 200 * 1024 ** 2:
            raise BackupError(f"There isn't enough free disk space to restore (about {human(info['total'])} needed).")
        why = CFG["busy"]()
        if why:
            raise BackupError(f"{why}. Wait for it to finish, then restore.")
        _set(msg="Waiting for a quiet moment…", pct=1)
        try:
            lock_ctx = joblock.hold("restore", wait=False)
            lock_ctx.__enter__()
        except joblock.Busy as e:
            raise BackupError(f"Siftwell is busy right now ({e}). Try again when it finishes.")
        try:
            with CFG["lock"]:
                os.makedirs(stage, exist_ok=True)
                _extract(UPLOAD, info, stage)
                inc_removed = any(n == "people_removed" for n in os.listdir(stage))
                _set(msg="Putting your current data aside…", pct=85)
                current = [n for n in os.listdir(D) if is_user_name(n, inc_removed) or n in SIDECARS]
                try:
                    if current:
                        os.makedirs(aside, exist_ok=True)
                    for n in current:
                        _move(os.path.join(D, n), os.path.join(aside, n))
                        moved_aside.append(n)
                    _set(msg="Restoring…", pct=92)
                    for n in sorted(os.listdir(stage)):
                        _move(os.path.join(stage, n), os.path.join(D, n))
                        placed.append(n)
                except BaseException:
                    for n in placed:           # roll back: the old data goes straight back
                        p = os.path.join(D, n)
                        try:
                            shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
                        except OSError:
                            pass
                    for n in moved_aside:
                        try:
                            _move(os.path.join(aside, n), os.path.join(D, n))
                        except OSError:
                            pass
                    raise
        finally:
            lock_ctx.__exit__(None, None, None)
        if current:
            res_aside = aside
        else:
            res_aside = ""
            shutil.rmtree(aside, ignore_errors=True)
        _set(msg="Updating…", pct=96)
        try:
            paths.migrate()
        except Exception:
            pass
        try:
            import catalog
            catalog.migrate(log=lambda *a, **k: None)
        except Exception:
            pass
        CFG["after"]()
        man = info["manifest"]
        phone = {}
        try:
            import getting_started
            phone = getting_started.status(fresh=True).get("phone") or {}
        except Exception:
            pass
        first = None
        try:
            import people
            first = people.first()
        except Exception:
            pass
        _set(state="done", msg="Restored.", pct=100, aside=res_aside, people=[p.get("name") for p in man.get("people") or []],
             phone=phone, first=first, token_changed=True)
    except BackupError as e:
        _set(state="error", msg=str(e))
    except Exception as e:
        _set(state="error", msg=f"The restore didn't finish ({type(e).__name__}: {str(e)[:160]}). Your data was left as it was.")
    finally:
        shutil.rmtree(stage, ignore_errors=True)
        try:
            os.remove(UPLOAD)
        except OSError:
            pass


def start_restore():
    with _L:
        if JOB.get("state") == "running":
            raise BackupError("A backup or restore is already in progress.")
        if not os.path.exists(UPLOAD):
            raise BackupError("Choose a backup file first.")
        JOB.clear()
        JOB.update(kind="restore", state="running", msg="Starting…", pct=0)
    threading.Thread(target=_do_restore, daemon=True).start()


# ---------------------------------------------------------------- HTTP
def status():
    with _L:
        job = {k: v for k, v in JOB.items() if k != "file"}
    return {"job": job, "has_data": has_data(), "version": app_version()}


def handle_get(h, path):
    """Returns True when it answered. h is the request handler (server.H)."""
    if path == "/api/backup/status":
        h._send(200, status())
        return True
    if path == "/api/backup/download":
        f = JOB.get("file")
        if JOB.get("kind") != "export" or JOB.get("state") != "done" or not f or not os.path.exists(f):
            h._send(404, {"error": "There's no finished backup to download. Make one first."})
            return True
        h._act("backup downloaded")
        size = os.path.getsize(f)
        h.send_response(200)
        h.send_header("Content-Type", "application/zip")
        h.send_header("Content-Disposition", f'attachment; filename="{JOB.get("name") or "Siftwell-backup.zip"}"')
        h.send_header("Content-Length", str(size))
        h.send_header("Cache-Control", "no-store")
        h.end_headers()
        with open(f, "rb") as fh:
            while True:
                b = fh.read(CHUNK)
                if not b:
                    break
                h.wfile.write(b)
        return True
    return False


def handle_upload(h):
    """POST /api/backup/upload: the raw zip as the body (Content-Length required), streamed to disk then validated."""
    try:
        n = int(h.headers.get("Content-Length") or 0)
    except ValueError:
        n = 0
    h.close_connection = True
    if n <= 0:
        return h._send(411, {"error": "The file's size wasn't sent. Try again."})
    if n > MAX_UPLOAD:
        return h._send(413, {"error": f"That file is larger than Siftwell restores ({human(MAX_UPLOAD)})."})
    with _L:
        if JOB.get("state") == "running":
            return h._send(409, {"error": "A backup or restore is already in progress."})
    os.makedirs(TMP, exist_ok=True)
    sweep_tmp(keep_upload=False)
    if _free(TMP) < n * 2 + 200 * 1024 ** 2:
        return h._send(507, {"error": f"There isn't enough free disk space for this backup (about {human(n * 2)} needed)."})
    part = UPLOAD + ".part"
    try:
        left = n
        with open(part, "wb") as out:
            while left > 0:
                b = h.rfile.read(min(CHUNK, left))
                if not b:
                    raise ConnectionError("upload ended early")
                out.write(b)
                left -= len(b)
    except (ConnectionError, OSError) as e:
        try:
            os.remove(part)
        except OSError:
            pass
        return h._send(400, {"error": "The upload was interrupted. Try again."})
    try:
        os.replace(part, UPLOAD)
        info = inspect(UPLOAD)
    except BackupError as e:
        for p in (part, UPLOAD):
            try:
                os.remove(p)
            except OSError:
                pass
        return h._send(400, {"error": str(e)})
    h._act("backup uploaded for restore", None, f"{human(n)}")
    return h._send(200, {"ok": True, "preview": _preview(info), "has_data": has_data()})


def handle_post(h, path, body):
    """JSON POSTs under /api/backup/. Returns True when it answered."""
    try:
        if path == "/api/backup/export":
            start_export(bool(body.get("include_removed")))
            h._act("backup export started", None, "with removed profiles" if body.get("include_removed") else "")
            h._send(202, {"ok": True})
        elif path == "/api/backup/restore":
            if body.get("confirm") is not True:
                raise BackupError("Confirm the restore first.")
            h._act("restore from backup started")
            start_restore()
            h._send(202, {"ok": True})
        elif path == "/api/backup/discard":
            if JOB.get("state") != "running":
                try:
                    os.remove(UPLOAD)
                except OSError:
                    pass
            h._send(200, {"ok": True})
        else:
            return False
    except BackupError as e:
        h._send(409, {"error": str(e)})
    return True


# ---------------------------------------------------------------- client side (settings pane + welcome page)
CSS = """<style>
.bk-btnrow{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.bk-bar{height:8px;border-radius:6px;background:var(--line);overflow:hidden;margin:10px 0 4px}
.bk-bar i{display:block;height:100%;width:0;background:var(--accent);transition:width .2s}
.bk-card{border:1px solid var(--line);border-radius:12px;background:var(--surface);padding:12px 14px;margin-top:10px;font-size:14px}
.bk-card h4{margin:0 0 6px;font-size:14px}
.bk-card ul{margin:6px 0 0;padding:0 0 0 18px}
.bk-card li{margin:2px 0}
.bk-warn{border:1px solid var(--bad);border-radius:10px;padding:10px 12px;margin-top:10px;font-size:13.5px;color:var(--ink)}
.bk-warn b{color:var(--bad)}
.bk-note{font-size:12.5px;color:var(--muted);margin:6px 0 0}
.bk-err{color:var(--bad);font-size:13.5px;margin-top:8px}
.bk-ok{color:var(--good);font-size:13.5px;margin-top:8px}
.bk-link{font-family:ui-monospace,Consolas,monospace;font-size:12px;word-break:break-all;margin-top:4px}
.btn.bk-armed{color:var(--bad);border-color:var(--bad)}
</style>
"""

PANE_HTML = """<section class="sgsec"><h3 class="sgtitle">Export everything</h3><div class="sgroup">
<div class="srow"><div class="slab"><label for="bkRemoved">Include removed profiles</label><small>Profiles you removed from the board (kept in the people_removed folder). Off by default.</small></div><div class="sctl"><input type="checkbox" role="switch" class="sw" id="bkRemoved"></div></div>
<div class="srow stack"><div class="bk-btnrow"><button class="btn primary" type="button" id="bkExport">Export everything</button><span class="note" id="bkExpMsg" role="status" aria-live="polite"></span></div>
<div class="bk-bar" id="bkExpBar" hidden><i></i></div><div id="bkExpDone"></div></div></div>
<p class="sfoot">One file with all profiles, resumes, saved and tailored resumes, ratings, marks and the job catalog, to keep as a backup or move to another computer.
<b>This file contains your resumes and personal details. Keep it private.</b> It doesn't include your Anthropic API key (enter it again on the other computer) or your Claude sign-in.</p></section>
<section class="sgsec"><h3 class="sgtitle">Restore from a backup</h3><div class="sgroup">
<div class="srow stack"><div class="slab"><span>Restore from a backup</span>
<small>Choose a Siftwell-backup-….zip made by Export everything, on this or another computer. You'll see what's inside before anything changes.</small></div>
<div id="bkImportMount"></div></div></div></section>"""

WELCOME_HTML = """<p class="more" style="margin-top:20px"><a href="#" id="bkOpen">Bring over my data from another computer</a></p>
<div id="bkWelcomeMount" hidden></div>"""

JS = r"""(function(){
const $ = id => document.getElementById(id);
const esc = s => String(s == null ? "" : s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const H = {"Content-Type": "application/json", "X-Jobboard": "1"};
const num = n => Number(n || 0).toLocaleString();
const api = (m, u, b) => fetch(u, {method: m, headers: H, body: b === undefined ? undefined : JSON.stringify(b)})
  .then(r => r.json().then(d => { if (!r.ok) throw new Error(d.error || "Something went wrong."); return d; }));
const netErr = e => e instanceof TypeError ? "Couldn't reach Siftwell. Is it still running?" : e.message;

function poll(onTick){
  return new Promise((resolve, reject) => {
    const t = setInterval(() => {
      api("GET", "/api/backup/status").then(s => {
        onTick(s.job);
        if (s.job.state === "done") { clearInterval(t); resolve(s.job); }
        else if (s.job.state === "error") { clearInterval(t); reject(new Error(s.job.msg)); }
      }).catch(e => { if (e instanceof TypeError || /forbidden/i.test(e.message)) { clearInterval(t); reject(new Error("Siftwell is not answering. If a restore was running it may have finished: reopen Siftwell and check.")); } });
    }, 1000);
  });
}

// ---- export (Settings pane)
function initExport(){
  const btn = $("bkExport"); if (!btn) return;
  const msg = $("bkExpMsg"), bar = $("bkExpBar"), done = $("bkExpDone");
  btn.addEventListener("click", () => {
    btn.disabled = true; done.innerHTML = ""; msg.textContent = "Starting…"; bar.hidden = false;
    api("POST", "/api/backup/export", {include_removed: $("bkRemoved").checked})
      .then(() => poll(j => { msg.textContent = j.msg || ""; bar.firstElementChild.style.width = (j.pct || 0) + "%"; }))
      .then(j => {
        msg.textContent = ""; bar.hidden = true;
        done.innerHTML = `<div class="bk-ok">Backup ready: ${esc(j.name)} (${esc(j.size_h)}).</div><div class="bk-btnrow" style="margin-top:8px"><a class="btn primary" href="/api/backup/download" download="${esc(j.name)}">Download backup</a></div>`
          + `<p class="bk-note">If the download doesn't start by itself, use the button. The file is kept here for an hour, then removed.</p>`;
        const a = document.createElement("a"); a.href = "/api/backup/download"; a.download = j.name; document.body.appendChild(a); a.click(); a.remove();
      })
      .catch(e => { bar.hidden = true; msg.textContent = ""; done.innerHTML = `<div class="bk-err">${esc(netErr(e))}</div>`; })
      .finally(() => { btn.disabled = false; });
  });
}

// ---- import (Settings pane and welcome page)
function mountImport(root, hasData){
  root.innerHTML = `<div class="bk-btnrow"><button class="btn" type="button" data-pick>Choose backup file…</button><input type="file" accept=".zip,application/zip" hidden></div>
    <div class="bk-bar" hidden><i></i></div><div class="bk-msg" role="status" aria-live="polite"></div><div class="bk-prev"></div>`;
  const file = root.querySelector("input[type=file]"), pick = root.querySelector("[data-pick]"), bar = root.querySelector(".bk-bar"),
        msg = root.querySelector(".bk-msg"), prev = root.querySelector(".bk-prev");
  const say = (t, cls) => { msg.className = "bk-msg " + (cls || ""); msg.textContent = t || ""; };
  pick.addEventListener("click", () => file.click());
  file.addEventListener("change", () => {
    const f = file.files[0]; file.value = ""; if (!f) return;
    prev.innerHTML = ""; say("Uploading " + f.name + "…"); bar.hidden = false; bar.firstElementChild.style.width = "0"; pick.disabled = true;
    const x = new XMLHttpRequest();
    x.open("POST", "/api/backup/upload");
    x.setRequestHeader("X-Jobboard", "1"); x.setRequestHeader("Content-Type", "application/zip");
    x.upload.onprogress = e => { if (e.lengthComputable) bar.firstElementChild.style.width = Math.round(e.loaded * 100 / e.total) + "%"; };
    x.onerror = () => { pick.disabled = false; bar.hidden = true; say("Couldn't reach Siftwell. Is it still running?", "bk-err"); };
    x.onload = () => {
      pick.disabled = false; bar.hidden = true;
      let d = {}; try { d = JSON.parse(x.responseText); } catch(e) {}
      if (x.status !== 200) return say(d.error || "That file couldn't be used.", "bk-err");
      say(""); showPreview(d.preview, hasData || d.has_data);
    };
    x.send(f);
  });
  function showPreview(p, replaces){
    const ppl = (p.people || []).map(q => `<li><b>${esc(q.name)}</b>: ${num(q.jobs)} jobs, ${num(q.ratings)} ratings, ${num(q.marks)} marked, ${num(q.tailored)} tailored resume${q.tailored === 1 ? "" : "s"}</li>`).join("") || "<li>No profiles</li>";
    const c = p.catalog || {};
    const cat = c.companies != null ? `<div class="bk-note">Job catalog: ${num(c.companies)} companies, ${num(c.open_listings)} open listings.</div>` : "";
    const warn = (p.warnings || []).map(w => `<div class="bk-note">${esc(w)}</div>`).join("");
    prev.innerHTML = `<div class="bk-card"><h4>This backup</h4>
      <div>Made ${esc(String(p.exported_at || "").replace("T", " ").slice(0, 16) || "at an unknown time")} by Siftwell ${esc(p.version || "?")} (${esc(p.size_h)}${p.has_removed ? ", includes removed profiles" : ""})</div>
      <ul>${ppl}</ul>${cat}${warn}</div>
      ${replaces ? `<div class="bk-warn"><b>This replaces everything currently in Siftwell on this computer.</b> Your current data is first moved to a folder named <code>_archive/before-restore-…</code> in your Siftwell data folder, so it can be recovered.</div>` : ""}
      <div class="bk-btnrow" style="margin-top:10px"><button class="btn primary" type="button" data-go>${replaces ? "Replace everything with this backup" : "Restore"}</button><button class="btn ghost" type="button" data-cancel>Cancel</button></div>`;
    const go = prev.querySelector("[data-go]"), cancel = prev.querySelector("[data-cancel]");
    let armed = false, t = null;
    cancel.addEventListener("click", () => { prev.innerHTML = ""; say(""); api("POST", "/api/backup/discard", {}).catch(() => {}); });
    go.addEventListener("click", () => {
      if (replaces && !armed) {
        armed = true; go.textContent = "Tap again to replace everything"; go.classList.add("bk-armed");
        clearTimeout(t); t = setTimeout(() => { armed = false; go.textContent = "Replace everything with this backup"; go.classList.remove("bk-armed"); }, 5000);
        return;
      }
      clearTimeout(t); go.disabled = true; cancel.disabled = true; pick.disabled = true; bar.hidden = false;
      say("Starting…");
      api("POST", "/api/backup/restore", {confirm: true})
        .then(() => poll(j => { say(j.msg || ""); bar.firstElementChild.style.width = (j.pct || 0) + "%"; }))
        .then(finish)
        .catch(e => { bar.hidden = true; pick.disabled = false; go.disabled = false; cancel.disabled = false; say(netErr(e), "bk-err"); });
    });
  }
  function finish(j){
    bar.hidden = true;
    const ph = j.phone || {};
    const phone = ph.on && ph.url ? `<div class="bk-note">Phone access is on. Open this new link on your phone (or scan the QR code again in Settings → Get started), because this computer's address may have changed:</div><div class="bk-link">${esc(ph.url)}</div>`
      + (ph.restart_needed ? `<div class="bk-note">Siftwell needs a restart for phone access to match the restored setting.</div>` : "") : "";
    prev.innerHTML = `<div class="bk-ok">Restored${(j.people || []).length ? ": " + esc(j.people.join(", ")) : ""}. Your boards are being refreshed from the restored data.</div>`
      + (j.aside ? `<div class="bk-note">Your previous data was kept at ${esc(j.aside)}.</div>` : "") + phone
      + `<div class="bk-btnrow" style="margin-top:10px"><button class="btn primary" type="button" data-open>Open my board</button></div>`;
    say("");
    const open = () => (j.first ? api("POST", "/api/person", {id: j.first}).catch(() => {}) : Promise.resolve()).then(() => { location.href = "/"; });
    prev.querySelector("[data-open]").addEventListener("click", open);
    if (!(ph.on && ph.url) && root.dataset.auto === "1") setTimeout(open, 1200);
  }
}

function init(){
  initExport();
  const m = $("bkImportMount");
  if (m) api("GET", "/api/backup/status").then(s => mountImport(m, s.has_data)).catch(() => mountImport(m, true));
  const o = $("bkOpen"), w = $("bkWelcomeMount");
  if (o && w) o.addEventListener("click", e => { e.preventDefault(); if (w.hidden) { w.hidden = false; w.dataset.auto = "1"; mountImport(w, false); } else w.hidden = true; });
}
init();
})();
"""


SCRIPT = "<script>" + JS + "</script>"
