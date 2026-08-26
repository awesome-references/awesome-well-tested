"""Tests for the README table rewriting.

These matter more than they look. recheck_listed.py --apply rewrites the list
itself, so a bug here silently deletes entries that belong on it.
"""

import unittest
from pathlib import Path

from _support import readme_table as rt, recheck_listed as rl

FIXTURE = """# Awesome Well-Tested

## Contents

- [Java](#java)

## Java

| Repository | Tier | Coverage | Mutation Score | Param. Tests | Coverage Tool | Mutation Tool |
| --- | --- | --- | --- | --- | --- | --- |
| [alpha](https://github.com/acme/alpha) | ![Gold](badges/gold.svg) | 100% | 90% | JUnit 5 | JaCoCo | PIT |
| [beta](https://github.com/acme/beta) | ![Silver](badges/silver.svg) | 91% | n/a | no | JaCoCo | PIT |

## Ruby

| Repository | Tier | Coverage | Mutation Score | Param. Tests | Coverage Tool | Mutation Tool |
| --- | --- | --- | --- | --- | --- | --- |
| [gamma](https://github.com/acme/gamma) | ![Bronze](badges/bronze.svg) | 84% | n/a | RSpec | SimpleCov | n/a |

## Other Languages

| Repository | Language | Tier | Coverage | Mutation Score | Param. Tests | Coverage Tool | Mutation Tool |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <!-- entries go here --> |  |  |  |  |  |  |  |
"""


def report(full_name, tier="silver", coverage=95.0, language="Java", **kw):
    owner, repo = full_name.split("/", 1)
    base = {
        "repository": full_name,
        "tier": tier,
        "coverage": {"service": "Codecov", "coverage": coverage},
        "mutation_score": None,
        "primary_coverage_tool": "jacoco",
        "mutation_tools": {"pit": {}},
        "parameterized_tests": {"frameworks": [], "detected": False},
        "metadata": {"language": language},
    }
    base.update(kw)
    return base


class ParseEntries(unittest.TestCase):
    def test_finds_every_entry_with_its_section(self):
        entries = rt.parse_entries(FIXTURE)
        self.assertEqual(
            [(e["full_name"], e["claimed_tier"], e["section"]) for e in entries],
            [
                ("acme/alpha", "gold", "Java"),
                ("acme/beta", "silver", "Java"),
                ("acme/gamma", "bronze", "Ruby"),
            ],
        )

    def test_ignores_the_tier_legend(self):
        # The Tiers table carries badges but no repository links.
        legend = (
            "| Tier | Badge |\n| --- | --- |\n"
            "| Gold | ![Gold](badges/gold.svg) |\n"
        )
        self.assertEqual(rt.parse_entries(legend), [])

    def test_ignores_placeholder_rows(self):
        self.assertNotIn("", [e["full_name"] for e in rt.parse_entries(FIXTURE)])


class TransformTables(unittest.TestCase):
    def test_round_trip_is_idempotent(self):
        once = rt.transform_tables(FIXTURE, lambda s, h, b: b)
        twice = rt.transform_tables(once, lambda s, h, b: b)
        self.assertEqual(once, twice)

    def test_round_trip_preserves_every_entry(self):
        once = rt.transform_tables(FIXTURE, lambda s, h, b: b)
        self.assertEqual(
            [e["full_name"] for e in rt.parse_entries(once)],
            [e["full_name"] for e in rt.parse_entries(FIXTURE)],
        )

    def test_renders_aligned_pipes(self):
        # awesome-lint rejects ragged tables.
        for line in rt.transform_tables(FIXTURE, lambda s, h, b: b).split("\n"):
            if line.startswith("|"):
                self.assertTrue(line.endswith("|"))
        table = [
            l for l in rt.transform_tables(FIXTURE, lambda s, h, b: b).split("\n")
            if l.startswith("| [alpha]") or l.startswith("| [beta]")
        ]
        self.assertEqual(len(set(len(l) for l in table)), 1)

    def test_leaves_non_entry_tables_alone(self):
        seen = []
        rt.transform_tables(FIXTURE, lambda s, h, b: seen.append(s) or b)
        self.assertNotIn(None, seen)


class CellsFromReport(unittest.TestCase):
    HEADER = [
        "Repository", "Tier", "Coverage", "Mutation Score",
        "Param. Tests", "Coverage Tool", "Mutation Tool",
    ]

    def test_maps_tools_to_display_names(self):
        cells = rt.cells_from_report(report("acme/x"), self.HEADER)
        self.assertEqual(cells["Coverage Tool"], "JaCoCo")
        self.assertEqual(cells["Mutation Tool"], "PIT")
        self.assertEqual(cells["Tier"], "![Silver](badges/silver.svg)")

    def test_trims_trailing_zeros_from_coverage(self):
        self.assertEqual(
            rt.cells_from_report(report("acme/x", coverage=100.0), self.HEADER)["Coverage"],
            "100%",
        )
        self.assertEqual(
            rt.cells_from_report(report("acme/x", coverage=88.44), self.HEADER)["Coverage"],
            "88.44%",
        )

    def test_distinguishes_not_checked_from_none_found(self):
        checked = report("acme/x", parameterized_tests={"frameworks": [], "detected": False})
        unchecked = report("acme/x", parameterized_tests=None)
        self.assertEqual(rt.cells_from_report(checked, self.HEADER)["Param. Tests"], "no")
        self.assertEqual(rt.cells_from_report(unchecked, self.HEADER)["Param. Tests"], "n/a")

    def test_falls_back_to_the_publishing_service(self):
        cells = rt.cells_from_report(
            report("acme/x", primary_coverage_tool=None), self.HEADER
        )
        self.assertEqual(cells["Coverage Tool"], "Codecov")

    def test_only_returns_columns_the_table_has(self):
        header = ["Repository", "Tier", "Coverage"]
        self.assertEqual(
            set(rt.cells_from_report(report("acme/x"), header)),
            {"Tier", "Coverage"},
        )

    def test_no_mutation_tool_reads_as_not_applicable(self):
        cells = rt.cells_from_report(report("acme/x", mutation_tools=None), self.HEADER)
        self.assertEqual(cells["Mutation Tool"], "n/a")


class CoverageQualifiers(unittest.TestCase):
    HEADER = [
        "Repository", "Tier", "Coverage", "Mutation Score",
        "Param. Tests", "Coverage Tool", "Mutation Tool",
    ]

    def cell(self, **coverage):
        base = {"service": "Codecov", "coverage": 96.87}
        base.update(coverage)
        return rt.cells_from_report(report("acme/x", coverage=base["coverage"], **{}) | {"coverage": base}, self.HEADER)

    def test_a_default_branch_figure_carries_no_qualifier(self):
        cells = self.cell(is_default_branch=True, age_days=10, measured_at="2026-08-01T00:00:00Z")
        self.assertEqual(cells["Coverage"], "96.87%")

    def test_another_branch_is_named(self):
        cells = self.cell(is_default_branch=False, branch="develop", age_days=1)
        self.assertEqual(cells["Coverage"], "96.87% (develop)")

    def test_a_long_branch_name_is_truncated(self):
        cells = self.cell(
            is_default_branch=False,
            branch="dependabot/github_actions/actions-major-46e1ab33c4",
            age_days=1,
        )
        self.assertLess(len(cells["Coverage"]), 40)
        self.assertIn("dependabot", cells["Coverage"])

    def test_a_stale_figure_is_dated(self):
        cells = self.cell(is_default_branch=True, age_days=2047, measured_at="2021-01-17T00:12:54Z")
        self.assertEqual(cells["Coverage"], "96.87% (2021)")

    def test_a_self_reported_score_says_so(self):
        cells = rt.cells_from_report(
            report("acme/x", mutation_score=100.0, mutation_score_source="readme-badge"),
            self.HEADER,
        )
        self.assertEqual(cells["Mutation Score"], "100% (self-reported)")

    def test_an_enforced_threshold_reads_as_a_floor(self):
        cells = rt.cells_from_report(
            report("acme/x", mutation_score=92.0, mutation_score_source="ci-threshold"),
            self.HEADER,
        )
        self.assertEqual(cells["Mutation Score"], ">= 92%")


class ApplyChanges(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.readme = Path(self.dir.name) / "README.md"
        self.readme.write_text(FIXTURE)
        self.reports = Path(self.dir.name) / "reports"
        self.reports.mkdir()
        for name in ("acme_alpha", "acme_beta", "acme_gamma"):
            (self.reports / f"{name}.json").write_text("{}")

    def names(self):
        return [e["full_name"] for e in rt.parse_entries(self.readme.read_text())]

    def test_dropping_an_entry_removes_only_that_row(self):
        rl.apply_changes(self.readme, {}, {"acme/beta"}, self.reports)
        self.assertEqual(self.names(), ["acme/alpha", "acme/gamma"])

    def test_dropping_an_entry_deletes_its_report(self):
        rl.apply_changes(self.readme, {}, {"acme/beta"}, self.reports)
        self.assertFalse((self.reports / "acme_beta.json").exists())
        self.assertTrue((self.reports / "acme_alpha.json").exists())

    def test_emptying_a_section_leaves_a_placeholder_not_a_broken_table(self):
        rl.apply_changes(self.readme, {}, {"acme/gamma"}, self.reports)
        text = self.readme.read_text()
        ruby = text.split("## Ruby", 1)[1].split("## Other", 1)[0]
        self.assertIn("entries go here", ruby)
        self.assertEqual(self.names(), ["acme/alpha", "acme/beta"])

    def test_changing_nothing_changes_nothing(self):
        rl.apply_changes(self.readme, {}, set(), self.reports)
        self.assertEqual(self.names(), ["acme/alpha", "acme/beta", "acme/gamma"])

    def test_a_lowered_tier_is_rewritten_in_place(self):
        rl.apply_changes(
            self.readme,
            {"acme/alpha": report("acme/alpha", tier="bronze", coverage=82.5)},
            set(),
            self.reports,
        )
        text = self.readme.read_text()
        self.assertIn("| [alpha](https://github.com/acme/alpha)", text)
        entry = next(e for e in rt.parse_entries(text) if e["full_name"] == "acme/alpha")
        self.assertEqual(entry["claimed_tier"], "bronze")
        self.assertIn("82.5%", text)
        # and says nothing about having been lowered
        self.assertNotIn("lowered", text.lower())
        self.assertNotIn("demot", text.lower())

    def test_refreshing_one_entry_does_not_touch_its_neighbours(self):
        before = self.readme.read_text()
        beta_row = next(l for l in before.split("\n") if "[beta]" in l)
        rl.apply_changes(
            self.readme, {"acme/alpha": report("acme/alpha")}, set(), self.reports
        )
        after = self.readme.read_text()
        self.assertIn("[beta](https://github.com/acme/beta)", after)
        cells = rt.split_row(next(l for l in after.split("\n") if "[beta]" in l))
        self.assertEqual(cells, rt.split_row(beta_row))

    def test_an_unknown_repository_in_drop_is_harmless(self):
        rl.apply_changes(self.readme, {}, {"acme/does-not-exist"}, self.reports)
        self.assertEqual(self.names(), ["acme/alpha", "acme/beta", "acme/gamma"])


class Classify(unittest.TestCase):
    def test_losing_every_tier_is_a_removal(self):
        self.assertEqual(rl.classify("gold", None), "removed")

    def test_direction_is_read_from_the_tier_order(self):
        self.assertEqual(rl.classify("gold", "silver"), "lowered")
        self.assertEqual(rl.classify("bronze", "gold"), "raised")
        self.assertEqual(rl.classify("silver", "silver"), "unchanged")


if __name__ == "__main__":
    unittest.main()
