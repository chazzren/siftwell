# Siftwell

**Your own job search assistant that runs on your computer.**

Siftwell checks the career pages of the companies you care about every night, filters the openings down to your location, pay and level, has Claude rate how well each one fits your resume, and tailors your resume for the jobs worth applying to. Several people in one household can each have their own profile.

> **Status: early preview.** Siftwell works day to day: it starts with a double-click, and a **Get started** checklist inside the app installs Claude Code and signs you in. Coming next: a Catalog page for managing companies, with **Find employers near me** (Claude researches employers in your area for you), a Re-rate panel.

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
On this page, open **Releases** (on the right side, or under the repository name on a phone), click the **latest** release, and under **Assets** download **Siftwell-x.y.z.zip** (for example `Siftwell-0.1.0.zip`). Unzip it somewhere permanent, for example `Documents\Siftwell` (Windows: right-click the ZIP → **Extract All**; Mac: double-click the ZIP).
(Please don't use the green **Code → Download ZIP** button: that's the in-progress development version, not a tested release.)
Avoid your Downloads folder and OneDrive or iCloud-synced folders.

### 2. Double-click "Start Siftwell"
- **Windows:** open the Siftwell folder and double-click **Start Siftwell** (`Start Siftwell.cmd`).
- **Mac:** open the Siftwell folder, **right-click** (or Control-click) **Start Siftwell** (`Start Siftwell.command`) and choose **Open**.

The first time, a window says *"Setting up Siftwell. This happens once and takes a couple of minutes..."* while it downloads what it needs (Python and a few packages) into a folder of its own on your computer, not into the Siftwell folder (Windows: `%LOCALAPPDATA%\Siftwell\runtime`; Mac: `~/Library/Application Support/Siftwell/runtime`). Newer versions of Siftwell you download later reuse it, so they start right away. You need to be connected to the internet for this. When it's done, Siftwell opens in its own window (like any other app, with a button in your taskbar), and on Windows the setup window closes by itself (on a Mac you can close the Terminal window).

**One-time security prompts.** Siftwell isn't from an app store, so the first time your computer may ask whether you trust it:
- **Windows** "Windows protected your PC": click **More info**, then **Run anyway**. If you see "Open File – Security Warning" instead, click **Run**. A "Windows Security" firewall window may also ask about Python: click **Allow** if you want to open Siftwell from your phone, otherwise **Cancel** (Siftwell still works on this computer either way).
- **Mac** "cannot be opened because it is from an unidentified developer" (or "Apple could not verify..."): click **Done** or **Cancel**, then right-click **Start Siftwell** → **Open** → **Open**. On macOS 15 (Sequoia) or newer, if there's no Open button: open **System Settings → Privacy & Security**, scroll down to the message about "Start Siftwell", click **Open Anyway**, and confirm.

### 3. Follow the page in the Siftwell window
The Siftwell window shows Siftwell, which runs on your computer at **http://127.0.0.1:8766** (if another program already uses that port, it picks the next free one, 8767 to 8775, and keeps using it). Links to other websites, such as job postings and the Claude sign-in page, open in your normal web browser, and resume downloads show a normal Save dialog. If your computer can't show the Siftwell window (it needs the free Microsoft Edge WebView2 component that Windows 11 includes), Siftwell says so and opens in your web browser instead. You'll be asked to add the first person, then a short setup walks you through your resume, location, pay and goals.

### 4. Finish setup with the "Get started" checklist
Open **Get started** (linked from the welcome page; once you have a profile it is the first item in **Settings**, the gear icon at the top, and the gear shows a small number while required steps are missing). It checks your computer and fixes things with buttons:
- **Claude Code installed:** click **Install Claude Code** and Siftwell runs the official installer for you.
- **Signed in to Claude:** click **Sign in to Claude**, open the link, sign in with your Claude account, and paste the code it shows back into Siftwell.
- **Browser for resume PDFs:** found automatically (Edge is already on Windows).

Optional switches on the same page: **Start Siftwell when I sign in to my computer** (on Windows it also offers **Switch to the new startup** if an older setup is still starting Siftwell), **Use Siftwell on my phone** (shows a link and a QR code to scan), **Keep Siftwell available to my phone when the window is closed** (see below), and how to set up **Astra** resume reviews.

<details>
<summary>Prefer to install Claude Code yourself?</summary>

- **Windows** (PowerShell): `irm https://claude.ai/install.ps1 | iex`
- **Mac** (Terminal): `curl -fsSL https://claude.ai/install.sh | bash`

Then run `claude` once and sign in, or use the **Sign in to Claude** button in Siftwell.
</details>

<details>
<summary><b>Advanced / manual install</b></summary>

If you'd rather set things up yourself, you need [uv](https://docs.astral.sh/uv/) (it installs Python for you).

**Windows** (PowerShell, in the Siftwell folder):
```powershell
cd "$HOME\Documents\Siftwell"
irm https://astral.sh/uv/install.ps1 | iex          # installs uv (sets up Python for you)
& "$HOME\.local\bin\uv.exe" venv --managed-python --python 3.12 .venv
& "$HOME\.local\bin\uv.exe" pip install --python .venv\Scripts\python.exe -r requirements.txt
.venv\Scripts\python.exe -X utf8 server.py
```
Leave that PowerShell window open while you use Siftwell. Run `server.py <port>` to use a port other than 8766. To start Siftwell when you sign in, use the switch in **Settings → Get started**.

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

- **Starting and stopping:** double-click **Start Siftwell** any time; it opens the Siftwell window (if it's already running, it just opens a window on it, or brings the open one to the front). **Closing the Siftwell window stops Siftwell**, including the nightly update, so leave the window open (minimized is fine) if you want Siftwell to keep working in the background. If an update or re-rate is running, Siftwell asks before it stops. The exception is **Keep Siftwell available to my phone when the window is closed** in **Settings → Get started** (off by default): when it's on, Siftwell keeps running quietly after you close the window, so your phone and the nightly update keep working, and **Start Siftwell** later just opens a window again. To stop it completely at any time, double-click **Stop Siftwell** (it also closes the window). If Siftwell was started by **Start Siftwell when I sign in**, it is already running when you open a window, and closing the window leaves it running. Siftwell remembers the window's size and position.
- **The board** shows your matching jobs with **Appeal** and **Match** scores. Click a job for Claude's read on it, then **Save**, **Mark applied**, **Not for me**, or **Tailor my resume**.
- **Header icons:** Home · Update job listings (checks every company, ~40 min) · Re-rate (Claude re-scores your best jobs after you change your resume or settings) · **My profile** (your resume, search settings, target and companies) · **Theme** (click to cycle Auto, Light and Dark; Auto follows your device, and it is the same choice as Settings → Display → Theme) · Settings (display, resume PDF, Claude usage, and the **Get started** setup checklist as its first item; a small number on the gear shows how many required setup steps are still missing, and it disappears once you're set up) · your profile menu at the top right (switch person, add a person, manage profiles).
- **Adding, renaming and removing people:** open **Settings → Profiles**. It lists everyone in your household with **Rename** and **Remove** buttons (Remove asks you to tap twice) and an **Add a person** button. Siftwell won't remove the last profile, or anyone while an update is running. A removed person isn't deleted: their folder is moved to `people_removed` inside your data folder, so it can be recovered by hand.
- **Getting a newer version:** download the latest release the same way (step 1); **Settings** shows which version you're running (bottom of the list, e.g. "Siftwell 0.1.0"). Unzip it, and double-click **Start Siftwell** in the new folder (stop the old one first with **Stop Siftwell**). You can delete the old Siftwell folder whenever you like. Everything carries over: profiles, ratings, your port and your phone link, with nothing re-rated and no new setup download unless the new version needs different packages. If you turned on **Start Siftwell when I sign in** on the Get started page, it switches to the new folder by itself the first time the new version starts. If you came from an older Siftwell or Job Board, see **Upgrading from an older Siftwell / Job Board** below.
- **Upgrading from an older Siftwell / Job Board (Windows):** older versions started Siftwell at sign-in with a Windows scheduled task called **Job Board server**, which points at the old folder and stops working once you delete it. After you start the new version, open **Settings → Get started** and click **Switch to the new startup**. That turns on the new sign-in startup and turns off the old task (it isn't deleted, and **Undo** turns it back on). Siftwell keeps running meanwhile; the new startup takes over the next time you sign in. If Windows says it needs administrator permission, click **Allow (asks for administrator permission)** and approve the Windows prompt, or follow the steps shown (Task Scheduler, **Job Board server**, **Disable**). Your PC's early-morning wake-up for the nightly update (the task **Job Board wake for nightly update**) keeps working as it is. Once the switch is done you can delete the old folder.
- **Nightly update:** every morning at 5:30 Siftwell checks for new and removed jobs and rates the new ones. You can change or turn this off.
- **On your phone:** new installs only answer on this computer. To use your phone, turn on **Use Siftwell on my phone** in **Settings → Get started** (Siftwell restarts once), then scan the QR code or open the link it shows (it ends in `?k=…`). Keep that link private: anyone on your home network with it can open your board. On Windows, click **Allow access** on the firewall prompt the first time. Your phone can only reach Siftwell while it is running: that means while its window is open, or after closing the window if **Keep Siftwell available to my phone when the window is closed** is on.

## Your data stays on your computer

Everything Siftwell creates or learns is stored only on your computer, outside the app folder:
- **Windows:** `%APPDATA%\JobBoard`
- **Mac:** `~/Library/Application Support/JobBoard`

That includes resumes, profiles, settings, saved and applied jobs, tailored resumes, the companies and job listings it has found, Claude's ratings, your phone access key, logs, and which port Siftwell uses. The Siftwell folder itself only holds the app; Siftwell never saves anything into it. Python and the packages Siftwell runs on sit in a separate folder (Windows: `%LOCALAPPDATA%\Siftwell\runtime`; Mac: `~/Library/Application Support/Siftwell/runtime`), which can be rebuilt from the internet any time and holds none of your data.

When Siftwell moves to a newer way of storing something, it puts the old files in an `_archive` folder inside your data folder and removes them after 30 days.

So you can delete the Siftwell folder and download the latest version (or move it) and pick up exactly where you left off. Claude's ratings are tied to your own information (resume, answers, goals and target), not to the app version, so a new version doesn't re-rate anything or spend your Claude plan on ratings you already have. They're only redone when you change your own information. Job descriptions and your resume are sent to Claude (and to ChatGPT if you turn on Astra) to rate and tailor; nothing is sent anywhere else.

## Good to know

- **Claude usage:** ratings run on your Claude plan. Settings → Claude usage controls how many jobs get rated and how carefully. Large first-time ratings can take a while and use a noticeable share of your plan's limits. If a new version shows many ratings as needing a fresh rating even though you haven't changed your resume or answers, press **Keep my current ratings** on that page (two taps) to mark them as up to date instead of re-rating them; it doesn't use Claude.
- **Job sites:** Siftwell reads the public job listings employers publish on their career sites, at a polite pace, for your personal job search. Use it responsibly and respect each site's terms.
- **Not affiliated** with Anthropic, OpenAI, or any job-board provider.

## Troubleshooting

- **The Siftwell window opened in my browser instead:** this computer couldn't show the window (the pywebview package didn't install, or the Microsoft Edge WebView2 component is missing; Windows 11 has it, for Windows 10 it is a free download from Microsoft). Siftwell works the same in the browser, but it then keeps running until you double-click **Stop Siftwell**. Details are in `window.log` in your data folder.
- **The page won't load:** double-click **Start Siftwell** again; it starts Siftwell if needed and opens the Siftwell window. If it still fails, double-click **Stop Siftwell**, then **Start Siftwell**. Logs are in your data folder: `server.log`, plus `window.log` (the Siftwell window), `start-error.log` on Windows if Siftwell stopped right after starting, and `launcher.log` on a Mac.
- **First-time setup failed:** check your internet connection and double-click **Start Siftwell** again; it picks up where it left off. Details are in `setup.log` in the runtime folder (Windows: `%LOCALAPPDATA%\Siftwell\runtime`; Mac: `~/Library/Application Support/Siftwell/runtime`). Deleting that runtime folder makes it set up from scratch (your data isn't touched).
- **Hidden `.siftwell` or `.venv` folder inside the Siftwell folder:** older versions put the setup there. This version doesn't use them (an old `.venv` is only a fallback if the new setup can't finish) and remembers your port from `.siftwell` automatically. After Siftwell has started once with this version you can delete `.siftwell`, and `.venv` too unless you started Siftwell by hand from it (**Advanced / manual install**).
- **I moved the Siftwell folder:** that's fine; stop Siftwell first, then double-click **Start Siftwell** in the new place. If **Start Siftwell when I sign in** is on, Siftwell points it at the new place the next time it starts.
- **"Claude Code is signed out":** click **Sign in to Claude** on the board, open the link, sign in, and paste the code back.
- **Another program is using port 8766:** Start Siftwell picks the next free port (8767 to 8775) by itself and remembers it; **Settings → Get started** shows which port Siftwell is using. Phone links need that port too.
- **My phone can't connect:** check **Use Siftwell on my phone** is on (**Settings → Get started**), Siftwell is running (its window is open, or **Keep Siftwell available to my phone when the window is closed** is on), the phone is on the same Wi-Fi, and Windows Firewall allowed Siftwell (Start menu → "Allow an app through Windows Firewall").
- **Which version am I running?** Open **Settings**: the version (for example "Siftwell 0.1.0") is shown small under the list of categories.
- **What happened, and when?** Siftwell keeps a plain-text diary of everything done from the pages (updates, re-rates, adding or removing people and companies, saved settings, changing start at sign-in, restarts): `actions.log` in your data folder. Each line has the time, the action, the profile, which device did it and its browser. It never records passwords or keys. When it gets big it starts a new file and keeps the old one as `actions.log.1`.
- **The board says "A background job is running":** an update or re-rate is still going (for example one that started before Siftwell was restarted). Wait for it to finish; Siftwell won't restart itself while it runs.
- **Resume PDFs don't build:** install Google Chrome or Microsoft Edge.

## License

[MIT](LICENSE)
