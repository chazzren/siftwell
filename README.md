# Siftwell

**Your own job search assistant that runs on your computer.**

Siftwell checks the career pages of the companies you care about every night, filters the openings down to your location, pay and level, has Claude rate how well each one fits your resume, and tailors your resume for the jobs worth applying to. Several people in one household can each have their own profile.

> **Status: early preview.** Siftwell works day to day: it starts with a double-click, and a **Get started** page inside the app installs Claude Code and signs you in. Coming next: a Catalog page for managing companies, with **Find employers near me** (Claude researches employers in your area for you), a Re-rate panel, and a proper desktop app window.

---

## What it does

- **Goes straight to the source.** Siftwell reads job listings directly from employers' own career sites (Greenhouse, Lever, Ashby, Workday, iCIMS, SmartRecruiters and 13 more), including smaller and nonprofit employers whose jobs often never reach the big job sites.
- **Filters to what fits you.** Distance from your home ZIP code, remote or in person, pay floor, seniority, travel, security clearance, and degree or license requirements you don't meet.
- **Two scores for every job:**
  - **Appeal:** how good the job is for *you* (pay, location, level, company, travel).
  - **Match:** how well your resume fits what *they* want, judged by Claude.
- **Search in plain English.** Type "remote product roles at climate nonprofits over 150k" and press Enter.
- **Reads your resume.** Upload a PDF, Word file or even a phone photo, and Siftwell builds your profile from it. You review it before it's used.
- **Tailors your resume** for a specific job, as a PDF or Word file, and asks you questions when it needs facts your resume doesn't have.
- **Optional second opinion ("Astra").** A ChatGPT-based reviewer grades each tailored resume and sends it back for another pass if it falls short.
- **Career "Target" tab.** Describe where you want to go next ("an AI product role", "move into nonprofit leadership") and get jobs rated for that goal, with what to work on.
- **Household profiles.** Each person has their own resume, settings, saved jobs and tailored resumes.
- **Use it from your phone.** Open the board from any phone or laptop on your home Wi-Fi using a private link.

## What you need

| | Needed? | Notes |
|---|---|---|
| A Windows 11 or Mac computer | Yes | It needs to be on (asleep is fine) for the nightly update. |
| A **Claude** subscription (Pro or Max) | Yes | Siftwell uses **Claude Code**, signed in with your Claude account, for ratings, resume reading and tailoring. An Anthropic API key works instead. |
| Google Chrome or Microsoft Edge | Yes | Used to make resume PDFs. Edge is already on Windows. |
| A **ChatGPT** account + Codex | Optional | Only for the Astra resume reviewer. |

Siftwell itself is free and open source. The Claude (and optional ChatGPT) usage is billed through your own accounts.

---

## Install

No terminal, no Python install and no administrator password needed.

### 1. Download Siftwell
On this page, click the green **Code** button → **Download ZIP**. Unzip it somewhere permanent, for example `Documents\Siftwell` (Windows: right-click the ZIP → **Extract All**; Mac: double-click the ZIP).
Avoid your Downloads folder and OneDrive or iCloud-synced folders.

### 2. Double-click "Start Siftwell"
- **Windows:** open the Siftwell folder and double-click **Start Siftwell** (`Start Siftwell.cmd`).
- **Mac:** open the Siftwell folder, **right-click** (or Control-click) **Start Siftwell** (`Start Siftwell.command`) and choose **Open**.

The first time, a window says *"Setting up Siftwell. This happens once and takes a couple of minutes..."* while it downloads what it needs (Python and a few packages) into a hidden `.siftwell` folder inside the Siftwell folder. You need to be connected to the internet for this. When it's done, your browser opens Siftwell, and on Windows the window closes by itself (on a Mac you can close the Terminal window; Siftwell keeps running).

**One-time security prompts.** Siftwell isn't from an app store, so the first time your computer may ask whether you trust it:
- **Windows** "Windows protected your PC": click **More info**, then **Run anyway**. If you see "Open File – Security Warning" instead, click **Run**. A "Windows Security" firewall window may also ask about Python: click **Allow** if you want to open Siftwell from your phone, otherwise **Cancel** (Siftwell still works on this computer either way).
- **Mac** "cannot be opened because it is from an unidentified developer" (or "Apple could not verify..."): click **Done** or **Cancel**, then right-click **Start Siftwell** → **Open** → **Open**. On macOS 15 (Sequoia) or newer, if there's no Open button: open **System Settings → Privacy & Security**, scroll down to the message about "Start Siftwell", click **Open Anyway**, and confirm.

### 3. Follow the page in your browser
Siftwell opens at **http://127.0.0.1:8766** (if another program already uses that port, it picks the next free one, 8767 to 8775, and keeps using it). You'll be asked to add the first person, then a short setup walks you through your resume, location, pay and goals. The pages may still say "Job Board": that's Siftwell's old name.

### 4. Finish setup on the "Get started" page
Open **Get started** (linked from the welcome page, and from your profile menu at the top right). It checks your computer and fixes things with buttons:
- **Claude Code installed:** click **Install Claude Code** and Siftwell runs the official installer for you.
- **Signed in to Claude:** click **Sign in to Claude**, open the link, sign in with your Claude account, and paste the code it shows back into Siftwell.
- **Browser for resume PDFs:** found automatically (Edge is already on Windows).

Optional switches on the same page: **Start Siftwell when I sign in to my computer**, **Use Siftwell on my phone** (shows a link and a QR code to scan), and how to set up **Astra** resume reviews.

<details>
<summary>Prefer to install Claude Code yourself?</summary>

- **Windows** (PowerShell): `irm https://claude.ai/install.ps1 | iex`
- **Mac** (Terminal): `curl -fsSL https://claude.ai/install.sh | bash`

Then run `claude` once and sign in, or use the **Sign in to Claude** button in Siftwell.
</details>

<details>
<summary><b>Advanced / manual install</b></summary>

If you'd rather set things up yourself, you need [uv](https://docs.astral.sh/uv/) (it installs Python for you).

**Windows** (PowerShell, in the Siftwell folder). The setup script installs everything into `.venv`, makes Siftwell start when you sign in to Windows, schedules the nightly update, starts it, and prints your links. Running it as administrator also lets phones on your home network connect.
```powershell
cd "$HOME\Documents\Siftwell"
powershell -ExecutionPolicy Bypass -File .\setup_windows.ps1
```

**Mac** (Terminal, in the Siftwell folder):
```bash
cd ~/Documents/Siftwell
curl -LsSf https://astral.sh/uv/install.sh | sh     # installs uv (sets up Python for you)
~/.local/bin/uv venv --managed-python --python 3.12 .venv
~/.local/bin/uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python -X utf8 server.py
```
Leave that Terminal window open while you use Siftwell. Run `server.py <port>` to use a port other than 8766.

</details>

### 5. Add companies to watch
A new install starts with no companies. Open **My profile → Companies** and paste the link to a company's careers page (for example `https://boards.greenhouse.io/examplecompany`). Siftwell figures out which job system it uses, checks that it can read the listings, and adds it. Then use **Update job listings** (the circular-arrow icon) to fetch jobs.

Coming soon: **Find employers near me**, where Claude researches employers in your area (big employers, hospitals, universities, nonprofits, startups and more), Siftwell checks which ones it can read, and you tick the ones to add. (The repository also includes `packs/dc-area.json`, a list of ~800 Washington, DC area employers it was first built with.)

---

## Using it day to day

- **Starting and stopping:** double-click **Start Siftwell** any time to open it (if it's already running, it just opens your browser). Siftwell keeps running in the background after the window closes, so the board and the nightly update keep working. To stop it, double-click **Stop Siftwell**. After restarting your computer, double-click **Start Siftwell** again, or turn on **Start Siftwell when I sign in** on the Get started page.
- **The board** shows your matching jobs with **Appeal** and **Match** scores. Click a job for Claude's read on it, then **Save**, **Mark applied**, **Not for me**, or **Tailor my resume**.
- **Header icons:** Home · Update job listings (checks every company, ~40 min) · Re-rate (Claude re-scores your best jobs after you change your resume or settings) · Settings · your profile menu.
- **Nightly update:** every morning at 5:30 Siftwell checks for new and removed jobs and rates the new ones. You can change or turn this off.
- **On your phone:** new installs only answer on this computer. To use your phone, turn on **Use Siftwell on my phone** on the Get started page (Siftwell restarts once), then scan the QR code or open the link it shows (it ends in `?k=…`). Keep that link private: anyone on your home network with it can open your board. On Windows, click **Allow access** on the firewall prompt the first time.

## Your data stays on your computer

Everything Siftwell creates or learns is stored only on your computer, outside the app folder:
- **Windows:** `%APPDATA%\JobBoard`
- **Mac:** `~/Library/Application Support/JobBoard`

That includes resumes, profiles, settings, saved and applied jobs, tailored resumes, the companies and job listings it has found, and Claude's ratings. Downloading a newer version of Siftwell (or deleting the app folder and downloading it again) doesn't touch it, so you pick up where you left off without paying for the same ratings twice. Job descriptions and your resume are sent to Claude (and to ChatGPT if you turn on Astra) to rate and tailor; nothing is sent anywhere else.

## Good to know

- **Claude usage:** ratings run on your Claude plan. Settings → Claude usage controls how many jobs get rated and how carefully. Large first-time ratings can take a while and use a noticeable share of your plan's limits.
- **Job sites:** Siftwell reads the public job listings employers publish on their career sites, at a polite pace, for your personal job search. Use it responsibly and respect each site's terms.
- **Not affiliated** with Anthropic, OpenAI, or any job-board provider.

## Troubleshooting

- **The page won't load:** double-click **Start Siftwell** again; it starts Siftwell if needed and opens the right address. If it still fails, double-click **Stop Siftwell**, then **Start Siftwell**. Logs are in your data folder (`server.log`; on a Mac also `.siftwell/launcher.log` in the Siftwell folder).
- **First-time setup failed:** check your internet connection and double-click **Start Siftwell** again; it picks up where it left off. Details are in `.siftwell/setup.log` inside the Siftwell folder. Deleting the hidden `.siftwell` and `.venv` folders makes it set up from scratch (your data isn't touched).
- **I moved the Siftwell folder:** that's fine; the next **Start Siftwell** repairs its setup. Stop Siftwell before moving it.
- **"Claude Code is signed out":** click **Sign in to Claude** on the board, open the link, sign in, and paste the code back.
- **Another program is using port 8766:** Start Siftwell picks the next free port (8767 to 8775) by itself and remembers it; the Get started page shows which port Siftwell is using. Phone links need that port too.
- **My phone can't connect:** check **Use Siftwell on my phone** is on (Get started page), the phone is on the same Wi-Fi, and Windows Firewall allowed Siftwell (Start menu → "Allow an app through Windows Firewall").
- **Resume PDFs don't build:** install Google Chrome or Microsoft Edge.

## License

[MIT](LICENSE)
