"""End-to-end tests for verifying one repository.

verify_repository is where every check meets, and where a mistake decides
whether a real project is listed, promoted or dropped. These drive it through
the fake services so the whole path runs without a token.
"""

import unittest

from _support import verify_repo as vr
from _support.fakes import (
    FakeAPI,
    codecov,
    coveralls,
    elements_report,
    repo_metadata,
)

WORKFLOW_CI = "name: ci\non: push\njobs:\n  test:\n    steps:\n      - run: ./gradlew test\n"
WORKFLOW_PIT = (
    "name: mutation\non: push\njobs:\n  pit:\n    steps:\n"
    "      - run: ./gradlew pitest\n"
)
BUILD_JACOCO = "plugins { id 'jacoco' }\njacocoTestReport { }\n"
BUILD_PIT_THRESHOLD = (
    "plugins { id 'info.solidsoft.pitest' }\npitest { mutationThreshold = 85 }\n"
)


class Verifying(unittest.TestCase):
    def setUp(self):
        # The parameterized check sleeps between code-search queries.
        original = vr.time.sleep
        vr.time.sleep = lambda _s: None
        self.addCleanup(setattr, vr.time, "sleep", original)

    def api(self, **kw):
        kw.setdefault("metadata", repo_metadata())
        return FakeAPI(**kw)

    def verify(self, api, owner="acme", repo="widget", **kw):
        return vr.verify_repository(api, owner, repo, verbose=False, **kw)

    # -- the tiers -----------------------------------------------------------

    def test_coverage_and_ci_alone_is_bronze(self):
        api = self.api(
            tree=[".github/workflows/ci.yml", "build.gradle"],
            workflows={"ci.yml": WORKFLOW_CI},
            files={"build.gradle": BUILD_JACOCO},
            coverage={"codecov": codecov(91.0)},
        )
        report = self.verify(api)
        self.assertEqual(report["tier"], "bronze")
        self.assertEqual(report["coverage"]["coverage"], 91.0)
        self.assertEqual(report["primary_coverage_tool"], "jacoco")

    def test_mutation_testing_without_a_score_is_silver(self):
        api = self.api(
            tree=[".github/workflows/ci.yml", "build.gradle"],
            workflows={"ci.yml": WORKFLOW_CI},
            files={"build.gradle": BUILD_JACOCO + "plugins { id 'info.solidsoft.pitest' }"},
            coverage={"codecov": codecov(91.0)},
        )
        report = self.verify(api)
        self.assertEqual(report["tier"], "silver")
        self.assertIn("pit", report["mutation_tools"])

    def test_a_dashboard_report_reaches_gold(self):
        api = self.api(
            tree=[".github/workflows/ci.yml", "build.gradle"],
            workflows={"ci.yml": WORKFLOW_CI},
            files={"build.gradle": BUILD_JACOCO + "id 'info.solidsoft.pitest'"},
            coverage={"codecov": codecov(91.0)},
            dashboard={"main": elements_report(killed=94, survived=6)},
        )
        report = self.verify(api)
        self.assertEqual(report["tier"], "gold")
        self.assertEqual(report["mutation_score"], 94.0)
        self.assertEqual(report["mutation_score_source"], "dashboard")

    def enforced(self, *, conclusion="success", jobs=None, **kw):
        return self.api(
            tree=[".github/workflows/mutation.yml", "build.gradle"],
            workflows={"mutation.yml": WORKFLOW_PIT},
            files={"build.gradle": BUILD_JACOCO + BUILD_PIT_THRESHOLD},
            coverage={"codecov": codecov(91.0)},
            runs={"workflow_runs": [{"id": 7, "conclusion": conclusion}]},
            jobs={"jobs": jobs if jobs is not None
                  else [{"name": "pit", "conclusion": "success"}]},
            **kw,
        )

    def test_a_green_build_behind_a_threshold_reaches_gold(self):
        report = self.verify(self.enforced())
        self.assertEqual(report["tier"], "gold")
        self.assertEqual(report["mutation_score"], 85.0)
        self.assertEqual(report["mutation_score_source"], "ci-threshold")

    def test_a_failing_build_behind_a_threshold_proves_nothing(self):
        report = self.verify(self.enforced(conclusion="failure"))
        self.assertEqual(report["tier"], "silver")
        self.assertIsNone(report["mutation_score"])
        self.assertFalse(report["mutation_ci_enforced"]["passing"])

    def test_a_skipped_mutation_job_in_a_green_run_proves_nothing(self):
        # A run concludes success when the job that matters was skipped by an
        # `if:`, excluded from a matrix, or failed under continue-on-error.
        report = self.verify(self.enforced(
            jobs=[{"name": "test", "conclusion": "success"},
                  {"name": "pit", "conclusion": "skipped"}]))
        self.assertEqual(report["tier"], "silver")
        self.assertFalse(report["mutation_ci_enforced"]["passing"])
        self.assertIn("pit", report["mutation_ci_enforced"]["run"]["why"])

    def test_jobs_that_cannot_be_read_prove_nothing(self):
        report = self.verify(self.enforced(jobs=[]))
        self.assertEqual(report["tier"], "silver")

    def test_a_threshold_in_a_comment_is_not_enforced(self):
        api = self.api(
            tree=[".github/workflows/mutation.yml", "build.gradle"],
            workflows={"mutation.yml": WORKFLOW_PIT},
            files={"build.gradle": BUILD_JACOCO
                   + "// pitest { mutationThreshold = 85 }\n"},
            coverage={"codecov": codecov(91.0)},
            runs={"workflow_runs": [{"id": 7, "conclusion": "success"}]},
            jobs={"jobs": [{"name": "pit", "conclusion": "success"}]},
        )
        report = self.verify(api)
        self.assertEqual(report["tier"], "silver")
        self.assertIsNone(report["mutation_score"])

    def test_a_readme_badge_stops_at_silver(self):
        api = self.api(
            tree=[".github/workflows/ci.yml", "build.gradle", "README.md"],
            workflows={"ci.yml": WORKFLOW_CI},
            files={
                "build.gradle": BUILD_JACOCO + "id 'info.solidsoft.pitest'",
                "README.md": "![m](https://img.shields.io/badge/mutation%20coverage-99%25-green)",
            },
            coverage={"codecov": codecov(91.0)},
        )
        report = self.verify(api)
        self.assertEqual(report["tier"], "silver")
        self.assertEqual(report["mutation_score"], 99.0)
        self.assertEqual(report["mutation_score_source"], "readme-badge")

    # -- refusals ------------------------------------------------------------

    def test_no_ci_means_no_tier(self):
        api = self.api(
            tree=["build.gradle"],
            files={"build.gradle": BUILD_JACOCO},
            coverage={"codecov": codecov(99.0)},
        )
        self.assertIsNone(self.verify(api)["tier"])

    def test_no_published_figure_means_no_tier(self):
        api = self.api(
            tree=[".github/workflows/ci.yml", "build.gradle"],
            workflows={"ci.yml": WORKFLOW_CI},
            files={"build.gradle": BUILD_JACOCO},
        )
        report = self.verify(api)
        self.assertIsNone(report["tier"])
        self.assertIn("Coverage percentage", report["tier_reason"])

    def test_a_figure_below_the_bar_means_no_tier(self):
        api = self.api(
            tree=[".github/workflows/ci.yml", "build.gradle"],
            workflows={"ci.yml": WORKFLOW_CI},
            files={"build.gradle": BUILD_JACOCO},
            coverage={"codecov": codecov(64.0)},
        )
        self.assertIsNone(self.verify(api)["tier"])

    def test_a_missing_repository_raises_rather_than_returning_a_tier(self):
        api = self.api(metadata=None)
        with self.assertRaises(vr.RepositoryMissing):
            self.verify(api)

    # -- provenance ----------------------------------------------------------

    def test_coveralls_is_used_when_codecov_knows_nothing(self):
        api = self.api(
            tree=[".github/workflows/ci.yml", "build.gradle"],
            workflows={"ci.yml": WORKFLOW_CI},
            files={"build.gradle": BUILD_JACOCO},
            coverage={"coveralls": coveralls(88.0, branch="release", created_at="2020-01-01T00:00:00Z")},
        )
        report = self.verify(api)
        self.assertEqual(report["coverage"]["service"], "Coveralls")
        self.assertFalse(report["coverage"]["is_default_branch"])
        self.assertGreater(report["coverage"]["age_days"], 1000)

    def test_a_hand_supplied_figure_is_marked_manual(self):
        api = self.api(
            tree=[".github/workflows/ci.yml", "build.gradle"],
            workflows={"ci.yml": WORKFLOW_CI},
            files={"build.gradle": BUILD_JACOCO},
        )
        report = self.verify(api, coverage_override=93.5)
        self.assertEqual(report["coverage"]["service"], "manual")
        self.assertEqual(report["tier"], "bronze")

    def test_issues_record_what_was_wrong_with_the_repository(self):
        api = self.api(
            metadata=repo_metadata(archived=True, fork=True, license=None,
                                   pushed_at="2020-01-01T00:00:00Z"),
            tree=[".github/workflows/ci.yml"],
            workflows={"ci.yml": WORKFLOW_CI},
            coverage={"codecov": codecov(99.0)},
        )
        issues = " ".join(self.verify(api)["issues"])
        self.assertIn("archived", issues)
        self.assertIn("fork", issues)
        self.assertIn("license", issues)

    # -- the parameterized column -------------------------------------------

    def test_parameterized_frameworks_are_reported(self):
        api = self.api(
            tree=[".github/workflows/ci.yml", "build.gradle"],
            workflows={"ci.yml": WORKFLOW_CI},
            files={"build.gradle": BUILD_JACOCO},
            coverage={"codecov": codecov(91.0)},
            searches={"ParameterizedTest": 42},
        )
        frameworks = self.verify(api)["parameterized_tests"]["frameworks"]
        self.assertEqual([f["framework"] for f in frameworks], ["JUnit 5 @ParameterizedTest"])

    def test_the_search_is_bounded(self):
        # Two hits is enough; four queries is all it will spend looking.
        api = self.api(
            tree=[".github/workflows/ci.yml", "build.gradle"],
            workflows={"ci.yml": WORKFLOW_CI},
            files={"build.gradle": BUILD_JACOCO},
            coverage={"codecov": codecov(91.0)},
            searches={t: 5 for t, _ in vr.PARAMETERIZED_MARKERS["Java"]},
        )
        result = self.verify(api)["parameterized_tests"]
        self.assertEqual(len(result["frameworks"]), vr.MAX_PARAMETERIZED_HITS)
        self.assertLessEqual(result["terms_tried"], vr.MAX_PARAMETERIZED_QUERIES)

    def test_without_a_token_the_check_is_skipped_not_answered(self):
        api = self.api(
            tree=[".github/workflows/ci.yml", "build.gradle"],
            workflows={"ci.yml": WORKFLOW_CI},
            files={"build.gradle": BUILD_JACOCO},
            coverage={"codecov": codecov(91.0)},
            authenticated=False,
        )
        self.assertIsNone(self.verify(api)["parameterized_tests"])

    def test_a_rate_limited_search_does_not_cost_the_entry(self):
        # The column is informational. Letting the search endpoint's limit
        # propagate would make it decide whether the entry gets verified at all.
        api = self.api(
            tree=[".github/workflows/ci.yml", "build.gradle"],
            workflows={"ci.yml": WORKFLOW_CI},
            files={"build.gradle": BUILD_JACOCO},
            coverage={"codecov": codecov(91.0)},
            raise_on=[("/search/code", vr.VerificationIncomplete("HTTP 403"))],
        )
        report = self.verify(api)
        self.assertEqual(report["tier"], "bronze")
        self.assertIsNone(report["parameterized_tests"])

    def test_a_search_that_stopped_early_says_so(self):
        api = self.api(
            tree=[".github/workflows/ci.yml", "build.gradle"],
            workflows={"ci.yml": WORKFLOW_CI},
            files={"build.gradle": BUILD_JACOCO},
            coverage={"codecov": codecov(91.0)},
            searches={"ParameterizedTest": 12},
            raise_on=[("RunWith", vr.VerificationIncomplete("HTTP 403"))],
        )
        result = self.verify(api)["parameterized_tests"]
        self.assertFalse(result["complete"])
        self.assertEqual(len(result["frameworks"]), 1)

    def test_a_language_with_no_markers_is_skipped(self):
        api = self.api(
            metadata=repo_metadata(language="Erlang"),
            tree=[".github/workflows/ci.yml"],
            workflows={"ci.yml": WORKFLOW_CI},
            coverage={"codecov": codecov(91.0)},
        )
        self.assertIsNone(self.verify(api)["parameterized_tests"])

    # -- config files that are their own evidence ---------------------------

    def test_a_bare_coveragerc_counts_as_a_coverage_tool(self):
        # Its sections are "[run]" and "[report]", so no pattern written for
        # pyproject.toml's "[tool.coverage." spelling can ever match it.
        api = self.api(
            metadata=repo_metadata(language="Python"),
            tree=[".github/workflows/ci.yml", ".coveragerc"],
            workflows={"ci.yml": WORKFLOW_CI},
            files={".coveragerc": "[run]\nbranch = True\n\n[report]\nfail_under = 92\n"},
            coverage={"codecov": codecov(91.0)},
        )
        report = self.verify(api)
        self.assertIn("coverage.py", report["coverage_tools"])
        self.assertEqual(report["coverage_tools"]["coverage.py"]["file"], ".coveragerc")

    def test_a_bare_nycrc_counts_as_a_coverage_tool(self):
        api = self.api(
            metadata=repo_metadata(language="TypeScript"),
            tree=[".github/workflows/ci.yml", ".nycrc"],
            files={".nycrc": '{"all": true, "check-coverage": true, "lines": 95}'},
            workflows={"ci.yml": WORKFLOW_CI},
            coverage={"codecov": codecov(91.0)},
        )
        self.assertIn("istanbul", self.verify(api)["coverage_tools"])

    def test_an_absent_config_file_is_not_evidence(self):
        api = self.api(
            metadata=repo_metadata(language="Python"),
            tree=[".github/workflows/ci.yml"],
            workflows={"ci.yml": WORKFLOW_CI},
            coverage={"codecov": codecov(91.0)},
        )
        self.assertEqual(self.verify(api)["coverage_tools"], None)

    # -- request economy -----------------------------------------------------

    def test_a_known_tree_keeps_the_request_count_small(self):
        api = self.api(
            tree=[".github/workflows/ci.yml", "build.gradle"],
            workflows={"ci.yml": WORKFLOW_CI},
            files={"build.gradle": BUILD_JACOCO},
            coverage={"codecov": codecov(91.0)},
        )
        self.verify(api)
        # Metadata, tree, one workflow, one build file, README attempts,
        # coverage and dashboard. Well under the fifty-three this once cost.
        self.assertLess(api.requests, 25)

    def test_a_truncated_tree_still_verifies(self):
        api = self.api(
            tree=None,
            workflows={"ci.yml": WORKFLOW_CI},
            files={"build.gradle": BUILD_JACOCO},
            coverage={"codecov": codecov(91.0)},
        )
        self.assertEqual(self.verify(api)["tier"], "bronze")


class CommandLine(unittest.TestCase):
    """The single-repository entry point should never end in a traceback."""

    def patch(self, obj, name, value):
        original = getattr(obj, name)
        setattr(obj, name, value)
        self.addCleanup(setattr, obj, name, original)

    def run_main(self, behaviour):
        import io
        import tempfile

        def fake_verify(api, owner, repo, *a, **kw):
            return behaviour(f"{owner}/{repo}")

        self.patch(vr, "verify_repository", fake_verify)
        self.patch(vr, "GitHubAPI", lambda **kw: object())
        self.patch(vr.sys, "stderr", io.StringIO())
        self.patch(vr.sys, "stdout", io.StringIO())
        with tempfile.TemporaryDirectory() as directory:
            self.patch(vr.sys, "argv", ["verify_repo.py", "acme/widget",
                                        "--token", "t", "--output-dir", directory])
            return vr.main(), vr.sys.stderr.getvalue()

    def test_a_missing_repository_reports_and_exits(self):
        def behaviour(name):
            raise vr.RepositoryMissing(name)

        code, err = self.run_main(behaviour)
        self.assertEqual(code, 1)
        self.assertIn("not found", err)

    def test_an_unfinished_check_says_it_is_not_a_verdict(self):
        def behaviour(name):
            raise vr.VerificationIncomplete("codecov said 503")

        code, err = self.run_main(behaviour)
        self.assertEqual(code, 1)
        self.assertIn("not a verdict", err)

    def test_a_successful_run_exits_zero(self):
        def behaviour(name):
            return {"repository": name, "tier": "bronze", "tier_reason": "fine",
                    "coverage": {"service": "Codecov", "coverage": 90.0},
                    "mutation_score": None, "metadata": {"language": "Java"},
                    "issues": None}

        code, _ = self.run_main(behaviour)
        self.assertEqual(code, 0)


class Reports(unittest.TestCase):
    def test_a_report_round_trips_through_disk(self):
        import json
        import tempfile
        from pathlib import Path

        report = {"repository": "acme/widget", "tier": "gold"}
        with tempfile.TemporaryDirectory() as directory:
            path = vr.save_report(report, directory)
            self.assertEqual(path.name, "acme_widget.json")
            self.assertEqual(json.loads(Path(path).read_text()), report)

    def test_parsing_accepts_every_way_of_naming_a_repository(self):
        for value in (
            "https://github.com/acme/widget",
            "https://github.com/acme/widget/",
            "acme/widget",
        ):
            self.assertEqual(vr.parse_repo_arg(value), ("acme", "widget"))


if __name__ == "__main__":
    unittest.main()
