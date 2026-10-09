# Close idle Chrome tabs

Each run queries a Chrome DevTools Protocol (CDP) endpoint for page tabs and compares each tab's title and URL with the previous run. When that pair has stayed unchanged for the configured threshold, the script reports the tab as idle; with `--close`, it asks Chrome to close it. It runs in dry-run mode by default, keeps one remaining page open, and skips URLs matching `--keep` patterns.

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

If you want a `cdpidletabs` command, use a virtual environment. On Debian/Ubuntu,
if venv fails because `ensurepip` is missing, first install `python3-venv` with
your package manager (for example `sudo apt install python3-venv`, requiring
administrator access), or continue with the direct script above.

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

```sh
google-chrome --remote-debugging-port=9222 --remote-debugging-address=127.0.0.1 \
  --user-data-dir="$HOME/.config/chrome-debug"
```

Use a dedicated, non-default `--user-data-dir`: Chrome 136 and later ignore the
remote debugging flags on the default profile directory. Keep the address on
loopback (`127.0.0.1`). Then use `CDP_ENDPOINT=http://127.0.0.1:9222`.

## Example systemd user units

The `examples/` folder contains optional user-unit templates that report only
(dry run, `--quiet`); to close tabs, add `--close` to `ExecStart` after reviewing
the reports. Installation is manual:

1. Create the working directory the service expects: `mkdir -p ~/.local/share/cdpidletabs`.
2. Create `~/.config/cdpidletabs/environment` containing one line,
   `CDP_ENDPOINT=http://127.0.0.1:9222`.
3. Copy both templates to `~/.config/systemd/user/` as `cdpidletabs.service`
   and `cdpidletabs.timer`, replacing `@VENV_BIN@` in the service with the
   `bin` directory of your virtual environment (for example `/home/you/cdpidletabs/.venv/bin`).
4. Run `systemctl --user daemon-reload` and `systemctl --user enable --now cdpidletabs.timer`.

The timer runs the service every 60 seconds, starting a minute after it is enabled.

## Example

With `CDP_ENDPOINT` set, this reports candidates for tabs unchanged for ten minutes and exempts the example documentation path:

```sh
python3 close_idle_tabs.py --idle-seconds 600 --keep 'https://example.com/docs/*'
```

The first run records the current tab states. Invoke it repeatedly from a timer, at a shorter interval than the idle threshold, to accumulate unchanged time. It prints target IDs and their status. After reviewing dry-run output, add `--close` to let Chrome close eligible pages. The last remaining page is always kept.

If the endpoint is unreachable (connection, DNS or timeout), the run is skipped,
observation state stays unchanged, and it exits 0 with one short notice. Add
`--quiet` for scheduled runs to suppress that notice and normal reports. Invalid
JSON, HTTP rejection, bad arguments and state-file errors remain real errors;
`--quiet` does not hide them. The portable service template uses `--quiet`.

## Honest limitations

CDP does not provide a tab's last-active time here, so the script treats an unchanged title and URL across timer runs as idle. A page can still be in use while unchanged, and the tab you are looking at (the active tab) is not exempt: use `--keep` to protect pages you need. Agent tabs have no owner in this interface, so the script cannot know which agent opened a tab or whether that agent's session is done. Use keep patterns for URLs that should stay open.

The threshold also gives each tab a grace period after the last **observed** title
or URL change: `--idle-seconds 300` waits five minutes after that change. It is not
a last-navigation timestamp. Reloading the same title/URL, background activity,
and navigating away and back between runs can be missed. Time while Chrome is
unreachable still counts since the last observation. Choose a conservative
threshold and keep important pages explicitly.

No real-browser closure test is part of the automated suite. Before relying on it,
use a disposable Chrome profile with expendable tabs, review dry-run output, then
confirm that only eligible tabs close and the last page stays open.
