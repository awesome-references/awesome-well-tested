#!/usr/bin/env python3
"""
discover_candidates.py - Find GitHub repos that likely have high test coverage.

Searches for repos that reference known coverage and mutation testing tools,
then runs verify_repo.py on each candidate.

Usage:
    python discover_candidates.py --language java --min-stars 100
    python discover_candidates.py --language python --mutation-only
    python discover_candidates.py --language java --token ghp_xxx

Note: GitHub code search API requires authentication.
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API_BASE = "https://api.github.com"

# Queries that find candidate repositories by their build and config files.
#
# No query carries a "language:" qualifier. In code search that matches the
# language of the FILE, and every query here pins a build or config file:
# pom.xml is XML, pyproject.toml is TOML, package.json is JSON. Asking for a
# Java pom.xml returns nothing at all.
SEARCH_QUERIES = {
    "java": [
        ('pitest filename:build.gradle.kts', 'PIT in a Gradle Kotlin DSL build (the existing java entries only cover'),
        ('mutationThreshold filename:pom.xml', 'Repos that fail the build below a PIT mutation threshold - the stronge'),
        ('pitest-descartes filename:pom.xml', 'Descartes extreme-mutation engine for PIT'),
        ('jacoco filename:build.gradle', 'JaCoCo in Gradle Groovy DSL - Bronze candidates; the existing dict onl'),
        ('openclover filename:pom.xml', 'OpenClover (the open-sourced Atlassian Clover) in Maven'),
    ],
    "kotlin": [
        ('pitest filename:build.gradle.kts', 'New key'),
        ('koverVerify filename:build.gradle.kts', 'New key'),
        ('kover filename:build.gradle.kts', 'New key'),
        ('kover filename:libs.versions.toml', 'New key'),
    ],
    "scala": [
        ('stryker4s filename:plugins.sbt', 'New key'),
        ('mutate filename:stryker4s.conf', 'New key'),
        ('sbt-scoverage filename:plugins.sbt', 'New key'),
        ('scoverage filename:build.sbt', 'New key'),
    ],
    "groovy": [
        ('pitest filename:build.gradle', 'New key'),
        ('spock-core filename:build.gradle', 'New key'),
    ],
    "python": [
        ('mutmut filename:setup.cfg', 'mutmut config in setup'),
        ('mutmut filename:pyproject.toml', 'mutmut config in pyproject'),
        ('mutmut filename:noxfile.py', 'mutmut driven from nox'),
        ('mutmut filename:tox.ini', 'mutmut driven from tox'),
        ('mutmut filename:requirements-dev.txt', 'mutmut as a dev dependency'),
        ('cosmic-ray filename:pyproject.toml', 'cosmic-ray config'),
        ('cosmic-ray filename:Makefile', 'cosmic-ray run from a Makefile'),
        ('mutatest filename:pyproject.toml', 'mutatest config'),
        ('mutpy filename:tox.ini', 'MutPy invoked from tox (expect a thin yield: MutPy is effectively unma'),
        ('pytest-cov filename:pyproject.toml', 'pytest-cov config'),
        ('pytest-cov filename:tox.ini', 'pytest-cov in the tox test env'),
        ('fail_under filename:.coveragerc', 'coverage'),
        ('fail_under filename:pyproject.toml', 'coverage floor in [tool'),
    ],
    "javascript": [
        ('@stryker-mutator/core filename:package.json', "Stryker core declared as a devDependency (tightens the existing '@stry"),
        ('mutate filename:stryker.conf.json', "Stryker JSON config at the repo root; 'mutate' is the glob key present"),
        ('mutate filename:stryker.conf.mjs', "Stryker ESM config variant (same 'mutate' key, module-format repos)"),
        ('@stryker-mutator/jest-runner filename:package.json', 'Stryker driving a Jest suite - narrower than core, and the runner pack'),
        ('coverageThreshold filename:jest.config.js', 'Jest repos that enforce a coverage floor rather than merely measuring '),
        ('check-coverage filename:.nycrc', 'nyc with enforced thresholds; '),
        ('@vitest/coverage-v8 filename:package.json', 'Modern Vitest coverage provider - finds the current generation of well'),
    ],
    "typescript": [
        ('@stryker-mutator/typescript-checker filename:package.json', 'Stryker with the TS type checker enabled - a repo that bothers with th'),
        ('mutate filename:stryker.config.mjs', "Newer 'stryker"),
        ('@stryker-mutator/vitest-runner filename:package.json', 'Stryker driving a Vitest suite - the current default combination for n'),
        ('@vitest/coverage-istanbul filename:package.json', 'Vitest with the Istanbul provider (branch coverage), coverage-only Bro'),
        ('coverageThreshold filename:jest.config.ts', 'Jest coverage floor declared in a TypeScript config file'),
        ('deno coverage filename:deno.json', 'Deno projects with a coverage task in deno'),
    ],
    "go": [
        ('gremlins filename:.gremlins.yaml', 'Gremlins mutation testing config at repo root'),
        ('gremlins unleash filename:Makefile', "The Gremlins CLI command ('gremlins unleash "),
        ('gtramontina/ooze filename:go.mod', 'Ooze is the one Go mutation tester that is a library rather than a CLI'),
        ('go-mutesting filename:go.mod', 'go-mutesting pinned as a tool dependency in go'),
        ('avito-tech/go-mutesting filename:Makefile', 'The maintained fork of go-mutesting, invoked from a Makefile'),
        ('go-mutesting filename:Makefile', 'Existing query, keep unchanged - still the most common way go-mutestin'),
        ('coverprofile filename:Makefile', "REPLACES the existing '-coverprofile filename:Makefile'"),
        ('coverprofile filename:Taskfile.yml', 'Same signal in Taskfile (go-task), which a growing share of Go repos u'),
        ('goveralls filename:Makefile', 'mattn/goveralls, the Go Coveralls uploader'),
        ('octocov filename:.octocov.yml', 'octocov (k1LoW) config'),
        ('threshold filename:.testcoverage.yml', 'vladopajic/go-test-coverage config'),
        ('gopter filename:go.mod', 'Property-based testing dependency'),
        ('pgregory.net/rapid filename:go.mod', 'The other real Go property-based library'),
    ],
    "rust": [
        ('cargo-mutants path:.github/workflows', 'cargo-mutants run in GitHub Actions'),
        ('exclude_globs filename:mutants.toml', 'cargo-mutants config file ('),
        ('cargo-mutants filename:Cargo.toml', 'cargo-mutants referenced in Cargo'),
        ('mutagen filename:Cargo.toml', 'mutagen mutation testing dependency'),
        ('tarpaulin path:.github/workflows', 'cargo-tarpaulin in CI'),
        ('cargo-llvm-cov path:.github/workflows', 'cargo-llvm-cov in CI'),
        ('grcov path:.github/workflows', 'grcov in CI'),
        ('tarpaulin filename:Cargo.toml', 'cargo-tarpaulin metadata in Cargo'),
    ],
    "ruby": [
        ('mutant-license filename:Gemfile', 'mutant license line in Gemfile (mutant requires a license gem/source l'),
        ('integration filename:mutant.yml', 'mutant config file - the filename qualifier matches mutant'),
        ('mutant-rspec filename:Gemfile', 'mutant with the RSpec integration (existing query, keep)'),
        ('mutant-minitest filename:Gemfile', 'mutant with the Minitest integration - finds the minitest half of the '),
        ('mutest filename:Gemfile', 'mutest, the maintained fork of mutant used in the dry-rb/rom-rb circle'),
        ('minimum_coverage filename:.simplecov', 'SimpleCov with an enforced coverage floor - selects repos that fail th'),
        ('simplecov-lcov filename:Gemfile', 'SimpleCov with the LCOV formatter - correlates with actually uploading'),
        ('simplecov filename:Gemfile', 'SimpleCov (existing broad query, keep for volume)'),
        ('undercover filename:Gemfile', 'undercover - gates coverage on changed lines; users are coverage-disci'),
    ],
    "php": [
        ('infection/infection filename:composer.json', 'Infection in composer require-dev (existing query, keep)'),
        ('filename:infection.json5', 'Infection config file, the modern default name'),
        ('filename:infection.json.dist', 'Infection config, distributed template variant'),
        ('pest-plugin-mutate filename:composer.json', 'Pest mutation testing plugin (Pest v3+)'),
        ('php-coveralls filename:composer.json', 'php-coveralls uploader, coverage-only Bronze candidates'),
        ('min-covered-msi filename:composer.json', 'Infection MSI quality gate in a composer script'),
        ('coverage-clover filename:composer.json', 'PHPUnit clover coverage script, Bronze candidates'),
    ],
    "csharp": [
        ('dotnet-stryker filename:dotnet-tools.json', 'Stryker'),
        ('stryker-config filename:stryker-config.json', 'Stryker'),
        ('dotnet-stryker path:.github/workflows', 'Stryker'),
        ('badge-api.stryker-mutator.io filename:README.md', 'Published Stryker dashboard mutation-score badge - the Gold shortlist,'),
        ('coverlet.msbuild extension:csproj', 'coverlet MSBuild integration (opt-in: implies /p:CollectCoverage runs '),
        ('coverlet.collector filename:Directory.Build.props', 'coverlet centralised in the repo-wide build props - higher signal than'),
        ('altcover extension:csproj', 'AltCover as a package reference'),
        ('JetBrains.dotCover.GlobalTool filename:dotnet-tools.json', 'JetBrains dotCover CLI installed as a dotnet tool'),
        ('OpenCover.Console filename:appveyor.yml', 'OpenCover driven from AppVeyor - the classic '),
    ],
    "fsharp": [
        ('altcover extension:fsproj', 'AltCover in an F# project - AltCover is the coverage tool of choice in'),
        ('coverlet.collector extension:fsproj', 'coverlet in an F# test project'),
        ('FsCheck extension:fsproj', 'FsCheck property-based tests referenced from an F# project file'),
    ],
    "vbnet": [
        ('coverlet.collector extension:vbproj', 'coverlet in a VB'),
    ],
    "swift": [
        ('muter filename:muter.conf.yml', 'Muter mutation testing config (Swift)'),
        ('muter filename:muter.conf.json', 'Muter legacy JSON config (Swift)'),
        ('slather filename:.slather.yml', 'Slather coverage config (Xcode/Swift)'),
        ('slather filename:Fastfile', 'Slather run from fastlane'),
        ('slather filename:Gemfile', 'Slather gem pinned in a Gemfile (iOS/macOS projects)'),
    ],
    "dart": [
        ('mutation_test filename:pubspec.yaml', 'mutation_test package as a dev_dependency (Dart)'),
        ('coverde filename:pubspec.yaml', 'coverde lcov tooling / coverage threshold enforcement (Dart)'),
        ('test_coverage filename:pubspec.yaml', 'test_coverage package (older Flutter coverage helper)'),
        ('very_good filename:melos.yaml', 'very_good test --min-coverage in a Melos workspace script'),
        ('dart filename:codecov.yml', 'Codecov config in a Dart/Flutter repo (finds repos that publish a fetc'),
    ],
    "elixir": [
        ('excoveralls filename:mix.exs', 'ExCoveralls dependency in mix'),
        ('minimum_coverage filename:coveralls.json', 'ExCoveralls with an enforced minimum coverage threshold (strong qualit'),
        ('muzak filename:mix.exs', 'Muzak mutation testing (Elixir) - essentially the entire population'),
        ('stream_data filename:mix.exs', 'StreamData property-based testing dependency'),
    ],
    "haskell": [
        ('QuickCheck extension:cabal', 'QuickCheck in build-depends (property-based tests)'),
        ('hedgehog extension:cabal', 'Hedgehog in build-depends (property-based tests)'),
        ('hpc-coveralls filename:stack.yaml', 'hpc-coveralls upload (the only route from HPC to a hosted number)'),
        ('MuCheck extension:cabal', 'MuCheck mutation testing - expected to be near-empty, kept so --mutati'),
    ],
    "c": [
        ('"-fprofile-arcs" filename:Makefile.am', 'gcov instrumentation in an Autotools build (quoted: a bare leading hyp'),
        ('"-ftest-coverage" filename:Makefile', 'gcov instrumentation in a plain Makefile (quoted for the same reason)'),
        ('genhtml filename:Makefile', 'lcov HTML report step in a Makefile'),
        ('mull-runner filename:Makefile', 'Mull mutation testing driven from a Makefile (C projects)'),
    ],
    "cpp": [
        ('gcovr filename:CMakeLists.txt', 'gcovr coverage wired into CMake'),
        ('CodeCoverage filename:CMakeLists.txt', 'include(CodeCoverage) from the common CodeCoverage'),
        ('mull-runner filename:CMakeLists.txt', 'Mull mutation testing wired into CMake'),
        ('mull filename:mull.yml', 'Mull config file (path term, since mull'),
        ('dextool filename:.dextool_mutate.toml', 'Dextool mutate config'),
        ('rapidcheck filename:CMakeLists.txt', 'RapidCheck property-based tests linked into a CMake build'),
    ],
}


# Search rejects requests faster than the rest of the API: 403 for the primary
# limit, 429 for the secondary one. Both carry Retry-After often enough to obey.
RETRY_CODES = (403, 429)
MAX_RETRIES = 3


def github_search(token: str, query: str, per_page: int = 30) -> dict | None:
    """Call the code search endpoint, backing off when the limit is hit.

    Note that no `language:` qualifier is added. In code search that qualifier
    matches the language of the *file*, and every query here pins a build or
    config file: pom.xml is XML, pyproject.toml is TOML, package.json is JSON.
    Combining the two is self-contradictory and returns nothing at all.
    """
    params = f"q={urllib.parse.quote(query)}&per_page={per_page}&sort=indexed"
    url = f"{API_BASE}/search/code?{params}"
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "Authorization": f"token {token}",
        "User-Agent": "awesome-well-tested",
    }

    for attempt in range(1, MAX_RETRIES + 1):
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 422:
                print(f"  Query rejected, skipping: {query}", file=sys.stderr)
                return None
            if e.code in RETRY_CODES and attempt < MAX_RETRIES:
                wait = int(e.headers.get("Retry-After") or 0) or 15 * attempt
                print(
                    f"  Search limited (HTTP {e.code}), retrying in {wait}s "
                    f"[{attempt}/{MAX_RETRIES - 1}]...",
                    file=sys.stderr,
                )
                time.sleep(wait)
                continue
            if e.code in RETRY_CODES:
                print(
                    f"  Search still limited (HTTP {e.code}) after {MAX_RETRIES} "
                    f"attempts, skipping: {query}",
                    file=sys.stderr,
                )
                return None
            raise
        except urllib.error.URLError as e:
            print(f"  Network error, skipping: {query} ({e})", file=sys.stderr)
            return None

    return None


def search_code(token: str, query: str) -> list[dict]:
    """Search GitHub code for repos matching a query."""
    data = github_search(token, query)
    if data is None:
        return []

    # Deduplicate by repo
    seen = set()
    repos = []
    for item in data.get("items", []):
        repo_name = item["repository"]["full_name"]
        if repo_name not in seen:
            seen.add(repo_name)
            repos.append({
                "full_name": repo_name,
                "matched_file": item["path"],
            })

    return repos


def get_repo_stars(token: str, full_name: str) -> int | None:
    """Star count for a repo, or None when the lookup itself failed.

    Returning 0 for a failure silently reclassified a rate-limited lookup as
    "too few stars", so a run against a busy API quietly discarded candidates
    it had already paid to find.
    """
    url = f"{API_BASE}/repos/{full_name}"
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "Authorization": f"token {token}",
        "User-Agent": "awesome-well-tested",
    }
    for attempt in range(1, 4):
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode()).get("stargazers_count", 0)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if e.code in (403, 429, 500, 502, 503, 504) and attempt < 3:
                wait = int(e.headers.get("Retry-After") or 0) or 5 * attempt
                time.sleep(min(wait, 60))
                continue
            return None
        except urllib.error.URLError:
            if attempt < 3:
                time.sleep(5 * attempt)
                continue
            return None
    return None


def main():
    parser = argparse.ArgumentParser(description="Discover well-tested repo candidates")
    parser.add_argument(
        "--language",
        choices=list(SEARCH_QUERIES.keys()),
        required=True,
        help="Programming language to search",
    )
    parser.add_argument("--min-stars", type=int, default=50, help="Minimum star count")
    parser.add_argument(
        "--mutation-only",
        action="store_true",
        help="Only search for mutation testing (higher quality candidates)",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("GITHUB_TOKEN"),
        help="GitHub personal access token (defaults to $GITHUB_TOKEN); code search requires one",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Automatically run verify_repo.py on candidates",
    )
    parser.add_argument("--max-results", type=int, default=20, help="Max candidates to process")
    args = parser.parse_args()

    if not args.token:
        print(
            "A token is required: GitHub code search rejects unauthenticated requests. "
            "Pass --token or set GITHUB_TOKEN.",
            file=sys.stderr,
        )
        sys.exit(1)

    queries = SEARCH_QUERIES.get(args.language, [])

    if args.mutation_only:
        mutation_keywords = [
            "pitest", "descartes", "mutmut", "cosmic-ray", "mutatest", "mutpy",
            "stryker", "stryker4s", "cargo-mutants", "mutagen", "go-mutesting",
            "gremlins", "ooze", "mutant", "mutest", "infection", "pest-plugin-mutate",
            "muter", "mutation_test", "muzak", "mucheck", "mull", "dextool",
            "mutationthreshold", "min-msi", "minmsi",
        ]
        queries = [
            (q, desc)
            for q, desc in queries
            if any(kw in q.lower() for kw in mutation_keywords)
        ]

    if not queries:
        print(f"No search queries for {args.language}", file=sys.stderr)
        sys.exit(1)

    all_candidates = {}

    for query, description in queries:
        print(f"Searching: {description} ({query})...")
        repos = search_code(args.token, query)

        for repo in repos:
            name = repo["full_name"]
            if name not in all_candidates:
                stars = get_repo_stars(args.token, name)
                if stars is None:
                    print(f"  Could not read stars for {name}, skipping", file=sys.stderr)
                elif stars >= args.min_stars:
                    all_candidates[name] = {
                        "full_name": name,
                        "stars": stars,
                        "matched_queries": [description],
                    }
                    print(f"  Found: {name} ({stars} stars)")
                # Rate limiting
                time.sleep(0.5)
            else:
                all_candidates[name]["matched_queries"].append(description)

        # Rate limiting between searches
        time.sleep(2)

    # Sort by stars descending
    candidates = sorted(all_candidates.values(), key=lambda x: x["stars"], reverse=True)
    candidates = candidates[: args.max_results]

    print(f"\n{'=' * 60}")
    print(f"  Found {len(candidates)} candidates for {args.language}")
    print(f"{'=' * 60}\n")

    for i, c in enumerate(candidates, 1):
        queries_str = ", ".join(c["matched_queries"])
        print(f"  {i:3d}. {c['full_name']} ({c['stars']} stars) - {queries_str}")

    # Save candidates
    repo_root = Path(__file__).resolve().parent.parent
    # Kept out of reports/ proper: candidate dumps are throwaway lists, while
    # every file directly in reports/ is a verification report object.
    output_dir = repo_root / "reports" / "candidates"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{args.language}.json"
    with open(output_path, "w") as f:
        json.dump(candidates, f, indent=2)
    print(f"\nCandidates saved to {output_path}")

    # Optionally verify each
    if args.verify:
        print(f"\nRunning verification on candidates...\n")
        for c in candidates:
            print(f"\n--- Verifying {c['full_name']} ---")
            subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).resolve().parent / "verify_repo.py"),
                    c["full_name"],
                    "--token",
                    args.token,
                ],
                cwd=str(repo_root),
            )
            time.sleep(1)


if __name__ == "__main__":
    main()
