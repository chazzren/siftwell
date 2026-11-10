# Siftwell user guide

Everything about installing, using and maintaining Siftwell. For the short version, see the [README](../README.md).

## Contents

- [What it does](#what-it-does)
- [What you need](#what-you-need)
- [Install](#install)
- [First run (all versions)](#first-run-all-versions)
- [Using it day to day](#using-it-day-to-day)
- [The Catalog page](#the-catalog-page)
- [Using Siftwell without Claude](#using-siftwell-without-claude)
- [Your data stays on your computer](#your-data-stays-on-your-computer)
- [Updating Siftwell](#updating-siftwell)
- [Moving to another computer / backups](#moving-to-another-computer--backups)
- [Good to know](#good-to-know)
- [Troubleshooting](#troubleshooting)
- [License](#license)

## What it does

- **Goes straight to the source.** Siftwell reads job listings directly from employers' own career sites (Greenhouse, Lever, Ashby, Workday, iCIMS, SmartRecruiters, SAP SuccessFactors, Taleo, Radancy, Eightfold, Avature and 13 more), including smaller and nonprofit employers whose jobs often never reach the big job sites.
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
| A Windows 11 or Mac computer | Yes | Only needs to be on while you use it. For automatic job updates (off by default) see **Automatic job updates** below; a laptop can wake itself if it is plugged in and asleep. |
| A **Claude** subscription (Pro or Max) | Optional | Siftwell works without it (see **Using Siftwell without Claude** below). With **Claude Code**, signed in with your Claude account, it also gives Match ratings, reads your resume and tailors it. |
| Google Chrome or Microsoft Edge | Yes | Used to make resume PDFs. Edge is already on Windows. |
| A **ChatGPT** account + Codex | Optional | Only for the Astra resume reviewer. |

Siftwell itself is free and open source. The Claude (and optional ChatGPT) usage is billed through your own accounts.

---

## Install

No terminal, no Python install and no administrator password needed.

### Windows: use the installer (recommended)
1. On this page, open **Releases** (on the right side, or under the repository name on a phone), click the **latest** release, and under **Assets** download **Siftwell-Setup-x.y.z.exe** (for example `Siftwell-Setup-0.1.0.exe`).
2. Double-click it, click **Next**, then **Install**, then **Finish**. Siftwell opens.

That's all: it installs just for you (into `%LOCALAPPDATA%\Programs\Siftwell`), adds **Siftwell** to your Start menu (tick the box on the first page if you also want a desktop shortcut) and lists itself under **Settings → Apps**. Python and everything else Siftwell needs are already inside, so there is no further download. Then carry on at **step 3** below.

**One-time security prompt.** The installer isn't digitally signed yet, so Windows may show **"Windows protected your PC"**: click **More info**, then **Run anyway**. (If you see "Open File – Security Warning" instead, click **Run**.) A "Windows Security" firewall window may also ask about Siftwell: click **Allow** if you want to open Siftwell from your phone, otherwise **Cancel** (Siftwell still works on this computer either way).

**Updating.** Siftwell tells you when a newer version is out and can install it for you (see **Updating Siftwell** below). Or download and run the newer **Siftwell-Setup-x.y.z.exe** the same way. It closes Siftwell if it is running, replaces the program, and your profiles, ratings and settings are exactly as you left them.

**Uninstalling.** Open **Settings → Apps → Installed apps**, find **Siftwell**, click **Uninstall**. Your data (profiles, resumes, ratings, saved jobs, settings; `%APPDATA%\JobBoard`) is **kept** unless you tick **Also remove my Siftwell data** in the window that appears (that cannot be undone). Install Siftwell again later and everything is back.

### Portable version (no install)
Want to run Siftwell from a USB stick, a Dropbox folder, or a computer where you can't install programs? Use the portable version. On the **Releases** page, under **Assets**, download **Siftwell-Portable-x.y.z.zip**, right-click it and choose **Extract all** (anywhere you like), open the **Siftwell** folder and double-click **Siftwell.exe**. Then carry on at **step 3** below.

- **Nothing is installed**, and by default nothing is written outside the Siftwell folder. Your profiles, resumes, ratings and settings are kept in a **data** folder right next to `Siftwell.exe`. **Deleting the Siftwell folder deletes your data**, so keep a copy of the `data` folder (or use **Settings → Backup & move**).
- The folder must be one you can write to (Documents, the Desktop, a USB stick). If it isn't, Siftwell says so: move the folder to Documents and open it again.
- **Start Siftwell when I sign in** and **Even when Siftwell is closed** (automatic job updates) are **off**. You can still turn them on in **Settings**; Siftwell reminds you that this adds something to this computer, outside the Siftwell folder.
- **Updating:** Siftwell shows **Download the new portable version**. Close Siftwell, unzip the new ZIP over the old folder (choose to replace files), or unzip it somewhere new and copy your old `data` folder into it, then open `Siftwell.exe` again. Siftwell never replaces itself.
- **Moving to another computer or drive:** close Siftwell and copy the whole folder; the data goes with it, and a changed drive letter (a USB stick on E: or F:) doesn't matter. On the new computer your phone link changes (**Settings → Get started** shows the new one) and you sign in to Claude Code again there.
- **Between the installed and the portable version:** with Siftwell closed, use **Settings → Backup & move** (export on one, import on the other), or copy the contents of `%APPDATA%\JobBoard` into the portable `data` folder (or the other way round).
- **Trying a new version side by side:** unzip the portable version into a test folder and, if you like, copy your data folder into its `data` folder first. It runs on its own port (the window title reads "Siftwell (test copy, port 8767)") and never stops, reuses or opens your main copy. **Settings → About & updates** shows which data folder a copy is using.

### Mac (Apple silicon): use the .dmg (recommended)
This is the normal way to install Siftwell on a Mac made since late 2020 (an M1, M2, M3 or newer chip; **Apple menu → About This Mac** says "Chip: Apple M…") running macOS 12 or newer. No Terminal, no Python install and no administrator password needed. (A Mac with an Intel chip uses the ZIP below.)
1. On this page, open **Releases** (on the right side, or under the repository name on a phone), click the **latest** release, and under **Assets** download **Siftwell-x.y.z.dmg** (for example `Siftwell-0.4.0.dmg`).
2. Open the downloaded file (double-click it in your Downloads folder). A window shows the **Siftwell** app next to an **Applications** folder. **Drag Siftwell onto Applications.**
3. Close that window, then eject the disk image (click the eject button next to **Siftwell** in the Finder sidebar) and delete the .dmg if you like.
4. Open **Siftwell** from **Applications** (or Launchpad or Spotlight). Siftwell opens in its own window, and Python and everything else it needs are already inside the app, so there is no further download. Then carry on at **step 3** below.

**One-time security prompt.** Siftwell isn't from the App Store and isn't signed with an Apple developer certificate yet, so the first time your Mac says something like *"Siftwell cannot be opened because Apple cannot check it for malicious software"* (or *"cannot be opened because it is from an unidentified developer"*, or *"Siftwell is damaged"* on some versions):
- **macOS 14 or older:** click **Cancel** (or **Done**), then in **Applications** **right-click** (or Control-click) **Siftwell**, choose **Open**, and click **Open** again.
- **macOS 15 (Sequoia) or newer:** the right-click trick no longer works. Open **System Settings → Privacy & Security**, scroll down to the message about "Siftwell" and click **Open Anyway**, then confirm with your password or Touch ID and click **Open Anyway** again.
- Only the first start asks. Updates that Siftwell installs for you don't ask again.

The icon in the Dock is Siftwell; closing the window (or right-clicking the Dock icon → **Quit**) stops it. If **Keep Siftwell available to my phone when the window is closed** is on, a small Siftwell icon stays in the menu bar at the top of the screen after you close the window (it has **Open Siftwell**, **Copy phone link** and **Stop Siftwell**). If the first-launch prompt blocks you for another reason, the ZIP below is the fallback.

**Updating.** Siftwell tells you when a newer version is out and can install it for you (see **Updating Siftwell** below). Or download the newer **Siftwell-x.y.z.dmg**, quit Siftwell, and drag the new Siftwell onto **Applications** again, choosing **Replace**. Your profiles, ratings and settings are exactly as you left them.

**Uninstalling.** Quit Siftwell (also **Stop Siftwell** in the menu-bar icon if it shows one), then drag **Siftwell** from **Applications** to the **Trash**. Your data (profiles, resumes, ratings, saved jobs, settings) stays in `~/Library/Application Support/JobBoard` until you delete that folder yourself (in Finder: **Go → Go to Folder…**, paste that path). If you turned on **Start Siftwell when I sign in**, switch it off in **Settings → Get started** before you uninstall.

### Intel Mac or advanced: use the ZIP (works on Windows too)
#### 1. Download Siftwell
On this page, open **Releases** (on the right side, or under the repository name on a phone), click the **latest** release, and under **Assets** download **Siftwell-x.y.z.zip** (for example `Siftwell-0.1.0.zip`). Unzip it somewhere permanent, for example `Documents\Siftwell` (Windows: right-click the ZIP → **Extract All**; Mac: double-click the ZIP).
(Please don't use the green **Code → Download ZIP** button: that's the in-progress development version, not a tested release.)
Avoid your Downloads folder and OneDrive or iCloud-synced folders.

#### 2. Double-click "Start Siftwell"
- **Windows:** open the Siftwell folder and double-click **Start Siftwell** (`Start Siftwell.cmd`).
- **Mac:** open the Siftwell folder, **right-click** (or Control-click) **Start Siftwell** (`Start Siftwell.command`) and choose **Open**.

The first time, a window says *"Setting up Siftwell. This happens once and takes a couple of minutes..."* while it downloads what it needs (Python and a few packages) into a folder of its own on your computer, not into the Siftwell folder (Windows: `%LOCALAPPDATA%\Siftwell\runtime`; Mac: `~/Library/Application Support/Siftwell/runtime`). Newer versions of Siftwell you download later reuse it, so they start right away. You need to be connected to the internet for this. When it's done, Siftwell opens in its own window (like any other app, with a button in your taskbar), and on Windows the setup window closes by itself (on a Mac you can close the Terminal window).

**One-time security prompts.** Siftwell isn't from an app store, so the first time your computer may ask whether you trust it:
- **Windows** "Windows protected your PC": click **More info**, then **Run anyway**. If you see "Open File – Security Warning" instead, click **Run**. A "Windows Security" firewall window may also ask about Python: click **Allow** if you want to open Siftwell from your phone, otherwise **Cancel** (Siftwell still works on this computer either way).
- **Mac** "cannot be opened because it is from an unidentified developer" (or "Apple could not verify..."): click **Done** or **Cancel**, then right-click **Start Siftwell** → **Open** → **Open**. On macOS 15 (Sequoia) or newer, if there's no Open button: open **System Settings → Privacy & Security**, scroll down to the message about "Start Siftwell", click **Open Anyway**, and confirm.

## First run (all versions)

### 1. Follow the page in the Siftwell window
The Siftwell window shows Siftwell, which runs on your computer at **http://127.0.0.1:8766** (if another program already uses that port, it picks the next free one, 8767 to 8775, and keeps using it). Links to other websites, such as job postings and the Claude sign-in page, open in your normal web browser, and resume downloads show a normal Save dialog. If your computer can't show the Siftwell window (it needs the free Microsoft Edge WebView2 component that Windows 11 includes), Siftwell says so and opens in your web browser instead. You'll be asked to add the first person, then a short setup walks you through your resume, location, pay and goals.

### 2. Finish setup with the "Get started" checklist
Open **Get started** (linked from the welcome page; once you have a profile it is the first item in **Settings**, the gear icon at the top, and the gear shows a small number while required steps are missing). It checks your computer and fixes things with buttons:
- **Browser for resume PDFs:** found automatically (Edge is already on Windows).

**Claude (optional).** Connect Claude to unlock Match ratings, resume reading and tailoring; Siftwell works without it. These two buttons never count as missing steps:
- **Claude Code installed:** click **Install Claude Code** and Siftwell runs the official installer for you.
- **Signed in to Claude:** click **Sign in to Claude**, open the link, sign in with your Claude account, and paste the code it shows back into Siftwell.

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

### 3. Add companies to watch
A new install starts with no companies. Open the **Catalog** page (the database icon at the top, next to Re-rate), go to **Companies**, and paste the link to a company's careers page (for example `https://boards.greenhouse.io/examplecompany`) under **Add a company**. Siftwell figures out which job system it uses, checks that it can read the listings, adds it, and fetches its jobs right away. Besides the common job systems (Greenhouse, Lever, Workday, SAP SuccessFactors, Taleo, Radancy, Eightfold, Avature and others; for a company on SuccessFactors or Taleo you can paste its careers page or its job-search page, and Siftwell finds the job system behind it; a very large Avature site may show as **Capped** in the Catalog because only its first few hundred jobs are read, and a site that forbids automated reading is left alone and shows an error), Siftwell can also read many custom careers sites that publish standard job data (the markup Google Jobs uses); if a site still can't be read, Siftwell tells you so when you paste the link. (You can still add a company from **My profile → Companies** too.) For safety Siftwell only opens ordinary public web links (`https://` or `http://`): it refuses links to this computer or to devices on your home network, and links on unusual ports.

Don't know where to start? Use **Catalog → Find employers near me** (see **The Catalog page** below): Claude looks up employers in your area and Siftwell checks which ones it can read, so you can add them with a tick. (The repository also includes `packs/dc-area.json`, a list of ~800 Washington, DC area employers it was first built with.)

---

## Using it day to day

- **Starting and stopping:** double-click **Start Siftwell** any time; it opens the Siftwell window (if it's already running, it just opens a window on it, or brings the open one to the front). **Closing the Siftwell window stops Siftwell**, including automatic job updates set to **While Siftwell is running**, so leave the window open (minimized is fine) if you want it to keep working in the background. (Updates set to **Even when Siftwell is closed** still run; see **Automatic job updates**.) If an update or re-rate is running, Siftwell asks before it stops. The exception is **Keep Siftwell available to my phone when the window is closed** in **Settings → Get started** (off by default): when it's on, Siftwell keeps running in the background after you close the window (a little memory used, reachable on your home network; a Siftwell icon appears in the system tray near the clock, and right-clicking it lets you open Siftwell, copy the phone link, or stop Siftwell) until you turn the switch off, double-click **Stop Siftwell**, or restart your computer, so your phone and automatic updates keep working, and **Start Siftwell** later just opens a window again. To stop it completely at any time, double-click **Stop Siftwell** (it also closes the window). **Stop Siftwell** only ends the Siftwell that was started from this copy, which it finds from the note Siftwell keeps in your data folder; it never ends other programs, and if it finds no Siftwell it just says "Siftwell isn't running". If Siftwell was started some other way (for example by an older Windows scheduled task), restart your computer or sign out and back in. If Siftwell was started by **Start Siftwell when I sign in**, it is already running when you open a window, and closing the window leaves it running. Siftwell remembers the window's size and position.
- **The board** shows your matching jobs with **Appeal** and **Match** scores. Click a job for Claude's read on it, then **Save**, **Mark applied**, **Not for me**, or **Tailor my resume**.
- **Header icons:** Home · Update job listings (checks every company, ~40 min) · Re-rate (the sparkle icon: opens the **Re-rate panel**, see below) · **Catalog** (the database icon: every company and listing the household tracks, see below) · **My profile** (the person icon: opens your profile page, see below) · **Theme** (click to cycle Auto, Light and Dark; Auto follows your device, and it is the same choice as Settings → Display → Theme) · Settings (app-wide: display, resume PDF, Claude usage, Backup & move, and the **Get started** setup checklist as its first item; a small number on the gear shows how many required setup steps are still missing, and it disappears once you're set up) · your profile menu at the top right (switch person, add a person, manage profiles).
- **My profile page:** click the person icon at the top (or open `/profile`). It is laid out like Settings: a list of sections on the left and the chosen section on the right (on a phone you see the list first, then one section with a **‹ My profile** back link). A status strip at the top shows whether your resume has been read, whether your profile is approved, how many jobs are on your board and how many Claude has rated, and lists anything that is missing, with links to where you fix it. Every control saves itself when you change it ("Saved" appears next to the section title); changes to your search or target re-check your board straight away. The sections:
  - **Resume:** upload or replace your resume (PDF, Word, a photo, or a Google Docs link), when it was last read, and how far along the reading is. A new resume becomes a draft; nothing changes until you approve it.
  - **About you:** what Claude read from your resume (summary, location, experience, skills, education, clearances, certifications, languages, what Claude may and may not claim). Fix anything wrong; once your profile is approved these edits save as you go. A new draft shows an **Approve and re-score jobs** button (and **Discard draft**). Your name is here too.
  - **Highlights & answers:** the degrees, licenses and certifications Siftwell pulled out (they decide which jobs that require something you lack are hidden) with **Edit** and **Re-read my resume**, and the answers you have given to Claude's questions (edit the resume wording or remove them, or **Answer general questions**).
  - **Job search:** home ZIP and radius, the ways of working you'd consider, remote jobs anywhere in the US, travel limit, the lowest base you'd take, your current pay, your level, the job titles to search for, and goals for Claude to weigh. Your saved **travel limit** sets where the board's **Travel** filter starts (Any travel, Under 25%, or 10% or less; "None" starts at 10% or less, the strictest choice the filter has); you can still change that filter on the board any time.
  - **What re-rates and what doesn't:** Claude's ratings judge how well a job fits *you*, so they are redone only when that information changes: your **resume** (including the notes and reframings), **highlights**, **answers** to Claude's questions, **goals**, and your **target**. Changing the **job titles to search for**, your location, radius, the ways of working, your travel limit, your level, or any board filter never resets a rating; those only change which jobs appear. (The lowest base you'd take and the Target scope matter only to your Target tab, so changing them re-rates only that tab.)
  - **Target:** what you're aiming for, which companies, what you'd do to get there, **Not sure? Suggest targets**, and how Claude read your target.
  - **Companies:** the company lists your board watches, the companies you added, and adding a company from its careers link.
- **Re-rate panel:** click the sparkle icon at the top (on a phone it slides up from the bottom). A small number on the icon shows how many of your top jobs need a fresh rating. Pick one of four runs:
  - **Full re-rate** (recommended): a quick check of the jobs that need it, then a careful look at your best jobs, then Claude's best judgment on your top ones. Only ratings made before you changed your resume, answers or settings are redone.
  - **Quick check · Haiku:** every job on your board that Claude would rate. With **Only jobs that need it** ticked (the default) it rates only jobs with no rating or an out-of-date one; untick it to give every job a fresh look.
  - **Careful look · Sonnet:** your top X% of jobs (filled in from Settings; it shows how many jobs that is).
  - **Best judgment · Opus:** your top Y jobs, plus the jobs you saved.
  Whenever you untick **Only ones that need it** on any run (Haiku, Sonnet or Opus), Siftwell first asks to confirm, telling you how many jobs it will re-rate and about how many Claude requests that is, because it also redoes ratings that are already current. If you press the same run again while it is already waiting in the queue, it isn't queued twice.
  "Top" means the Best bets order. The numbers you type apply to that run only (your defaults stay in **Settings → Claude usage**), and **Only ones that need it** is ticked by default. The bottom of the panel shows about how many Claude requests each run takes (it uses your Claude plan). If you have a target, each run has its own **Also rate for my Target tab** box showing the extra Claude requests it adds: it is ticked for **Full re-rate** and unticked for the single-model runs (Haiku, Sonnet, Opus), so Target ratings only run when you choose them. If many jobs haven't had a quick check yet, the panel suggests running it first, so the careful looks go to the right jobs.
  The progress bar shows which model is working and how far along it is. **Stop** ends the run early and keeps every rating finished so far. Press **Run** again while something is running and it waits its turn ("Queued: …"); Stop also cancels anything queued. **Run** is refused while job listings are being updated; try again when the update finishes.
  After you install a newer version, a board that was last built by an older version can't be counted yet: the panel shows **Counting…** instead of numbers while Siftwell refreshes that board once (no new listings, no Claude), then the page reloads by itself.
- **New jobs get a quick check by themselves:** when you change your search settings or companies or finish setup, and that puts new jobs on your board that Claude hasn't rated, Siftwell runs a quick check (Haiku) of just those jobs a few seconds after your last change. It shows as "Quick check of N new jobs" in the progress bar. For a new person's first board every job that passes their filters is new, so it shows as "First quick check of N jobs". The limit is **Quick ratings per night** in **Settings → Claude usage**, and it applies to each run: a first quick check of more jobs than that rates that many and leaves the rest for the Re-rate panel or the next automatic update. It doesn't run if **Rate new jobs during updates** is off in Settings. Careful looks and best judgment for them come with an automatic update (if you turned them on), or use the Re-rate panel. (Updating job listings already rates the new listings it finds.)
- **Adding, renaming and removing people:** open **Settings → Profiles** (the rest of a person's details are on **My profile**). It lists everyone in your household with **Rename** and **Remove** buttons (Remove asks you to tap twice) and an **Add a person** button. Siftwell won't remove the last profile, or anyone while an update is running. A removed person isn't deleted: their folder is moved to `people_removed` inside your data folder, so it can be recovered by hand.
- **Getting a newer version:** see **Updating Siftwell** below for the short version. If you installed with **Siftwell-Setup-x.y.z.exe**, click **Update** when Siftwell offers it, or just run the newer installer (see **Updating** under Install). Otherwise (the ZIP) download the latest release the same way (step 1); **Settings** shows which version you're running (bottom of the list, e.g. "Siftwell 0.1.0"). Unzip it, and double-click **Start Siftwell** in the new folder (stop the old one first with **Stop Siftwell**). You can delete the old Siftwell folder whenever you like. Everything carries over: profiles, ratings, your port and your phone link, with nothing re-rated and no new setup download unless the new version needs different packages. If you turned on **Start Siftwell when I sign in** on the Get started page, it switches to the new folder by itself the first time the new version starts. If you came from an older Siftwell or Job Board, see **Upgrading from an older Siftwell / Job Board** below.
- **Upgrading from an older Siftwell / Job Board (Windows):** older versions started Siftwell at sign-in with a Windows scheduled task called **Job Board server**, which points at the old folder and stops working once you delete it. After you start the new version, open **Settings → Get started** and click **Switch to the new startup**. That turns on the new sign-in startup and turns off the old task (it isn't deleted, and **Undo** turns it back on). Siftwell keeps running meanwhile; the new startup takes over the next time you sign in. If Windows says it needs administrator permission, click **Allow (asks for administrator permission)** and approve the Windows prompt, or follow the steps shown (Task Scheduler, **Job Board server**, **Disable**). Your PC's early-morning wake-up for the nightly update (the task **Job Board wake for nightly update**) keeps working as it is. Once the switch is done you can delete the old folder.
- **Automatic job updates:** new installs have them **off**; you choose in **Settings → Updates** (the same control is under **Catalog → Runs & updates**). Siftwell then checks every company for new and removed jobs, and rates the new ones, once a day at the time you pick (5:30 AM unless you change it). Your three choices:
  - **Off** (the default for a new install): nothing runs by itself; use **Update** on the board or **Fetch everything now** in Catalog.
  - **While Siftwell is running**: Siftwell does it at that time, but only if it is running then (the Siftwell window open, or kept available in the background). If you were already using Siftwell before this setting existed, this is on at 5:30 AM, as before.
  - **Even when Siftwell is closed**: your computer starts a small background job (no window, no administrator permission; you need to be signed in) that runs the update at that time. On Windows it is a Task Scheduler task called **Siftwell automatic update**, on a Mac a LaunchAgent, on Linux a line in your user crontab. If Siftwell happens to be open it runs the update there, so you can watch it; otherwise it runs quietly, writes to `update.log` and `actions.log` in your data folder, and stops. Switching to another choice removes that job. Re-rating after the update only happens if Claude is installed and signed in, and only for profiles with **Re-rate overnight when my info changes** on.
  - **Wake my computer to run it** (Windows, with the previous choice): wakes the computer to run the update. It works only if the laptop is **plugged in and asleep**, not shut down; a computer that is off won't wake. The older **Job Board wake for nightly update** task, if you have it, counts as this being on; Siftwell shows it and leaves it alone.
- **On your phone:** new installs only answer on this computer. To use your phone, turn on **Use Siftwell on my phone** in **Settings → Get started** (Siftwell restarts once), then scan the QR code or open the link it shows (it ends in `?k=…`). Keep that link private: anyone on your home network with it can open your board. On Windows, click **Allow access** on the firewall prompt the first time. Your phone can only reach Siftwell while it is running: that means while its window is open, or after closing the window if **Keep Siftwell available to my phone when the window is closed** is on.

## The Catalog page

The **Catalog** (the database icon at the top) is the household's shared list of every company Siftwell watches and every job listing it has found. Everyone's board is built from it, so a change here updates everyone's board within a minute. On a phone it shows the list of sections first; tap one to open it.

- **Companies:** every company with its job system, which lists it's in, when it was last checked, how many listings are open, and a status: **OK**; **Suspect** (the last check returned far fewer jobs than before, so Siftwell kept the old ones open rather than trust it); **Capped** (the job site only shows its first few thousand jobs, so nothing was closed); **Error** (with the reason); **Paused**; or **Not fetched yet**. Search and filter by status, list or job system. **Add a company** takes a careers page link and the list to put it in. Each company has **Fetch now** (checks just that company, a minute or so; it waits its turn if something else is running), **Pause** / **Resume** (a paused company isn't checked and its jobs leave the boards until you resume it) and **Remove** (tap twice; its listings are kept as closed, so adding it back later keeps their history). Under each name you also see its **company facts** status ("Facts looked up Nov 10, 2026", "No company facts yet", "Facts researched by hand", or "Facts: none found" with the date), and a **Look up facts** / **Refresh facts** button (see **Company facts** below).
- **Listings:** every listing in the catalog, 50 per page, searchable by title, company or location, open or closed, with when it was first and last seen. Under each one you see who it currently passes the filters for and Claude's rating for them ("not rated yet", "Opus 82", and so on). **On someone's board** / **On <name>'s board** narrows the list to listings that made it onto a board.
- **Runs & updates:** the history of updates, board rebuilds, re-rates and employer searches (how many companies, new and closed listings, problems, and how long each Claude model took). This is also where you choose the **automatic job update** (off, while Siftwell is running, or even when it is closed) and its time, the same control as **Settings → Updates**, and where **Fetch everything now** checks every company (about 40 minutes, with a progress bar; Claude then rates the new listings, which uses your Claude plan).
- **Rating:** for each person, how many listings pass their filters, how many Claude has rated (and how many got a careful or best-judgment look), and how many are waiting for a rating or need a fresh one. **Open Re-rate for <name>** switches to that person and opens the board's Re-rate panel.

### Company facts

When you open a job, **About <company>** shows facts about the employer: who owns it, its value (market cap or latest valuation), funding, headcount, founding year, headquarters, what employees usually get as equity, recent layoffs, and its Glassdoor rating, each with a link to where it came from. The Glassdoor rating and layoffs also count toward the company part of **Appeal**.

Siftwell gathers these facts itself, using Claude (the quick Haiku model, searching the web), so **it uses your Claude plan** (a small amount per company: Claude reads a few web pages for each one).

- **During each update:** after the listings are fetched and rated, Claude looks up facts for the companies that need them most: first the ones with jobs on someone's board (the more good jobs there, the sooner), then the rest of the catalog. The progress bar shows "Claude is looking up company facts". The boards are refreshed afterwards so Appeal and the company details use the new facts.
- **How many per update:** **Settings → Claude usage → Company facts per update** (40 unless you change it; 0 to 200, and 0 turns it off). Facts are shared by the whole household, so an update uses the highest number any profile has set.
- **Refreshing:** each company is looked up again after about six months. If Claude can't find facts for a company, Siftwell waits two weeks before trying it again.
- **Right now, for one company:** **Catalog → Companies** has a **Look up facts** button on each company (**Refresh facts** once it has some). It usually takes under a minute. If an update, re-rate or employer search is running, it asks you to try again when that finishes.
- **Hand-researched facts win:** companies whose facts were researched by hand (files in the `company_facts` folder of your data folder) keep those facts; Claude doesn't look them up, and they show "Facts researched by hand" with no button.
- Facts Claude looked up say so under **About <company>** with the date. They can be wrong or out of date, so check the source links before you rely on them.

Without Claude connected, nothing is looked up: updates skip this step, and the Catalog shows "Connect Claude to get company facts: Settings, then Get started" instead of the buttons. Privacy: Claude is sent only the company's name, its sector, and a few of its job titles and locations from the catalog; nothing from your profile.

### Find employers near me

**Catalog → Find employers near me** builds your company list for you. Type a location (it starts with your home ZIP and radius, if you set them), an optional focus (for example "program management" or "healthcare"), tick the kinds of employers to look for (big employers and headquarters, regional offices of national firms, hospitals and health systems, universities, government and contractors, nonprofits and associations, startups and tech, small and mid-size businesses, and remote-friendly employers in your field), and pick a size: small (about 30 employers), medium (about 80), large (about 150) or **Exhaustive** (as many as it can find; see below). Siftwell tells you roughly how long it takes (up to an hour for a large search) before you start.

For each kind of employer, Claude searches the web for employers and their careers pages; this uses your Claude plan. Siftwell itself then opens each careers page and checks whether it can read the listings, skipping companies you already have. Progress shows per kind of employer. The search runs in the background: you can leave the page or close it and come back, and **Stop** / **Resume** pick up where it left off (even after Siftwell restarts). It takes turns with updates and re-rates, so one may wait for the other.

When it's done you see the employers Siftwell can read, with their kind, location, job system and number of open jobs. Tick the ones you want (or **Add all readable**) and choose a list; the default is a new **Near me** list that the person who ran the search watches automatically. Siftwell then fetches their jobs. Employers Siftwell can't read are listed separately (folded away), grouped by the job system their careers page uses (for example "3 use Taleo, 2 use their own custom careers site"), biggest group first, with the reason and their careers link, so you can look at them yourself and see which job systems would add the most employers if Siftwell could read them. Under each kind of employer the page counts how many were found, how many Siftwell can read, how many it can't, and how many you already have.

**Exhaustive search** keeps going until it runs out of new employers. For each kind of employer, Claude searches again and again, each time digging into something narrower: first published lists (state and county "largest employers" lists, chamber of commerce directories, hospital association member lists, school district and college lists, state agency directories, Built In for your city), then sub-types (for example clinics and specialty practices after hospitals, community colleges after universities, county and city agencies after government), then each sizeable city or town within your radius and its county. Each time it tells Claude which employers it already found (names only) and asks for more. A kind of employer stops once two searches in a row add fewer than 2 new employers Siftwell can read. Siftwell still checks every careers page itself, and never checks the same link twice in one search.

- **It uses a lot of your Claude plan and takes hours.** Before you start, the page shows how many Claude searches ("passes") it may take and a rough time (for example "2 hours to 4 hours" for a big metro).
- **Budget:** you choose the most Claude passes it may use (40 to start with, between 5 and 200). The page shows "pass 12 of up to 40" while it runs. When it reaches the budget it stops; raise the budget next to **Resume** to keep going.
- **Stop** / **Resume** work the same as for the other sizes: it remembers what it already found and carries on from there, even after Siftwell restarts. A pass that was stopped half way is done again when you resume (and counts towards the budget again). Between passes it lets updates and re-rates run.

Find employers needs Claude Code installed and signed in on this computer. If it isn't, the page says so and links to **Settings → Get started**.

Privacy: for its web searches, Find employers sends Claude the location you typed (and your focus, if any), plus the names of companies already in your catalog so it can skip them (an Exhaustive search also sends the names of the employers it has found so far, and the cities and towns in your area). For the **Remote-friendly employers in my field** kind it also sends your target roles and the career direction from your profile. Nothing else from your profile or resume is sent.

### Sharing companies and listings

**Catalog → Share** lets you pass your company list to another Siftwell household (a friend in the same city, say), or receive theirs.

- **Export:** tick whole lists or pick companies, choose whether to include their current listings (the open job posts and their text), and click **Download .siftwell file**. The file only holds public information: company names, their job systems and, if ticked, their open listings. It never contains profiles, resumes, saved or applied marks, tailored resumes, settings, your access key, Claude's ratings, company research or Glassdoor facts, or who added what.
- **Import:** choose a `.siftwell` file. Siftwell shows what it holds ("312 new companies, 9,840 new listings, 41 already in your catalog"), you pick the list to put the new companies in, and click **Add**. Companies you already have are matched by their job board, listings by their id; nothing you have is removed or closed, and each listing keeps the earliest "first seen" and latest "last seen" date. Everyone's boards are rebuilt afterwards. Siftwell checks everything in the file first: companies with a job system it doesn't know or with settings that look wrong (for example a link to a private network address) are skipped, links that aren't ordinary web links are dropped, and dates in the future are set to today.

## Using Siftwell without Claude

Claude is an optional upgrade. Without it Siftwell still fetches listings, filters them to your location, pay and level, and ranks them by **Appeal**.

**What works without Claude**
- Automatic job updates (if you turn them on), the board, **Appeal** ranking (the board sorts by Appeal until there are Match ratings), every filter, Save / Applied / Not for me, the Companies tab and the company lists.
- **Search** the board by typing words and pressing Enter: it matches every word against the title, company, place and posting text, with a one-line note that this is a plain keyword search.
- **Fill in my profile myself:** on **My profile → Resume** (and in the first-time setup) a short form takes your name, location, current title, summary, roles, skills, education, certifications and clearance and makes your profile. A Word (`.docx`) or text (`.txt`) resume can pre-fill the form (it is read on your computer, no AI); you check everything before saving. Scanned PDFs, photos and Google Doc links need Claude.

**What needs Claude**
- **Match** ratings, the verdicts and **Claude's read** on each job, the **Re-rate** panel and automatic rating after updates (these quietly skip).
- **Tailor my resume**, the Astra review, tailoring questions, **Target** suggestions and ratings, reading a resume with Claude, and plain-English search that understands what you mean.
- Looking up **company facts** (updates skip it quietly; facts already gathered still show).

Where something needs Claude, Siftwell shows one note ("Connect Claude to get Match ratings and tailoring → Settings → Get started") and a dash where the Match number would be, instead of an error. Once you connect Claude, upload your resume and Claude reads it to improve the profile you filled in.

## Your data stays on your computer

Your information stays on this computer. Siftwell keeps your resume, profiles, saved jobs and ratings in a folder on your PC (not in the cloud). If you connect Claude, job descriptions and your resume are sent to Claude only to rate jobs and tailor resumes. Everything Siftwell creates or learns is stored only on your computer, outside the app folder:
- **Windows:** `%APPDATA%\JobBoard`
- **Mac:** `~/Library/Application Support/JobBoard`

That includes resumes, profiles, settings, saved and applied jobs, tailored resumes, the companies and job listings it has found, Claude's ratings, your phone access key, logs, and which port Siftwell uses. The Siftwell folder itself only holds the app; Siftwell never saves anything into it. Python and the packages Siftwell runs on sit in a separate folder (Windows: `%LOCALAPPDATA%\Siftwell\runtime`; Mac: `~/Library/Application Support/Siftwell/runtime`), which can be rebuilt from the internet any time and holds none of your data.

When Siftwell moves to a newer way of storing something, it puts the old files in an `_archive` folder inside your data folder and removes them after 30 days.

So you can delete the Siftwell folder and download the latest version (or move it) and pick up exactly where you left off. Claude's ratings are tied to your own information (resume, answers, goals and target), not to the app version, so a new version doesn't re-rate anything or spend your Claude plan on ratings you already have. They're only redone when you change your own information. Job descriptions and your resume are sent to Claude (and to ChatGPT if you turn on Astra) to rate and tailor; nothing is sent anywhere else.

## Updating Siftwell

Siftwell looks for a newer version on the project's GitHub **Releases** page: once a day (when it starts, then daily) and whenever you click **Settings → About & updates → Check for updates**. Switch the daily look off with **Check for updates automatically** in the same place; **About & updates** also shows the version you're running. If the page can't be reached (no internet, or the project's page is private), Siftwell says nothing.

When a newer version exists, a small bar appears on the board and in Settings: **Siftwell 0.3.0 is available. What's new · Update**. **What's new** shows the release notes as plain text. **Dismiss** hides the bar for that version (**About & updates** still shows it).
- **Installed with the Windows installer:** click **Update**. Siftwell downloads **Siftwell-Setup-x.y.z.exe** into the `_updates` folder inside your data folder, checks it arrived whole (size and, when GitHub lists one, its checksum), then runs it quietly in the background, closes, and opens again by itself when the new version is in. Your profiles, ratings and settings stay as they are. If the download or the install fails, Siftwell shows why and keeps running the version you have. It won't start while an update or re-rate is running; try again when it finishes.
- **Portable version:** Siftwell never replaces itself. The bar shows **Download the new portable version** with the steps (close Siftwell, unzip the new ZIP over the old folder or copy your `data` folder into the new one, open `Siftwell.exe`).
- **Installed as a Mac app (from the .dmg):** click **Update**. Siftwell downloads **Siftwell-x.y.z.dmg** into the `_updates` folder inside your data folder, checks it arrived whole (size and, when GitHub lists one, its checksum), copies the new Siftwell next to the old one and checks it, then quits, swaps the two and opens the new one by itself. Your data stays as it is, and macOS doesn't ask about the new version again. If Siftwell can't replace itself (it isn't in a folder you can write to, or you are running it straight from the disk image instead of from Applications) it says why and shows **Download the new version**; then update by hand: download the .dmg and drag Siftwell onto **Applications**, choosing **Replace**. A log of the swap is in `_updates/mac-update.log`.
- **Using the ZIP (or a source copy):** Siftwell never replaces itself. The bar shows **Download the new version**, which opens the release page. Download the new ZIP the same way as the first time (step 1 of **Install**), unzip it, double-click **Stop Siftwell** in the old folder and then **Start Siftwell** in the new one. Everything carries over, and you can delete the old folder.

## Moving to another computer / backups

Siftwell can pack **everything it knows** into one file and unpack it on any computer, so it doubles as a backup.

**Make a backup:** open **Settings → Backup & move** and click **Export everything**. After a short wait (a minute or so for a big board) your browser saves `Siftwell-backup-YYYY-MM-DD.zip`. It holds every profile with its resume, settings, saved and applied marks and tailored resumes, Claude's ratings, the job catalog and companies, your schedule, phone-access setting and access key. It leaves out logs, temporary files and your Anthropic API key (type it in again on the new computer). Profiles you removed are only included if you tick **Include removed profiles**. If an update or re-rate is running, Siftwell asks you to try again when it finishes, so nothing is saved half-written.

**This file contains your resumes and personal details. Keep it private** (don't email it or put it somewhere public).

**Move to another computer:**
1. Install Siftwell on the new computer (steps above) and start it.
2. On the welcome page click **Bring over my data from another computer** and choose the backup file. (If you've already set up a profile there, use **Settings → Backup & move → Restore from a backup** instead.)
3. Siftwell shows what's inside: who, how many jobs, ratings and tailored resumes, and which Siftwell version made it. Click **Restore**, then **Open my board**.

Restoring onto a computer that already has data **replaces everything currently in Siftwell on that computer**, so it asks you to tap twice. Before replacing anything it moves the current data to a folder named `before-restore-<date and time>` inside the `_archive` folder in your data folder, so you can get it back by hand. Siftwell checks the file first and refuses anything that isn't a Siftwell backup or isn't safe to open. A backup made by a newer Siftwell restores with a warning; one from a newer backup format asks you to update Siftwell first.

After a restore the boards refresh by themselves (no restart). Your phone link keeps the same key but your new computer's network address may differ: if phone access is on, the new link is shown after the restore (you can also scan the QR code again in **Settings → Get started**). Claude's ratings come back with the backup; a restore never starts Claude by itself. Jobs that aren't rated yet get rated at the next update or when you re-rate.

## Good to know

- **Claude usage:** ratings and company facts run on your Claude plan. Settings → Claude usage controls how many jobs get rated and how carefully, and how many companies get their facts looked up per update. Large first-time ratings can take a while and use a noticeable share of your plan's limits. If a new version shows many ratings as needing a fresh rating even though you haven't changed your resume or answers, press **Keep my current ratings** on that page (two taps) to mark them as up to date instead of re-rating them; it doesn't use Claude.
- **Job sites:** Siftwell reads the public job listings employers publish on their career sites, at a polite pace, for your personal job search. Use it responsibly and respect each site's terms.
- **Not affiliated** with Anthropic, OpenAI, or any job-board provider.

## Troubleshooting

- **The Mac app won't open ("cannot be opened because Apple cannot check it", or "damaged"):** that is the one-time prompt described under **Install → Mac (Apple silicon)**: right-click **Siftwell** → **Open** on macOS 14 or older, or **System Settings → Privacy & Security → Open Anyway** on macOS 15 or newer. If the .dmg itself says it can't be opened, download it again.
- **The Mac app is stuck or I can't find how to stop it:** quit it from the Dock (right-click the icon → **Quit**), or use **Stop Siftwell** in the menu-bar icon if one is showing. Logs are in `~/Library/Application Support/JobBoard`: `window.log`, `server.log` and `launcher.log`.
- **The Siftwell window opened in my browser instead:** this computer couldn't show the window (the pywebview package didn't install, or the Microsoft Edge WebView2 component is missing; Windows 11 has it, for Windows 10 it is a free download from Microsoft). Siftwell works the same in the browser, but it then keeps running until you double-click **Stop Siftwell**. Details are in `window.log` in your data folder.
- **The page won't load:** double-click **Start Siftwell** again; it starts Siftwell if needed and opens the Siftwell window. If it still fails, double-click **Stop Siftwell**, then **Start Siftwell**. Logs are in your data folder: `server.log`, plus `window.log` (the Siftwell window), `start-error.log` on Windows if Siftwell stopped right after starting, and `launcher.log` on a Mac.
- **First-time setup failed:** check your internet connection and double-click **Start Siftwell** again; it picks up where it left off. Details are in `setup.log` in the runtime folder (Windows: `%LOCALAPPDATA%\Siftwell\runtime`; Mac: `~/Library/Application Support/Siftwell/runtime`). Deleting that runtime folder makes it set up from scratch (your data isn't touched).
- **Hidden `.siftwell` or `.venv` folder inside the Siftwell folder:** older versions put the setup there. This version doesn't use them (an old `.venv` is only a fallback if the new setup can't finish) and remembers your port from `.siftwell` automatically. After Siftwell has started once with this version you can delete `.siftwell`, and `.venv` too unless you started Siftwell by hand from it (**Advanced / manual install**).
- **I moved the Siftwell folder:** that's fine; stop Siftwell first, then double-click **Start Siftwell** in the new place. If **Start Siftwell when I sign in** is on, Siftwell points it at the new place the next time it starts.
- **"Connect Claude to get Match ratings and tailoring":** Claude isn't installed or signed in on the computer running Siftwell. Everything else still works; to unlock Match ratings, open **Settings → Get started** and use **Install Claude Code** and **Sign in to Claude**.
- **"Claude Code is signed out":** click **Sign in to Claude** on the board, open the link, sign in, and paste the code back.
- **Another program is using port 8766:** Start Siftwell picks the next free port (8767 to 8775) by itself and remembers it; **Settings → Get started** shows which port Siftwell is using. Phone links need that port too.
- **My phone can't connect:** check **Use Siftwell on my phone** is on (**Settings → Get started**), Siftwell is running (its window is open, or **Keep Siftwell available to my phone when the window is closed** is on), the phone is on the same Wi-Fi, and Windows Firewall allowed Siftwell (Start menu → "Allow an app through Windows Firewall").
- **Which version am I running?** Open **Settings → About & updates**: it shows the version (for example "Siftwell 0.1.0"), which is also shown small under the list of categories.
- **What happened, and when?** Siftwell keeps a plain-text diary of everything done from the pages (updates, re-rates, adding or removing people and companies, saved settings, changing start at sign-in, restarts): `actions.log` in your data folder. Each line has the time, the action, the profile, which device did it and its browser. It never records passwords or keys. When it gets big it starts a new file and keeps the old one as `actions.log.1`.
- **The board says "A background job is running":** an update or re-rate is still going (for example one that started before Siftwell was restarted). Wait for it to finish; Siftwell won't restart itself while it runs.
- **Resume PDFs don't build:** install Google Chrome or Microsoft Edge.

## License

[MIT](../LICENSE)
