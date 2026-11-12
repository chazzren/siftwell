"""Make the seed list the app ships (assets/directory/seed.json.gz) from a directory builder state on disk.

    python scripts/make_seed.py --state <index out>/_state/tenants.json.gz [--out assets/directory/seed.json.gz]

The seed is every job board the builder knows, with its last-known name and states (hints only): what "Build my own
directory" starts from (index_build/seed.py, index_build/local.py). The weekly build publishes the same file on the
`index` branch, and a release picks that one up by itself (scripts/refresh_seed.py); this script is for making one by
hand from a local builder run. The state is only read. Prints the size and the number of boards."""
import argparse, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def main():
    ap = argparse.ArgumentParser(description="Make the shipped seed list from a builder state.")
    ap.add_argument("--state", required=True, help="the builder's _state/tenants.json.gz")
    ap.add_argument("--out", default=os.path.join(ROOT, "assets", "directory", "seed.json.gz"))
    ap.add_argument("--built", default="", help="date to stamp it with (default: today)")
    args = ap.parse_args()
    os.environ.setdefault("JOBBOARD_DATA", os.path.join(tempfile.mkdtemp(prefix="siftwell-seed-"), "data"))
    os.environ["SIFTWELL_FORBID_CLAUDE"] = "1"
    sys.path.insert(0, ROOT)
    import datetime as dt
    from index_build import build, seed
    tenants = build.load_json_gz(os.path.abspath(args.state), None)
    if not isinstance(tenants, dict) or not tenants:
        print(f"No builder state at {args.state}.")
        return 1
    s = seed.make(tenants, args.built or dt.date.today().isoformat())
    data = seed.dumps(s)
    n = seed.count(data)
    with_states = sum(1 for b in seed.boards(s) if b["st"])
    out = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "wb") as f:
        f.write(data)
    print(f"{out}: {len(data):,} bytes, {n:,} boards ({with_states:,} with last-known states), from {len(tenants):,} in the state")
    return 0


if __name__ == "__main__":
    sys.exit(main())
