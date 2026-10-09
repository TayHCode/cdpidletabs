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

    def test_close_keeps_last_page_and_removes_closed_state(self):
        self.args.close = True
        self.run_at(100)
        close = self.run_at(111)
        close.assert_called_once_with(self.args.endpoint, "one")
        self.assertEqual(set(tool.load_state(self.state)), {"two"})

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
        with patch.dict(os.environ, {}, clear=True), patch("sys.argv", ["cdpidletabs", "--help"]), patch.object(tool, "urlopen") as opened, redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                tool.parse_args()
        self.assertEqual(caught.exception.code, 0)
        opened.assert_not_called()

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
        out, err = io.StringIO(), io.StringIO()
        with patch.object(tool, "fetch_pages") as fetch, patch.object(tool, "close_page") as close, patch("sys.argv", ["cdpidletabs", "--endpoint", self.args.endpoint, "--close", "--state-file", self.args.state_file]), redirect_stdout(out), redirect_stderr(err):
            code = tool.main()
        self.assertEqual(code, 1)
        fetch.assert_not_called()
        close.assert_not_called()
        self.assertEqual(out.getvalue(), "")
        self.assertIn("could not write the state file", err.getvalue())

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
            with self.assertRaises(tool.ToolError):tool.save_state(self.state, {})

    def test_keep_glob_resets_idle_clock_until_removed(self):
        self.args.keep = ['https://example.com/*']; self.args.close = True
        self.run_at(100); self.run_at(150).assert_not_called()
        self.args.keep = []; self.run_at(151).assert_not_called()
        self.run_at(161).assert_called_once_with(self.args.endpoint, 'one')

    def test_cli_dry_run_and_quiet_defaults(self):
        with patch('sys.argv', ['cdpidletabs', '--endpoint', 'https://browser.example.test']):
            args=tool.parse_args()
        self.assertFalse(args.close); self.assertFalse(args.quiet)


if __name__ == "__main__":
    unittest.main()
