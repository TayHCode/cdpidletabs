#!/usr/bin/env python3
"""Report or close unchanged Chrome page targets through the DevTools HTTP API."""

import argparse
import fnmatch
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen


DEFAULT_STATE_FILE = ".close_idle_tabs_state.json"
REQUEST_TIMEOUT_SECONDS = 5
MINIMUM_PYTHON = (3, 8)


class ToolError(Exception):
    pass


class EndpointUnavailable(ToolError):
    """A transport failure is an expected skipped timer run."""


def parse_args():
    parser = argparse.ArgumentParser(
        description="Report or close Chrome page tabs whose title and URL stay unchanged."
    )
    connection = parser.add_mutually_exclusive_group()
    connection.add_argument(
        "--endpoint",
        default=os.environ.get("CDP_ENDPOINT"),
        help="Chrome DevTools HTTP base endpoint (or set CDP_ENDPOINT).",
    )
    connection.add_argument(
        "--port", type=int, metavar="PORT",
        help="use http://127.0.0.1:PORT, overriding CDP_ENDPOINT (choose a free port)",
    )
    parser.add_argument(
        "--idle-seconds",
        type=int,
        default=600,
        help="unchanged time required before a page is eligible (default: 600)",
    )
    parser.add_argument(
        "--keep",
        action="append",
        default=[],
        metavar="URL_GLOB",
        help="URL pattern to keep; may be given more than once",
    )
    parser.add_argument(
        "--state-file",
        default=DEFAULT_STATE_FILE,
        help="file used to remember observations between timer runs",
    )
    parser.add_argument(
        "--close",
        action="store_true",
        help="close eligible pages; without this option, only report them",
    )
    parser.add_argument("--quiet", action="store_true",
                        help="suppress normal reports and unavailable-endpoint notices")
    args = parser.parse_args()

    if args.port is not None:
        if not 1 <= args.port <= 65535:
            parser.error("--port must be between 1 and 65535")
        args.endpoint = "http://127.0.0.1:{}".format(args.port)
    if not args.endpoint:
        parser.error("set CDP_ENDPOINT or pass --endpoint or --port")
    if args.idle_seconds < 1:
        parser.error("--idle-seconds must be a positive integer")
    problem = endpoint_problem(args.endpoint)
    if problem:
        parser.error("--endpoint " + problem)
    return args


def endpoint_problem(endpoint):
    """Name why an endpoint is unusable, or return None."""
    try:
        parts = urlsplit(endpoint)
    except ValueError:
        return "must be a valid HTTP(S) base URL"
    try:
        parts.port  # Validate numeric ports before any request.
    except ValueError:
        try:
            int(parts.netloc.rpartition(":")[2])
        except ValueError:
            return "has a port that is not a number (use 0 to 65535)"
        return "port must be between 0 and 65535"
    if parts.scheme not in ("http", "https"):
        return "must be an HTTP(S) base URL (scheme must be http or https)"
    if not parts.hostname:
        return "must be an HTTP(S) base URL with a host name"
    if parts.username is not None or parts.password is not None:
        return "must not contain credentials"
    if parts.query or parts.fragment:
        return "must not contain a query string or fragment"
    return None


def request_json(endpoint, path):
    request = Request(
        endpoint.rstrip("/") + path,
        headers={"Accept": "application/json"},
    )
    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        raise ToolError("CDP rejected the page-list request") from error
    except (URLError, TimeoutError, OSError) as error:
        raise EndpointUnavailable("CDP endpoint unavailable; skipped this run") from error
    except ValueError as error:
        raise ToolError("CDP returned invalid JSON") from error


def fetch_pages(endpoint):
    result = request_json(endpoint, "/json/list")
    if not isinstance(result, list):
        raise ToolError("CDP returned an invalid page list")
    return [target for target in result if isinstance(target, dict) and target.get("type") == "page"]


def signature_for(target):
    title = target.get("title", "")
    url = target.get("url", "")
    if not isinstance(title, str):
        title = ""
    if not isinstance(url, str):
        url = ""
    payload = (title + "\0" + url).encode("utf-8", errors="replace")
    return hashlib.sha256(payload).hexdigest(), url


def load_state(path):
    try:
        with path.open("r", encoding="utf-8") as state_file:
            state = json.load(state_file)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as error:
        raise ToolError("could not read the state file") from error

    if not isinstance(state, dict) or state.get("version") != 1 or not isinstance(state.get("pages"), dict):
        raise ToolError("state file has an unsupported format")
    return state["pages"]


def save_state(path, pages):
    state = {"version": 1, "pages": pages}
    try:
        path.write_text(json.dumps(state, sort_keys=True) + "\n", encoding="utf-8")
    except OSError as error:
        raise ToolError("could not write the state file") from error


def check_state_writable(path):
    """Fail before any browser action if the state file could not be saved."""
    parent = path.parent
    if not parent.is_dir() or not os.access(parent, os.W_OK | os.X_OK):
        raise ToolError("could not write the state file")
    if path.exists() and (not path.is_file() or not os.access(path, os.W_OK)):
        raise ToolError("could not write the state file")


def is_kept(url, patterns):
    return any(fnmatch.fnmatchcase(url, pattern) for pattern in patterns)


def close_page(endpoint, target_id):
    url = endpoint.rstrip("/") + "/json/close/" + quote(target_id, safe="")
    request = Request(url, method="PUT")
    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            response.read()
    except (HTTPError, URLError, TimeoutError, OSError) as error:
        raise ToolError("CDP rejected a close request") from error


def run(args):
    state_path = Path(args.state_file)
    # Closing tabs must never succeed when the observations cannot be recorded.
    check_state_writable(state_path)
    # A sleeping/offline browser must not read or overwrite observation state.
    page_targets = fetch_pages(args.endpoint)
    old_pages = load_state(state_path)
    now = time.time()
    observations = {}
    candidates = []
    def report(message):
        if not getattr(args, "quiet", False):
            print(message)

    report("Pages found: {}".format(len(page_targets)))
    for target in page_targets:
        target_id = target.get("id")
        if not isinstance(target_id, str) or not target_id:
            continue

        signature, url = signature_for(target)
        previous = old_pages.get(target_id)
        unchanged = (
            isinstance(previous, dict)
            and previous.get("signature") == signature
            and isinstance(previous.get("since"), (int, float))
            and previous["since"] <= now
        )
        if unchanged:
            since = previous["since"]
        else:
            since = now

        kept = is_kept(url, args.keep)
        if kept:
            since = now

        observations[target_id] = {"signature": signature, "since": since}
        elapsed = max(0, int(now - since))
        if kept:
            report("Page {}: kept by URL pattern.".format(target_id))
        elif elapsed >= args.idle_seconds:
            candidates.append((target_id, elapsed))
        elif not unchanged:
            report("Page {}: observed; waiting for another run.".format(target_id))
        else:
            report("Page {}: unchanged for {} seconds; waiting.".format(target_id, elapsed))

    remaining_pages = len(page_targets)
    for target_id, elapsed in candidates:
        if remaining_pages <= 1:
            report("Page {}: kept as the last page.".format(target_id))
            continue
        if args.close:
            try:
                close_page(args.endpoint, target_id)
            except ToolError:
                print("Page {}: close request failed.".format(target_id), file=sys.stderr)
                continue
            observations.pop(target_id, None)
            remaining_pages -= 1
            report("Page {}: close requested after {} unchanged seconds.".format(target_id, elapsed))
        else:
            remaining_pages -= 1
            report("Page {}: would close after {} unchanged seconds.".format(target_id, elapsed))

    save_state(state_path, observations)
    if not args.close:
        report("Dry run; no pages were closed. Pass --close to enable closing.")


def main():
    if sys.version_info[:2] < MINIMUM_PYTHON:
        print("cdpidletabs needs Python 3.8 or newer (found {}.{}).".format(
            sys.version_info[0], sys.version_info[1]), file=sys.stderr)
        return 2
    args = parse_args()
    try:
        run(args)
    except EndpointUnavailable as error:
        if not args.quiet:
            print(str(error) + ".", file=sys.stderr)
        return 0
    except ToolError as error:
        print("Error: {}.".format(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
