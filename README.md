<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/brand/siftwell-logo-dark.svg">
    <img src="assets/brand/siftwell-logo.svg" alt="Siftwell" width="320">
  </picture>
</p>

# Siftwell

**Your own job search assistant that runs on your computer.**

Siftwell checks the career pages of the companies you care about every night, filters the openings down to your location, pay and level, has Claude rate how well each one fits your resume, and tailors your resume for the jobs worth applying to. Several people in one household can each have their own profile.

> **Status: early preview.** Siftwell works day to day: it starts with a double-click, and a **Get started** checklist inside the app installs Claude Code and signs you in. Coming next: a proper desktop app window.

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
A new install starts with no companies. Open the **Catalog** page (the database icon at the top, next to Re-rate), go to **Companies**, and paste the link to a company's careers page (for example `https://boards.greenhouse.io/examplecompany`) under **Add a company**. Siftwell figures out which job system it uses, checks that it can read the listings, adds it, and fetches its jobs right away. Besides the common job systems (Greenhouse, Lever, Workday and others), Siftwell can also read many custom careers sites that publish standard job data (the markup Google Jobs uses); if a site still can't be read, Siftwell tells you so when you paste the link. (You can still add a company from **My profile → Companies** too.) For safety Siftwell only opens ordinary public web links (`https://` or `http://`): it refuses links to this computer or to devices on your home network, and links on unusual ports.

Don't know where to start? Use **Catalog → Find employers near me** (see **The Catalog page** below): Claude looks up employers in your area and Siftwell checks which ones it can read, so you can add them with a tick. (The repository also includes `packs/dc-area.json`, a list of ~800 Washington, DC area employers it was first built with.)

---

## Using it day to day

- **Starting and stopping:** double-click **Start Siftwell** any time; it opens the Siftwell window (if it's already running, it just opens a window on it, or brings the open one to the front). **Closing the Siftwell window stops Siftwell**, including the nightly update, so leave the window open (minimized is fine) if you want Siftwell to keep working in the background. If an update or re-rate is running, Siftwell asks before it stops. The exception is **Keep Siftwell available to my phone when the window is closed** in **Settings → Get started** (off by default): when it's on, Siftwell keeps running in the background after you close the window (a little memory used, reachable on your home network; a Siftwell icon appears in the system tray near the clock, and right-clicking it lets you open Siftwell, copy the phone link, or stop Siftwell) until you turn the switch off, double-click **Stop Siftwell**, or restart your computer, so your phone and the nightly update keep working, and **Start Siftwell** later just opens a window again. To stop it completely at any time, double-click **Stop Siftwell** (it also closes the window). If Siftwell was started by **Start Siftwell when I sign in**, it is already running when you open a window, and closing the window leaves it running. Siftwell remembers the window's size and position.
- **The board** shows your matching jobs with **Appeal** and **Match** scores. Click a job for Claude's read on it, then **Save**, **Mark applied**, **Not for me**, or **Tailor my resume**.
- **Header icons:** Home · Update job listings (checks every company, ~40 min) · Re-rate (the sparkle icon: opens the **Re-rate panel**, see below) · **Catalog** (the database icon: every company and listing the household tracks, see below) · **My profile** (the person icon: opens your profile page, see below) · **Theme** (click to cycle Auto, Light and Dark; Auto follows your device, and it is the same choice as Settings → Display → Theme) · Settings (app-wide: display, resume PDF, Claude usage, Backup & move, and the **Get started** setup checklist as its first item; a small number on the gear shows how many required setup steps are still missing, and it disappears once you're set up) · your profile menu at the top right (switch person, add a person, manage profiles).
- **My profile page:** click the person icon at the top (or open `/profile`). It is laid out like Settings: a list of sections on the left and the chosen section on the right (on a phone you see the list first, then one section with a **‹ My profile** back link). A status strip at the top shows whether your resume has been read, whether your profile is approved, how many jobs are on your board and how many Claude has rated, and lists anything that is missing, with links to where you fix it. Every control saves itself when you change it ("Saved" appears next to the section title); changes to your search or target re-check your board straight away. The sections:
  - **Resume:** upload or replace your resume (PDF, Word, a photo, or a Google Docs link), when it was last read, and how far along the reading is. A new resume becomes a draft; nothing changes until you approve it.
  - **About you:** what Claude read from your resume (summary, location, experience, skills, education, clearances, certifications, languages, what Claude may and may not claim). Fix anything wrong; once your profile is approved these edits save as you go. A new draft shows an **Approve and re-score jobs** button (and **Discard draft**). Your name is here too.
  - **Highlights & answers:** the degrees, licenses and certifications Siftwell pulled out (they decide which jobs that require something you lack are hidden) with **Edit** and **Re-read my resume**, and the answers you have given to Claude's questions (edit the resume wording or remove them, or **Answer general questions**).
  - **Job search:** home ZIP and radius, the ways of working you'd consider, remote jobs anywhere in the US, travel limit, the lowest base you'd take, your current pay, your level, the job titles to search for, and goals for Claude to weigh.
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
- **New jobs get a quick check by themselves:** when you change your search settings or companies or finish setup, and that puts new jobs on your board that Claude hasn't rated, Siftwell runs a quick check (Haiku) of just those jobs a few seconds after your last change. It shows as "Quick check of N new jobs" in the progress bar. For a new person's first board every job that passes their filters is new, so it shows as "First quick check of N jobs". The limit is **Quick ratings per night** in **Settings → Claude usage**, and it applies to each run: a first quick check of more jobs than that rates that many and leaves the rest for the Re-rate panel or the nightly run. It doesn't run if **Rate new jobs during updates** is off in Settings. Careful looks and best judgment for them come with the nightly update, or use the Re-rate panel. (Updating job listings already rates the new listings it finds.)
- **Adding, renaming and removing people:** open **Settings → Profiles** (the rest of a person's details are on **My profile**). It lists everyone in your household with **Rename** and **Remove** buttons (Remove asks you to tap twice) and an **Add a person** button. Siftwell won't remove the last profile, or anyone while an update is running. A removed person isn't deleted: their folder is moved to `people_removed` inside your data folder, so it can be recovered by hand.
- **Getting a newer version:** download the latest release the same way (step 1); **Settings** shows which version you're running (bottom of the list, e.g. "Siftwell 0.1.0"). Unzip it, and double-click **Start Siftwell** in the new folder (stop the old one first with **Stop Siftwell**). You can delete the old Siftwell folder whenever you like. Everything carries over: profiles, ratings, your port and your phone link, with nothing re-rated and no new setup download unless the new version needs different packages. If you turned on **Start Siftwell when I sign in** on the Get started page, it switches to the new folder by itself the first time the new version starts. If you came from an older Siftwell or Job Board, see **Upgrading from an older Siftwell / Job Board** below.
- **Upgrading from an older Siftwell / Job Board (Windows):** older versions started Siftwell at sign-in with a Windows scheduled task called **Job Board server**, which points at the old folder and stops working once you delete it. After you start the new version, open **Settings → Get started** and click **Switch to the new startup**. That turns on the new sign-in startup and turns off the old task (it isn't deleted, and **Undo** turns it back on). Siftwell keeps running meanwhile; the new startup takes over the next time you sign in. If Windows says it needs administrator permission, click **Allow (asks for administrator permission)** and approve the Windows prompt, or follow the steps shown (Task Scheduler, **Job Board server**, **Disable**). Your PC's early-morning wake-up for the nightly update (the task **Job Board wake for nightly update**) keeps working as it is. Once the switch is done you can delete the old folder.
- **Nightly update:** every morning at 5:30 Siftwell checks for new and removed jobs and rates the new ones. You can change the time or turn it off in **Catalog → Runs & updates**.
- **On your phone:** new installs only answer on this computer. To use your phone, turn on **Use Siftwell on my phone** in **Settings → Get started** (Siftwell restarts once), then scan the QR code or open the link it shows (it ends in `?k=…`). Keep that link private: anyone on your home network with it can open your board. On Windows, click **Allow access** on the firewall prompt the first time. Your phone can only reach Siftwell while it is running: that means while its window is open, or after closing the window if **Keep Siftwell available to my phone when the window is closed** is on.

## The Catalog page

The **Catalog** (the database icon at the top) is the household's shared list of every company Siftwell watches and every job listing it has found. Everyone's board is built from it, so a change here updates everyone's board within a minute. On a phone it shows the list of sections first; tap one to open it.

- **Companies:** every company with its job system, which lists it's in, when it was last checked, how many listings are open, and a status: **OK**; **Suspect** (the last check returned far fewer jobs than before, so Siftwell kept the old ones open rather than trust it); **Capped** (the job site only shows its first few thousand jobs, so nothing was closed); **Error** (with the reason); **Paused**; or **Not fetched yet**. Search and filter by status, list or job system. **Add a company** takes a careers page link and the list to put it in. Each company has **Fetch now** (checks just that company, a minute or so; it waits its turn if something else is running), **Pause** / **Resume** (a paused company isn't checked and its jobs leave the boards until you resume it) and **Remove** (tap twice; its listings are kept as closed, so adding it back later keeps their history).
- **Listings:** every listing in the catalog, 50 per page, searchable by title, company or location, open or closed, with when it was first and last seen. Under each one you see who it currently passes the filters for and Claude's rating for them ("not rated yet", "Opus 82", and so on). **On someone's board** / **On <name>'s board** narrows the list to listings that made it onto a board.
- **Runs & updates:** the history of updates, board rebuilds, re-rates and employer searches (how many companies, new and closed listings, problems, and how long each Claude model took). This is also where you turn the **automatic daily update** on or off and pick its time, and where **Fetch everything now** checks every company (about 40 minutes, with a progress bar; Claude then rates the new listings, which uses your Claude plan).
- **Rating:** for each person, how many listings pass their filters, how many Claude has rated (and how many got a careful or best-judgment look), and how many are waiting for a rating or need a fresh one. **Open Re-rate for <name>** switches to that person and opens the board's Re-rate panel.

### Find employers near me

**Catalog → Find employers near me** builds your company list for you. Type a location (it starts with your home ZIP and radius, if you set them), an optional focus (for example "program management" or "healthcare"), tick the kinds of employers to look for (big employers and headquarters, regional offices of national firms, hospitals and health systems, universities, government and contractors, nonprofits and associations, startups and tech, small and mid-size businesses, and remote-friendly employers in your field), and pick a size: small (about 30 employers), medium (about 80) or large (about 150). Siftwell tells you roughly how long it takes (up to an hour for a large search) before you start.

For each kind of employer, Claude searches the web for employers and their careers pages; this uses your Claude plan. Siftwell itself then opens each careers page and checks whether it can read the listings, skipping companies you already have. Progress shows per kind of employer. The search runs in the background: you can leave the page or close it and come back, and **Stop** / **Resume** pick up where it left off (even after Siftwell restarts). It takes turns with updates and re-rates, so one may wait for the other.

When it's done you see the employers Siftwell can read, with their kind, location, job system and number of open jobs. Tick the ones you want (or **Add all readable**) and choose a list; the default is a new **Near me** list that the person who ran the search watches automatically. Siftwell then fetches their jobs. Employers Siftwell can't read are listed separately (folded away) with the reason and their careers link, so you can look at them yourself.

Find employers needs Claude Code installed and signed in on this computer. If it isn't, the page says so and links to **Settings → Get started**.

Privacy: for its web searches, Find employers sends Claude the location you typed (and your focus, if any), plus the names of companies already in your catalog so it can skip them. For the **Remote-friendly employers in my field** kind it also sends your target roles and the career direction from your profile. Nothing else from your profile or resume is sent.

### Sharing companies and listings

**Catalog → Share** lets you pass your company list to another Siftwell household (a friend in the same city, say), or receive theirs.

- **Export:** tick whole lists or pick companies, choose whether to include their current listings (the open job posts and their text), and click **Download .siftwell file**. The file only holds public information: company names, their job systems and, if ticked, their open listings. It never contains profiles, resumes, saved or applied marks, tailored resumes, settings, your access key, Claude's ratings, company research or Glassdoor facts, or who added what.
- **Import:** choose a `.siftwell` file. Siftwell shows what it holds ("312 new companies, 9,840 new listings, 41 already in your catalog"), you pick the list to put the new companies in, and click **Add**. Companies you already have are matched by their job board, listings by their id; nothing you have is removed or closed, and each listing keeps the earliest "first seen" and latest "last seen" date. Everyone's boards are rebuilt afterwards. Siftwell checks everything in the file first: companies with a job system it doesn't know or with settings that look wrong (for example a link to a private network address) are skipped, links that aren't ordinary web links are dropped, and dates in the future are set to today.

## Your data stays on your computer

Your information stays on this computer. Siftwell keeps your resume, profiles, saved jobs and ratings in a folder on your PC (not in the cloud). If you connect Claude, job descriptions and your resume are sent to Claude only to rate jobs and tailor resumes. Everything Siftwell creates or learns is stored only on your computer, outside the app folder:
- **Windows:** `%APPDATA%\JobBoard`
- **Mac:** `~/Library/Application Support/JobBoard`

That includes resumes, profiles, settings, saved and applied jobs, tailored resumes, the companies and job listings it has found, Claude's ratings, your phone access key, logs, and which port Siftwell uses. The Siftwell folder itself only holds the app; Siftwell never saves anything into it. Python and the packages Siftwell runs on sit in a separate folder (Windows: `%LOCALAPPDATA%\Siftwell\runtime`; Mac: `~/Library/Application Support/Siftwell/runtime`), which can be rebuilt from the internet any time and holds none of your data.

When Siftwell moves to a newer way of storing something, it puts the old files in an `_archive` folder inside your data folder and removes them after 30 days.

So you can delete the Siftwell folder and download the latest version (or move it) and pick up exactly where you left off. Claude's ratings are tied to your own information (resume, answers, goals and target), not to the app version, so a new version doesn't re-rate anything or spend your Claude plan on ratings you already have. They're only redone when you change your own information. Job descriptions and your resume are sent to Claude (and to ChatGPT if you turn on Astra) to rate and tailor; nothing is sent anywhere else.

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
