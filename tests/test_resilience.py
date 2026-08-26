"""Tests for the difference between "no" and "could not tell".

A curated list that removes an entry when a coverage service returns 429 is
worse than one that never rechecks at all, because the damage is silent and
permanent. Everything here guards that boundary.
"""

import io
import json
import unittest
import urllib.error

from _support import verify_repo as vr


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return json.dumps(self.payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def http_error(code, headers=None):
    return urllib.error.HTTPError(
        "https://example.invalid", code, "boom", headers or {}, None
    )


class Retrying(unittest.TestCase):
    def client(self, responses, attempts=4):
        api = vr.GitHubAPI(token="t", retries=attempts)
        self.calls = []

        def fake_urlopen(req, timeout=None):
            self.calls.append(req.full_url)
            outcome = responses.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return FakeResponse(outcome)

        self._patch(vr.urllib.request, "urlopen", fake_urlopen)
        self._patch(vr.time, "sleep", lambda _s: None)
        # The retry notices are for a human watching a run, not for test output.
        self._patch(vr.sys, "stderr", io.StringIO())
        return api

    def _patch(self, obj, name, value):
        original = getattr(obj, name)
        setattr(obj, name, value)
        self.addCleanup(setattr, obj, name, original)

    def test_a_transient_error_is_retried_and_then_succeeds(self):
        api = self.client([http_error(502), {"ok": True}])
        self.assertEqual(api.get("https://example.invalid/x"), {"ok": True})
        self.assertEqual(len(self.calls), 2)

    def test_a_persistent_rate_limit_raises_rather_than_returning_none(self):
        api = self.client([http_error(429)] * 4)
        with self.assertRaises(vr.VerificationIncomplete):
            api.get("https://example.invalid/x")

    def test_a_missing_resource_is_an_answer_not_a_failure(self):
        api = self.client([http_error(404)])
        self.assertIsNone(api.get("https://example.invalid/x"))
        self.assertEqual(len(self.calls), 1)

    def test_a_rejected_query_is_an_answer_not_a_failure(self):
        api = self.client([http_error(422)])
        self.assertIsNone(api.get("https://example.invalid/x"))

    def test_a_network_error_raises_rather_than_reading_as_absent(self):
        api = self.client([urllib.error.URLError("down")] * 4)
        with self.assertRaises(vr.VerificationIncomplete):
            api.get_text("https://example.invalid/x")

    def test_retry_after_is_obeyed(self):
        api = vr.GitHubAPI(token="t")
        wait = api._sleep_for(http_error(429, {"Retry-After": "37"}), 1)
        self.assertEqual(wait, 37)

    def test_an_absurd_retry_after_is_capped(self):
        api = vr.GitHubAPI(token="t")
        self.assertLessEqual(api._sleep_for(http_error(429, {"Retry-After": "99999"}), 1), 120)

    def test_backoff_grows_when_the_server_says_nothing(self):
        api = vr.GitHubAPI(token="t")
        waits = [api._sleep_for(http_error(503), n) for n in (1, 2, 3)]
        self.assertEqual(waits, sorted(waits))
        self.assertLess(waits[0], waits[-1])

    def test_nothing_calls_sys_exit(self):
        # The 403 handler used to exit the process from four levels down, which
        # took the whole weekly run with it.
        from pathlib import Path

        source = Path(vr.__file__).read_text()
        api_class = source[source.index("class GitHubAPI"):source.index("def parse_repo_arg")]
        self.assertNotIn("sys.exit", api_class)


class CoverageServiceStatuses(Retrying):
    """A coverage service says 403 for a repository it does not track."""

    def test_a_forbidden_response_from_a_coverage_service_is_an_answer(self):
        # Retrying it as a rate limit and then giving up would mean an entry
        # never gets rechecked again.
        api = self.client([http_error(403)])
        self.assertIsNone(api.get_public_json("https://api.codecov.io/x"))
        self.assertEqual(len(self.calls), 1)

    def test_an_unauthorised_response_is_also_an_answer(self):
        api = self.client([http_error(401)])
        self.assertIsNone(api.get_public_json("https://coveralls.io/x"))

    def test_the_github_client_still_treats_403_as_a_rate_limit(self):
        api = self.client([http_error(403)] * 4)
        with self.assertRaises(vr.VerificationIncomplete):
            api.get("https://api.github.com/x")

    def test_a_service_outage_still_propagates(self):
        api = self.client([http_error(503)] * 4)
        with self.assertRaises(vr.VerificationIncomplete):
            api.get_public_json("https://api.codecov.io/x")


class TreeLookups(unittest.TestCase):
    def test_a_truncated_tree_falls_back_rather_than_lying(self):
        api = vr.GitHubAPI(token="t")
        api.get = lambda url: {"truncated": True, "tree": []}
        self.assertIsNone(vr.fetch_tree(api, "a", "b", "main"))

    def test_only_files_are_returned(self):
        api = vr.GitHubAPI(token="t")
        api.get = lambda url: {
            "truncated": False,
            "tree": [
                {"path": "pom.xml", "type": "blob"},
                {"path": "src", "type": "tree"},
            ],
        }
        self.assertEqual(vr.fetch_tree(api, "a", "b", "main"), {"pom.xml"})

    def test_a_known_absent_file_costs_no_request(self):
        api = vr.GitHubAPI(token="t")
        api.get_text = lambda url: self.fail("should not have been fetched")
        found = vr.check_tools(
            api, "a", "b", "main",
            {"jacoco": {"files": ["pom.xml"], "patterns": ["jacoco"], "language": "Java"}},
            workflow_contents={},
            tree=set(),
        )
        self.assertEqual(found, {})


if __name__ == "__main__":
    unittest.main()
