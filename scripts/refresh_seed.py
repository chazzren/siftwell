"""Bring the seed list the app ships (assets/directory/seed.json.gz) up to date from the published employer directory.

    python scripts/refresh_seed.py [--base <url of the index branch>] [--out <file>] [--strict]

The weekly directory build publishes seed.json.gz next to manifest.json on the `index` branch (index_build/build.py);
the release workflow runs this in every job that packages the app, so each release carries the newest list of job
sites for "Build my own directory". It is deliberately forgiving: when the directory can't be reached, has no seed
yet, fails its checksum or looks wrong (far fewer job sites than the one already in the repo, or too big), it says so
and leaves the committed file alone (exit code 0), so a release never fails because of it. --strict: exit 1 instead.
Stdlib only; nothing here needs a data folder."""
import argparse, hashlib, json, os, sys, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MAX_BYTES = 3_000_000       # the app's target is under ~2 MB; a bigger one than this is refused


def _repo():
    slug = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if slug:
        return slug
    sys.path.insert(0, ROOT)
    try:
        import re
        src = open(os.path.join(ROOT, "appupdate.py"), encoding="utf-8").read()
        m = re.search(r'^REPO\s*=\s*["\']([^"\']+)["\']', src, re.M)
        return m.group(1) if m else ""
    except OSError:
        return ""


def _get(url, cap):
    req = urllib.request.Request(url, headers={"User-Agent": "Siftwell release (seed list)"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read(cap + 1)
    if len(data) > cap:
        raise ValueError(f"{url} is larger than {cap:,} bytes")
    return data


def main():
    ap = argparse.ArgumentParser(description="Refresh the shipped seed list from the published directory.")
    ap.add_argument("--base", default="", help="where manifest.json and seed.json.gz are (default: this repo's index branch)")
    ap.add_argument("--out", default=os.path.join(ROOT, "assets", "directory", "seed.json.gz"))
    ap.add_argument("--strict", action="store_true", help="exit 1 when the seed could not be refreshed")
    args = ap.parse_args()
    sys.path.insert(0, ROOT)
    from index_build import seed
    base = (args.base or f"https://raw.githubusercontent.com/{_repo()}/index").rstrip("/")
    try:
        have = seed.count(open(args.out, "rb").read())
    except (OSError, ValueError, EOFError):
        have = 0
    try:
        man = json.loads(_get(base + "/manifest.json", 5_000_000).decode("utf-8"))
        ent = man.get("seed") if isinstance(man, dict) else None
        if not isinstance(ent, dict) or not ent.get("sha256"):
            raise ValueError("the published directory has no seed list yet")
        data = _get(base + "/" + seed.FILE, MAX_BYTES)
        if hashlib.sha256(data).hexdigest() != ent["sha256"]:
            raise ValueError("checksum mismatch")
        n = seed.count(data)
        if n < 1000 or n < 0.6 * have:
            raise ValueError(f"only {n:,} job sites in the published seed (the shipped one has {have:,})")
    except Exception as e:
        print(f"Seed list NOT refreshed ({type(e).__name__}: {str(e)[:200]}). Keeping the one in the repo ({have:,} job sites).")
        return 1 if args.strict else 0
    try:
        with open(args.out, "rb") as f:
            same = f.read() == data
    except OSError:
        same = False
    if same:
        print(f"Seed list is already the newest ({n:,} job sites, {len(data):,} bytes).")
        return 0
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "wb") as f:
        f.write(data)
    print(f"Seed list refreshed: {n:,} job sites, {len(data):,} bytes (was {have:,}); directory built {man.get('built')}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
