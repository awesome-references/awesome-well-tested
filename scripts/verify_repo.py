#!/usr/bin/env python3
"""
verify_repo.py - Verify a GitHub repository's test quality for awesome-well-tested.

Usage:
    python verify_repo.py https://github.com/owner/repo
    python verify_repo.py owner/repo
    python verify_repo.py owner/repo --token ghp_xxx
    python verify_repo.py owner/repo --coverage 94.2 --mutation-score 81

Checks:
    1. Repository metadata (license, activity, stars)
    2. CI configuration (GitHub Actions, Travis, Jenkins, GitLab CI)
    3. Coverage tool configuration (JaCoCo, pytest-cov, Istanbul, etc.)
    4. Mutation testing configuration (PIT, mutmut, Stryker, etc.)
    5. Coverage badges and linked reports (Codecov, Coveralls)
    6. Actual coverage percentage, read from the Codecov or Coveralls API
    7. Mutation score, read from a Shields.io badge in the README

The tier is only awarded when the numbers are known: a configured coverage tool
alone proves nothing about the coverage level. Pass --coverage or
--mutation-score to supply figures the scripts cannot fetch.

Output:
    JSON report in reports/<owner>_<repo>.json
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API_BASE = "https://api.github.com"
CODECOV_API = "https://api.codecov.io/api/v2/github"
COVERALLS_API = "https://coveralls.io/github"
STRYKER_DASHBOARD_API = "https://dashboard.stryker-mutator.io/api/reports/github.com"

# How a mutation tool looks when a CI workflow actually runs it, as opposed to
# merely declaring it as a dependency.
MUTATION_INVOCATIONS = {
    "pit": r"pitest|pitestReport|mutationCoverage",
    "descartes": r"pitest.*descartes|mutationEngine",
    "stryker": r"stryker\s+run|npx\s+stryker",
    "stryker4s": r"stryker4s|sbt.*stryker",
    "stryker-net": r"dotnet[-\s]stryker",
    "infection": r"infection(?:\.phar)?\s|--min-msi",
    "pest-mutate": r"pest[^\n]{0,40}--mutate",
    "mutmut": r"mutmut\s+run",
    "cosmic-ray": r"cosmic-ray\s+(?:init|exec)",
    "mutatest": r"mutatest\s",
    "mutpy": r"mut\.py\s",
    "mutant": r"mutant\s+run|bundle\s+exec\s+mutant",
    "mutest": r"mutest\s+run",
    "cargo-mutants": r"cargo\s+mutants",
    "mutagen": r"cargo\s+mutagen",
    "go-mutesting": r"go-mutesting",
    "gremlins": r"gremlins\s+unleash",
    "ooze": r"\booze\b",
    "muter": r"muter\s+run",
    "mutation-test": r"dart\s+run\s+mutation_test",
    "muzak": r"mix\s+muzak",
    "mucheck": r"mucheck",
    "mull": r"mull-runner|mull-cxx",
    "dextool-mutate": r"dextool\s+mutate",
}

# A threshold the build fails below. The number is a floor somebody else's
# machine has verified, which is what makes it usable as evidence.
#
# Keyed by tool: a repository can carry configuration for more than one, and
# reading Stryker's "break" as if it were PIT's mutationThreshold would award a
# tier on a number belonging to something else.
MUTATION_THRESHOLDS = {
    "pit": [
        r"mutationThreshold\s*[=:]\s*(\d+(?:\.\d+)?)",
        r"<mutationThreshold>\s*(\d+(?:\.\d+)?)\s*</mutationThreshold>",
    ],
    "infection": [
        r"--min-msi[= ](\d+(?:\.\d+)?)",
        r"[\"']minMsi[\"']\s*:\s*(\d+(?:\.\d+)?)",
    ],
    "stryker": [
        r"[\"']break[\"']\s*:\s*(\d+(?:\.\d+)?)",
        r"--break-at[= ](\d+(?:\.\d+)?)",
    ],
}

# Bounds on the parameterized-test check: enough evidence, or enough spent
# looking. Code search costs one request per term and is tightly rate limited.
MAX_PARAMETERIZED_HITS = 2
MAX_PARAMETERIZED_QUERIES = 4

# Minimum line/branch coverage required for any tier
MIN_COVERAGE = 80.0
# Minimum mutation score required for Gold
MIN_MUTATION_SCORE = 70.0

# Detection patterns per category
CI_PATTERNS = {
    "github_actions": [".github/workflows"],
    "travis": [".travis.yml"],
    "jenkins": ["Jenkinsfile"],
    "gitlab_ci": [".gitlab-ci.yml"],
    "circle_ci": [".circleci/config.yml"],
}

COVERAGE_TOOLS = {
    "jacoco": {
        # Multi-module builds often configure coverage in a convention plugin or
        # only in CI, so the workflows are searched as well as the root build.
        "files": ["pom.xml", "build.gradle", "build.gradle.kts", ".github/workflows"],
        "patterns": [
            r"jacoco",
            r"org\.jacoco",
            r"jacocoTestReport",
            r"jacocoTestCoverageVerification",
        ],
        "language": "Java/Kotlin/Scala/Groovy",
    },
    "kover": {
        "files": ["build.gradle", "build.gradle.kts", ".github/workflows"],
        # A leading word boundary only: "\bkover\b" fails on koverXmlReport and
        # koverVerify, while a bare "kover" matches "stackoverflow".
        "patterns": [r"kotlinx\.kover", r"\bkover"],
        "language": "Kotlin",
    },
    "pytest-cov": {
        "files": [
            "pyproject.toml",
            "setup.cfg",
            "pytest.ini",
            "tox.ini",
            "noxfile.py",
            ".github/workflows",
        ],
        # "--cov" without the boundary is a prefix of "--coverage-clover", so
        # it matched every PHP workflow that collects coverage.
        "patterns": [r"pytest-cov", r"--cov\b", r"--cov="],
        "language": "Python",
    },
    "coverage.py": {
        # "[tool.coverage]" is not a section coverage.py reads - the real ones
        # are [tool.coverage.run], [tool.coverage.report] and friends - so the
        # pattern that used to be here could never match anything.
        # No workflows here. "coverage report" and "coverage xml" read as
        # commands in a config file but as ordinary English in a CI step name -
        # "Upload coverage report" matched every ecosystem.
        "files": ["pyproject.toml", "setup.cfg", ".coveragerc", "tox.ini"],
        "patterns": [
            r"\[tool\.coverage\.",
            r"\[coverage:",
            r"coverage run",
            r"coverage combine",
        ],
        "language": "Python",
    },
    "istanbul": {
        "files": ["package.json", ".nycrc", ".nycrc.json", ".github/workflows"],
        # Every pattern names a package or a flag, never a bare word. "istanbul"
        # on its own matches the timezone Europe/Istanbul in a CI matrix, and
        # "\bc8\b" matches a container tag like quay.io/centos/centos:c8.
        "patterns": [
            r"babel-plugin-istanbul",
            r"istanbul-lib",
            r"@istanbuljs",
            r"[\"']nyc[\"']",
            r"\bnyc\s+--",
            r"[\"']c8[\"']",
            r"\bc8\s+--",
            r"collectCoverage",
            r"@vitest/coverage",
        ],
        "language": "JavaScript/TypeScript",
    },
    "go_cover": {
        "files": ["Makefile", ".github/workflows"],
        "patterns": [r"-coverprofile", r"go tool cover"],
        "language": "Go",
    },
    "tarpaulin": {
        "files": ["Cargo.toml", ".github/workflows"],
        "patterns": [r"cargo-tarpaulin", r"tarpaulin"],
        "language": "Rust",
    },
    "phpunit": {
        "files": [
            "composer.json",
            "phpunit.xml",
            "phpunit.xml.dist",
            ".github/workflows",
        ],
        # Not "phpunit": every PHP project declares phpunit/phpunit as a dev
        # dependency, and the test runner's name is not evidence that coverage
        # is collected. Not bare "xdebug" either: its commonest appearance in a
        # workflow is the line that turns coverage off.
        "patterns": [
            r"coverage-clover",
            r"coverage-cobertura",
            r"coverage-text",
            r"php-coveralls",
            r"coverage:\s*(?:pcov|xdebug)",
            r"xdebug\.mode\s*=\s*coverage",
            r"pcov\.enabled",
            r"<coverage",
        ],
        "language": "PHP",
    },
    "simplecov": {
        "files": ["Gemfile", ".simplecov", ".github/workflows"],
        "patterns": [r"simplecov", r"SimpleCov"],
        "language": "Ruby",
    },
    "scoverage": {
        "files": ["build.sbt", "project/plugins.sbt", "pom.xml", ".github/workflows"],
        "patterns": [r"scoverage", r"sbt-scoverage", r"coverageMinimumStmtTotal"],
        "language": "Scala",
    },
    "clover": {
        # Never a bare "clover": clover.xml is the near-universal XML coverage
        # report format, written by PHPUnit, Istanbul and Jest alike.
        "files": ["pom.xml", "build.gradle", "build.xml", ".github/workflows"],
        "patterns": [r"openclover", r"org\.openclover", r"com\.atlassian\.clover",
                     r"clover-maven-plugin"],
        "language": "Java/Groovy",
    },
    "cobertura": {
        "files": ["pom.xml", "build.gradle", ".github/workflows"],
        "patterns": [r"cobertura-maven-plugin", r"net\.sourceforge\.cobertura",
                     r"net\.saliman\.cobertura"],
        "language": "Java",
    },
    "c8": {
        "files": ["package.json", ".c8rc", ".c8rc.json", ".github/workflows"],
        "patterns": [r"[\"']c8[\"']\s*:", r"npx c8\b",
                     r"\bc8\s+(?:--|node|npm|yarn|pnpm|npx|mocha|ava|tap|vitest|deno)"],
        "language": "JavaScript/TypeScript",
    },
    "vitest-coverage": {
        "files": ["package.json", "vitest.config.ts", "vitest.config.js", ".github/workflows"],
        "patterns": [r"@vitest/coverage-v8", r"@vitest/coverage-istanbul"],
        "language": "JavaScript/TypeScript",
    },
    "jest-coverage": {
        "files": ["package.json", "jest.config.js", "jest.config.ts", ".github/workflows"],
        "patterns": [r"coverageThreshold", r"coverageReporters", r"coveragePathIgnorePatterns"],
        "language": "JavaScript/TypeScript",
    },
    "deno-coverage": {
        "files": ["deno.json", "deno.jsonc", ".github/workflows"],
        "patterns": [r"deno\s+coverage\b"],
        "language": "TypeScript",
    },
    "php-coveralls": {
        "files": ["composer.json", ".github/workflows"],
        "patterns": [r"php-coveralls", r"coveralls\.phar"],
        "language": "PHP",
    },
    "undercover": {
        "files": ["Gemfile", ".github/workflows"],
        "patterns": [r"[\"']undercover[\"']", r"undercover\s+--compare"],
        "language": "Ruby",
    },
    "deep-cover": {
        "files": ["Gemfile", ".github/workflows"],
        "patterns": [r"deep[-_]cover", r"DeepCover"],
        "language": "Ruby",
    },
    "cargo-llvm-cov": {
        "files": ["Cargo.toml", "Makefile", ".github/workflows"],
        "patterns": [r"cargo[-\s]llvm-cov"],
        "language": "Rust",
    },
    "grcov": {
        "files": ["Cargo.toml", "Makefile", ".github/workflows"],
        "patterns": [r"\bgrcov\b"],
        "language": "Rust",
    },
    "goveralls": {
        "files": ["Makefile", ".github/workflows"],
        "patterns": [r"\bgoveralls\b", r"mattn/goveralls"],
        "language": "Go",
    },
    "gocov": {
        "files": ["Makefile", ".github/workflows"],
        "patterns": [r"axw/gocov", r"gocov-xml", r"gocovmerge"],
        "language": "Go",
    },
    "octocov": {
        "files": [".octocov.yml", "Makefile", ".github/workflows"],
        "patterns": [r"k1LoW/octocov", r"\boctocov\b"],
        "language": "Go",
    },
    "go-test-coverage": {
        # Not "local-prefix": a Go import-path setting shared by several
        # unrelated tools, naming none of them.
        "files": [".testcoverage.yml", "Makefile", ".github/workflows"],
        "patterns": [r"vladopajic/go-test-coverage", r"go-test-coverage@v"],
        "language": "Go",
    },
    "coverlet": {
        # Not "coverlet.collector": dotnet new xunit writes that PackageReference
        # into every generated test project whether or not anyone collects
        # anything. These are the things that only appear when someone does.
        "files": ["Directory.Build.props", "Makefile", ".github/workflows"],
        "patterns": [r"coverlet\.msbuild", r"coverlet\.console",
                     r"CollectCoverage\s*=\s*true", r"CoverletOutputFormat",
                     r"--collect[: ]+[\"']?XPlat Code Coverage"],
        "language": "C#/F#/Visual Basic .NET",
    },
    "altcover": {
        "files": ["Directory.Build.props", ".github/workflows"],
        "patterns": [r"\baltcover\b", r"AltCover=true"],
        "language": "C#/F#/Visual Basic .NET",
    },
    "dotcover": {
        "files": ["Directory.Build.props", "Makefile", ".github/workflows"],
        "patterns": [r"jetbrains\.dotcover", r"dotnet\s+dotcover",
                     r"dotcover\s+(?:cover|analyse|report)", r"dotCover\.exe"],
        "language": "C#/Visual Basic .NET",
    },
    "opencover": {
        "files": ["Makefile", ".github/workflows"],
        "patterns": [r"opencover\.console", r"opencover\.exe"],
        "language": "C#/Visual Basic .NET",
    },
    "xccov": {
        "files": ["Package.swift", "Makefile", ".github/workflows"],
        "patterns": [r"xcrun\s+xccov", r"--enable-code-coverage", r"-enableCodeCoverage"],
        "language": "Swift",
    },
    "slather": {
        "files": ["Gemfile", ".slather.yml", ".github/workflows"],
        "patterns": [r"\bslather\b"],
        "language": "Swift",
    },
    "flutter-coverage": {
        "files": ["pubspec.yaml", "Makefile", ".github/workflows"],
        "patterns": [r"flutter\s+test[^\n]*--coverage", r"dart\s+test[^\n]*--coverage",
                     r"format_coverage", r"\bcoverde\b"],
        "language": "Dart",
    },
    "excoveralls": {
        "files": ["mix.exs", ".github/workflows"],
        "patterns": [r"excoveralls", r"tool:\s*ExCoveralls"],
        "language": "Elixir",
    },
    "hpc": {
        "files": ["stack.yaml", "Makefile", ".github/workflows"],
        "patterns": [r"hpc-coveralls", r"-fhpc", r"hpc\s+(?:report|markup)"],
        "language": "Haskell",
    },
    "gcov-lcov": {
        "files": ["Makefile", "CMakeLists.txt", ".github/workflows"],
        "patterns": [r"-fprofile-arcs", r"-ftest-coverage", r"-fprofile-instr-generate",
                     r"-fcoverage-mapping", r"\bgcovr\b", r"\bgenhtml\b",
                     r"llvm-cov\s+(?:show|export|gcov)"],
        "language": "C/C++",
    },
    "opencppcoverage": {
        "files": ["Makefile", "CMakeLists.txt", ".github/workflows"],
        "patterns": [r"OpenCppCoverage"],
        "language": "C++",
    },
}

MUTATION_TOOLS = {
    "pit": {
        "files": ["pom.xml", "build.gradle", "build.gradle.kts"],
        "patterns": [r"pitest", r"org\.pitest", r"pit-maven", r"info\.solidsoft\.pitest",
                     r"mutationCoverage", r"arcmutate"],
        "language": "Java/Kotlin/Scala/Groovy",
    },
    "mutmut": {
        "files": ["pyproject.toml", "setup.cfg"],
        "patterns": [r"mutmut", r"\[tool\.mutmut\]"],
        "language": "Python",
    },
    "cosmic-ray": {
        "files": ["pyproject.toml", "setup.cfg", ".cosmic-ray.toml"],
        "patterns": [r"cosmic.ray", r"cosmic_ray"],
        "language": "Python",
    },
    "stryker": {
        "files": ["package.json", "stryker.conf.js", "stryker.conf.mjs", "stryker.conf.json"],
        "patterns": [r"@stryker-mutator", r"stryker"],
        "language": "JavaScript/TypeScript",
    },
    "cargo-mutants": {
        "files": ["Cargo.toml", ".github/workflows", "Makefile"],
        "patterns": [r"cargo.mutants", r"cargo-mutants"],
        "language": "Rust",
    },
    "go-mutesting": {
        "files": ["Makefile", ".github/workflows"],
        "patterns": [r"go-mutesting"],
        "language": "Go",
    },
    "mutant": {
        # A Gemfile-only list missed projects that only invoke mutant from CI.
        "files": ["Gemfile", "mutant.yml", ".github/workflows"],
        "patterns": [r"\bmutant\b", r"mutant[/-]rspec", r"mutant[/-]minitest",
                     r"mutant-license"],
        "language": "Ruby",
    },
    "infection": {
        "files": ["composer.json", "infection.json", "infection.json.dist"],
        "patterns": [r"infection", r"infection/infection"],
        "language": "PHP",
    },
    "descartes": {
        "files": ["pom.xml", "build.gradle", "build.gradle.kts", ".github/workflows"],
        "patterns": [r"pitest-descartes", r"eu\.stamp-project"],
        "language": "Java/Kotlin/Scala/Groovy",
    },
    "stryker4s": {
        "files": ["build.sbt", "project/plugins.sbt", "stryker4s.conf", ".github/workflows"],
        "patterns": [r"stryker4s", r"sbt-stryker4s"],
        "language": "Scala",
    },
    "mutatest": {
        "files": ["pyproject.toml", "setup.cfg", ".github/workflows"],
        "patterns": [r"\bmutatest"],
        "language": "Python",
    },
    "mutpy": {
        "files": ["pyproject.toml", "setup.cfg", ".github/workflows"],
        "patterns": [r"\bmutpy\b", r"mut\.py\s+--target"],
        "language": "Python",
    },
    "pest-mutate": {
        # Not "--mutate": too short and too common to stand alone.
        "files": ["composer.json", ".github/workflows"],
        "patterns": [r"pestphp/pest-plugin-mutate"],
        "language": "PHP",
    },
    "mutest": {
        "files": ["Gemfile", ".github/workflows"],
        "patterns": [r"\bmutest\b", r"mutest-rspec"],
        "language": "Ruby",
    },
    "mutagen": {
        "files": ["Cargo.toml", ".github/workflows"],
        "patterns": [r"llogiq/mutagen", r"mutagen\s*=\s*[\"{]"],
        "language": "Rust",
    },
    "gremlins": {
        # Not "timeout-coefficient": a generic config key naming no tool.
        "files": [".gremlins.yaml", "Makefile", ".github/workflows"],
        "patterns": [r"go-gremlins/gremlins", r"gremlins-lang/gremlins",
                     r"gremlins\s+unleash"],
        "language": "Go",
    },
    "ooze": {
        "files": ["go.mod", "Makefile", ".github/workflows"],
        "patterns": [r"gtramontina/ooze"],
        "language": "Go",
    },
    "stryker-net": {
        "files": ["Directory.Build.props", "stryker-config.json", ".github/workflows"],
        "patterns": [r"dotnet-stryker", r"dotnet\s+stryker", r"stryker-config",
                     r"StrykerOutput"],
        "language": "C#/F#/Visual Basic .NET",
    },
    "muter": {
        # Not "\bmuter\b": five letters that occur inside ordinary identifiers.
        "files": [".muter.conf.yml", "Makefile", ".github/workflows"],
        "patterns": [r"muter-mutation-testing", r"muter\s+run"],
        "language": "Swift",
    },
    "mutation-test": {
        "files": ["pubspec.yaml", ".github/workflows"],
        "patterns": [r"mutation_test\s*:\s*[\^0-9]", r"dart\s+run\s+mutation_test"],
        "language": "Dart",
    },
    "muzak": {
        "files": ["mix.exs", ".github/workflows"],
        "patterns": [r"\{:muzak", r"mix\s+muzak"],
        "language": "Elixir",
    },
    "mucheck": {
        "files": ["stack.yaml", ".github/workflows"],
        "patterns": [r"MuCheck", r"mucheck-"],
        "language": "Haskell",
    },
    "mull": {
        "files": ["Makefile", "CMakeLists.txt", ".github/workflows"],
        "patterns": [r"mull-runner", r"mull-cxx", r"mull-ir-frontend"],
        "language": "C/C++",
    },
    "dextool-mutate": {
        # Not "\bdextool\b": its most-used subcommands generate test doubles,
        # and a mutation-tool hit is what promotes a repository to Silver.
        "files": ["Makefile", "CMakeLists.txt", ".github/workflows"],
        "patterns": [r"dextool\s+mutate", r"dextool_mutate"],
        "language": "C/C++",
    },
}

# Shields.io badges are the common way to publish a mutation score, since no
# hosted service reports one. Example: mutation%20coverage-98%25-brightgreen
MUTATION_BADGE_PATTERN = (
    r"img\.shields\.io/badge/"
    r"mutation(?:%20|[-_ ])?(?:coverage|score|testing)"
    # The fraction is part of the number: truncating 69.8 to 69 turns a Gold
    # entry into a Silver one.
    r"[-_]{1,2}(\d{1,3}(?:\.\d+)?)%25"
)

# Parameterized and property-based tests are a quality signal that coverage
# cannot express: they exercise a function across many inputs instead of one.
# Detected with repository-scoped code search, one query per marker, because
# code search does not honour OR between terms.
#
# Keys are the language GitHub reports for the repository. Go is deliberately
# absent: table-driven tests are idiomatic there but use no keyword of their
# own, so any marker would be guesswork.
PARAMETERIZED_MARKERS = {
    "Java": [
        ("ParameterizedTest", "JUnit 5 @ParameterizedTest"),
        ("RunWith(Parameterized", "JUnit 4 @Parameterized"),
        ("dataProviderClass", "TestNG @DataProvider"),
        ("jqwik", "jqwik (property-based)"),
        ("QuickTheories", "QuickTheories (property-based)"),
    ],
    "Kotlin": [
        ("ParameterizedTest", "JUnit 5 @ParameterizedTest"),
        # Not "withData": it matches ordinary builder methods. The import has to
        # be there for the data-driven DSL to exist at all.
        ("io.kotest.datatest", "Kotest data-driven testing"),
        ("checkAll", "Kotest property testing"),
    ],
    "Scala": [
        ("scalacheck", "ScalaCheck (property-based)"),
        ("TableDrivenPropertyChecks", "ScalaTest table-driven checks"),
    ],
    "Groovy": [
        ("@Unroll", "Spock @Unroll"),
        ("ParameterizedTest", "JUnit 5 @ParameterizedTest"),
    ],
    "Python": [
        ("parametrize", "pytest.mark.parametrize"),
        ("hypothesis", "Hypothesis (property-based)"),
        ("parameterized.expand", "parameterized.expand"),
        ("subTest", "unittest subTest"),
    ],
    "JavaScript": [
        ("describe.each", "Jest/Vitest .each"),
        ("test.each", "Jest/Vitest .each"),
        ("fast-check", "fast-check (property-based)"),
    ],
    "TypeScript": [
        ("describe.each", "Jest/Vitest .each"),
        ("test.each", "Jest/Vitest .each"),
        ("fast-check", "fast-check (property-based)"),
    ],
    "Rust": [
        ("rstest", "rstest"),
        ("test-case", "test-case"),
        ("proptest", "proptest (property-based)"),
        ("quickcheck", "quickcheck (property-based)"),
    ],
    "Go": [
        # Table-driven tests still have no keyword and are still undetectable.
        # These are the Go constructs that do announce themselves.
        ("gopter", "gopter (property-based)"),
        ("pgregory.net/rapid", "rapid (property-based)"),
        ("DescribeTable", "Ginkgo DescribeTable"),
        ("testing/quick", "testing/quick (property-based)"),
    ],
    "Ruby": [
        # Not "shared_examples" or "it_behaves_like": those share example code
        # between contexts, which is reuse, not running one example over many
        # inputs.
        ("rspec-parameterized", "rspec-parameterized"),
        ("rantly", "Rantly (property-based)"),
        ("prop_check", "PropCheck (property-based)"),
    ],
    "C#": [
        # Not bare "TestCase": it is a substring of TestCaseSource and appears
        # in ordinary prose and method names.
        ("InlineData", "xUnit [Theory]/[InlineData]"),
        ("MemberData", "xUnit [MemberData]"),
        ("TestCaseSource", "NUnit [TestCaseSource]"),
        ("DataTestMethod", "MSTest [DataTestMethod]"),
        ("FsCheck", "FsCheck (property-based)"),
    ],
    "F#": [
        ("FsCheck", "FsCheck (property-based)"),
        ("testProperty", "Expecto testProperty"),
        ("InlineData", "xUnit [Theory]/[InlineData]"),
    ],
    "Visual Basic .NET": [
        ("InlineData", "xUnit [Theory]/[InlineData]"),
        ("DataTestMethod", "MSTest [DataTestMethod]"),
    ],
    "PHP": [
        # Not "dataset": too common a word outside Pest.
        ("dataProvider", "PHPUnit @dataProvider"),
        ("giorgiosironi/eris", "Eris (property-based)"),
        ("innmind/black-box", "BlackBox (property-based)"),
    ],
    "Swift": [
        # Not "itBehavesLike": Quick's shared examples are reuse, not
        # parameterization, for the same reason as Ruby's.
        ("SwiftCheck", "SwiftCheck (property-based)"),
        ("Test(arguments", "Swift Testing arguments"),
    ],
    "Dart": [
        ("glados", "glados (property-based)"),
        ("parameterized_test", "parameterized_test"),
    ],
    "Elixir": [
        ("ExUnitProperties", "StreamData property testing"),
        ("PropCheck", "PropCheck (property-based)"),
        ("param_test", "param_test"),
    ],
    "Haskell": [
        ("QuickCheck", "QuickCheck (property-based)"),
        ("SmallCheck", "SmallCheck (property-based)"),
        ("hedgehog", "Hedgehog (property-based)"),
    ],
    "C++": [
        ("INSTANTIATE_TEST_SUITE_P", "GoogleTest parameterized suite"),
        ("TEMPLATE_TEST_CASE", "Catch2 template test case"),
        ("rapidcheck", "RapidCheck (property-based)"),
    ],
    "C": [
        ("cmocka_unit_test_prestate", "cmocka prestate tests"),
        ("theft_run", "theft (property-based)"),
    ],
}

# Coverage badges only. A Code Climate badge is usually maintainability and a
# SonarCloud one is usually quality gate, so both have to name the coverage
# metric before they count. Matched case-insensitively: badge URLs are written
# by hand and their casing varies.
BADGE_PATTERNS = [
    (r"codecov\.io/(?:gh|github)/([^/\s)]+/[^/\s)]+)", "Codecov"),
    (r"coveralls\.io/(?:repos/)?github/([^/\s)]+/[^/\s)]+)", "Coveralls"),
    (r"codeclimate\.com/github/([^/\s)]+/[^/\s)]+)/badges/[^/\s)]*coverage", "Code Climate"),
    (r"api\.codeclimate\.com/v1/badges/[^/\s)]+/test_coverage", "Code Climate"),
    (r"sonarcloud\.io/api/project_badges/measure\?[^\s)\"']*metric=coverage", "SonarCloud"),
    (r"img\.shields\.io/(?:codecov|coveralls)/", "Shields.io (service badge)"),
    (r"img\.shields\.io/badge/coverage", "Shields.io (manual badge)"),
]


class VerificationIncomplete(Exception):
    """A check could not be carried out, as opposed to having found nothing.

    The distinction decides whether an entry is removed from the list. A
    repository that no longer publishes 80% coverage should come off; one whose
    coverage service happened to answer 429 must not. Everything that talks to
    the network raises this rather than returning a value that reads like a
    negative result.
    """


class RepositoryMissing(Exception):
    """The repository is gone: renamed away, deleted, or made private.

    Unlike VerificationIncomplete this is an answer, and a listed entry that
    raises it does belong off the list.
    """


class GitHubAPI:
    """Minimal GitHub API client using urllib."""

    # 403 is the primary rate limit, 429 the secondary one; 5xx is the service
    # having a bad day. All three are worth waiting out rather than treating as
    # an answer.
    RETRY_CODES = (403, 429, 500, 502, 503, 504)
    MAX_ATTEMPTS = 4

    def __init__(self, token: str | None = None, retries: int | None = None):
        self.headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "awesome-well-tested",
        }
        self.authenticated = bool(token)
        self.attempts = self.MAX_ATTEMPTS if retries is None else retries
        self.requests = 0
        if token:
            self.headers["Authorization"] = f"token {token}"

    def _sleep_for(self, error: urllib.error.HTTPError, attempt: int) -> float:
        """How long to wait, preferring what the server asked for."""
        retry_after = error.headers.get("Retry-After")
        if retry_after and retry_after.isdigit():
            return min(int(retry_after), 120)
        reset = error.headers.get("X-RateLimit-Reset")
        remaining = error.headers.get("X-RateLimit-Remaining")
        if reset and remaining == "0":
            try:
                wait = int(reset) - int(time.time())
                if 0 < wait <= 120:
                    return wait
            except ValueError:
                pass
        return min(2 ** attempt, 60)

    def _request(self, url: str, headers: dict, decode, absent_codes=(404, 422)):
        """Issue a request, retrying what is worth retrying.

        Returns None for 404 and 422 - the resource genuinely is not there, or
        the query was rejected - and raises VerificationIncomplete for anything
        that means "ask again later".
        """
        for attempt in range(1, self.attempts + 1):
            req = urllib.request.Request(url, headers=headers)
            try:
                self.requests += 1
                with urllib.request.urlopen(req, timeout=20) as resp:
                    return decode(resp)
            except urllib.error.HTTPError as e:
                if e.code in absent_codes:
                    return None
                if e.code in self.RETRY_CODES and attempt < self.attempts:
                    wait = self._sleep_for(e, attempt)
                    print(
                        f"  HTTP {e.code} from {url.split('?')[0]}, "
                        f"retrying in {wait}s [{attempt}/{self.attempts - 1}]",
                        file=sys.stderr,
                    )
                    time.sleep(wait)
                    continue
                raise VerificationIncomplete(f"HTTP {e.code} for {url}") from e
            except (urllib.error.URLError, TimeoutError) as e:
                if attempt < self.attempts:
                    time.sleep(min(2 ** attempt, 30))
                    continue
                raise VerificationIncomplete(f"network error for {url}: {e}") from e
            except json.JSONDecodeError as e:
                raise VerificationIncomplete(f"malformed JSON from {url}") from e
        raise VerificationIncomplete(f"gave up on {url}")

    def get(self, url: str) -> dict | list | None:
        return self._request(
            url, self.headers, lambda resp: json.loads(resp.read().decode())
        )

    def get_public_json(self, url: str) -> dict | list | None:
        """GET JSON from a non-GitHub public endpoint (Codecov, Coveralls).

        Deliberately does not send the GitHub token: these are third-party hosts.
        """
        headers = {"Accept": "application/json", "User-Agent": "awesome-well-tested"}
        # A coverage service answers 401 or 403 for a repository it does not
        # track, not only for a caller it is throttling. Retrying that as if it
        # were a rate limit, and then giving up on the whole verification, would
        # mean an entry never gets rechecked again.
        return self._request(
            url,
            headers,
            lambda resp: json.loads(resp.read().decode()),
            absent_codes=(401, 403, 404, 422, 451),
        )

    def get_text(self, url: str) -> str | None:
        headers = {**self.headers, "Accept": "application/vnd.github.v3.raw"}
        return self._request(
            url, headers, lambda resp: resp.read().decode(errors="replace")
        )


def parse_repo_arg(arg: str) -> tuple[str, str]:
    """Extract owner/repo from URL or shorthand."""
    arg = arg.rstrip("/")
    match = re.search(r"github\.com/([^/]+)/([^/]+)", arg)
    if match:
        return match.group(1), match.group(2)
    parts = arg.split("/")
    if len(parts) == 2:
        return parts[0], parts[1]
    print(f"Cannot parse repo: {arg}", file=sys.stderr)
    sys.exit(1)


def check_repo_metadata(api: GitHubAPI, owner: str, repo: str) -> dict:
    """Check basic repo info: license, activity, language."""
    data = api.get(f"{API_BASE}/repos/{owner}/{repo}")
    if not data:
        raise RepositoryMissing(f"{owner}/{repo}")

    pushed_at = data.get("pushed_at", "")
    days_since_push = None
    if pushed_at:
        pushed = datetime.fromisoformat(pushed_at.replace("Z", "+00:00"))
        days_since_push = (datetime.now(timezone.utc) - pushed).days

    return {
        "full_name": data.get("full_name"),
        "description": data.get("description"),
        "language": data.get("language"),
        "license": data.get("license", {}).get("spdx_id") if data.get("license") else None,
        "stars": data.get("stargazers_count", 0),
        "forks": data.get("forks_count", 0),
        "archived": data.get("archived", False),
        "fork": data.get("fork", False),
        "last_push": pushed_at,
        "days_since_push": days_since_push,
        "default_branch": data.get("default_branch", "main"),
    }


def check_ci(
    api: GitHubAPI, owner: str, repo: str, branch: str, tree: set | None = None
) -> dict:
    """Detect CI configuration.

    With the tree in hand this costs nothing: every CI marker is a path, and
    asking whether a path exists is a set lookup rather than a request.
    """
    found = {}

    if tree is not None:
        workflow_names = sorted(
            path.split("/", 2)[2]
            for path in tree
            if path.startswith(".github/workflows/") and path.count("/") == 2
        )
        if workflow_names:
            found["github_actions"] = workflow_names
        for ci_name, paths in CI_PATTERNS.items():
            if ci_name == "github_actions":
                continue
            if any(path in tree for path in paths):
                found[ci_name] = True
        return found

    workflows = api.get(f"{API_BASE}/repos/{owner}/{repo}/contents/.github/workflows?ref={branch}")
    if workflows and isinstance(workflows, list):
        found["github_actions"] = [w["name"] for w in workflows if w.get("name")]

    for ci_name, paths in CI_PATTERNS.items():
        if ci_name == "github_actions":
            continue
        for path in paths:
            content = api.get(f"{API_BASE}/repos/{owner}/{repo}/contents/{path}?ref={branch}")
            if content:
                found[ci_name] = True

    return found


def search_file_for_patterns(content: str, patterns: list[str]) -> list[str]:
    """Search file content for regex patterns, return matches."""
    matches = []
    for pattern in patterns:
        if re.search(pattern, content, re.IGNORECASE):
            matches.append(pattern)
    return matches


def fetch_tree(api: GitHubAPI, owner: str, repo: str, branch: str) -> set | None:
    """Every file path in the repository, in one request.

    Knowing what exists turns roughly twenty-five speculative fetches per
    repository - Cargo.toml in a Java project, composer.json in a Python one -
    into none. Returns None when the tree is unavailable or truncated, in which
    case callers must fall back to asking for each file.
    """
    data = api.get(f"{API_BASE}/repos/{owner}/{repo}/git/trees/{branch}?recursive=1")
    if not isinstance(data, dict) or data.get("truncated"):
        return None
    return {
        entry["path"]
        for entry in data.get("tree", [])
        if entry.get("type") == "blob" and entry.get("path")
    }


def fetch_workflow_contents(
    api: GitHubAPI, owner: str, repo: str, branch: str, tree: set | None = None
) -> dict:
    """Download every GitHub Actions workflow file so tools invoked only in CI are visible."""
    if tree is not None:
        names = sorted(
            path.split("/", 2)[2]
            for path in tree
            if path.startswith(".github/workflows/")
            and path.endswith((".yml", ".yaml"))
            and path.count("/") == 2
        )
    else:
        workflows = api.get(
            f"{API_BASE}/repos/{owner}/{repo}/contents/.github/workflows?ref={branch}"
        )
        if not workflows or not isinstance(workflows, list):
            return {}
        names = [
            w["name"] for w in workflows
            if w.get("name", "").endswith((".yml", ".yaml"))
        ]

    contents = {}
    for name in names:
        path = urllib.parse.quote(name)
        text = api.get_text(
            f"{API_BASE}/repos/{owner}/{repo}/contents/.github/workflows/{path}?ref={branch}"
        )
        if text:
            contents[f".github/workflows/{name}"] = text
    return contents


def check_tools(
    api: GitHubAPI,
    owner: str,
    repo: str,
    branch: str,
    tool_definitions: dict,
    workflow_contents: dict | None = None,
    file_cache: dict | None = None,
    tree: set | None = None,
) -> dict:
    """Check for coverage or mutation testing tools in config files and CI workflows.

    file_cache is shared between the coverage and mutation passes. Without it
    every build file common to both - pom.xml, package.json, Cargo.toml and
    eight others - is fetched twice, which is eleven wasted requests per
    repository against an hourly budget that a full recheck already strains.
    """
    found = {}
    checked_files: dict[str, str | None] = file_cache if file_cache is not None else {}
    workflow_contents = workflow_contents or {}

    for tool_name, tool_info in tool_definitions.items():
        for filename in tool_info["files"]:
            # ".github/workflows" is a directory marker: scan every workflow file instead
            if filename == ".github/workflows":
                for wf_path, wf_text in workflow_contents.items():
                    matches = search_file_for_patterns(wf_text, tool_info["patterns"])
                    if matches:
                        found[tool_name] = {
                            "file": wf_path,
                            "language": tool_info["language"],
                            "matched_patterns": matches,
                        }
                        break
                continue

            if filename not in checked_files:
                if tree is not None and filename not in tree:
                    checked_files[filename] = None
                else:
                    checked_files[filename] = api.get_text(
                        f"{API_BASE}/repos/{owner}/{repo}/contents/"
                        f"{urllib.parse.quote(filename)}?ref={branch}"
                    )

            content = checked_files[filename]
            if not content:
                continue

            matches = search_file_for_patterns(content, tool_info["patterns"])
            if matches:
                found[tool_name] = {
                    "file": filename,
                    "language": tool_info["language"],
                    "matched_patterns": matches,
                }

    return found


def extract_mutation_score_from_readme(readme: str) -> float | None:
    """Read a mutation score off a Shields.io badge in the README, if one is present."""
    match = re.search(MUTATION_BADGE_PATTERN, readme, re.IGNORECASE)
    if not match:
        return None
    score = float(match.group(1))
    return score if 0 <= score <= 100 else None


def fetch_readme(api: GitHubAPI, owner: str, repo: str, branch: str) -> str | None:
    """Fetch the README, trying the common filename variants."""
    # A repository whose README is spelled differently loses its badges and,
    # with them, any self-reported mutation score.
    variants = [
        "README.md", "readme.md", "Readme.md", "README.MD",
        "README.markdown", "README.rst", "readme.rst",
        "README.adoc", "README.asciidoc", "README.txt", "README",
    ]
    for variant in variants:
        content = api.get_text(
            f"{API_BASE}/repos/{owner}/{repo}/contents/{variant}?ref={branch}"
        )
        if content:
            return content
    return None


def check_badges(readme_content: str | None) -> list[dict]:
    """Check README for coverage badges."""
    if not readme_content:
        return []

    found = []
    for pattern, service in BADGE_PATTERNS:
        match = re.search(pattern, readme_content, re.IGNORECASE)
        if match:
            found.append({"service": service, "match": match.group(0)})

    return found


def check_parameterized_tests(
    api: GitHubAPI,
    owner: str,
    repo: str,
    language: str | None,
    throttle: float = 2.5,
) -> dict | None:
    """Detect parameterized or property-based tests in a repository.

    Uses repository-scoped code search, which needs an authenticated token and
    is rate limited far more tightly than the rest of the API, hence the
    throttle between queries. Returns None when the check could not run, which
    is not the same as finding nothing.
    """
    if not api.authenticated:
        return None

    markers = PARAMETERIZED_MARKERS.get(language or "")
    if not markers:
        return None

    frameworks = []
    queries = 0
    for term, label in markers:
        # Code search is rate limited to about 30 requests a minute and each
        # query needs its own, so this is bounded twice: enough evidence, or
        # enough spent looking. The column shows two or three names at most.
        if len(frameworks) >= MAX_PARAMETERIZED_HITS or queries >= MAX_PARAMETERIZED_QUERIES:
            break
        query = urllib.parse.quote(f"repo:{owner}/{repo} {term}")
        data = api.get(f"{API_BASE}/search/code?q={query}&per_page=1")
        queries += 1
        if isinstance(data, dict) and data.get("total_count", 0) > 0:
            label_names = {f["framework"] for f in frameworks}
            if label not in label_names:
                frameworks.append({"framework": label, "matches": data["total_count"]})
        time.sleep(throttle)

    return {
        "frameworks": frameworks,
        "detected": bool(frameworks),
        "language": language,
        "terms_tried": queries,
        "terms_available": len(markers),
    }


def _age_in_days(timestamp: str | None) -> int | None:
    """Days between a service's timestamp and now, or None if it is unreadable."""
    if not timestamp:
        return None
    text = timestamp.replace("Z", "+00:00")
    try:
        measured = datetime.fromisoformat(text)
    except ValueError:
        return None
    if measured.tzinfo is None:
        measured = measured.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - measured).days


def fetch_coverage_percent(
    api: GitHubAPI, owner: str, repo: str, default_branch: str | None = None
) -> dict | None:
    """Fetch the real coverage percentage from a public coverage service.

    Tries Codecov first, then Coveralls. Both expose public read endpoints for
    public repositories, so no extra credentials are needed.

    Both also answer with the last build they saw, on whatever branch that was,
    and neither says so unless asked. A figure from a release branch, a
    maintenance branch or a dependabot pull request is reported here as such,
    along with how old it is, because a number measured against code that has
    since been rewritten is not evidence about the code as it stands.
    """
    data = api.get_public_json(f"{CODECOV_API}/{owner}/repos/{repo}/")
    if isinstance(data, dict):
        totals = data.get("totals") or {}
        coverage = totals.get("coverage")
        if coverage is not None:
            branch = data.get("branch")
            measured_at = data.get("updatestamp")
            return {
                "service": "Codecov",
                "coverage": round(float(coverage), 2),
                "branch": branch,
                "is_default_branch": (
                    None if not (branch and default_branch) else branch == default_branch
                ),
                "measured_at": measured_at,
                "age_days": _age_in_days(measured_at),
                "source": f"https://codecov.io/gh/{owner}/{repo}",
            }

    data = api.get_public_json(f"{COVERALLS_API}/{owner}/{repo}.json")
    if isinstance(data, dict):
        coverage = data.get("covered_percent")
        if coverage is not None:
            branch = data.get("branch")
            measured_at = data.get("created_at")
            return {
                "service": "Coveralls",
                "coverage": round(float(coverage), 2),
                "branch": branch,
                "is_default_branch": (
                    None if not (branch and default_branch) else branch == default_branch
                ),
                "measured_at": measured_at,
                "age_days": _age_in_days(measured_at),
                "source": f"https://coveralls.io/github/{owner}/{repo}",
            }

    return None


# Projects that publish to the dashboard usually link it from their README,
# either as a shields endpoint badge or as a plain link to the report. Both name
# the branch, which saves guessing at it.
DASHBOARD_BADGE_PATTERNS = [
    r"badge-api\.stryker-mutator\.io%2Fgithub\.com%2F[^%]+%2F[^%]+%2F([^%&\)\"'\s]+)",
    r"dashboard\.stryker-mutator\.io/reports/github\.com/[^/]+/[^/]+/([^\)\"'\s#]+)",
]


def dashboard_branch_from_readme(readme: str | None) -> str | None:
    """The branch a project's own dashboard link points at."""
    if not readme:
        return None
    for pattern in DASHBOARD_BADGE_PATTERNS:
        match = re.search(pattern, readme)
        if match:
            branch = match.group(1).strip()
            if branch and "/" not in branch:
                return branch
    return None


def fetch_dashboard_mutation_score(
    api: GitHubAPI,
    owner: str,
    repo: str,
    default_branch: str | None,
    hinted_branch: str | None = None,
) -> dict | None:
    """Read a mutation score from the Stryker dashboard.

    This is the one mutation figure that is not self-reported. The report is
    produced by the repository's own CI, but it is stored and served by
    stryker-mutator.io at a URL the repository does not control, so a project
    cannot state a score it has not measured. Any tool emitting the
    mutation-testing-elements format can publish there, Stryker and Infection
    among them.
    """
    branches = [b for b in (hinted_branch, default_branch, "main", "master") if b]
    seen = set()
    for branch in branches:
        if branch in seen:
            continue
        seen.add(branch)
        report = api.get_public_json(f"{STRYKER_DASHBOARD_API}/{owner}/{repo}/{branch}")
        if not isinstance(report, dict) or "files" not in report:
            continue

        detected = total = 0
        for entry in report["files"].values():
            for mutant in entry.get("mutants", []):
                status = mutant.get("status")
                # NoCoverage counts against the score; Ignored and CompileError
                # are excluded, which is how the format defines it.
                if status in ("Killed", "Survived", "Timeout", "NoCoverage"):
                    total += 1
                if status in ("Killed", "Timeout"):
                    detected += 1
        if not total:
            continue

        return {
            "score": round(100 * detected / total, 2),
            "branch": branch,
            "mutants": total,
            "source": f"https://dashboard.stryker-mutator.io/reports/github.com/{owner}/{repo}/{branch}",
        }
    return None


def check_ci_enforced_mutation(
    api: GitHubAPI,
    owner: str,
    repo: str,
    branch: str,
    mutation_tools: dict,
    workflow_contents: dict,
    file_cache: dict,
) -> dict | None:
    """Detect a mutation run that CI performs and that fails below a threshold.

    A threshold the build enforces is a lower bound somebody else's machine has
    already checked: if the workflow is green, the score is at least that. That
    makes it evidence in a way a number typed into a README is not.
    """
    if not mutation_tools:
        return None

    invoking = None
    for path, text in workflow_contents.items():
        for tool in mutation_tools:
            if re.search(MUTATION_INVOCATIONS.get(tool, tool), text, re.IGNORECASE):
                invoking = (path, tool)
                break
        if invoking:
            break
    if not invoking:
        return None

    workflow_path, tool = invoking

    patterns = MUTATION_THRESHOLDS.get(tool)
    if not patterns:
        return None

    threshold = None
    for text in list(file_cache.values()) + list(workflow_contents.values()):
        if not text:
            continue
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    candidate = float(match.group(1))
                except (TypeError, ValueError):
                    continue
                if 0 < candidate <= 100:
                    threshold = candidate
                    break
        if threshold is not None:
            break
    if threshold is None:
        return None

    workflow_file = workflow_path.rsplit("/", 1)[-1]
    runs = api.get(
        f"{API_BASE}/repos/{owner}/{repo}/actions/workflows/"
        f"{urllib.parse.quote(workflow_file)}/runs"
        f"?branch={urllib.parse.quote(branch)}&per_page=1&status=completed"
    )
    conclusion = None
    if isinstance(runs, dict) and runs.get("workflow_runs"):
        conclusion = runs["workflow_runs"][0].get("conclusion")

    return {
        "tool": tool,
        "threshold": threshold,
        "workflow": workflow_path,
        "last_run": conclusion,
        "passing": conclusion == "success",
    }


# A mutation score only earns Gold when something other than the repository's
# own prose stands behind it.
GOLD_EVIDENCE = ("dashboard", "ci-threshold")


def determine_tier(
    ci: dict,
    coverage_tools: dict,
    mutation_tools: dict,
    coverage: dict | None,
    mutation_score: float | None,
    mutation_score_source: str | None = None,
) -> tuple[str | None, str]:
    """Determine the tier and the reason for it.

    Returns (tier, reason). A tier of None means the repo does not qualify yet;
    the reason explains what is missing or still unverified.
    """
    if not ci:
        return None, "No CI configuration found"

    if coverage is None:
        return None, (
            f"Coverage percentage could not be verified automatically; "
            f"supply it with --coverage once confirmed (>= {MIN_COVERAGE:.0f}% required)"
        )

    # A percentage published by Codecov or Coveralls is itself proof that CI
    # reports coverage: somebody had to upload it. Demanding that a coverage
    # tool also be recognisable in the build files on top of that rejected
    # repositories with published, verified coverage merely because their
    # tooling was not in the list - which is a gap in the list, not in them.
    if coverage["service"] == "manual" and not coverage_tools:
        return None, (
            "Coverage was supplied by hand and no coverage tool could be found in "
            "the repository, so there is nothing to corroborate the figure"
        )

    if coverage["coverage"] < MIN_COVERAGE:
        return None, (
            f"Coverage {coverage['coverage']}% is below the required {MIN_COVERAGE:.0f}%"
        )

    if not mutation_tools:
        return "bronze", (
            f"Coverage {coverage['coverage']}% with CI reporting, no mutation testing configured"
        )

    if mutation_score is None:
        return "silver", (
            "Mutation testing is configured but no mutation score could be established"
        )

    if mutation_score < MIN_MUTATION_SCORE:
        return "silver", (
            f"Mutation score {mutation_score}% is below the "
            f"{MIN_MUTATION_SCORE:.0f}% required for Gold"
        )

    if mutation_score_source not in GOLD_EVIDENCE:
        # The number is high enough, but nothing outside the repository stands
        # behind it. Anyone can write a percentage into their own README.
        return "silver", (
            f"Mutation score {mutation_score}% is self-reported; Gold needs either a "
            "score hosted by a service the repository does not control, or a mutation "
            "run that CI performs and fails below a threshold"
        )

    evidence = (
        "an independently hosted report"
        if mutation_score_source == "dashboard"
        else "a threshold the build enforces"
    )
    return "gold", (
        f"Coverage {coverage['coverage']}% and mutation score {mutation_score}%, "
        f"backed by {evidence}"
    )


def primary_coverage_tool(coverage_tools: dict, language: str | None) -> str | None:
    """Pick the tool to name for a repository when several patterns matched.

    Build and CI files borrow each other's vocabulary, so a repository can match
    more than one tool. The one whose language matches the repository is the
    honest answer.
    """
    if not coverage_tools:
        return None
    if language:
        # Split rather than substring-match: "Java" is a substring of
        # "JavaScript/TypeScript", so a Java repository could be credited with a
        # JavaScript coverage tool.
        for name, info in coverage_tools.items():
            languages = [part.strip() for part in (info.get("language") or "").split("/")]
            if language in languages:
                return name
    return next(iter(coverage_tools))


def generate_report(
    owner: str,
    repo: str,
    metadata: dict,
    ci: dict,
    coverage_tools: dict,
    mutation_tools: dict,
    badges: list[dict],
    coverage: dict | None,
    mutation_score: float | None,
    parameterized: dict | None = None,
    mutation_score_source: str | None = None,
    dashboard: dict | None = None,
    ci_enforced: dict | None = None,
) -> dict:
    """Generate the full verification report."""
    tier, tier_reason = determine_tier(
        ci, coverage_tools, mutation_tools, coverage, mutation_score, mutation_score_source
    )

    issues = []
    if metadata.get("archived"):
        issues.append("Repository is archived")
    if metadata.get("fork"):
        issues.append("Repository is a fork (submit upstream instead)")
    if not metadata.get("license"):
        issues.append("No license detected")
    if metadata.get("days_since_push") and metadata["days_since_push"] > 365:
        issues.append(f"No activity for {metadata['days_since_push']} days")
    if not ci:
        issues.append("No CI configuration found")
    if not coverage_tools:
        issues.append("No coverage tool configuration found")
    if coverage is None:
        issues.append("Coverage percentage not published on Codecov or Coveralls")

    return {
        "repository": f"{owner}/{repo}",
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "tier": tier,
        "tier_reason": tier_reason,
        "coverage": coverage,
        "mutation_score": mutation_score,
        "mutation_score_source": mutation_score_source,
        "mutation_dashboard": dashboard,
        "mutation_ci_enforced": ci_enforced,
        "parameterized_tests": parameterized,
        "issues": issues if issues else None,
        "metadata": metadata,
        "ci": ci if ci else None,
        "coverage_tools": coverage_tools if coverage_tools else None,
        "primary_coverage_tool": primary_coverage_tool(
            coverage_tools, metadata.get("language")
        ),
        "mutation_tools": mutation_tools if mutation_tools else None,
        "badges": badges if badges else None,
    }


def print_summary(report: dict) -> None:
    """Print a human-readable summary."""
    tier = report["tier"]
    repo = report["repository"]

    tier_display = {
        "gold": "GOLD",
        "silver": "SILVER",
        "bronze": "BRONZE",
        None: "NOT QUALIFIED",
    }

    print(f"\n{'=' * 60}")
    print(f"  Repository:  {repo}")
    print(f"  Language:    {report['metadata'].get('language', 'unknown')}")
    print(f"  Stars:       {report['metadata'].get('stars', 0)}")
    print(f"  License:     {report['metadata'].get('license', 'none')}")
    print(f"  Tier:        {tier_display.get(tier, 'UNKNOWN')}")
    print(f"{'=' * 60}")

    if report.get("ci"):
        print(f"\n  CI:          {', '.join(report['ci'].keys())}")

    if report.get("coverage"):
        cov = report["coverage"]
        detail = f"via {cov['service']}"
        if cov.get("branch"):
            detail += f", branch {cov['branch']}"
        if cov.get("age_days") is not None:
            detail += f", {cov['age_days']}d old"
        print(f"  Coverage:    {cov['coverage']}% ({detail})")

    if report.get("mutation_score") is not None:
        source = report.get("mutation_score_source") or "unknown"
        print(f"  Mut. score:  {report['mutation_score']}% ({source})")

    param = report.get("parameterized_tests")
    if param is not None:
        if param["frameworks"]:
            names = ", ".join(f["framework"] for f in param["frameworks"])
            print(f"  Param. tests: {names}")
        else:
            print(f"  Param. tests: none detected")

    if report.get("coverage_tools"):
        tools = ", ".join(report["coverage_tools"].keys())
        print(f"  Cov. tools:  {tools}")

    if report.get("mutation_tools"):
        tools = ", ".join(report["mutation_tools"].keys())
        print(f"  Mutation:    {tools}")

    if report.get("badges"):
        services = ", ".join(b["service"] for b in report["badges"])
        print(f"  Badges:      {services}")

    if report.get("issues"):
        print(f"\n  Issues:")
        for issue in report["issues"]:
            print(f"    - {issue}")

    print(f"\n  Reason:      {report['tier_reason']}")
    print()


def verify_repository(
    api: GitHubAPI,
    owner: str,
    repo: str,
    coverage_override: float | None = None,
    mutation_score_override: float | None = None,
    verbose: bool = True,
) -> dict:
    """Run every check against one repository and return the report.

    Kept separate from main() so other scripts (and CI) can verify repositories
    in-process instead of shelling out once per repository.
    """

    def say(message: str) -> None:
        if verbose:
            print(message)

    metadata = check_repo_metadata(api, owner, repo)
    branch = metadata["default_branch"]

    tree = fetch_tree(api, owner, repo, branch)

    say("  Checking CI configuration...")
    ci = check_ci(api, owner, repo, branch, tree)
    workflow_contents = fetch_workflow_contents(api, owner, repo, branch, tree)

    file_cache: dict[str, str | None] = {}

    say("  Checking coverage tools...")
    coverage_tools = check_tools(
        api, owner, repo, branch, COVERAGE_TOOLS, workflow_contents, file_cache, tree
    )

    say("  Checking mutation testing tools...")
    mutation_tools = check_tools(
        api, owner, repo, branch, MUTATION_TOOLS, workflow_contents, file_cache, tree
    )

    say("  Checking badges...")
    readme = fetch_readme(api, owner, repo, branch)
    badges = check_badges(readme)

    say("  Looking for an independently hosted mutation report...")
    dashboard = fetch_dashboard_mutation_score(
        api, owner, repo, branch, dashboard_branch_from_readme(readme)
    )

    ci_enforced = check_ci_enforced_mutation(
        api, owner, repo, branch, mutation_tools, workflow_contents, file_cache
    )

    # In order of how much the number can be trusted.
    mutation_score = mutation_score_override
    mutation_score_source = "manual" if mutation_score is not None else None
    if mutation_score is None and dashboard:
        mutation_score = dashboard["score"]
        mutation_score_source = "dashboard"
        say(f"  Mutation score {mutation_score}% from the Stryker dashboard.")
    if mutation_score is None and ci_enforced and ci_enforced["passing"]:
        # The build fails below the threshold and the build is green, so the
        # real score is at least this.
        mutation_score = ci_enforced["threshold"]
        mutation_score_source = "ci-threshold"
        say(f"  Mutation score at least {mutation_score}%, enforced by {ci_enforced['workflow']}.")
    if mutation_score is None and readme:
        mutation_score = extract_mutation_score_from_readme(readme)
        if mutation_score is not None:
            mutation_score_source = "readme-badge"
            say(f"  Mutation score {mutation_score}% read from README badge (self-reported).")

    say("  Checking for parameterized tests...")
    parameterized = check_parameterized_tests(api, owner, repo, metadata.get("language"))
    if parameterized is None:
        say("  Skipped: needs a token and a language with known markers.")

    say("  Fetching coverage percentage...")
    if coverage_override is not None:
        coverage = {
            "service": "manual",
            "coverage": round(coverage_override, 2),
            "source": "supplied via --coverage",
        }
    else:
        coverage = fetch_coverage_percent(api, owner, repo, branch)

    return generate_report(
        owner,
        repo,
        metadata,
        ci,
        coverage_tools,
        mutation_tools,
        badges,
        coverage,
        mutation_score,
        parameterized,
        mutation_score_source,
        dashboard,
        ci_enforced,
    )


def save_report(report: dict, output_dir: str | Path) -> Path:
    """Write a report to <output_dir>/<owner>_<repo>.json and return the path."""
    owner, repo = report["repository"].split("/", 1)
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{owner}_{repo}.json"
    with open(path, "w") as f:
        json.dump(report, f, indent=2)
        f.write("\n")
    return path


def main():
    parser = argparse.ArgumentParser(
        description="Verify a GitHub repo for awesome-well-tested"
    )
    parser.add_argument("repo", help="GitHub repo URL or owner/repo")
    parser.add_argument(
        "--token",
        help="GitHub personal access token (defaults to $GITHUB_TOKEN)",
        default=os.environ.get("GITHUB_TOKEN"),
    )
    parser.add_argument(
        "--coverage",
        type=float,
        default=None,
        help="Coverage percentage, if it is not published on Codecov or Coveralls",
    )
    parser.add_argument(
        "--mutation-score",
        type=float,
        default=None,
        help=f"Verified mutation score; >= {MIN_MUTATION_SCORE:.0f} is required for Gold",
    )
    parser.add_argument(
        "--output-dir",
        help="Output directory for reports",
        default="reports",
    )
    args = parser.parse_args()

    owner, repo = parse_repo_arg(args.repo)
    api = GitHubAPI(token=args.token)

    print(f"Verifying {owner}/{repo}...")
    try:
        report = verify_repository(
            api, owner, repo, args.coverage, args.mutation_score
        )
    except RepositoryMissing as e:
        print(f"Repository {e} not found: deleted, renamed or private.", file=sys.stderr)
        return 1
    except VerificationIncomplete as e:
        print(
            f"Could not finish verifying {owner}/{repo}: {e}\n"
            "This is a failure to check, not a verdict on the repository.",
            file=sys.stderr,
        )
        return 1

    report_path = save_report(report, args.output_dir)
    print_summary(report)
    print(f"Report saved to {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
