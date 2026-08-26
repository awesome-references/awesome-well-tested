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

# Search queries per language to find well-tested repos
SEARCH_QUERIES = {
    "java": [
        ("pitest filename:pom.xml", "PIT in Maven"),
        ("pitest filename:build.gradle", "PIT in Gradle"),
        ("jacoco filename:pom.xml", "JaCoCo in Maven"),
    ],
    "python": [
        ("mutmut filename:pyproject.toml", "mutmut config"),
        ("cosmic-ray filename:pyproject.toml", "cosmic-ray config"),
        ("pytest-cov filename:pyproject.toml", "pytest-cov config"),
    ],
    "javascript": [
        ("@stryker-mutator filename:package.json", "Stryker in npm"),
        ("nyc filename:package.json", "Istanbul/nyc in npm"),
    ],
    "typescript": [
        ("@stryker-mutator filename:package.json", "Stryker in npm"),
    ],
    "go": [
        ("go-mutesting filename:Makefile", "go-mutesting"),
        ("-coverprofile filename:Makefile", "go cover"),
    ],
    "rust": [
        ("cargo-mutants filename:Cargo.toml", "cargo-mutants"),
        ("tarpaulin filename:Cargo.toml", "cargo-tarpaulin"),
    ],
    "ruby": [
        ("mutant-rspec filename:Gemfile", "mutant for Ruby"),
        ("simplecov filename:Gemfile", "SimpleCov"),
    ],
    "php": [
        ("infection/infection filename:composer.json", "Infection PHP"),
    ],
    "csharp": [
        ("Stryker.NET extension:csproj", "Stryker.NET"),
    ],
}


def search_code(token: str, query: str, language: str) -> list[dict]:
    """Search GitHub code for repos matching a query."""
    search_q = f"{query} language:{language}"
    params = f"q={urllib.parse.quote(search_q)}&per_page=30&sort=indexed"
    url = f"{API_BASE}/search/code?{params}"

    headers = {
        "Accept": "application/vnd.github.v3+json",
        "Authorization": f"token {token}",
    }

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 403:
            print(f"  Rate limited, waiting 30s...", file=sys.stderr)
            time.sleep(30)
            return []
        if e.code == 422:
            print(f"  Search query too complex, skipping: {query}", file=sys.stderr)
            return []
        raise

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


def get_repo_stars(token: str, full_name: str) -> int:
    """Get star count for a repo."""
    url = f"{API_BASE}/repos/{full_name}"
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "Authorization": f"token {token}",
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            return data.get("stargazers_count", 0)
    except (urllib.error.HTTPError, urllib.error.URLError):
        return 0


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
            "pitest", "mutmut", "cosmic-ray", "stryker", "cargo-mutants",
            "go-mutesting", "mutant", "infection",
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
        repos = search_code(args.token, query, args.language)

        for repo in repos:
            name = repo["full_name"]
            if name not in all_candidates:
                stars = get_repo_stars(args.token, name)
                if stars >= args.min_stars:
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
    output_dir = repo_root / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"candidates_{args.language}.json"
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
