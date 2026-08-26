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

    def test_go_markers_name_libraries_never_table_driven_tests(self):
        # Table-driven tests still have no keyword of their own. What Go does
        # announce is its property-testing and table-DSL libraries, so those are
        # detected and the idiom is not guessed at.
        terms = [term for term, _ in vr.PARAMETERIZED_MARKERS["Go"]]
        self.assertIn("gopter", terms)
        for guess in ("[]struct", "t.Run", "tests :=", "tt."):
            self.assertNotIn(guess, terms)

    def test_every_marker_language_has_at_least_one_term(self):
        for language, markers in vr.PARAMETERIZED_MARKERS.items():
            self.assertTrue(markers, f"{language} has no markers")
            for term, label in markers:
                self.assertNotIn(" OR ", term, "code search does not honour OR")
                self.assertTrue(label.strip(), f"{term} has no label")

    def test_shared_examples_are_not_treated_as_parameterization(self):
        # Sharing example code between contexts is reuse. Running one example
        # over many inputs is what this column claims.
        for language in ("Ruby", "Swift"):
            terms = [t for t, _ in vr.PARAMETERIZED_MARKERS[language]]
            self.assertNotIn("shared_examples", terms)
            self.assertNotIn("it_behaves_like", terms)
            self.assertNotIn("itBehavesLike", terms)

    def test_no_marker_is_a_substring_of_a_more_specific_one(self):
        # "TestCase" matched TestCaseSource and ordinary method names alike.
        for language, markers in vr.PARAMETERIZED_MARKERS.items():
            terms = [t for t, _ in markers]
            for term in terms:
                others = [o for o in terms if o != term]
                self.assertFalse(
                    any(term in other for other in others),
                    f"{language}: {term!r} is a substring of a sibling marker",
                )

    def test_every_pattern_in_the_tool_tables_compiles(self):
        import re
        for table in (vr.COVERAGE_TOOLS, vr.MUTATION_TOOLS):
            for key, tool in table.items():
                self.assertTrue(tool["files"], f"{key} checks no files")
                self.assertTrue(tool["patterns"], f"{key} has no patterns")
                for pattern in tool["patterns"]:
                    re.compile(pattern)

    def test_no_tool_pattern_is_a_bare_common_word(self):
        # Each of these was, at some point, a pattern that misfired.
        forbidden = {"coverage", "test", "phpunit", "istanbul", "clover", "dextool",
                     "muter", "--coverage", "c8", "kover"}
        for table in (vr.COVERAGE_TOOLS, vr.MUTATION_TOOLS):
            for key, tool in table.items():
                for pattern in tool["patterns"]:
                    self.assertNotIn(
                        pattern.strip().lower(), forbidden,
                        f"{key} matches the bare word {pattern!r}",
                    )


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


class DashboardBranchHint(unittest.TestCase):
    """Guessing default/main/master misses projects that publish from elsewhere."""

    def test_a_shields_endpoint_badge_names_the_branch(self):
        readme = (
            "![m](https://img.shields.io/endpoint?url=https%3A%2F%2Fbadge-api."
            "stryker-mutator.io%2Fgithub.com%2Facme%2Fthing%2Fnext)"
        )
        self.assertEqual(vr.dashboard_branch_from_readme(readme), "next")

    def test_a_plain_report_link_names_the_branch(self):
        readme = "[report](https://dashboard.stryker-mutator.io/reports/github.com/a/b/develop)"
        self.assertEqual(vr.dashboard_branch_from_readme(readme), "develop")

    def test_a_readme_without_one_hints_nothing(self):
        self.assertIsNone(vr.dashboard_branch_from_readme("no badge here"))
        self.assertIsNone(vr.dashboard_branch_from_readme(None))


class MutationInvocations(unittest.TestCase):
    def test_every_mutation_tool_can_be_recognised_when_ci_runs_it(self):
        # Without an entry the CI-enforced check falls back to the dict key,
        # and keys like "stryker-net" never appear in a workflow.
        missing = [k for k in vr.MUTATION_TOOLS if k not in vr.MUTATION_INVOCATIONS]
        self.assertEqual(missing, [])

    def test_mutant_does_not_match_the_immutant_gem(self):
        self.assertEqual(
            vr.search_file_for_patterns(
                "gem 'immutant'", vr.MUTATION_TOOLS["mutant"]["patterns"]
            ),
            [],
        )

    def test_mutant_matches_its_own_gems(self):
        for text in ("gem 'mutant-rspec'", "gem 'mutant-minitest'", "gem 'mutant'"):
            self.assertTrue(
                vr.search_file_for_patterns(text, vr.MUTATION_TOOLS["mutant"]["patterns"]),
                text,
            )


class CoverageBadges(unittest.TestCase):
    """A badge only counts when it is a coverage badge."""

    def services(self, text):
        return [b["service"] for b in vr.check_badges(text)]

    def test_a_maintainability_badge_is_not_coverage(self):
        self.assertEqual(
            self.services("![c](https://api.codeclimate.com/v1/badges/abc/maintainability)"), []
        )

    def test_a_code_climate_coverage_badge_counts(self):
        self.assertEqual(
            self.services("![c](https://api.codeclimate.com/v1/badges/abc/test_coverage)"),
            ["Code Climate"],
        )

    def test_a_sonar_quality_gate_is_not_coverage(self):
        self.assertEqual(
            self.services(
                "![s](https://sonarcloud.io/api/project_badges/measure?project=x&metric=alert_status)"
            ),
            [],
        )

    def test_a_sonar_coverage_badge_counts(self):
        self.assertEqual(
            self.services(
                "![s](https://sonarcloud.io/api/project_badges/measure?project=x&metric=coverage)"
            ),
            ["SonarCloud"],
        )

    def test_badge_urls_are_matched_whatever_their_casing(self):
        self.assertEqual(
            self.services("![cov](https://CODECOV.IO/GH/a/b/graph/badge.svg)"), ["Codecov"]
        )

    def test_a_missing_readme_yields_no_badges(self):
        self.assertEqual(vr.check_badges(None), [])


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

    def test_a_score_alone_no_longer_reaches_gold(self):
        # See GoldNeedsEvidence: the number must come from somewhere the
        # repository does not control.
        self.assertEqual(
            self.tier(mutation_tools={"pit": {}}, mutation_score=69.9), "silver"
        )
        self.assertEqual(
            self.tier(mutation_tools={"pit": {}}, mutation_score=100.0), "silver"
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


class GoldNeedsEvidence(unittest.TestCase):
    """Gold is the tier that says a project measured its tests, so the number
    behind it must not be one the project simply asserted."""

    def tier(self, score, source):
        return vr.determine_tier(
            ci={"github_actions": ["ci.yml"]},
            coverage_tools={"jacoco": {}},
            mutation_tools={"pit": {}},
            coverage={"service": "Codecov", "coverage": 95.0},
            mutation_score=score,
            mutation_score_source=source,
        )[0]

    def test_a_readme_badge_does_not_reach_gold(self):
        self.assertEqual(self.tier(100.0, "readme-badge"), "silver")

    def test_an_independently_hosted_score_reaches_gold(self):
        self.assertEqual(self.tier(88.76, "dashboard"), "gold")

    def test_a_threshold_the_build_enforces_reaches_gold(self):
        self.assertEqual(self.tier(92.0, "ci-threshold"), "gold")

    def test_a_hand_supplied_score_does_not_reach_gold(self):
        self.assertEqual(self.tier(100.0, "manual"), "silver")

    def test_evidence_does_not_rescue_a_score_below_the_bar(self):
        self.assertEqual(self.tier(69.9, "dashboard"), "silver")

    def test_the_reason_says_the_score_was_self_reported(self):
        _, reason = vr.determine_tier(
            ci={"github_actions": ["ci.yml"]},
            coverage_tools={"jacoco": {}},
            mutation_tools={"pit": {}},
            coverage={"service": "Codecov", "coverage": 95.0},
            mutation_score=100.0,
            mutation_score_source="readme-badge",
        )
        self.assertIn("self-reported", reason)


class MutationThresholds(unittest.TestCase):
    def test_thresholds_are_bound_to_the_tool_that_defines_them(self):
        # Reading Stryker's "break" as PIT's mutationThreshold would award a
        # tier on a number belonging to a different tool.
        self.assertIn("pit", vr.MUTATION_THRESHOLDS)
        for tool, patterns in vr.MUTATION_THRESHOLDS.items():
            self.assertTrue(patterns, f"{tool} has no threshold pattern")

    def test_infection_min_msi_is_read(self):
        import re
        patterns = vr.MUTATION_THRESHOLDS["infection"]
        hits = [re.search(p, '  "minMsi": 92,', re.IGNORECASE) for p in patterns]
        self.assertTrue(any(h for h in hits))
        self.assertEqual(next(h for h in hits if h).group(1), "92")

    def test_a_pit_pattern_does_not_read_an_infection_setting(self):
        import re
        for pattern in vr.MUTATION_THRESHOLDS["pit"]:
            self.assertIsNone(re.search(pattern, '  "minMsi": 92,', re.IGNORECASE))


class CoverageProvenance(unittest.TestCase):
    def test_an_unreadable_timestamp_is_not_an_age(self):
        self.assertIsNone(vr._age_in_days("not a date"))
        self.assertIsNone(vr._age_in_days(None))

    def test_an_old_timestamp_reads_as_old(self):
        self.assertGreater(vr._age_in_days("2020-01-01T00:00:00Z"), 1500)


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


class StripVolatileDerivedFields(unittest.TestCase):
    """Everything computed from "now" has to be stripped, or nothing compares
    equal and the weekly noise pull request comes back."""

    def base(self):
        return {
            "repository": "acme/x",
            "verified_at": "2026-01-01T00:00:00+00:00",
            "tier": "gold",
            "coverage": {"service": "Codecov", "coverage": 95.0, "age_days": 30,
                         "measured_at": "2026-01-01T00:00:00Z"},
            "parameterized_tests": {"frameworks": [{"framework": "JUnit 5", "matches": 40}]},
            "issues": ["No activity for 400 days"],
            "metadata": {"stars": 1, "forks": 0, "last_push": "a", "days_since_push": 1},
        }

    def test_a_growing_coverage_age_does_not_count_as_a_change(self):
        import copy
        from _support import prune_unchanged_reports as prune

        a, b = self.base(), copy.deepcopy(self.base())
        b["coverage"]["age_days"] = 37
        self.assertEqual(prune.strip_volatile(a), prune.strip_volatile(b))

    def test_a_growing_search_count_does_not_count_as_a_change(self):
        import copy
        from _support import prune_unchanged_reports as prune

        a, b = self.base(), copy.deepcopy(self.base())
        b["parameterized_tests"]["frameworks"][0]["matches"] = 91
        self.assertEqual(prune.strip_volatile(a), prune.strip_volatile(b))

    def test_a_growing_day_count_inside_an_issue_does_not_count_as_a_change(self):
        import copy
        from _support import prune_unchanged_reports as prune

        a, b = self.base(), copy.deepcopy(self.base())
        b["issues"] = ["No activity for 407 days"]
        self.assertEqual(prune.strip_volatile(a), prune.strip_volatile(b))

    def test_a_coverage_figure_moving_still_counts(self):
        import copy
        from _support import prune_unchanged_reports as prune

        a, b = self.base(), copy.deepcopy(self.base())
        b["coverage"]["coverage"] = 81.0
        self.assertNotEqual(prune.strip_volatile(a), prune.strip_volatile(b))


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
