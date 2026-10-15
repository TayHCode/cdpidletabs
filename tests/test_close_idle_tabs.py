import argparse
from contextlib import redirect_stdout, redirect_stderr
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from urllib.error import HTTPError, URLError

import close_idle_tabs as tool


class IdleTabsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = Path(self.tmp.name) / "state.json"
        self.args = argparse.Namespace(endpoint="https://browser.example.test", idle_seconds=10,
                                       keep=[], state_file=str(self.state), close=False, quiet=False)
        self.pages = [{"id": "one", "type": "page", "title": "First", "url": "https://example.com/one"},
                      {"id": "two", "type": "page", "title": "Second", "url": "https://example.com/two"}]

    def run_at(self, now, pages=None):
        with patch.object(tool, "fetch_pages", return_value=self.pages if pages is None else pages), patch.object(tool.time, "time", return_value=now), patch.object(tool, "close_page") as close, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            tool.run(self.args)
        return close

    def test_first_observation_never_closes(self):
        self.args.close = True
        close = self.run_at(100)
        close.assert_not_called()

    def test_dry_run_never_sends_close_request(self):
        self.run_at(100)
        close = self.run_at(111)
        close.assert_not_called()
        self.assertEqual(len(tool.load_state(self.state)), 2)

    def test_idle_report_names_elapsed_time_and_threshold(self):
        self.args.idle_seconds = 2
        self.run_at(100)
        with patch.object(tool, "fetch_pages", return_value=self.pages), patch.object(tool.time, "time", return_value=104), patch.object(tool, "close_page") as close, redirect_stdout(io.StringIO()) as out:
            tool.run(self.args)
        close.assert_not_called()
        self.assertIn("idle for 4s (threshold 2s); would close", out.getvalue())
        self.assertNotIn("would close after", out.getvalue())

    def test_close_keeps_last_page_and_removes_closed_state(self):
        self.args.close = True
        self.run_at(100)
        close = self.run_at(111)
        close.assert_called_once_with(self.args.endpoint, "two")
        self.assertEqual(set(tool.load_state(self.state)), {"one"})

    def test_changed_title_or_url_restarts_clock(self):
        self.args.close = True
        self.run_at(100)
        self.pages[0]["title"] = "Changed"
        self.pages[1]["url"] = "https://example.com/new"
        close = self.run_at(111)
        close.assert_not_called()
        self.assertTrue(all(p["since"] == 111 for p in tool.load_state(self.state).values()))

    def test_keep_pattern_exempts_page(self):
        self.args.close = True
        self.args.keep = ["https://example.com/one"]
        self.run_at(100)
        close = self.run_at(111)
        close.assert_called_once_with(self.args.endpoint, "two")
        self.assertEqual(set(tool.load_state(self.state)), {"one"})

    def test_failed_close_does_not_lose_page_state(self):
        self.run_at(100)
        self.args.close = True
        with patch.object(tool, "fetch_pages", return_value=self.pages), patch.object(tool.time, "time", return_value=111), patch.object(tool, "close_page", side_effect=tool.ToolError("fixture failure")), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            tool.run(self.args)
        self.assertEqual(set(tool.load_state(self.state)), {"one", "two"})

    def test_state_has_no_page_titles_or_urls(self):
        self.run_at(100)
        raw = self.state.read_text()
        for page in self.pages:
            self.assertNotIn(page["title"], raw)
            self.assertNotIn(page["url"], raw)

    def test_corrupt_state_fails_instead_of_resetting(self):
        self.state.write_text("not json")
        with self.assertRaises(tool.ToolError):
            tool.load_state(self.state)
        self.state.write_text(json.dumps({"version": 2, "pages": {}}))
        with self.assertRaises(tool.ToolError):
            tool.load_state(self.state)

    def test_fetch_pages_filters_non_page_targets_and_rejects_bad_response(self):
        with patch.object(tool, "request_json", return_value=[*self.pages, {"type": "worker"}, None]):
            self.assertEqual(tool.fetch_pages(self.args.endpoint), self.pages)
        with patch.object(tool, "request_json", return_value={}):
            with self.assertRaises(tool.ToolError):
                tool.fetch_pages(self.args.endpoint)

    def test_close_request_uses_put_and_escapes_id(self):
        response = MagicMock()
        response.__enter__.return_value = response
        with patch.object(tool, "urlopen", return_value=response) as opened:
            tool.close_page(self.args.endpoint, "page/id")
        request = opened.call_args.args[0]
        self.assertEqual(request.get_method(), "PUT")
        self.assertTrue(request.full_url.endswith("/json/close/page%2Fid"))

    def test_help_without_endpoint_does_not_contact_browser(self):
        with patch.dict(os.environ, {}, clear=True), patch("sys.argv", ["cdpidletabs", "--help"]), patch.object(tool, "urlopen") as opened, redirect_stdout(io.StringIO()) as out:
            with self.assertRaises(SystemExit) as caught:
                tool.parse_args()
        self.assertEqual(caught.exception.code, 0)
        self.assertIn("minimum: 1", out.getvalue())
        opened.assert_not_called()

    def test_idle_seconds_minimum_is_one(self):
        for value in ("0", "-1"):
            with patch("sys.argv", ["cdpidletabs", "--port", "9450", "--idle-seconds", value]), patch.object(tool, "urlopen") as opened, redirect_stderr(io.StringIO()) as err:
                with self.assertRaises(SystemExit) as caught:
                    tool.parse_args()
            self.assertEqual(caught.exception.code, 2)
            self.assertIn("--idle-seconds must be at least 1", err.getvalue())
            opened.assert_not_called()
        with patch("sys.argv", ["cdpidletabs", "--port", "9450", "--idle-seconds", "1"]):
            self.assertEqual(tool.parse_args().idle_seconds, 1)

    def test_invalid_idle_seconds_without_endpoint_is_reported_first(self):
        for value in ("0", "-5"):
            with patch.dict(os.environ, {}, clear=True), patch("sys.argv", ["cdpidletabs", "--idle-seconds", value]), patch.object(tool, "run") as run, redirect_stderr(io.StringIO()) as err:
                with self.assertRaises(SystemExit) as caught:
                    tool.main()
            self.assertEqual(caught.exception.code, 2)
            self.assertIn("--idle-seconds must be at least 1", err.getvalue())
            run.assert_not_called()

    def test_large_idle_threshold_notice_including_quiet_mode(self):
        for quiet in (False, True):
            options = ["--quiet"] if quiet else []
            with patch("sys.argv", ["cdpidletabs", "--port", "9490", "--idle-seconds", "99999999999", *options]), patch.object(tool, "run") as run, redirect_stderr(io.StringIO()) as err:
                self.assertEqual(tool.main(), 0)
            self.assertEqual(run.call_args.args[0].idle_seconds, 99999999999)
            self.assertIn("Reuse --state-file across runs", err.getvalue())
            self.assertEqual(len(err.getvalue().splitlines()), 1)

    def test_long_idle_notice_boundary(self):
        for value, notice in ((31536000, False), (31536001, True)):
            with patch("sys.argv", ["cdpidletabs", "--port", "9490", "--idle-seconds", str(value)]), patch.object(tool, "run"), redirect_stderr(io.StringIO()) as err:
                self.assertEqual(tool.main(), 0)
            self.assertEqual("Notice:" in err.getvalue(), notice)

    def test_large_threshold_can_become_eligible_from_saved_observations(self):
        self.args.idle_seconds = 99999999999
        self.args.close = True
        self.run_at(100)
        close = self.run_at(100 + self.args.idle_seconds)
        close.assert_called_once_with(self.args.endpoint, "two")

    def test_old_python_gets_friendly_error_before_arguments_or_network(self):
        with patch.object(tool.sys, "version_info", (3, 7, 17)), patch.object(tool, "parse_args") as parse, patch.object(tool, "urlopen") as opened, redirect_stderr(io.StringIO()) as err:
            self.assertEqual(tool.main(), 2)
        self.assertIn("needs Python 3.8 or newer (found 3.7)", err.getvalue())
        self.assertNotIn("Traceback", err.getvalue())
        parse.assert_not_called()
        opened.assert_not_called()

    def test_minimum_python_and_mac_system_python_can_print_help(self):
        for version in ((3, 8, 20), (3, 9, 6)):
            with patch.object(tool.sys, "version_info", version), patch("sys.argv", ["cdpidletabs", "--help"]), patch.object(tool, "urlopen") as opened, redirect_stdout(io.StringIO()) as out:
                with self.assertRaises(SystemExit) as caught:
                    tool.main()
            self.assertEqual(caught.exception.code, 0)
            self.assertIn("--endpoint", out.getvalue())
            opened.assert_not_called()

    def test_endpoint_validation_rejects_credentials_and_queries(self):
        for value in ("https://" + "user:" + "pass@" + "browser.example.test", "https://browser.example.test/?a=b", "file:///data"):
            with patch("sys.argv", ["cdpidletabs", "--endpoint", value]), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    tool.parse_args()

    def test_endpoint_errors_name_the_real_cause(self):
        cases = (("http://127.0.0.1:99999", "port"),
                 ("http://127.0.0.1:9222/?a=b", "query string"),
                 ("http://127.0.0.1:9222/#x", "query string or fragment"),
                 ("http://" + "user:" + "pass@127.0.0.1:9222", "credentials"),
                 ("ftp://127.0.0.1:9222", "scheme"),
                 ("http://", "host name"))
        for value, expected in cases:
            with patch("sys.argv", ["cdpidletabs", "--endpoint", value]), redirect_stderr(io.StringIO()) as err:
                with self.assertRaises(SystemExit) as caught:
                    tool.parse_args()
            self.assertEqual(caught.exception.code, 2)
            self.assertIn(expected, err.getvalue())
            self.assertNotIn("user:" + "pass", err.getvalue())

    def test_missing_state_directory_fails_before_observing_or_closing(self):
        self.args.close = True
        self.args.state_file = str(Path(self.tmp.name) / "missing" / "state.json")
        try:
            Path(self.args.state_file).parent.stat()
        except OSError as error:
            expected_reason = error.strerror
        out, err = io.StringIO(), io.StringIO()
        with patch.object(tool, "fetch_pages") as fetch, patch.object(tool, "close_page") as close, patch("sys.argv", ["cdpidletabs", "--endpoint", self.args.endpoint, "--close", "--state-file", self.args.state_file]), redirect_stdout(out), redirect_stderr(err):
            code = tool.main()
        self.assertEqual(code, 1)
        fetch.assert_not_called()
        close.assert_not_called()
        self.assertEqual(out.getvalue(), "")
        self.assertIn("could not write the state file", err.getvalue())
        self.assertIn(self.args.state_file, err.getvalue())
        self.assertIn(expected_reason, err.getvalue())

    def test_state_preflight_names_path_and_reason_without_touching_browser(self):
        blocker = Path(self.tmp.name) / "ordinary-file"
        blocker.write_text("preserve me")
        for path, reason in ((blocker / "state.json", os.strerror(tool.errno.ENOTDIR)),
                             (Path(self.tmp.name), os.strerror(tool.errno.EISDIR))):
            self.args.state_file = str(path)
            with patch.object(tool, "fetch_pages") as fetch, patch.object(tool, "close_page") as close:
                with self.assertRaises(tool.ToolError) as caught:
                    tool.run(self.args)
            self.assertIn(str(path), str(caught.exception))
            self.assertIn(reason, str(caught.exception))
            fetch.assert_not_called()
            close.assert_not_called()
        self.assertEqual(blocker.read_text(), "preserve me")
        with patch.object(tool.os, "access", return_value=False):
            with self.assertRaises(tool.ToolError) as caught:
                tool.check_state_writable(self.state)
        self.assertIn(str(self.state), str(caught.exception))
        self.assertIn(os.strerror(tool.errno.EACCES), str(caught.exception))

    def test_future_state_timestamp_does_not_close(self):
        self.run_at(200)
        self.args.close = True
        self.run_at(100).assert_not_called()


    def test_bad_port_is_a_clean_input_error_without_network(self):
        with patch('sys.argv',['cdpidletabs','--endpoint','http://localhost:abc']), patch.object(tool,'fetch_pages') as fetch, redirect_stderr(io.StringIO()) as err:
            with self.assertRaises(SystemExit) as result:tool.parse_args()
        self.assertEqual(result.exception.code,2)
        fetch.assert_not_called()
        self.assertIn('port that is not a number',err.getvalue())

    def test_out_of_range_port_names_range_without_calling_it_nonnumeric(self):
        for value in ("99999", "-1"):
            with patch("sys.argv", ["cdpidletabs", "--endpoint", "http://127.0.0.1:" + value]), patch.object(tool, "urlopen") as opened, redirect_stderr(io.StringIO()) as err:
                with self.assertRaises(SystemExit) as caught:
                    tool.parse_args()
            self.assertEqual(caught.exception.code, 2)
            self.assertIn("port must be between 0 and 65535", err.getvalue())
            self.assertNotIn("not a number", err.getvalue())
            opened.assert_not_called()

    def test_port_selects_loopback_and_overrides_environment_without_requests(self):
        for port in (1, 9446, 65535):
            with patch.dict(os.environ, {"CDP_ENDPOINT": "https://browser.example.test"}), patch("sys.argv", ["cdpidletabs", "--port", str(port)]), patch.object(tool, "urlopen") as opened:
                args = tool.parse_args()
            self.assertEqual(args.endpoint, "http://127.0.0.1:" + str(port))
            self.assertFalse(args.close)
            opened.assert_not_called()

    def test_port_rejects_bad_values_and_explicit_endpoint_conflicts(self):
        for options in (["--port", "0"], ["--port", "65536"], ["--port", "-1"], ["--port", "bad"], ["--port", "9446", "--endpoint", self.args.endpoint]):
            with patch("sys.argv", ["cdpidletabs", *options]), patch.object(tool, "urlopen") as opened, redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as caught:
                    tool.parse_args()
            self.assertEqual(caught.exception.code, 2)
            opened.assert_not_called()

    def test_internal_page_acknowledged_close_is_reported_only_as_requested(self):
        intro = {"id": "intro", "type": "page", "title": "Sign in to Chrome", "url": "chrome://intro/"}
        pages = [intro, self.pages[1]]
        self.args.close = True
        self.args.include_internal = True
        self.run_at(100, pages)
        out = io.StringIO()
        # Chrome acknowledges the request, but continues listing its intro page.
        with patch.object(tool, "fetch_pages", return_value=pages), patch.object(tool.time, "time", return_value=111), patch.object(tool, "close_page") as close, redirect_stdout(out):
            tool.run(self.args)
        close.assert_called_once_with(self.args.endpoint, "intro")
        self.assertIn("idle for 11s (threshold 10s); close requested", out.getvalue())
        self.assertNotIn(": closed", out.getvalue())
        self.assertNotIn("intro", tool.load_state(self.state))

        self.run_at(112, pages).assert_not_called()
        self.assertEqual(tool.load_state(self.state)["intro"]["since"], 112)

    def test_internal_page_keep_pattern_prevents_a_close_request(self):
        intro = {"id": "intro", "type": "page", "title": "Sign in to Chrome", "url": "chrome://intro/"}
        self.args.keep = ["chrome://*"]
        self.args.close = True
        self.run_at(100, [intro, self.pages[1]])
        close = self.run_at(111, [intro, self.pages[1]])
        close.assert_not_called()
        self.assertEqual(set(tool.load_state(self.state)), {"intro", "two"})

    def test_timer_starts_without_a_prior_service_activation(self):
        import configparser
        config=configparser.ConfigParser();config.read(Path(__file__).parents[1]/'examples/cdpidletabs.timer.in')
        self.assertTrue(any(config.has_option('Timer',key) for key in ['OnActiveSec','OnBootSec','OnStartupSec']))
        self.assertTrue(config.has_option('Timer','OnUnitActiveSec'))

    def test_unreachable_endpoint_exits_zero_and_preserves_state(self):
        self.run_at(100)
        before = self.state.read_bytes()
        for quiet in (False, True):
            self.args.quiet = quiet
            with patch.object(tool, 'parse_args', return_value=self.args), patch.object(tool, 'urlopen', side_effect=URLError('fixture offline')), redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()) as err:
                self.assertEqual(tool.main(), 0)
            self.assertEqual(out.getvalue(), '')
            self.assertEqual(len(err.getvalue().splitlines()), 0 if quiet else 1)
            self.assertEqual(self.state.read_bytes(), before)

    def test_timeout_is_skipped_without_creating_state(self):
        with patch.object(tool, 'parse_args', return_value=self.args), patch.object(tool, 'urlopen', side_effect=TimeoutError()), redirect_stderr(io.StringIO()):
            self.assertEqual(tool.main(), 0)
        self.assertFalse(self.state.exists())

    def test_refused_endpoint_is_clearly_not_checked_and_names_port(self):
        self.args.endpoint = "http://127.0.0.1:9450"
        self.run_at(100)
        before = self.state.read_bytes()
        for quiet in (False, True):
            self.args.quiet = quiet
            refused = URLError(ConnectionRefusedError(tool.errno.ECONNREFUSED, "fixture refused"))
            with patch.object(tool, "parse_args", return_value=self.args), patch.object(tool, "urlopen", side_effect=refused), redirect_stderr(io.StringIO()) as err:
                self.assertEqual(tool.main(), 0)
            if quiet:
                self.assertEqual(err.getvalue(), "")
            else:
                self.assertIn("NOT CHECKED: nothing is listening on port 9450", err.getvalue())
            self.assertEqual(self.state.read_bytes(), before)

    def test_timeout_does_not_claim_no_listener(self):
        with patch.object(tool, "parse_args", return_value=self.args), patch.object(tool, "urlopen", side_effect=TimeoutError()), redirect_stderr(io.StringIO()) as err:
            self.assertEqual(tool.main(), 0)
        self.assertIn("NOT CHECKED: CDP endpoint unavailable", err.getvalue())
        self.assertNotIn("nothing is listening", err.getvalue())

    def test_bad_json_and_http_rejection_remain_errors_in_quiet_mode(self):
        self.args.quiet = True
        response = MagicMock(); response.__enter__.return_value = response
        response.read.return_value = b'not json'
        for result in (response, HTTPError('https://browser.example.test', 403, 'denied', {}, None)):
            with patch.object(tool, 'parse_args', return_value=self.args), patch.object(tool, 'urlopen', **({'side_effect': result} if isinstance(result, Exception) else {'return_value': result})), redirect_stderr(io.StringIO()) as err:
                self.assertEqual(tool.main(), 1)
            self.assertIn('Error:', err.getvalue())

    def test_quiet_suppresses_dry_run_reports_without_closing(self):
        self.run_at(100); self.args.quiet = True
        with patch.object(tool, 'fetch_pages', return_value=self.pages), patch.object(tool.time, 'time', return_value=111), patch.object(tool, 'close_page') as close, redirect_stdout(io.StringIO()) as out:
            tool.run(self.args)
        close.assert_not_called(); self.assertEqual(out.getvalue(), '')

    def test_removed_targets_are_pruned_from_state(self):
        self.run_at(100); self.run_at(111, [self.pages[1]])
        self.assertEqual(set(tool.load_state(self.state)), {'two'})

    def test_missing_state_is_empty_and_write_failure_is_reported(self):
        self.assertEqual(tool.load_state(self.state), {})
        with patch.object(Path, 'write_text', side_effect=OSError('fixture denied')):
            with self.assertRaises(tool.ToolError) as caught:tool.save_state(self.state, {})
        self.assertIn(str(self.state), str(caught.exception))
        self.assertIn('fixture denied', str(caught.exception))

    def test_state_read_failure_names_path_and_os_reason(self):
        with patch.object(Path, "open", side_effect=PermissionError(tool.errno.EACCES, os.strerror(tool.errno.EACCES))):
            with self.assertRaises(tool.ToolError) as caught:
                tool.load_state(self.state)
        self.assertIn(str(self.state), str(caught.exception))
        self.assertIn(os.strerror(tool.errno.EACCES), str(caught.exception))

    def test_keep_glob_resets_idle_clock_until_removed(self):
        self.args.keep = ['https://example.com/*']; self.args.close = True
        self.run_at(100); self.run_at(150).assert_not_called()
        self.args.keep = []; self.run_at(151).assert_not_called()
        self.run_at(161).assert_called_once_with(self.args.endpoint, 'two')

    def test_cli_dry_run_and_quiet_defaults(self):
        with patch('sys.argv', ['cdpidletabs', '--endpoint', 'https://browser.example.test']):
            args=tool.parse_args()
        self.assertFalse(args.close); self.assertFalse(args.quiet)

    def test_fake_cdp_user_and_internal_both_orders_keep_the_user(self):
        user = self.pages[0]
        for url in ("chrome://intro/", "chrome://newtab/", "chrome-untrusted://new-tab-page/",
                    "devtools://devtools/bundled/inspector.html", "chrome-extension://abc/page.html",
                    "chrome-search://local-ntp/local-ntp.html"):
            internal = dict(id="internal", type="page", title="Internal", url=url)
            for pages in ([user, internal], [internal, user]):
                for include_internal in (False, True):
                    for close_mode in (False, True):
                        with self.subTest(url=url, first=pages[0]["id"],
                                          include_internal=include_internal, close=close_mode):
                            self.state.unlink(missing_ok=True)
                            self.args.close = close_mode
                            self.args.include_internal = include_internal
                            with patch.object(tool, "request_json", return_value=pages) as request, \
                                    patch.object(tool.time, "time", return_value=100), \
                                    redirect_stdout(io.StringIO()):
                                tool.run(self.args)
                            request.assert_called_once_with(self.args.endpoint, "/json/list")
                            with patch.object(tool, "request_json", return_value=pages), \
                                    patch.object(tool.time, "time", return_value=111), \
                                    patch.object(tool, "close_page") as close, \
                                    redirect_stdout(io.StringIO()) as out:
                                tool.run(self.args)
                            if include_internal and close_mode:
                                close.assert_called_once_with(self.args.endpoint, "internal")
                            else:
                                close.assert_not_called()
                            self.assertIn("one", tool.load_state(self.state))
                            self.assertNotIn("Page one: idle", out.getvalue())
                            self.assertEqual(tool.load_state(self.state)["one"]["since"], 111)

    def test_first_real_page_is_protected_after_list_order_changes(self):
        self.args.close = True
        self.run_at(100)
        # Activating the second tab moves it first in Chrome's list.
        close = self.run_at(111, list(reversed(self.pages)))
        close.assert_called_once_with(self.args.endpoint, "one")
        self.assertEqual(set(tool.load_state(self.state)), {"two"})
        self.assertEqual(tool.load_state(self.state)["two"]["since"], 111)

    def test_guarded_page_gets_full_grace_period_when_it_loses_guard(self):
        self.args.close = True
        self.run_at(100)
        self.run_at(150, [self.pages[0]])
        self.run_at(151, list(reversed(self.pages))).assert_not_called()
        self.run_at(161, list(reversed(self.pages))).assert_called_once_with(self.args.endpoint, "one")

    def test_blank_is_fallback_only_without_real_pages(self):
        blank = dict(id="blank", type="page", title="", url="about:blank")
        internal = dict(id="internal", type="page", title="NTP", url="chrome://newtab/")
        for pages in ([blank, self.pages[0]], [self.pages[0], blank]):
            self.assertEqual(tool.protected_page(pages), "one")
        self.assertEqual(tool.protected_page([internal, blank]), "blank")
        self.assertIsNone(tool.protected_page([internal]))
        self.args.close = True
        self.run_at(100, [blank, self.pages[0]])
        self.run_at(111, [blank, self.pages[0]]).assert_called_once_with(self.args.endpoint, "blank")

    def test_only_blank_pages_leave_first_blank_open(self):
        pages = [dict(id=name, type="page", title="", url="about:blank") for name in ("a", "b")]
        self.args.close = True
        self.run_at(100, pages)
        self.run_at(111, pages).assert_called_once_with(self.args.endpoint, "b")
        self.assertEqual(set(tool.load_state(self.state)), {"a"})

    def test_internal_only_pages_are_skipped_unless_opted_in(self):
        pages = [dict(id="internal", type="page", title="Intro", url="chrome://intro/")]
        self.args.close = True
        self.run_at(100, pages)
        self.run_at(111, pages).assert_not_called()
        self.args.include_internal = True
        self.run_at(112, pages).assert_not_called()
        self.run_at(122, pages).assert_called_once_with(self.args.endpoint, "internal")

    def test_invalid_id_and_empty_url_never_displace_real_guard(self):
        invalid = [dict(type="page", url="https://example.com/"),
                   dict(id="", type="page", url="https://example.com/"),
                   dict(id="empty", type="page", url=None)]
        self.assertEqual(tool.protected_page(invalid + self.pages), "one")

    def test_internal_keep_does_not_allow_all_real_pages_to_close(self):
        internal = dict(id="internal", type="page", title="Intro", url="chrome://intro/")
        self.args.close = True
        self.args.keep = ["chrome://*"]
        pages = [internal] + self.pages
        self.run_at(100, pages)
        self.run_at(111, pages).assert_called_once_with(self.args.endpoint, "two")
        self.assertEqual(set(tool.load_state(self.state)), {"internal", "one"})

    def test_ordinary_page_clock_persists_with_reused_default_state_file(self):
        with patch.object(tool, "DEFAULT_STATE_FILE", str(self.state)), \
                patch("sys.argv", ["cdpidletabs", "--port", "9460"]):
            self.args = tool.parse_args()
        self.run_at(100)
        self.run_at(150)
        self.assertEqual(tool.load_state(self.state)["two"]["since"], 100)
        self.state.unlink()
        self.run_at(151)
        self.assertEqual(tool.load_state(self.state)["two"]["since"], 151)

    def test_cli_internal_opt_in_defaults_off(self):
        for options, expected in (([], False), (["--include-internal"], True)):
            with patch("sys.argv", ["cdpidletabs", "--port", "9460"] + options):
                self.assertEqual(tool.parse_args().include_internal, expected)


if __name__ == "__main__":
    unittest.main()
