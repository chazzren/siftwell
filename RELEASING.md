# Releasing Siftwell

## Cut a release (about a minute)

1. On GitHub open the repo, then **Actions -> Release -> Run workflow**.
2. Pick the default branch, enter the **version** (like `0.2.0`, no `v`), optionally add **notes**, click **Run workflow**.
3. When the run turns green, the release is at **Releases -> latest**, with `Siftwell-<version>.zip` (Mac / manual), `Siftwell-Setup-<version>.exe` (the Windows installer) and `Siftwell-Portable-<version>.zip` (Windows, no install, data next to the app) attached.

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
6. Only when the checks, the ZIP, the installer and the portable ZIP all succeeded does it push the commit and tag, and create the GitHub Release (ZIP, installer and portable ZIP attached together) with notes made from the commit subjects since the last release.

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

## Run the checks locally

```
python scripts/release_check.py --local
```

`--local` also looks at files not yet committed and treats missing launchers as warnings. Set `LEAK_PATTERNS` in your shell to test private patterns.

## Executable bit for macOS

`Start Siftwell.command` must be executable inside the ZIP. Set it once in git: `git update-index --chmod=+x "Start Siftwell.command"`, then commit. The workflow fails if it is missing.

**False alarms from your private names list:** the leak check ignores matches inside this repository's own address (owner/name) and inside public phrases listed in `scripts/leak_allow.txt` (one per line, e.g. a company like "Charles Schwab"). Only add public company or place names there, never people.
