# Siftwell: notes for AI coding agents

Siftwell is a self-hosted household job board: it fetches listings from employer career sites, filters them per profile, rates fit with Claude (via the Claude Code CLI), and tailors resumes. Plain Python (stdlib HTTP server) + server-rendered HTML/JS; no build step, no frameworks.

## Map
- `server.py`: HTTP server (`python server.py [port]`), all routes in `H.do_GET` / `H.do_POST`. POSTs need header `X-Jobboard: 1` and same origin. Access: from 127.0.0.1 directly, or a cookie set by `/?k=<access key>`. Current profile = `jb_person` cookie.
- `paths.py`: APP (repo), DATA (user data dir outside the repo; env `JOBBOARD_DATA` overrides), ASSETS, PACKS, `load_config()`, `load_companies()`, one-time `migrate()`.
- `people.py`: profiles, per-profile settings and prefs (`PREF_SCHEMA`).
- `jobfinder.py`: fetching (ATS fetchers), per-person filtering (`select_for_person`), scoring, board build. `extra_fetchers.py`, `smb_fetchers.py`: more ATS fetchers. `company_add.py`: add a company from a careers link (detect + verify).
- `ai_score.py`: Claude Match ratings (Haiku → Sonnet → Opus funnel). `pivot.py`: Target-tab ratings. `claude_cli.py`: wrapper around `claude -p`. `nlsearch.py`: natural-language search.
- `report.py`: the board page. `HEAD`/`BODY`/`TOOLS` are plain strings; `SCRIPT` is a **raw** string holding all board JS. Output: `DATA/people/<id>/report.html`.
- Other pages: `settings_page.py` (/settings), `setup_page.py` + `setup_flow.py` (/setup), `welcome_page.py` (no profiles yet).
- `resume.py`, `tailor.py`, `review.py` (Astra, via Codex CLI), `interview.py`, `highlights.py`, `requirements.py`, `target.py`, `geo.py` (offline geocoding from `assets/geo`).

## Conventions
- Keep each file's existing line endings (some are CRLF, some LF). Never put a raw newline inside a JS string literal; use `\n`.
- After editing page JS, syntax-check it: write `re.sub(r"</?script>", "", report.SCRIPT)` (or the page's script) to a temp `.js` and run `node --check`.
- Boards re-render automatically at server start when `report.py` is newer than a board (`refresh_stale_boards`), so restart the server after editing `report.py`.
- Visual style: reuse the CSS custom properties at the top of `report.HEAD` (light + dark). Pages must work at 375px wide with no horizontal scroll.
- No new dependencies without asking. Python 3.12, stdlib first.
- Never commit, push, or change git config unless the project manager asks. Don't commit user data (it lives outside the repo anyway).

## README must always match the app
`README.md` is the user-facing manual for people who barely know GitHub. **Any change that alters what users see or do (install steps, pages, buttons, settings, defaults, requirements, where data lives) must update README.md in the same change**, in plain language. Don't describe features that aren't built yet except in the clearly marked "coming next" status line. Reviewers check this too.

## Testing
- Run a test server on its own port with its own data: `JOBBOARD_DATA=<scratch dir> python -X utf8 server.py <port>`. Never point tests at a real user's data folder.
- **Don't spend the user's Claude plan in tests**: use tiny runs (a handful of jobs) or stub `claude_cli` responses; ask before anything larger.
- Verify UI in a browser at desktop width and 375px, and check the console for errors.
- Stop only processes you started. Restore any setting you change while testing.

## Reporting
Short summary: files changed, decisions made, what you verified and how, what you couldn't verify, open questions.
