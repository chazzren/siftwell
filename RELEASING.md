# Releasing Siftwell

## Cut a release (about a minute)

1. On GitHub open the repo, then **Actions -> Release -> Run workflow**.
2. Pick the default branch, enter the **version** (like `0.2.0`, no `v`), optionally add **notes**, click **Run workflow**.
3. When the run turns green, the release is at **Releases -> latest**, with `Siftwell-<version>.zip` (Intel Mac / manual), `Siftwell-Setup-<version>.exe` (the Windows installer), `Siftwell-Portable-<version>.zip` (Windows, no install, data next to the app) and `Siftwell-<version>.dmg` (the Mac app, Apple silicon, unsigned) attached.

Versions starting with `0.` are marked "Pre-release". Nothing is published unless you click Run.

## What the workflow does

1. Checks the version looks like `x.y.z`, runs from the default branch, and that tag `v<version>` is new.
2. Runs `scripts/release_check.py`:
   - every `.py` file compiles;
   - the JavaScript inside each page passes `node --check`;
   - leak scan of tracked files: email addresses, phone numbers, API keys and tokens, private keys, tracked `data/` files, plus your own patterns from `LEAK_PATTERNS`;
   - required files exist (README, LICENSE, requirements, server, launchers).
3. Writes the version into `VERSION`, commits "Release v<version>", and tags it (locally).
4. Builds the ZIP with `git archive` (folder `Siftwell/`, dev-only files left out via `.gitattributes`) and checks that the `.command` files are still executable.
5. In parallel on a Windows runner (`windows` job, after the checks): builds `Siftwell.exe` with PyInstaller (`installer/siftwell.spec`), builds `Siftwell-Setup-<version>.exe` with Inno Setup (`installer/siftwell.iss`), and test-installs, starts and uninstalls it. The same job zips the PyInstaller bundle as `Siftwell-Portable-<version>.zip`: a top-level `Siftwell/` folder with the bundle plus `portable.txt` (the marker that switches portable mode on: data goes to `Siftwell/data`) and `README-portable.txt` (both live in `installer/portable/`). It unzips that ZIP into a scratch folder and checks `Siftwell.exe --version`.
6. In parallel on a `macos-15` runner (Apple silicon, `macos` job, after the checks): `installer/build_mac.sh` builds `Siftwell.app` with PyInstaller (`installer/siftwell-mac.spec`; the icon is `assets/brand/siftwell.icns`), signs it ad hoc and packs it with an `Applications` shortcut into `Siftwell-<version>.dmg` (hdiutil); `installer/smoke_mac.sh` then mounts that .dmg, checks the version and that the window / menu-bar libraries load (`Siftwell --check-imports`), starts `Siftwell --server <port>` on scratch data with Claude blocked, waits for `/api/ping`, and runs `Siftwell --stop`. The app is not signed with a developer certificate or notarized, so users do the first-launch Gatekeeper steps in `docs/GUIDE.md`. To try the Mac build without releasing anything, run **Actions -> Mac build test** (same build and smoke test; the .dmg is kept as a workflow artifact for 3 days).
   **The seed list.** Every job that packages the app (Windows, Mac and the ZIP's release commit) first runs `python scripts/refresh_seed.py`: it downloads `seed.json.gz` from the published employer directory (the `index` branch; the weekly **Employer directory** workflow writes it next to `manifest.json`), checks its SHA-256 against the manifest and puts it in `assets/directory/seed.json.gz`. That file is the list of job sites **Build my own directory** starts from, so every release ships the newest one, and the release commit carries it. The step never fails a release: if the directory can't be reached, has no seed yet, or the seed looks wrong (bad checksum, far fewer job sites than the one in the repo, larger than 3 MB), it says so in the log and the file already in the repo is shipped. Because each job downloads it by itself, the three could differ by a week if the directory is republished in the middle of a release; that is harmless (the seed only gives reading order and names).
7. Only when the checks, the ZIP, the installer, the portable ZIP and the .dmg all succeeded does it push the commit and tag, and create the GitHub Release (all four attached together) with notes made from the commit subjects since the last release.

If any check fails, nothing is pushed or published.

## Private patterns (`LEAK_PATTERNS`)

Put personal words in a secret, never in the repo.

1. Repo **Settings -> Secrets and variables -> Actions -> New repository secret**.
2. Name: `LEAK_PATTERNS`. Value: one regular expression per line, for example:

   ```
   Jane\s+Doe
   Acme Corp
   \b185,?000\b
   ```
3. Matching is case-insensitive. Without the secret the workflow still runs, but warns that name checks were skipped.

## A check failed

Open the failed run and read the **Release checks** step; each problem is listed as `file:line` with the match partly hidden. Fix it in the repo (or fix the pattern), then run **Release** again with the same version. Nothing was tagged, so the version is still free.

If a run fails after "Push commit and tag" (rare, for example a network error while creating the release), the tag exists. Finish by hand under Releases -> Draft a new release using that tag, or delete the tag and re-run.

## The seed list for "Build my own directory"

`assets/directory/seed.json.gz` (about 0.9 MB) lists every job site the directory builder knows: job system, its settings, the last-known employer name and the states it was last seen hiring in (hints only; the app reads each site itself). That includes the careers sites the weekly build found for big local employers from public lists (hospitals, colleges, school districts, governments: `index_build/resolve.py`), with the list's name and, before they are first read, the employer's state; nothing changes in how the seed is refreshed. Three ways it gets refreshed:

- **By a release**, automatically (see step 6 above): `scripts/refresh_seed.py`.
- **By hand from the published directory:** `python scripts/refresh_seed.py` (add `--strict` to get exit code 1 when it couldn't be refreshed), then commit the file.
- **By hand from a local builder run** (no published directory needed): `python scripts/make_seed.py --state <index out>/_state/tenants.json.gz`, then commit the file. It prints the size and the number of job sites; keep it under about 2 MB.

`scripts/release_check.py` fails when the file is missing, and `Siftwell --check-imports` (run by the Windows and Mac build jobs) fails when the installed program can't load the builder or read the seed. Offline tests: `python -X utf8 scripts/test_localdir.py`.

## Run the checks locally

```
python scripts/release_check.py --local
```

`--local` also looks at files not yet committed and treats missing launchers as warnings. Set `LEAK_PATTERNS` in your shell to test private patterns.

## Executable bit for macOS

`Start Siftwell.command` must be executable inside the ZIP. Set it once in git: `git update-index --chmod=+x "Start Siftwell.command"`, then commit. The workflow fails if it is missing.

**False alarms from your private names list:** the leak check ignores matches inside this repository's own address (owner/name) and inside public phrases listed in `scripts/leak_allow.txt` (one per line, e.g. a company like "Charles Schwab"). Only add public company or place names there, never people.
