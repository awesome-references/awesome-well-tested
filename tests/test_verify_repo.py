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


class PatternsThatNameThingsNotWords(unittest.TestCase):
    """Every case here is a counterexample an audit produced against the live table."""

    def matched(self, tool, text):
        return bool(
            vr.search_file_for_patterns(text, vr.COVERAGE_TOOLS[tool]["patterns"])
        )

    def test_phpunit_as_a_dev_dependency_is_not_coverage(self):
        # Every PHP project declares it; the runner's name proves nothing.
        self.assertFalse(
            self.matched("phpunit", '{"require-dev": {"phpunit/phpunit": "^11.0"}}')
        )

    def test_a_workflow_switching_coverage_off_is_not_coverage(self):
        self.assertFalse(self.matched("phpunit", "  coverage: none   # xdebug is slow"))

    def test_phpunit_collecting_coverage_is_coverage(self):
        self.assertTrue(
            self.matched("phpunit", "run: vendor/bin/phpunit --coverage-clover coverage.xml")
        )
        self.assertTrue(self.matched("phpunit", "  with:\n    coverage: pcov"))

    def test_the_istanbul_timezone_is_not_the_coverage_tool(self):
        # Date libraries run their suite across timezones; Europe/Istanbul is a
        # standard DST fixture.
        self.assertFalse(self.matched("istanbul", "env:\n  TZ: Europe/Istanbul"))

    def test_a_centos_container_tag_is_not_c8(self):
        self.assertFalse(self.matched("istanbul", "container: quay.io/centos/centos:c8"))

    def test_nyc_as_a_dependency_is_coverage(self):
        self.assertTrue(self.matched("istanbul", '"devDependencies": {"nyc": "^15.1.0"}'))

    def test_the_real_coverage_py_sections_match(self):
        self.assertTrue(self.matched("coverage.py", "[tool.coverage.run]\nbranch = true"))

    def test_cov_does_not_match_the_start_of_coverage(self):
        # "--cov" is a prefix of "--coverage-clover", so without a boundary it
        # made every PHP repository look like a pytest-cov user.
        self.assertFalse(
            self.matched("pytest-cov", "run: vendor/bin/phpunit --coverage-clover coverage.xml")
        )
        self.assertFalse(self.matched("pytest-cov", "run: npx jest --coverage"))

    def test_pytest_collecting_coverage_still_matches(self):
        self.assertTrue(self.matched("pytest-cov", "run: pytest --cov=src"))
        self.assertTrue(self.matched("pytest-cov", "addopts = --cov src"))

    def test_a_step_named_upload_coverage_report_is_not_coverage_py(self):
        # Reads as a command in a config file and as English in a CI step name.
        self.assertFalse(
            self.matched("coverage.py", "- name: Upload coverage report\n  uses: codecov/codecov-action@v4")
        )

    def test_the_section_coverage_py_does_not_have_does_not_match(self):
        # "[tool.coverage]" is not a section coverage.py reads, so a pattern for
        # it could never match a real file.
        self.assertFalse(self.matched("coverage.py", "[tool.coverage]\nbranch = true"))


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


class MutationBadgeNumbers(unittest.TestCase):
    def test_a_fractional_score_keeps_its_fraction(self):
        # Truncating 69.8 to 69 costs a repository its Gold tier.
        self.assertEqual(
            vr.extract_mutation_score_from_readme(
                "![m](https://img.shields.io/badge/mutation%20coverage-69.8%25-yellow)"
            ),
            69.8,
        )

    def test_a_score_above_one_hundred_is_rejected(self):
        self.assertIsNone(
            vr.extract_mutation_score_from_readme(
                "![m](https://img.shields.io/badge/mutation%20coverage-150%25-green)"
            )
        )


class PrimaryCoverageTool(unittest.TestCase):
    def test_java_is_not_credited_with_a_javascript_tool(self):
        # "Java" is a substring of "JavaScript/TypeScript".
        tools = {
            "istanbul": {"language": "JavaScript/TypeScript"},
            "jacoco": {"language": "Java/Kotlin"},
        }
        self.assertEqual(vr.primary_coverage_tool(tools, "Java"), "jacoco")

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
