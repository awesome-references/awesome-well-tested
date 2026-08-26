"""Tests for the weekly rewrite.

This is the code that removes entries. Everything here is about the difference
between "this repository stopped qualifying" and "the run could not tell".
"""

import io
import json
import tempfile
import unittest
from pathlib import Path

from _support import readme_table as rt, recheck_listed as rl, verify_repo as vr

README = """# Awesome Well-Tested

## Contents

- [Java](#java)

## Java

| Repository | Tier | Coverage | Mutation Score | Param. Tests | Coverage Tool | Mutation Tool |
| --- | --- | --- | --- | --- | --- | --- |
| [alpha](https://github.com/acme/alpha) | ![Gold](badges/gold.svg) | 100% | 90% | JUnit 5 | JaCoCo | PIT |
| [beta](https://github.com/acme/beta) | ![Silver](badges/silver.svg) | 91% | n/a | no | JaCoCo | PIT |
| [gamma](https://github.com/acme/gamma) | ![Bronze](badges/bronze.svg) | 84% | n/a | no | JaCoCo | n/a |
"""


def report(full_name, tier="silver", coverage=95.0, **kw):
    base = {
        "repository": full_name,
        "tier": tier,
        "tier_reason": "because",
        "coverage": {"service": "Codecov", "coverage": coverage, "is_default_branch": True},
        "mutation_score": None,
        "mutation_score_source": None,
        "primary_coverage_tool": "jacoco",
        "coverage_tools": {"jacoco": {}},
        "mutation_tools": {"pit": {}},
        "parameterized_tests": {"frameworks": [], "detected": False},
        "metadata": {"language": "Java"},
        "issues": None,
    }
    base.update(kw)
    return base


class Recheck(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.root = Path(self.dir.name)
        self.readme = self.root / "README.md"
        self.readme.write_text(README)
        self.reports = self.root / "reports"
        self.reports.mkdir()
        for name in ("acme_alpha", "acme_beta", "acme_gamma"):
            (self.reports / f"{name}.json").write_text("{}")
        self.patch(rl.sys, "stderr", io.StringIO())
        self.patch(rl.sys, "stdout", io.StringIO())

    def patch(self, obj, name, value):
        original = getattr(obj, name)
        setattr(obj, name, value)
        self.addCleanup(setattr, obj, name, original)

    def run_with(self, behaviour, *extra):
        """Run main() with verify_repository replaced by `behaviour`."""
        def fake_verify(api, owner, repo, **kw):
            return behaviour(f"{owner}/{repo}", **kw)

        self.patch(rl, "verify_repository", fake_verify)
        self.patch(rl, "GitHubAPI", lambda **kw: object())
        argv = ["recheck_listed.py", "--token", "t",
                "--readme", str(self.readme), "--output-dir", str(self.reports), *extra]
        self.patch(rl.sys, "argv", argv)
        return rl.main()

    def names(self):
        return [e["full_name"] for e in rt.parse_entries(self.readme.read_text())]

    # -- the ordinary path ---------------------------------------------------

    def test_a_run_that_changes_nothing_leaves_the_list_alone(self):
        tiers = {"acme/alpha": "gold", "acme/beta": "silver", "acme/gamma": "bronze"}
        code = self.run_with(lambda name, **kw: report(name, tier=tiers[name]), "--apply")
        self.assertEqual(code, 0)
        self.assertEqual(self.names(), ["acme/alpha", "acme/beta", "acme/gamma"])

    def test_an_entry_that_stops_qualifying_is_dropped_with_its_report(self):
        def behaviour(name, **kw):
            return report(name, tier=None if name == "acme/beta" else "bronze")

        self.run_with(behaviour, "--apply")
        self.assertEqual(self.names(), ["acme/alpha", "acme/gamma"])
        self.assertFalse((self.reports / "acme_beta.json").exists())

    def test_a_deleted_repository_is_dropped(self):
        def behaviour(name, **kw):
            if name == "acme/gamma":
                raise vr.RepositoryMissing(name)
            return report(name, tier="bronze")

        self.run_with(behaviour, "--apply")
        self.assertEqual(self.names(), ["acme/alpha", "acme/beta"])

    def test_a_tier_change_is_written_in_place(self):
        def behaviour(name, **kw):
            return report(name, tier="bronze" if name == "acme/alpha" else "silver")

        self.run_with(behaviour, "--apply")
        entry = next(e for e in rt.parse_entries(self.readme.read_text())
                     if e["full_name"] == "acme/alpha")
        self.assertEqual(entry["claimed_tier"], "bronze")

    # -- the failure path ----------------------------------------------------

    def test_an_unverifiable_entry_is_left_exactly_as_it_was(self):
        def behaviour(name, **kw):
            if name == "acme/beta":
                raise vr.VerificationIncomplete("codecov said 429")
            return report(name, tier="bronze")

        self.run_with(behaviour, "--apply")
        self.assertIn("acme/beta", self.names())
        self.assertTrue((self.reports / "acme_beta.json").exists())

    def test_a_mostly_failed_run_refuses_to_touch_the_list(self):
        def behaviour(name, **kw):
            raise vr.VerificationIncomplete("everything is down")

        code = self.run_with(behaviour, "--apply")
        self.assertEqual(code, 1)
        self.assertEqual(self.names(), ["acme/alpha", "acme/beta", "acme/gamma"])

    def test_apply_without_a_token_is_refused(self):
        self.patch(rl, "GitHubAPI", lambda **kw: object())
        self.patch(rl.sys, "argv", ["recheck_listed.py", "--apply",
                                    "--readme", str(self.readme),
                                    "--output-dir", str(self.reports)])
        self.patch(rl.os, "environ", {})
        self.assertEqual(rl.main(), 1)
        self.assertEqual(self.names(), ["acme/alpha", "acme/beta", "acme/gamma"])

    # -- bounds on destruction ----------------------------------------------

    def test_a_run_where_everything_stopped_qualifying_is_refused(self):
        # One systemic cause - a coverage service answering 403 to the runner
        # for a whole run - makes every entry look like it stopped qualifying,
        # and no exception is raised anywhere. Nothing legitimate removes a
        # whole curated list in one week.
        code = self.run_with(lambda name, **kw: report(name, tier=None), "--apply")
        self.assertEqual(code, 1)
        self.assertEqual(self.names(), ["acme/alpha", "acme/beta", "acme/gamma"])
        for name in ("acme_alpha", "acme_beta", "acme_gamma"):
            self.assertTrue((self.reports / f"{name}.json").exists())

    def test_removing_one_entry_is_still_allowed(self):
        def behaviour(name, **kw):
            return report(name, tier=None if name == "acme/beta" else "bronze")

        self.assertEqual(self.run_with(behaviour, "--apply"), 0)
        self.assertEqual(self.names(), ["acme/alpha", "acme/gamma"])

    def test_a_refused_run_writes_no_reports_at_all(self):
        # save_report used to run inside the loop, so a run that then refused to
        # apply still left refreshed reports for the workflow to commit.
        before = {p.name: p.read_text() for p in self.reports.glob("*.json")}
        self.run_with(lambda name, **kw: report(name, tier=None), "--apply")
        after = {p.name: p.read_text() for p in self.reports.glob("*.json")}
        self.assertEqual(before, after)

    def test_a_row_that_could_not_be_removed_keeps_its_report(self):
        # The entries are found by one parser and rewritten by another. A
        # malformed table makes them disagree, and deleting the evidence for a
        # row the list still shows is the worst outcome available.
        self.readme.write_text(README.replace(
            "| [beta](https://github.com/acme/beta)",
            "\n| [beta](https://github.com/acme/beta)",
        ))

        def behaviour(name, **kw):
            return report(name, tier=None if name == "acme/beta" else "bronze")

        code = self.run_with(behaviour, "--apply")
        self.assertEqual(code, 1)
        self.assertTrue((self.reports / "acme_beta.json").exists())

    # -- reporting -----------------------------------------------------------

    def test_a_dry_run_touches_no_service(self):
        def behaviour(name, **kw):
            raise AssertionError("should not have been called")

        self.assertEqual(self.run_with(behaviour, "--dry-run"), 0)

    def test_redacting_keeps_names_out_of_the_output(self):
        out = io.StringIO()
        self.patch(rl.sys, "stdout", out)

        def behaviour(name, **kw):
            return report(name, tier=None if name == "acme/beta" else "bronze")

        self.run_with(behaviour, "--apply", "--redact")
        self.assertNotIn("acme/beta", out.getvalue())

    def test_fail_on_mismatch_reports_a_change_as_a_failure(self):
        def behaviour(name, **kw):
            return report(name, tier="bronze")

        self.assertEqual(self.run_with(behaviour, "--fail-on-mismatch"), 1)

    def test_selecting_one_entry_rechecks_only_that_one(self):
        seen = []

        def behaviour(name, **kw):
            seen.append(name)
            return report(name, tier="gold")

        self.run_with(behaviour, "--repo", "acme/alpha")
        self.assertEqual(seen, ["acme/alpha"])

    def test_an_unknown_selection_is_an_error(self):
        self.assertEqual(self.run_with(lambda name, **kw: report(name), "--repo", "no/such"), 1)

    # -- figures a maintainer supplied --------------------------------------

    def test_hand_supplied_figures_survive_a_recheck(self):
        (self.reports / "acme_alpha.json").write_text(json.dumps({
            "coverage": {"service": "manual", "coverage": 88.0},
            "mutation_score": 91.0,
            "mutation_score_source": "manual",
        }))
        passed = {}

        def behaviour(name, **kw):
            if name == "acme/alpha":
                passed.update(kw)
            return report(name, tier="gold")

        self.run_with(behaviour)
        self.assertEqual(passed.get("coverage_override"), 88.0)
        self.assertEqual(passed.get("mutation_score_override"), 91.0)

    def test_figures_that_were_not_supplied_are_not_carried_over(self):
        (self.reports / "acme_beta.json").write_text(json.dumps({
            "coverage": {"service": "Codecov", "coverage": 91.0},
            "mutation_score": 77.0,
            "mutation_score_source": "dashboard",
        }))
        passed = {}

        def behaviour(name, **kw):
            if name == "acme/beta":
                passed.update(kw)
            return report(name, tier="silver")

        self.run_with(behaviour)
        self.assertIsNone(passed.get("coverage_override"))
        self.assertIsNone(passed.get("mutation_score_override"))

    def test_an_unreadable_previous_report_carries_nothing_over(self):
        (self.reports / "acme_beta.json").write_text("{not json")
        self.assertEqual(
            rl.carried_over_figures(self.reports, "acme", "beta"), (None, None, None)
        )

    def test_an_absent_previous_report_carries_nothing_over(self):
        self.assertEqual(
            rl.carried_over_figures(self.reports, "acme", "never-seen"), (None, None, None)
        )

    def test_a_complete_parameterized_answer_is_carried_forward(self):
        # Four code-search requests per entry, for a column that changes about
        # as often as a project changes test framework.
        (self.reports / "acme_alpha.json").write_text(json.dumps({
            "parameterized_tests": {"frameworks": [{"framework": "JUnit 5"}], "complete": True},
        }))
        _, _, carried = rl.carried_over_figures(self.reports, "acme", "alpha")
        self.assertEqual(carried["frameworks"][0]["framework"], "JUnit 5")

    def test_an_incomplete_parameterized_answer_is_not_carried_forward(self):
        (self.reports / "acme_alpha.json").write_text(json.dumps({
            "parameterized_tests": {"frameworks": [], "complete": False},
        }))
        _, _, carried = rl.carried_over_figures(self.reports, "acme", "alpha")
        self.assertIsNone(carried)

    def test_refresh_parameterized_ignores_what_was_carried(self):
        (self.reports / "acme_alpha.json").write_text(json.dumps({
            "parameterized_tests": {"frameworks": [{"framework": "JUnit 5"}], "complete": True},
        }))
        passed = {}

        def behaviour(name, **kw):
            if name == "acme/alpha":
                passed.update(kw)
            return report(name, tier="gold")

        self.run_with(behaviour, "--refresh-parameterized")
        self.assertIsNone(passed.get("parameterized_override"))


if __name__ == "__main__":
    unittest.main()
