"""Where things live. Import this before touching any file.

APP     the app folder (this repo): code plus shipped read-only files.
ASSETS  shipped read-only data (assets/geo/ place tables).
PACKS   shipped starter company lists (packs/*.json).
DATA    the person's own data, kept OUTSIDE the app folder so the app can be replaced or re-downloaded safely:
          Windows  %APPDATA%\\JobBoard
          macOS    ~/Library/Application Support/JobBoard
          Linux    $XDG_DATA_HOME/jobboard (default ~/.local/share/jobboard)
        Set JOBBOARD_DATA to use another folder (tests, portable installs).

On first start after an upgrade, an old in-app data/ folder (plus the root companies.json and config.json) is copied
into DATA and the old folder is renamed data.migrated-<date>. See migrate()."""
import datetime as dt
import json
import os
import shutil
import sys

APP = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(APP, "assets")
PACKS = os.path.join(APP, "packs")
CONFIG_DEFAULT = os.path.join(APP, "config.default.json")


def _data_dir():
    env = os.environ.get("JOBBOARD_DATA")
    if env:
        return os.path.abspath(os.path.expanduser(env))
    if sys.platform == "win32":
        return os.path.join(os.environ.get("APPDATA") or os.path.expanduser(r"~\AppData\Roaming"), "JobBoard")
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support/JobBoard")
    return os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), "jobboard")


DATA = _data_dir()
COMPANIES = os.path.join(DATA, "companies.json")   # this household's working company list (company_add.py writes it)
CONFIG = os.path.join(DATA, "config.json")         # overrides merged over config.default.json
SECRETS = os.path.join(DATA, "secrets.json")
ACCESS_KEY = os.path.join(DATA, "access_key")
MIGRATION_LOG = os.path.join(DATA, "migration.log")


def data(*parts):
    """A path inside DATA (the folder is created on demand)."""
    os.makedirs(DATA, exist_ok=True)
    return os.path.join(DATA, *parts)


def asset(*parts):
    return os.path.join(ASSETS, *parts)


def write_atomic(path, text, encoding=None, newline=None):
    """Write a text file so readers see either the old or the new version, never half of one: write a temp file in
    the same folder, then os.replace it over the target. On Windows the replace fails while another process has the
    target open, so it is retried for a few seconds."""
    import tempfile, time
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="." + os.path.basename(path) + ".", suffix=".tmp", dir=d)
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline=newline) as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        for i in range(40):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                if i == 39:
                    raise
                time.sleep(0.25)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def dump_json_atomic(path, obj, **kw):
    write_atomic(path, json.dumps(obj, **kw))


class CacheUnreadable(Exception):
    """A cache file exists but can't be read or parsed. Callers must not carry on with an empty cache and save it
    (that would wipe every rating); they abort that rating run instead."""


def load_json_cache(path, tries=4, delay=0.5):
    """A JSON cache file: missing -> None (start empty); unreadable or corrupt -> retried briefly (a writer may be
    replacing it), then CacheUnreadable."""
    import time
    err = None
    for i in range(tries):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as e:
            err = e
            if i < tries - 1:
                time.sleep(delay)
    raise CacheUnreadable(f"{os.path.basename(path)} can't be read ({type(err).__name__}: {str(err)[:120]}); "
                          f"left it untouched. Fix or restore the file, then try again.")


def _merge(base, over):
    out = dict(base)
    for k, v in (over or {}).items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load_config():
    """config.default.json with the user's DATA/config.json merged over it (nested sections merge key by key)."""
    base = json.load(open(CONFIG_DEFAULT, encoding="utf-8"))
    try:
        over = json.load(open(CONFIG, encoding="utf-8"))
    except FileNotFoundError:
        over = {}
    return _merge(base, over)


def load_companies():
    """The working company list; empty on a fresh install (a starter pack can be imported later)."""
    try:
        return json.load(open(COMPANIES, encoding="utf-8"))
    except FileNotFoundError:
        return []


# ---- one-time move of the old in-app data folder
OLD = os.path.join(APP, "data")
_SKIP = {"geo"}  # shipped now (assets/geo)


def _log(msg):
    line = f"{dt.datetime.now().isoformat(timespec='seconds')}  {msg}"
    os.makedirs(DATA, exist_ok=True)
    with open(MIGRATION_LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def migrate():
    """Copy APP/data (+ root companies.json / config.json) into DATA once. Idempotent: does nothing when DATA already
    has people.json or there is no old data/people.json. The old folder is renamed, never deleted."""
    if os.path.exists(os.path.join(DATA, "people.json")) or not os.path.exists(os.path.join(OLD, "people.json")):
        return False
    _log(f"migrating {OLD} -> {DATA}")
    os.makedirs(DATA, exist_ok=True)
    n = 0
    for name in os.listdir(OLD):
        if name in _SKIP:
            _log(f"  skip {name} (shipped in assets/ now)")
            continue
        src, dst = os.path.join(OLD, name), os.path.join(DATA, name)
        if name == "people.json":
            continue  # copied last, so an interrupted copy is retried on the next start
        if os.path.isdir(src):
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dst)
        n += 1
    for name, dst in (("companies.json", COMPANIES), ("config.json", CONFIG)):
        src = os.path.join(APP, name)
        if os.path.exists(src) and not os.path.exists(dst):
            shutil.copy2(src, dst)
            _log(f"  copied {src} -> {dst}")
    shutil.copy2(os.path.join(OLD, "people.json"), os.path.join(DATA, "people.json"))
    _log(f"  copied {n + 1} entries from {OLD}")
    dest = f"{OLD}.migrated-{dt.date.today().isoformat()}"
    i = 2
    while os.path.exists(dest):
        dest = f"{OLD}.migrated-{dt.date.today().isoformat()}-{i}"; i += 1
    try:
        os.rename(OLD, dest)
        _log(f"  renamed {OLD} -> {dest}")
    except OSError as e:
        _log(f"  could not rename {OLD} ({e}); it is no longer used and can be renamed by hand")
    _log("migration done")
    return True


migrate()
