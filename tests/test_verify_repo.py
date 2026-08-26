"""Tests for the detection and tier logic.

Every case here corresponds to something that actually went wrong, or to a bar
the list claims to hold and would otherwise be trusting to luck.
"""

import unittest

from _support import prune_unchanged_reports as prune, verify_repo as vr


class MutationBadge(unittest.TestCase):
    def test_reads_a_shields_badge(self):
        self.assertEqual(
            vr.extract_mutation_score_from_readme(
                "[![Mutation](https://img.shields.io/badge/mutation%20coverage-98%25-brightgreen)]"
            ),
            98.0,
        )

    def test_accepts_the_underscore_and_score_spellings(self):
        self.assertEqual(
            vr.extract_mutation_score_from_readme(
                "![m](https://img.shields.io/badge/mutation_score-72%25-yellow)"
            ),
            72.0,
        )

    def test_returns_none_without_a_badge(self):
        self.assertIsNone(vr.extract_mutation_score_from_readme("no badge here"))

    def test_ignores_an_unrelated_coverage_badge(self):
        self.assertIsNone(
            vr.extract_mutation_score_from_readme(
                "![c](https://img.shields.io/badge/coverage-93%25-green)"
            )
        )


class ParameterizedMarkers(unittest.TestCase):
    def test_kover_does_not_match_stackoverflow(self):
        # A plain substring search for "kover" matches "stackoverflow", which is
        # exactly how a false positive was nearly recorded as a finding.
        patterns = vr.COVERAGE_TOOLS["kover"]["patterns"]
        self.assertEqual(
            vr.search_file_for_patterns(
                "# see https://stackoverflow.com/a/67532120", patterns
            ),
            [],
        )

    def test_kover_matches_the_task_names_it_is_configured_by(self):
        patterns = vr.COVERAGE_TOOLS["kover"]["patterns"]
        for text in ("koverXmlReport", "koverHtmlReport", "koverVerify",
                     'id("org.jetbrains.kotlinx.kover")'):
            self.assertTrue(
                vr.search_file_for_patterns(text, patterns), f"{text} not detected"
            )

    def test_istanbul_does_not_claim_phpunit_coverage_flags(self):
        # "--coverage" matched "phpunit --coverage-clover" and labelled every
        # PHP repository an Istanbul user.
        matches = vr.search_file_for_patterns(
            "run: vendor/bin/phpunit --coverage-clover coverage.xml",
            vr.COVERAGE_TOOLS["istanbul"]["patterns"],
        )
        self.assertEqual(matches, [])

    def test_go_has_no_parameterized_markers(self):
        # Table-driven tests have no keyword; a marker would be guesswork.
        self.assertNotIn("Go", vr.PARAMETERIZED_MARKERS)

    def test_every_marker_language_has_at_least_one_term(self):
        for language, markers in vr.PARAMETERIZED_MARKERS.items():
            self.assertTrue(markers, f"{language} has no markers")
            for term, label in markers:
                self.assertNotIn(" OR ", term, "code search does not honour OR")


class DetermineTier(unittest.TestCase):
    CI = {"github_actions": ["ci.yml"]}
    TOOLS = {"jacoco": {}}
    SERVICE = {"service": "Codecov", "coverage": 95.0}

    def tier(self, **kw):
        args = {
            "ci": self.CI,
            "coverage_tools": self.TOOLS,
            "mutation_tools": {},
            "coverage": self.SERVICE,
            "mutation_score": None,
        }
        args.update(kw)
        return vr.determine_tier(**args)[0]

    def test_no_ci_means_no_tier(self):
        self.assertIsNone(self.tier(ci={}))

    def test_no_coverage_figure_means_no_tier(self):
        self.assertIsNone(self.tier(coverage=None))

    def test_below_the_threshold_means_no_tier(self):
        self.assertIsNone(self.tier(coverage={"service": "Codecov", "coverage": 79.9}))

    def test_exactly_at_the_threshold_qualifies(self):
        self.assertEqual(
            self.tier(coverage={"service": "Codecov", "coverage": 80.0}), "bronze"
        )

    def test_a_published_figure_stands_without_a_recognised_tool(self):
        # Somebody had to upload it, so CI reports coverage. Demanding the tool
        # as well rejected repositories for gaps in our table, not in theirs.
        self.assertEqual(self.tier(coverage_tools={}), "bronze")

    def test_a_hand_supplied_figure_still_needs_corroboration(self):
        self.assertIsNone(
            self.tier(
                coverage_tools={},
                coverage={"service": "manual", "coverage": 95.0, "source": "--coverage"},
            )
        )

    def test_mutation_testing_without_a_score_is_silver(self):
        self.assertEqual(self.tier(mutation_tools={"pit": {}}), "silver")

    def test_gold_needs_the_score_not_just_the_tool(self):
        self.assertEqual(
            self.tier(mutation_tools={"pit": {}}, mutation_score=69.9), "silver"
        )
        self.assertEqual(
            self.tier(mutation_tools={"pit": {}}, mutation_score=70.0), "gold"
        )

    def test_every_outcome_explains_itself(self):
        for kwargs in ({"ci": {}}, {"coverage": None}, {"mutation_tools": {"pit": {}}}):
            args = {
                "ci": self.CI,
                "coverage_tools": self.TOOLS,
                "mutation_tools": {},
                "coverage": self.SERVICE,
                "mutation_score": None,
            }
            args.update(kwargs)
            _, reason = vr.determine_tier(**args)
            self.assertTrue(reason.strip())


class PrimaryCoverageTool(unittest.TestCase):
    def test_prefers_the_tool_matching_the_repository_language(self):
        tools = {
            "istanbul": {"language": "JavaScript/TypeScript"},
            "phpunit": {"language": "PHP"},
        }
        self.assertEqual(vr.primary_coverage_tool(tools, "PHP"), "phpunit")

    def test_falls_back_to_the_first_match(self):
        tools = {"istanbul": {"language": "JavaScript/TypeScript"}}
        self.assertEqual(vr.primary_coverage_tool(tools, "Erlang"), "istanbul")

    def test_no_tools_means_no_answer(self):
        self.assertIsNone(vr.primary_coverage_tool({}, "PHP"))


class StripVolatile(unittest.TestCase):
    def base(self):
        return {
            "repository": "acme/x",
            "verified_at": "2026-01-01T00:00:00+00:00",
            "tier": "gold",
            "metadata": {"stars": 10, "forks": 2, "last_push": "a", "days_since_push": 1,
                         "language": "Java"},
        }

    def test_a_run_with_no_real_change_compares_equal(self):
        a, b = self.base(), self.base()
        b["verified_at"] = "2026-06-01T00:00:00+00:00"
        b["metadata"]["stars"] = 4000
        b["metadata"]["days_since_push"] = 99
        self.assertEqual(prune.strip_volatile(a), prune.strip_volatile(b))

    def test_a_tier_change_does_not_compare_equal(self):
        a, b = self.base(), self.base()
        b["tier"] = "silver"
        self.assertNotEqual(prune.strip_volatile(a), prune.strip_volatile(b))

    def test_a_language_change_does_not_compare_equal(self):
        a, b = self.base(), self.base()
        b["metadata"]["language"] = "Kotlin"
        self.assertNotEqual(prune.strip_volatile(a), prune.strip_volatile(b))

    def test_the_original_is_not_mutated(self):
        a = self.base()
        prune.strip_volatile(a)
        self.assertIn("verified_at", a)
        self.assertIn("stars", a["metadata"])


if __name__ == "__main__":
    unittest.main()
