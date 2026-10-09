# Close idle Chrome tabs

Each run queries a Chrome DevTools Protocol (CDP) endpoint for page tabs and compares each tab's title and URL with the previous run. When that pair has stayed unchanged for the configured threshold, the script reports the tab as idle; with `--close`, it asks Chrome to close it. It runs in dry-run mode by default, keeps one remaining page open, and skips URLs matching `--keep` patterns.

## Setup

Requires Python 3.9 or newer and Chrome with its DevTools Protocol endpoint enabled. Set `CDP_ENDPOINT` in the environment to the browser's HTTP debugging endpoint, or pass it with `--endpoint`. The script uses only Python's standard library and Chrome's existing CDP HTTP endpoints (`/json/list` and `/json/close/{id}`).

Run the script from the same working directory each time so its default `.close_idle_tabs_state.json` observation file is reused (cron and systemd must set the same working directory, or every run starts fresh). The file stores target IDs, SHA-256 digests of title and URL pairs, and timestamps; it does not store page titles or URLs. To check the command from a fresh checkout, run `python3 close_idle_tabs.py --help`; it prints the available options and exits without contacting Chrome.

## Quickstart from a local clone

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install .
cdpidletabs --help
```

On Debian/Ubuntu, `python3 -m venv` may need `apt install python3-venv`.
The help check works without a configured endpoint and makes no browser requests.
Automated tests use mocked HTTP responses and temporary state files:

```sh
python -m unittest discover -s tests -q
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
