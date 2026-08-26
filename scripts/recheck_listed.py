#!/usr/bin/env python3
"""
recheck_listed.py - Re-verify every repository already listed in README.md.

The README promises that entries are re-verified periodically and demoted when
their test quality degrades. This script is what makes that true: it reads the
listed entries and their claimed tier out of the README tables, verifies each
one again, refreshes the report under reports/ and reports any entry whose tier
no longer matches what the list claims.

Usage:
    python recheck_listed.py
    python recheck_listed.py --repo astrapi69/crypt-data
    python recheck_listed.py --fail-on-mismatch

The token defaults to $GITHUB_TOKEN, which GitHub Actions provides for free.
"""

import argparse
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from verify_repo import (  # noqa: E402
    GitHubAPI,
    print_summary,
    save_report,
    verify_repository,
)

TIER_ORDER = {"bronze": 1, "silver": 2, "gold": 3}

REPO_LINK = re.compile(r"\[[^\]]+\]\(https://github\.com/([^/)]+)/([^/)#]+?)/?\)")
TIER_BADGE = re.compile(r"!\[(Gold|Silver|Bronze)\]\(badges/", re.IGNORECASE)


def parse_listed_entries(readme_path: Path) -> list[dict]:
    """Read owner/repo and the claimed tier out of the README tables."""
    entries = []
    for line in readme_path.read_text().split("\n"):
        if not line.startswith("|"):
            continue
        repo_match = REPO_LINK.search(line)
        tier_match = TIER_BADGE.search(line)
        if not repo_match or not tier_match:
            continue
        entries.append(
            {
                "owner": repo_match.group(1),
                "repo": repo_match.group(2),
                "claimed_tier": tier_match.group(1).lower(),
            }
        )
    return entries


def main():
    parser = argparse.ArgumentParser(
        description="Re-verify the repositories listed in README.md"
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("GITHUB_TOKEN"),
        help="GitHub token (defaults to $GITHUB_TOKEN)",
    )
    parser.add_argument(
        "--repo",
        action="append",
        default=None,
        help="Only recheck this owner/repo; may be repeated",
    )
    parser.add_argument(
        "--readme",
        default=None,
        help="Path to the README to read entries from",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Where reports are written",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the entries parsed out of the README and exit without calling the API",
    )
    parser.add_argument(
        "--fail-on-mismatch",
        action="store_true",
        help="Exit non-zero when a listed entry no longer holds its tier",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    readme_path = Path(args.readme) if args.readme else repo_root / "README.md"
    output_dir = Path(args.output_dir) if args.output_dir else repo_root / "reports"

    entries = parse_listed_entries(readme_path)
    if args.repo:
        wanted = {r.lower() for r in args.repo}
        entries = [e for e in entries if f"{e['owner']}/{e['repo']}".lower() in wanted]

    if not entries:
        print("No listed entries found to recheck.", file=sys.stderr)
        return 1

    if args.dry_run:
        for entry in entries:
            print(f"{entry['owner']}/{entry['repo']} listed as {entry['claimed_tier']}")
        print(f"\n{len(entries)} entries parsed from {readme_path}")
        return 0

    if not args.token:
        print(
            "Warning: no token. Unauthenticated GitHub API access is limited to 60 "
            "requests per hour and each repository costs roughly 20.",
            file=sys.stderr,
        )

    api = GitHubAPI(token=args.token)
    mismatches = []

    for entry in entries:
        full_name = f"{entry['owner']}/{entry['repo']}"
        print(f"\nRechecking {full_name} (listed as {entry['claimed_tier']})...")
        report = verify_repository(api, entry["owner"], entry["repo"])
        save_report(report, output_dir)
        print_summary(report)

        actual = report["tier"]
        claimed = entry["claimed_tier"]
        if actual != claimed:
            direction = (
                "downgrade"
                if TIER_ORDER.get(actual, 0) < TIER_ORDER.get(claimed, 0)
                else "upgrade"
            )
            mismatches.append(
                {
                    "repository": full_name,
                    "claimed": claimed,
                    "actual": actual,
                    "direction": direction,
                    "reason": report["tier_reason"],
                }
            )

    print(f"\n{'=' * 60}")
    print(f"  Rechecked {len(entries)} entries, {len(mismatches)} mismatched")
    print(f"{'=' * 60}\n")

    for m in mismatches:
        actual = m["actual"] or "not qualified"
        print(f"  {m['direction'].upper():<9} {m['repository']}: {m['claimed']} -> {actual}")
        print(f"            {m['reason']}")

    if mismatches and args.fail_on_mismatch:
        print("\nREADME tiers are out of date. Update the entries above.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
