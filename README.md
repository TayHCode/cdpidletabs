# Close idle Chrome tabs

Each run queries a Chrome DevTools Protocol (CDP) endpoint for page tabs and compares each tab's title and URL with the previous run. When that pair has stayed unchanged for the configured threshold, the script reports the tab as idle; with `--close`, it asks Chrome to close it. It runs in dry-run mode by default, protects the first real page in Chrome’s list, and skips URLs matching `--keep` patterns.

## Install

Python **3.8+** is required; **no packages needed**. From the cloned repository,
run this first (on Windows, use `py -3` in place of `python3`):

```sh
python3 close_idle_tabs.py --help
```

Help prints the available options and exits without contacting Chrome. The script
uses only Python's standard library and Chrome's existing CDP HTTP endpoints
(`/json/list` and `/json/close/{id}`). Python below 3.8 gets a short
"needs Python 3.8 or newer" message. Chrome with debugging enabled is needed for
actual tab observations; see the launch commands below.

### Linux

Check `python3 --version`. If Python is missing or older than 3.8, install a
supported Python 3 through your distribution's package manager. You can run
`python3 close_idle_tabs.py` directly; neither pip nor a virtual environment is
required.

### macOS

Check `python3 --version` before starting. The Python supplied by macOS developer
tools can be 3.9.6, which works; some Macs have an older version or no Python 3.
For a newer version, use the [Python.org macOS installer](https://www.python.org/downloads/macos/),
then open a new Terminal and check `python3 --version` again. Run
`python3 close_idle_tabs.py --help` from the clone.

### Windows (PowerShell)

Use the Python launcher, not `python3`, which can be a Microsoft Store stub:

```powershell
py -3 --version
py -3 close_idle_tabs.py --help
```

If `py` is unavailable or reports a version below 3.8, install Python 3 from
[Python.org for Windows](https://www.python.org/downloads/windows/) with the
launcher option enabled, reopen PowerShell, and repeat the check. Use `py -3`
for the script and test commands throughout this README.

### Optional installed command

If you want a `cdpidletabs` command, use a virtual environment. The direct script
above is the first-class, no-admin path. On Debian/Ubuntu, venv needs
`python3-venv`. If creation fails because `ensurepip` is missing, delete the
partial environment with `rm -rf .venv` (only the environment you just created)
and continue with `python3 close_idle_tabs.py --help` and the direct script.
If you prefer to retry installation, install `python3-venv` with your package
manager (for example `sudo apt install python3-venv`, requiring administrator
access), delete that partial `.venv`, then repeat the optional commands below.

Linux/macOS:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install .
cdpidletabs --help
```

Windows PowerShell (activation is optional):

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install .
cdpidletabs --help
```

If PowerShell blocks activation, use `.\.venv\Scripts\python.exe -m pip install .`
and `.\.venv\Scripts\cdpidletabs.exe --help` without changing execution policy.
If you already use pipx, `pipx install .` is another optional way to install the
command; pipx itself and package building need installation tools and downloads.

Set `CDP_ENDPOINT` in the environment to the browser's HTTP debugging endpoint,
or pass it with `--endpoint`.

Run the script from the same working directory each time so its default `.close_idle_tabs_state.json` observation file is reused (cron and systemd must set the same working directory, or every run starts fresh). The file stores target IDs, SHA-256 digests of title and URL pairs, and timestamps; it does not store page titles or URLs. To check the command from a fresh checkout, run `python3 close_idle_tabs.py --help`; it prints the available options and exits without contacting Chrome.

Automated tests use mocked HTTP responses and temporary state files:

```sh
python3 -m unittest discover -s tests -q
```

MIT licensed, pre-release. No package or public release has been published.
See [SECURITY.md](SECURITY.md) before enabling browser access.

## Starting Chrome with debugging

Choose a **free port** and a **new profile directory** for your own Chrome
instance. The examples use 9222; the browser owner can pick any available TCP
port. Change both Chrome's `--remote-debugging-port` and the script's endpoint
when choosing another. Port 9222 is a common convention, not a required port,
and may already belong to someone else on a shared machine.

Before launching, check the example port (use `py -3` on Windows). If this fails
with "address already in use", pick a different port; do not attach to or stop
the existing browser:

```sh
python3 -c "import socket; s=socket.socket(); s.bind(('127.0.0.1',9222)); s.close(); print('Port 9222 is available')"
```

Use a dedicated, non-default `--user-data-dir`: [Chrome 136 and later ignore
remote debugging flags on the default profile directory](https://developer.chrome.com/blog/remote-debugging-port).
Keep the address on loopback (`127.0.0.1`). Do not use your everyday profile.
Install Chrome from [Google's download page](https://www.google.com/chrome/)
if it is missing: on Debian/Ubuntu select the `.deb` and install it with your
package manager; on macOS move the app to Applications; on Windows run the
installer. Installation may require administrator access. For Linux without
that access, [Chrome for Testing](https://googlechromelabs.github.io/chrome-for-testing/)
offers a ZIP that runs from your own folder; see the exact no-admin commands
below. System shared libraries are still required.

### Linux

The graphical command needs a desktop session with a working display
(`DISPLAY` on X11). `google-chrome` is the usual installed binary name:

```sh
chrome_profile=$(mktemp -d "${TMPDIR:-/tmp}/cdpidletabs-profile.XXXXXX")
google-chrome --no-first-run --remote-debugging-port=9222 --remote-debugging-address=127.0.0.1 \
  --user-data-dir="$chrome_profile"
```

`--no-first-run` skips Linux's initial setup dialog, which can otherwise pause
startup before the debugging endpoint is available in a new profile.

Over SSH without a display, use this headless alternative (no visible window):

```sh
chrome_profile=$(mktemp -d "${TMPDIR:-/tmp}/cdpidletabs-profile.XXXXXX")
google-chrome --headless=new --remote-debugging-port=9222 \
  --remote-debugging-address=127.0.0.1 --user-data-dir="$chrome_profile"
```

### Linux without administrator access: Chrome for Testing

For **Linux x86-64**, these commands need `curl`, `unzip` and Python 3. They
select Google's current Stable ZIP, download it into a new folder and extract
with `unzip`, which preserves Unix executable permissions. Do not substitute
Python's `zipfile` extraction: it drops those permissions. Explicitly restore
the executable bits on Chrome and its helper binaries as well; a non-executable
`chrome_crashpad_handler` causes a `posix_spawn ... Permission denied` crash.

Run from the repository in a shell with a free port (9222 here):

```sh
cft_dir=$(mktemp -d "${TMPDIR:-/tmp}/cdpidletabs-cft.XXXXXX")
curl -fL https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions-with-downloads.json -o "$cft_dir/versions.json"
cft_url=$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(next(x["url"] for x in d["channels"]["Stable"]["downloads"]["chrome"] if x["platform"] == "linux64"))' "$cft_dir/versions.json")
curl -fL "$cft_url" -o "$cft_dir/chrome.zip"
unzip -q "$cft_dir/chrome.zip" -d "$cft_dir"
chmod +x "$cft_dir/chrome-linux64/chrome" "$cft_dir/chrome-linux64/chrome_crashpad_handler" "$cft_dir/chrome-linux64/chrome_sandbox"
chrome_profile="$cft_dir/profile"
"$cft_dir/chrome-linux64/chrome" --headless=new --no-first-run --no-default-browser-check --remote-debugging-port=9222 --remote-debugging-address=127.0.0.1 --user-data-dir="$chrome_profile" >"$cft_dir/chrome.log" 2>&1 &
chrome_pid=$!
```

Wait a few seconds, then require a successful version response before running
this tool. If it fails, read `"$cft_dir/chrome.log"`; do not infer startup from
the background command's exit status. These flags worked with the normal Chrome
sandbox; they do not require `--no-sandbox`.

```sh
curl --fail http://127.0.0.1:9222/json/version
python3 close_idle_tabs.py --port 9222
```

Keep these variables in the same shell. When finished, stop only the instance
you just launched and delete only its new download/profile folder:

```sh
kill "$chrome_pid"
wait "$chrome_pid" || true
rm -rf -- "$cft_dir"
```

### macOS

In Terminal, launch a separate Chrome app instance:

```sh
chrome_profile=$(mktemp -d "${TMPDIR:-/tmp}/cdpidletabs-profile.XXXXXX")
open -na "Google Chrome" --args --remote-debugging-port=9222 \
  --remote-debugging-address=127.0.0.1 --user-data-dir="$chrome_profile"
```

The app binary is also usable directly, including over SSH into a Mac with a
logged-in graphical session (use a fresh profile when trying this alternative):

```sh
chrome_profile=$(mktemp -d "${TMPDIR:-/tmp}/cdpidletabs-profile.XXXXXX")
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --remote-debugging-port=9222 --remote-debugging-address=127.0.0.1 \
  --user-data-dir="$chrome_profile"
```

### Windows (PowerShell)

#### At the Windows machine: desktop PowerShell

Run this in a normal desktop PowerShell window on the Windows machine:

```powershell
$chromeProfile = Join-Path $env:TEMP ("cdpidletabs-profile-" + [guid]::NewGuid())
& "$env:ProgramFiles\Google\Chrome\Application\chrome.exe" --no-first-run --remote-debugging-port=9222 --remote-debugging-address=127.0.0.1 "--user-data-dir=$chromeProfile"
```

If Chrome is installed elsewhere, replace the executable path with its actual
location. `$chromeProfile` is a new disposable directory, not your regular profile.
Check `/json/version` from a second PowerShell window as shown below.

#### Over SSH / remote shell: use an interactive scheduled task

The current Windows user must also be logged into the desktop. This route opens
a visible Chrome window there and survives the launching SSH session ending.
Use your own free port and a new task/profile. The block creates no trigger or
recurring schedule, and does not require a password or an elevated principal.
Use the shipped [scripts/windows-launch.ps1](scripts/windows-launch.ps1) instead
of pasting a multiline launch block. From the repository, a single command
creates and runs a uniquely named task, waits for `/json/version`, and prints
the task name and disposable profile for later cleanup:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows-launch.ps1 -Port 9222
```

The `ProfileDir` parameter accepts a **new, nonexistent** disposable directory; `-ChromeExe`
accepts another installed Chrome path. The script rejects existing profiles,
task names and occupied ports. It does not run the Python tool or delete the
task on success. Copy the printed task name/profile: variables and returned
objects do **not** survive between SSH calls.

For a complete create/run/check/delete walkthrough, **save the following block
to a file named `launch.ps1` in the repository root** (or create the file locally
and transfer it with `scp`). Do not pipe or paste the multiline block into
`powershell -Command -` over SSH: that can exit 0 silently without creating a
task. Run the saved file from the repository with:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File launch.ps1
```

Complete contents of `launch.ps1` (this walkthrough closes its own browser and
removes its task/profile after the dry run, including on startup failure):

```powershell
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$chromePort = 9222
$chromeProfile = Join-Path $env:TEMP ("cdpidletabs-profile-" + [guid]::NewGuid())
$taskName = "cdpidletabs-temp-" + [guid]::NewGuid()
if ((Test-Path -LiteralPath $chromeProfile) -or (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue)) { throw 'Choose a new profile and task' }
try {
  $launchOptions = @{ Port = $chromePort; ProfileDir = $chromeProfile; TaskName = $taskName }
  $launch = & .\scripts\windows-launch.ps1 @launchOptions
  $launch.Version
  Get-ScheduledTask -TaskName $taskName | Select-Object TaskName, State
  Invoke-RestMethod "http://127.0.0.1:$chromePort/json/version"
  py -3 close_idle_tabs.py --port $chromePort
  if ($LASTEXITCODE -ne 0) { throw 'Python check failed' }
} finally {
  if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName $taskName
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
  }
  $profileArgument = '--user-data-dir=("?)' + [regex]::Escape($chromeProfile) + '\1(?=\s|$)'
  Get-CimInstance Win32_Process -Filter "name = 'chrome.exe'" |
    Where-Object { $_.CommandLine -and $_.CommandLine -match $profileArgument } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -ErrorAction SilentlyContinue }
  Start-Sleep -Seconds 2
  if (Test-Path -LiteralPath $chromeProfile) { Remove-Item -LiteralPath $chromeProfile -Recurse -Force }
  if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) { throw 'Own task remains' }
  if (Test-Path -LiteralPath $chromeProfile) { throw 'Own profile remains' }
  if (Get-NetTCPConnection -LocalPort $chromePort -State Listen -ErrorAction SilentlyContinue) { throw 'Port still has a listener; investigate without stopping other browsers' }
  'Cleanup verified: own task/profile removed, port has no listener.'
}
```

To clean up a browser launched with the standalone script, save the `finally`
body as `cleanup.ps1`, preceded by `$ErrorActionPreference = 'Stop'` and explicit
assignments to `$taskName`, `$chromeProfile` and `$chromePort` using the printed
values. Run it with `powershell -NoProfile -ExecutionPolicy Bypass -File cleanup.ps1`.
Never stop all Chrome processes. The desktop command above creates no task;
stop only its profile-matched Chrome and remove that disposable profile.

An ordinary Windows SSH shell has no interactive desktop. In verification,
both direct headless launch and `Start-Process` exposed a listener while the
launching SSH session remained open, then lost it after disconnect. Other
remote-shell attempts returned status 0 with no listener: an exit code alone is
not proof of startup. Keeping a TTY SSH session open is not a persistent launch
route. Use the interactive task above for remote-shell use. A logged-out desktop
and a non-interactive task principal are not covered by these instructions.

### Check the dedicated endpoint

In another terminal, confirm that **your newly launched** Chrome responds:

```sh
curl http://127.0.0.1:9222/json/version
python3 close_idle_tabs.py --endpoint http://127.0.0.1:9222
```

For a local browser, `python3 close_idle_tabs.py --port 9222` is shorthand for
that endpoint. `--port` accepts 1–65535 and overrides `CDP_ENDPOINT`; do not
combine it with `--endpoint`. Use `--endpoint` for an explicit HTTP(S) base URL.
The script does not assume port 9222: supply `--port`, `--endpoint`, or
`CDP_ENDPOINT` each run. These options select an existing endpoint; they do not
launch Chrome or reserve a port.

PowerShell equivalent:

```powershell
Invoke-RestMethod http://127.0.0.1:9222/json/version
py -3 close_idle_tabs.py --endpoint http://127.0.0.1:9222
```

The version request must return Chrome's JSON before continuing. If no listener
is available, the script prints **`NOT CHECKED: nothing is listening on port 9222`**
(followed by a skipped-run explanation). Its exit status is still 0 for
scheduled-use compatibility; this is **not a successful endpoint check**. Fix
the launch or port and repeat the version request. DNS/timeout failures also
print `NOT CHECKED`, without claiming that there is no listener.

Or set `CDP_ENDPOINT=http://127.0.0.1:9222` in a POSIX shell with
`export CDP_ENDPOINT=http://127.0.0.1:9222`, or in PowerShell with
`$env:CDP_ENDPOINT = 'http://127.0.0.1:9222'`. Reuse the same working directory
and profile for repeated observations. For a disposable test, stop only the
Chrome instance you launched and remove its profile directory after it exits.

## Example systemd user units

The `examples/` folder contains optional user-unit templates that report only
(dry run, `--quiet`); to close tabs, add `--close` to `ExecStart` after reviewing
the reports. Installation is manual:

1. Create the working directory the service expects: `mkdir -p ~/.local/share/cdpidletabs`.
2. Create `~/.config/cdpidletabs/environment` containing one line,
   `CDP_ENDPOINT=http://127.0.0.1:9222` (replace 9222 with your browser's port).
3. Copy both templates to `~/.config/systemd/user/` as `cdpidletabs.service`
   and `cdpidletabs.timer`, replacing `@VENV_BIN@` in the service with the
   `bin` directory of your virtual environment (for example `<clone-directory>/.venv/bin`).
4. Run `systemctl --user daemon-reload` and `systemctl --user enable --now cdpidletabs.timer`.

The timer runs the service every 60 seconds, starting a minute after it is enabled.

## Example

With `CDP_ENDPOINT` set, this reports candidates for tabs unchanged for ten minutes and exempts the example documentation path:

```sh
python3 close_idle_tabs.py --idle-seconds 600 --keep 'https://example.com/docs/*'
```

The first run records the current tab states. Invoke it repeatedly, at a shorter
interval than the idle threshold, to accumulate unchanged time. It prints target
IDs and their status. After reviewing dry-run output, add `--close` to request
closure of eligible pages. The guard always leaves at least one real page from
the fetched list open, if one exists: it protects the **first real page** in
Chrome's list, usually the most recently activated tab. Internal pages never
satisfy this guard. `about:blank` is protected only when no real page exists;
when there are only internal pages, there is no real page to protect.

`--idle-seconds` accepts integers with a **minimum of 1 second** (default: 600);
0 is rejected before checking for an endpoint. There is **no maximum**: the
threshold is compared with elapsed time since the saved observation, not with
how long this single invocation runs. Above **31536000 seconds (365 days)**, a
one-line notice on stderr (also under `--quiet`) warns that eligibility needs
observations this old in saved state. Reuse the same default state file or
`--state-file` across runs; a fresh state cannot immediately qualify. A very
large threshold may therefore never be reached in practice. Eligible dry-run output such as `idle for 4s (threshold 2s); would close`
describes time already observed, not an additional wait.

If the endpoint is unreachable (connection, DNS or timeout), the run is skipped,
observation state stays unchanged, and it exits 0 with one `NOT CHECKED` notice. Add
`--quiet` for scheduled runs to suppress that notice and normal reports. Invalid
JSON, HTTP rejection, bad arguments and state-file errors remain real errors;
`--quiet` does not hide them. The portable service template uses `--quiet`.

## Honest limitations

CDP does not provide a tab's last-active time here, so the script treats an unchanged title and URL across timer runs as idle. A page can still be in use while unchanged, and list order is only a preference for the guard, not proof that a tab is idle: use `--keep` to protect pages you need. Agent tabs have no owner in this interface, so the script cannot know which agent opened a tab or whether that agent's session is done. Use keep patterns for URLs that should stay open.

The threshold also gives each tab a grace period after the last **observed** title
or URL change: `--idle-seconds 300` waits five minutes after that change. It is not
a last-navigation timestamp. Reloading the same title/URL, background activity,
and navigating away and back between runs can be missed. Time while Chrome is
unreachable still counts since the last observation. Choose a conservative
threshold and keep important pages explicitly.

Ordinary pages keep their idle clock between runs when the same state file is
reused. `--state-file` is optional: by default the script already reuses
`.close_idle_tabs_state.json` in the working directory. A new/missing state file,
a different working directory with no saved state, a changed target ID, or an
observed title/URL change starts a fresh clock. Pages protected by `--keep`, the
real-page guard, or the default internal-page skip restart their clock each run;
after losing that protection they must reach the full threshold again. Dry runs
also save these observations. `--state-file /path/to/state.json` makes reuse
explicit across working directories; it does not measure activity between runs.

No real-browser closure test is part of the automated suite. Before relying on it,
use a disposable Chrome profile with expendable tabs, review dry-run output, then
confirm that only eligible tabs close and a real page stays open.

Internal pages are skipped by default: `chrome://`, `chrome-untrusted://`,
`devtools://`, `chrome-extension://`, and `chrome-search://` (including first-run,
sign-in and new-tab pages). They never count as the real page the guard protects,
even with `--keep`. To consider closing internal/extension pages, explicitly
use `--include-internal`; keep patterns still apply. This opt-in can request
closure of all internal pages when no real or blank page exists. Ordinary web,
file and data pages are real pages. A blank tab is only a fallback when there
are no real pages. Chrome usually lists the most recently activated page first;
the tool uses the first real page in the fetched order without inferring a
last-active timestamp. It protects that page even when other real pages are
kept, still within their grace period, or fail to close.

`--close` prints **"close requested"** when Chrome accepts the HTTP request;
it does not confirm disappearance from `/json/list`. Ordinary pages can close
asynchronously, and internal pages such as "Sign in to Chrome" can remain
listed despite an accepted request. Check the dedicated instance's `/json/list`
afterwards when verifying actual closure. An accepted request removes that
target's saved observation; if it is still listed on the next run, its idle clock
starts again. Failed requests retain their observations. The guard never
requests closure of its chosen page, but only sees the fetched list: it cannot prevent Chrome or
another user closing that page concurrently.
