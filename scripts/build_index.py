"""Build the Siftwell employer directory (see scripts/index_build/build.py and .github/workflows/index.yml).

    python scripts/build_index.py --out <folder> [--work <scratch>] [--states OH,CO] [--limit 500] [--minutes 60]

The app modules it reuses (fetchers, detection, geo) need a data folder: it gets a scratch one (--work, default a temp
folder), never a real Siftwell data folder, and Claude is blocked for the whole run."""
import os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def main():
    work = None
    if "--work" in sys.argv:
        i = sys.argv.index("--work")
        work = sys.argv[i + 1]
        del sys.argv[i:i + 2]
    work = os.path.abspath(work or tempfile.mkdtemp(prefix="siftwell-index-"))
    os.makedirs(work, exist_ok=True)
    os.environ["JOBBOARD_DATA"] = os.path.join(work, "data")
    os.environ["SIFTWELL_FORBID_CLAUDE"] = "1"
    sys.path[:0] = [ROOT, HERE]
    from index_build import build
    return build.main()


if __name__ == "__main__":
    sys.exit(main())
