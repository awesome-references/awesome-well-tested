"""Tests for candidate discovery.

Code search is the least forgiving endpoint GitHub offers, and the module had a
history of reporting its own failures as empty results.
"""

import io
import json
import unittest
import urllib.error

from _support import discover_candidates as dc


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
    return urllib.error.HTTPError("https://api.invalid", code, "boom", headers or {}, None)


class Patched(unittest.TestCase):
    def patch(self, obj, name, value):
        original = getattr(obj, name)
        setattr(obj, name, value)
        self.addCleanup(setattr, obj, name, original)

    def responses(self, outcomes):
        self.calls = []

        def fake_urlopen(req, timeout=None):
            self.calls.append(req.full_url)
            outcome = outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return FakeResponse(outcome)

        self.patch(dc.urllib.request, "urlopen", fake_urlopen)
        self.patch(dc.time, "sleep", lambda _s: None)
        self.patch(dc.sys, "stderr", io.StringIO())


class Searching(Patched):
    def test_a_result_set_is_deduplicated_by_repository(self):
        self.responses([{
            "items": [
                {"repository": {"full_name": "a/b"}, "path": "pom.xml"},
                {"repository": {"full_name": "a/b"}, "path": "sub/pom.xml"},
                {"repository": {"full_name": "c/d"}, "path": "pom.xml"},
            ]
        }])
        repos = dc.search_code("t", "pitest filename:pom.xml")
        self.assertEqual([r["full_name"] for r in repos], ["a/b", "c/d"])

    def test_no_query_carries_a_language_qualifier(self):
        # The qualifier matches the language of the file, and every query here
        # pins a build file. Adding it returns nothing at all.
        for key, queries in dc.SEARCH_QUERIES.items():
            for query, _ in queries:
                self.assertNotIn("language:", query, f"{key}: {query}")

    def test_no_query_uses_a_wildcard_filename(self):
        for key, queries in dc.SEARCH_QUERIES.items():
            for query, _ in queries:
                if "filename:" in query:
                    name = query.split("filename:", 1)[1].split(" ", 1)[0]
                    self.assertNotIn("*", name, f"{key}: {query}")

    def test_a_rejected_query_is_skipped_rather_than_retried(self):
        self.responses([http_error(422)])
        self.assertEqual(dc.search_code("t", "nonsense"), [])
        self.assertEqual(len(self.calls), 1)

    def test_a_secondary_rate_limit_is_retried(self):
        self.responses([http_error(429), {"items": [{"repository": {"full_name": "a/b"}, "path": "p"}]}])
        self.assertEqual(len(dc.search_code("t", "q")), 1)
        self.assertEqual(len(self.calls), 2)

    def test_a_persistent_rate_limit_gives_up_without_a_traceback(self):
        self.responses([http_error(403)] * dc.MAX_RETRIES)
        self.assertEqual(dc.search_code("t", "q"), [])

    def test_retry_after_is_preferred_over_backoff(self):
        waits = []
        self.responses([http_error(429, {"Retry-After": "11"}), {"items": []}])
        self.patch(dc.time, "sleep", lambda s: waits.append(s))
        dc.search_code("t", "q")
        self.assertIn(11, waits)


class Stars(Patched):
    def test_a_star_count_is_returned(self):
        self.responses([{"stargazers_count": 512}])
        self.assertEqual(dc.get_repo_stars("t", "a/b"), 512)

    def test_a_missing_repository_is_none(self):
        self.responses([http_error(404)])
        self.assertIsNone(dc.get_repo_stars("t", "a/b"))

    def test_a_rate_limited_lookup_is_none_not_zero(self):
        # Zero meant "too few stars", which silently discarded candidates the
        # run had already paid a search request to find.
        self.responses([http_error(403)] * 3)
        self.assertIsNone(dc.get_repo_stars("t", "a/b"))

    def test_a_transient_failure_is_retried(self):
        self.responses([http_error(502), {"stargazers_count": 7}])
        self.assertEqual(dc.get_repo_stars("t", "a/b"), 7)


class Queries(unittest.TestCase):
    def test_every_language_has_at_least_one_query(self):
        for key, queries in dc.SEARCH_QUERIES.items():
            self.assertTrue(queries, f"{key} has no queries")
            for query, description in queries:
                self.assertTrue(query.strip() and description.strip())

    def test_the_mutation_filter_leaves_something_for_most_languages(self):
        keywords = ["pitest", "descartes", "mutmut", "cosmic-ray", "mutatest", "mutpy",
                    "stryker", "cargo-mutants", "mutagen", "go-mutesting", "gremlins",
                    "ooze", "mutant", "mutest", "infection", "muter", "mutation_test",
                    "muzak", "mucheck", "mull", "dextool", "min-msi"]
        without = [
            key for key, queries in dc.SEARCH_QUERIES.items()
            if not any(any(k in q.lower() for k in keywords) for q, _ in queries)
        ]
        # F# and VB.NET share the .NET tooling and are searched through csharp.
        self.assertLessEqual(len(without), 2, f"no mutation query for {without}")


class Running(Patched):
    def setUp(self):
        import tempfile
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.patch(dc.sys, "stdout", io.StringIO())
        self.patch(dc.time, "sleep", lambda _s: None)

    def main(self, *args, root=None):
        from pathlib import Path

        root = Path(root or self.dir.name)
        (root / "scripts").mkdir(parents=True, exist_ok=True)
        original = dc.__file__
        dc.__file__ = str(root / "scripts" / "discover_candidates.py")
        self.addCleanup(setattr, dc, "__file__", original)
        self.patch(dc.sys, "argv", ["discover_candidates.py", *args])
        return dc.main()

    def test_a_run_without_a_token_is_refused(self):
        self.patch(dc.os, "environ", {})
        self.patch(dc.sys, "stderr", io.StringIO())
        self.assertEqual(self.main("--language", "java"), 1)

    def test_candidates_are_written_where_the_workflow_looks(self):
        from pathlib import Path

        self.patch(dc, "search_code", lambda t, q: [{"full_name": "a/b", "matched_file": "pom.xml"}])
        self.patch(dc, "get_repo_stars", lambda t, n: 300)
        self.main("--language", "java", "--token", "t", "--min-stars", "50")
        path = Path(self.dir.name) / "reports" / "candidates" / "java.json"
        self.assertTrue(path.exists())
        self.assertEqual(json.loads(path.read_text())[0]["full_name"], "a/b")

    def test_candidates_below_the_star_floor_are_left_out(self):
        from pathlib import Path

        self.patch(dc, "search_code", lambda t, q: [{"full_name": "a/b", "matched_file": "pom.xml"}])
        self.patch(dc, "get_repo_stars", lambda t, n: 3)
        self.main("--language", "java", "--token", "t", "--min-stars", "50")
        path = Path(self.dir.name) / "reports" / "candidates" / "java.json"
        self.assertEqual(json.loads(path.read_text()), [])

    def test_a_star_lookup_that_failed_does_not_become_a_rejection(self):
        from pathlib import Path

        self.patch(dc, "search_code", lambda t, q: [{"full_name": "a/b", "matched_file": "pom.xml"}])
        self.patch(dc, "get_repo_stars", lambda t, n: None)
        self.patch(dc.sys, "stderr", io.StringIO())
        self.main("--language", "java", "--token", "t")
        path = Path(self.dir.name) / "reports" / "candidates" / "java.json"
        self.assertEqual(json.loads(path.read_text()), [])
        self.assertIn("Could not read stars", dc.sys.stderr.getvalue())

    def test_mutation_only_narrows_the_queries(self):
        asked = []
        self.patch(dc, "search_code", lambda t, q: asked.append(q) or [])
        self.main("--language", "java", "--token", "t", "--mutation-only")
        self.assertTrue(asked)
        self.assertTrue(all("jacoco" not in q for q in asked))


if __name__ == "__main__":
    unittest.main()
