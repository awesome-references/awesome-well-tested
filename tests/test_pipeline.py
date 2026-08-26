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

    def test_a_green_build_behind_a_threshold_reaches_gold(self):
        api = self.api(
            tree=[".github/workflows/mutation.yml", "build.gradle"],
            workflows={"mutation.yml": WORKFLOW_PIT},
            files={"build.gradle": BUILD_JACOCO + BUILD_PIT_THRESHOLD},
            coverage={"codecov": codecov(91.0)},
            runs={"workflow_runs": [{"conclusion": "success"}]},
        )
        report = self.verify(api)
        self.assertEqual(report["tier"], "gold")
        self.assertEqual(report["mutation_score"], 85.0)
        self.assertEqual(report["mutation_score_source"], "ci-threshold")

    def test_a_failing_build_behind_a_threshold_proves_nothing(self):
        api = self.api(
            tree=[".github/workflows/mutation.yml", "build.gradle"],
            workflows={"mutation.yml": WORKFLOW_PIT},
            files={"build.gradle": BUILD_JACOCO + BUILD_PIT_THRESHOLD},
            coverage={"codecov": codecov(91.0)},
            runs={"workflow_runs": [{"conclusion": "failure"}]},
        )
        report = self.verify(api)
        self.assertEqual(report["tier"], "silver")
        self.assertIsNone(report["mutation_score"])
        self.assertFalse(report["mutation_ci_enforced"]["passing"])

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

    def test_a_language_with_no_markers_is_skipped(self):
        api = self.api(
            metadata=repo_metadata(language="Erlang"),
            tree=[".github/workflows/ci.yml"],
            workflows={"ci.yml": WORKFLOW_CI},
            coverage={"codecov": codecov(91.0)},
        )
        self.assertIsNone(self.verify(api)["parameterized_tests"])

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
