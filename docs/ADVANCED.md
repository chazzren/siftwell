# Siftwell: more options & troubleshooting

The everyday guide is **[GUIDE.md](GUIDE.md)**. This page holds the less common things: other ways to install, uninstalling, where files are kept, updating by hand, doing the setup yourself, and what to try when something doesn't work.

- [Portable version (no install)](#portable-version-no-install)
- [Intel Mac or advanced: use the ZIP](#intel-mac-or-advanced-use-the-zip-works-on-windows-too)
- [Uninstalling](#uninstalling)
- [Where Siftwell keeps things](#where-siftwell-keeps-things)
- [Updating the portable version or the ZIP](#updating-the-portable-version-or-the-zip)
- [Upgrading from an older Siftwell / Job Board (Windows)](#upgrading-from-an-older-siftwell--job-board-windows)
- [Find new jobs automatically: what it adds to your computer](#find-new-jobs-automatically-what-it-adds-to-your-computer)
- [Installing Claude Code yourself](#installing-claude-code-yourself)
- [Advanced / manual install](#advanced--manual-install)
- [Troubleshooting](#troubleshooting)

## Portable version (no install)
Want to run Siftwell from a USB stick, a Dropbox folder, or a computer where you can't install programs? Use the portable version. On the **Releases** page, under **Assets**, download **Siftwell-Portable-x.y.z.zip**, right-click it and choose **Extract all** (anywhere you like), open the **Siftwell** folder and double-click **Siftwell.exe**. Then carry on at **First run** in the [guide](GUIDE.md#first-run).

- **Nothing is installed**, and by default nothing is written outside the Siftwell folder. Your profiles, resumes, ratings and settings are kept in a **data** folder right next to `Siftwell.exe`. **Deleting the Siftwell folder deletes your data**, so keep a copy of the `data` folder (or use **Settings → Backup & move**).
- The folder must be one you can write to (Documents, the Desktop, a USB stick). If it isn't, Siftwell says so: move the folder to Documents and open it again.
- **Start Siftwell when I sign in** and **Even when Siftwell is closed** (automatic job updates) are **off**. You can still turn them on in **Settings**; Siftwell reminds you that this adds something to this computer, outside the Siftwell folder.
- **Updating:** Siftwell shows **Download the new portable version**. Close Siftwell, unzip the new ZIP over the old folder (choose to replace files), or unzip it somewhere new and copy your old `data` folder into it, then open `Siftwell.exe` again. Siftwell never replaces itself.
- **Moving to another computer or drive:** close Siftwell and copy the whole folder; the data goes with it, and a changed drive letter (a USB stick on E: or F:) doesn't matter. On the new computer your phone link changes (**Settings → Get started** shows the new one) and you sign in to Claude Code again there.
- **Between the installed and the portable version:** with Siftwell closed, use **Settings → Backup & move** (export on one, import on the other), or copy the contents of `%APPDATA%\JobBoard` into the portable `data` folder (or the other way round).
- **Trying a new version side by side:** unzip the portable version into a test folder and, if you like, copy your data folder into its `data` folder first. It runs on its own port (the window title reads "Siftwell (test copy, port 8767)") and never stops, reuses or opens your main copy. **Settings → About & updates** shows which data folder a copy is using.

## Intel Mac or advanced: use the ZIP (works on Windows too)
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

## Uninstalling

**Windows (installer).** Open **Settings → Apps → Installed apps**, find **Siftwell**, click **Uninstall**. Your data (profiles, resumes, ratings, saved jobs, settings; `%APPDATA%\JobBoard`) is **kept** unless you tick **Also remove my Siftwell data** in the window that appears (that cannot be undone). Install Siftwell again later and everything is back.

**Mac (.dmg).** Quit Siftwell (also **Stop Siftwell** in the menu-bar icon if it shows one), then drag **Siftwell** from **Applications** to the **Trash**. Your data (profiles, resumes, ratings, saved jobs, settings) stays in `~/Library/Application Support/JobBoard` until you delete that folder yourself (in Finder: **Go → Go to Folder…**, paste that path). If you turned on **Start Siftwell when I sign in**, switch it off in **Settings → Get started** before you uninstall.

**Portable version or the ZIP.** Stop Siftwell and delete its folder. The portable version keeps your data in the `data` folder inside it, so copy that first if you want to keep it.

## Where Siftwell keeps things

- **Your data** (profiles, resumes, ratings, saved jobs, settings, the employers and listings, logs): Windows `%APPDATA%\JobBoard`; Mac `~/Library/Application Support/JobBoard`; the portable version keeps it in the `data` folder next to `Siftwell.exe`. **Settings → About & updates** shows the folder in use.
- **The app itself** (installer): `%LOCALAPPDATA%\Programs\Siftwell` on Windows, **Applications** on a Mac. Siftwell never saves anything into its own folder.
- **The ZIP's setup** (Python and the packages Siftwell runs on): Windows `%LOCALAPPDATA%\Siftwell\runtime`; Mac `~/Library/Application Support/Siftwell/runtime`. It can be rebuilt from the internet any time and holds none of your data.
- **The address Siftwell runs at:** **http://127.0.0.1:8766** on your own computer. If another program already uses that port, Siftwell picks the next free one (8767 to 8775) and keeps using it; **Settings → Get started** shows which.
- **The employer directory's files:** a `directory` folder inside your data folder (see the guide). A directory you built on this computer is in `directory/local` (deleting that folder only means Siftwell would have to build it again).

## Updating the portable version or the ZIP

- **Portable version:** Siftwell never replaces itself. The bar shows **Download the new portable version** with the steps (close Siftwell, unzip the new ZIP over the old folder or copy your `data` folder into the new one, open `Siftwell.exe`).
- **Using the ZIP (or a source copy):** Siftwell never replaces itself. The bar shows **Download the new version**, which opens the release page. Download the new ZIP the same way as the first time (step 1 of **Install**), unzip it, double-click **Stop Siftwell** in the old folder and then **Start Siftwell** in the new one. Everything carries over, and you can delete the old folder.

More detail for the ZIP: If you installed with **Siftwell-Setup-x.y.z.exe**, click **Update** when Siftwell offers it, or just run the newer installer (see **Updating** under Install). Otherwise (the ZIP) download the latest release the same way (step 1); **Settings** shows which version you're running (bottom of the list, e.g. "Siftwell 0.1.0"). Unzip it, and double-click **Start Siftwell** in the new folder (stop the old one first with **Stop Siftwell**). You can delete the old Siftwell folder whenever you like. Everything carries over: profiles, ratings, your port and your phone link, with nothing re-rated and no new setup download unless the new version needs different packages. If you turned on **Start Siftwell when I sign in** on the Get started page, it switches to the new folder by itself the first time the new version starts. If you came from an older Siftwell or Job Board, see **Upgrading from an older Siftwell / Job Board** below.

## Upgrading from an older Siftwell / Job Board (Windows)

Older versions started Siftwell at sign-in with a Windows scheduled task called **Job Board server**, which points at the old folder and stops working once you delete it. After you start the new version, open **Settings → Get started** and click **Switch to the new startup**. That turns on the new sign-in startup and turns off the old task (it isn't deleted, and **Undo** turns it back on). Siftwell keeps running meanwhile; the new startup takes over the next time you sign in. If Windows says it needs administrator permission, click **Allow (asks for administrator permission)** and approve the Windows prompt, or follow the steps shown (Task Scheduler, **Job Board server**, **Disable**). Your PC's early-morning wake-up for the nightly update (the task **Job Board wake for nightly update**) keeps working as it is. Once the switch is done you can delete the old folder.

## Find new jobs automatically: what it adds to your computer

With **Find new jobs automatically** set to **Even when Siftwell is closed** (see the [guide](GUIDE.md#using-it-day-to-day)), your computer runs a small background job at the time you chose. On Windows it is a Task Scheduler task called **Siftwell automatic update**, on a Mac a LaunchAgent, on Linux a line in your user crontab. When Siftwell isn't open it writes to `update.log` and `actions.log` in your data folder. Switching to another choice removes the job.

## Installing Claude Code yourself

The **Install Claude Code** button in Siftwell does this for you. To do it by hand:

- **Windows** (PowerShell): `irm https://claude.ai/install.ps1 | iex`
- **Mac** (Terminal): `curl -fsSL https://claude.ai/install.sh | bash`

Then run `claude` once and sign in, or use the **Sign in to Claude** button in Siftwell.

## Advanced / manual install

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

The repository also includes `packs/dc-area.json`, a list of about 800 Washington, DC area employers the project was first built with, and the starter lists of large US employers used when the employer directory can't be reached.

## Troubleshooting

- **The Mac app won't open ("cannot be opened because Apple cannot check it", or "damaged"):** that is the one-time prompt described under **Install → Mac (Apple silicon)** in the [guide](GUIDE.md#install): right-click **Siftwell** → **Open** on macOS 14 or older, or **System Settings → Privacy & Security → Open Anyway** on macOS 15 or newer. If the .dmg itself says it can't be opened, download it again.
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
- **The board says "Siftwell is finishing a job that was started earlier":** a check for new jobs or a re-rate is still going (for example one that started before Siftwell was restarted). Wait for it to finish; Siftwell won't restart itself while it runs.
- **The board says "Siftwell isn't running":** the page is still open but Siftwell itself has stopped (its window was closed, or the computer restarted). Open Siftwell again and reload the page; a job search that was running carries on where it stopped (**Continue checking**).
- **Resume PDFs don't build:** install Google Chrome or Microsoft Edge.
