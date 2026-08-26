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
        "patterns": [r"jacoco", r"org\.jacoco"],
        "language": "Java",
    },
    "kover": {
        "files": ["build.gradle", "build.gradle.kts", ".github/workflows"],
        # A leading word boundary only: "\bkover\b" fails on koverXmlReport and
        # koverVerify, while a bare "kover" matches "stackoverflow".
        "patterns": [r"kotlinx\.kover", r"\bkover"],
        "language": "Kotlin",
    },
    "pytest-cov": {
        "files": ["pyproject.toml", "setup.cfg", "pytest.ini", "tox.ini"],
        "patterns": [r"pytest-cov", r"--cov", r"addopts.*--cov"],
        "language": "Python",
    },
    "coverage.py": {
        "files": ["pyproject.toml", "setup.cfg", ".coveragerc"],
        "patterns": [r"\[tool\.coverage\]", r"\[coverage:", r"coverage run"],
        "language": "Python",
    },
    "istanbul": {
        "files": ["package.json", ".nycrc", ".nycrc.json", ".github/workflows"],
        # Deliberately not "--coverage": that also matches phpunit
        # --coverage-clover and go test --coverage in a CI workflow, which
        # labelled PHP and Go repositories as using Istanbul.
        "patterns": [
            r"istanbul",
            r"\"nyc\"",
            r"\bc8\b",
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
        "patterns": [r"coverage-clover", r"php-coveralls", r"phpunit", r"pcov", r"xdebug"],
        "language": "PHP",
    },
    "simplecov": {
        "files": ["Gemfile", ".simplecov", ".github/workflows"],
        "patterns": [r"simplecov", r"SimpleCov"],
        "language": "Ruby",
    },
}

MUTATION_TOOLS = {
    "pit": {
        "files": ["pom.xml", "build.gradle", "build.gradle.kts"],
        "patterns": [r"pitest", r"org\.pitest", r"pit-maven", r"info\.solidsoft\.pitest"],
        "language": "Java",
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
        "files": ["Gemfile"],
        "patterns": [r"mutant", r"mutant-rspec"],
        "language": "Ruby",
    },
    "infection": {
        "files": ["composer.json", "infection.json", "infection.json.dist"],
        "patterns": [r"infection", r"infection/infection"],
        "language": "PHP",
    },
}

# Shields.io badges are the common way to publish a mutation score, since no
# hosted service reports one. Example: mutation%20coverage-98%25-brightgreen
MUTATION_BADGE_PATTERN = (
    r"img\.shields\.io/badge/"
    r"mutation(?:%20|[-_ ])?(?:coverage|score|testing)"
    r"[-_]{1,2}(\d{1,3})(?:\.\d+)?%25"
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
        ("jqwik", "jqwik (property-based)"),
    ],
    "Kotlin": [
        ("ParameterizedTest", "JUnit 5 @ParameterizedTest"),
        ("checkAll", "Kotest property testing"),
    ],
    "Groovy": [
        ("@Unroll", "Spock @Unroll"),
    ],
    "Python": [
        ("parametrize", "pytest.mark.parametrize"),
        ("hypothesis", "Hypothesis (property-based)"),
    ],
    "JavaScript": [
        ("describe.each", "Jest/Vitest .each"),
        ("fast-check", "fast-check (property-based)"),
    ],
    "TypeScript": [
        ("describe.each", "Jest/Vitest .each"),
        ("fast-check", "fast-check (property-based)"),
    ],
    "Rust": [
        ("rstest", "rstest"),
        ("proptest", "proptest (property-based)"),
        ("quickcheck", "quickcheck (property-based)"),
    ],
    "Ruby": [
        ("shared_examples", "RSpec shared examples"),
        ("rantly", "Rantly (property-based)"),
    ],
    "C#": [
        ("InlineData", "xUnit [Theory]/[InlineData]"),
        ("TestCase", "NUnit [TestCase]"),
        ("FsCheck", "FsCheck (property-based)"),
    ],
    "PHP": [
        ("dataProvider", "PHPUnit @dataProvider"),
    ],
}

BADGE_PATTERNS = [
    (r"codecov\.io/gh/([^/]+/[^/]+)", "Codecov"),
    (r"coveralls\.io/repos/github/([^/]+/[^/]+)", "Coveralls"),
    (r"codeclimate\.com/github/([^/]+/[^/]+)", "Code Climate"),
    (r"sonarcloud\.io.*component=([^&\"]+)", "SonarCloud"),
    (r"img\.shields\.io/badge/coverage", "Shields.io (manual badge)"),
]


class GitHubAPI:
    """Minimal GitHub API client using urllib."""

    def __init__(self, token: str | None = None):
        self.headers = {"Accept": "application/vnd.github.v3+json"}
        self.authenticated = bool(token)
        if token:
            self.headers["Authorization"] = f"token {token}"

    def get(self, url: str) -> dict | list | None:
        req = urllib.request.Request(url, headers=self.headers)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if e.code == 403:
                print(f"Rate limited. Use --token for higher limits.", file=sys.stderr)
                sys.exit(1)
            raise
        except urllib.error.URLError as e:
            print(f"Network error: {e}", file=sys.stderr)
            return None

    def get_public_json(self, url: str) -> dict | list | None:
        """GET JSON from a non-GitHub public endpoint (Codecov, Coveralls).

        Deliberately does not send the GitHub token: these are third-party hosts.
        """
        req = urllib.request.Request(
            url, headers={"Accept": "application/json", "User-Agent": "awesome-well-tested"}
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode())
        except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError):
            return None

    def get_text(self, url: str) -> str | None:
        headers = {**self.headers, "Accept": "application/vnd.github.v3.raw"}
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return resp.read().decode(errors="replace")
        except (urllib.error.HTTPError, urllib.error.URLError):
            return None


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
        print(f"Repository {owner}/{repo} not found.", file=sys.stderr)
        sys.exit(1)

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


def check_ci(api: GitHubAPI, owner: str, repo: str, branch: str) -> dict:
    """Detect CI configuration."""
    found = {}

    # Check GitHub Actions specifically (most common)
    workflows = api.get(f"{API_BASE}/repos/{owner}/{repo}/contents/.github/workflows?ref={branch}")
    if workflows and isinstance(workflows, list):
        found["github_actions"] = [w["name"] for w in workflows if w.get("name")]

    # Check other CI files at repo root
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


def fetch_workflow_contents(api: GitHubAPI, owner: str, repo: str, branch: str) -> dict:
    """Download every GitHub Actions workflow file so tools invoked only in CI are visible."""
    workflows = api.get(f"{API_BASE}/repos/{owner}/{repo}/contents/.github/workflows?ref={branch}")
    contents = {}
    if not workflows or not isinstance(workflows, list):
        return contents
    for entry in workflows:
        name = entry.get("name", "")
        if not name.endswith((".yml", ".yaml")):
            continue
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
) -> dict:
    """Check for coverage or mutation testing tools in config files and CI workflows."""
    found = {}
    checked_files: dict[str, str | None] = {}
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
                content = api.get_text(
                    f"{API_BASE}/repos/{owner}/{repo}/contents/{filename}?ref={branch}"
                )
                checked_files[filename] = content

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
    for variant in ["README.md", "readme.md", "README.rst", "README.adoc"]:
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
        match = re.search(pattern, readme_content)
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
    for term, label in markers:
        query = urllib.parse.quote(f"repo:{owner}/{repo} {term}")
        data = api.get(f"{API_BASE}/search/code?q={query}&per_page=1")
        if isinstance(data, dict) and data.get("total_count", 0) > 0:
            frameworks.append({"framework": label, "matches": data["total_count"]})
        time.sleep(throttle)

    return {
        "frameworks": frameworks,
        "detected": bool(frameworks),
        "language": language,
    }


def fetch_coverage_percent(api: GitHubAPI, owner: str, repo: str) -> dict | None:
    """Fetch the real coverage percentage from a public coverage service.

    Tries Codecov first, then Coveralls. Both expose public read endpoints for
    public repositories, so no extra credentials are needed. Returns None when
    neither service knows the repository.
    """
    # Codecov v2 API
    data = api.get_public_json(f"{CODECOV_API}/{owner}/repos/{repo}/")
    if isinstance(data, dict):
        totals = data.get("totals") or {}
        coverage = totals.get("coverage")
        if coverage is not None:
            return {
                "service": "Codecov",
                "coverage": round(float(coverage), 2),
                "source": f"https://codecov.io/gh/{owner}/{repo}",
            }

    # Coveralls JSON endpoint
    data = api.get_public_json(f"{COVERALLS_API}/{owner}/{repo}.json")
    if isinstance(data, dict):
        coverage = data.get("covered_percent")
        if coverage is not None:
            return {
                "service": "Coveralls",
                "coverage": round(float(coverage), 2),
                "source": f"https://coveralls.io/github/{owner}/{repo}",
            }

    return None


def determine_tier(
    ci: dict,
    coverage_tools: dict,
    mutation_tools: dict,
    coverage: dict | None,
    mutation_score: float | None,
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
            "Mutation testing is configured but the mutation score is unverified; "
            f"supply it with --mutation-score (>= {MIN_MUTATION_SCORE:.0f}% required for Gold)"
        )

    if mutation_score < MIN_MUTATION_SCORE:
        return "silver", (
            f"Mutation score {mutation_score}% is below the "
            f"{MIN_MUTATION_SCORE:.0f}% required for Gold"
        )

    return "gold", (
        f"Coverage {coverage['coverage']}% and mutation score {mutation_score}%"
    )


def primary_coverage_tool(coverage_tools: dict, language: str | None) -> str | None:
    """Pick the tool to name for a repository when several patterns matched.

    Build and CI files borrow each other's vocabulary, so a repository can match
    more than one tool. The one whose language matches the repository is the
    honest answer.
    """
    if not coverage_tools:
        return None
    for name, info in coverage_tools.items():
        if language and language in (info.get("language") or ""):
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
) -> dict:
    """Generate the full verification report."""
    tier, tier_reason = determine_tier(
        ci, coverage_tools, mutation_tools, coverage, mutation_score
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
        print(f"  Coverage:    {cov['coverage']}% (via {cov['service']})")

    if report.get("mutation_score") is not None:
        print(f"  Mut. score:  {report['mutation_score']}%")

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

    say("  Checking CI configuration...")
    ci = check_ci(api, owner, repo, branch)
    workflow_contents = fetch_workflow_contents(api, owner, repo, branch)

    say("  Checking coverage tools...")
    coverage_tools = check_tools(api, owner, repo, branch, COVERAGE_TOOLS, workflow_contents)

    say("  Checking mutation testing tools...")
    mutation_tools = check_tools(api, owner, repo, branch, MUTATION_TOOLS, workflow_contents)

    say("  Checking badges...")
    readme = fetch_readme(api, owner, repo, branch)
    badges = check_badges(readme)

    mutation_score = mutation_score_override
    if mutation_score is None and readme:
        mutation_score = extract_mutation_score_from_readme(readme)
        if mutation_score is not None:
            say(f"  Mutation score {mutation_score}% read from README badge.")

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
        coverage = fetch_coverage_percent(api, owner, repo)

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
    report = verify_repository(
        api, owner, repo, args.coverage, args.mutation_score
    )

    report_path = save_report(report, args.output_dir)
    print_summary(report)
    print(f"Report saved to {report_path}")


if __name__ == "__main__":
    main()
