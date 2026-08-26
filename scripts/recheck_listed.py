#!/usr/bin/env python3
"""
recheck_listed.py - Re-verify every repository already listed in README.md.

The README promises that entries are re-verified and that an entry whose test
quality degrades does not stay. This is what makes that true.

Removal is silent by design. A repository that falls below the bar is taken off
the list without the list recording why, and without naming it in any public
run output. The list exists to point at software that is well tested; it is not
a place to publish a verdict on software that no longer is. An entry that moves
between tiers is simply rewritten to the tier it now holds - which is still a
statement that it qualifies, not a demotion notice.

Usage:
    python recheck_listed.py                     # report only
    python recheck_listed.py --apply             # rewrite README and reports
    python recheck_listed.py --apply --redact    # ... naming nothing in output
    python recheck_listed.py --dry-run           # just parse the entries

The token defaults to $GITHUB_TOKEN, which GitHub Actions provides for free.
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import readme_table as rt  # noqa: E402
from verify_repo import (  # noqa: E402
    GitHubAPI,
    RepositoryMissing,
    VerificationIncomplete,
    print_summary,
    save_report,
    verify_repository,
)

TIER_ORDER = {"bronze": 1, "silver": 2, "gold": 3}


def classify(claimed: str, actual: str | None) -> str:
    if actual is None:
        return "removed"
    if actual == claimed:
        return "unchanged"
    if TIER_ORDER.get(actual, 0) < TIER_ORDER.get(claimed, 0):
        return "lowered"
    return "raised"


def apply_changes(
    readme_path: Path,
    reports: dict,
    drop: set,
    output_dir: Path,
) -> None:
    """Rewrite the README rows and delete the reports of dropped entries."""

    def transform(section, header, body):
        kept = []
        for row in body:
            name = rt.row_full_name(row)
            if name in drop:
                continue
            report = reports.get(name)
            if report is not None:
                row = rt.update_row(row, header, rt.cells_from_report(report, header))
            kept.append(row)
        return kept

    text = rt.transform_tables(rt.read_readme(readme_path), transform)
    rt.write_readme(readme_path, text)

    for name in drop:
        owner, repo = name.split("/", 1)
        path = output_dir / f"{owner}_{repo}.json"
        if path.exists():
            path.unlink()


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
    parser.add_argument("--readme", default=None, help="README to read entries from")
    parser.add_argument("--output-dir", default=None, help="Where reports are written")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the entries parsed out of the README and exit without calling the API",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Rewrite the README: refresh figures, and silently drop entries that no longer qualify",
    )
    parser.add_argument(
        "--redact",
        action="store_true",
        help="Never name a dropped or lowered entry in the output; print counts only",
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

    entries = rt.parse_entries(rt.read_readme(readme_path))
    if args.repo:
        wanted = {r.lower() for r in args.repo}
        entries = [e for e in entries if e["full_name"].lower() in wanted]

    if not entries:
        print("No listed entries found to recheck.", file=sys.stderr)
        return 1

    if args.dry_run:
        for entry in entries:
            print(f"{entry['full_name']} listed as {entry['claimed_tier']}")
        print(f"\n{len(entries)} entries parsed from {readme_path}")
        return 0

    if not args.token and args.apply:
        # check_parameterized_tests needs code search, which needs a token, and
        # returns None without one. cells_from_report writes that as "n/a" - the
        # same string the README documents as "not applicable" - so an
        # unauthenticated --apply would quietly erase the column.
        print(
            "--apply needs a token: without one the parameterized-test check cannot "
            "run, and every entry's Param. Tests cell would be overwritten with "
            "'n/a'. Pass --token or set GITHUB_TOKEN.",
            file=sys.stderr,
        )
        return 1

    if not args.token:
        print(
            "Warning: no token. Unauthenticated GitHub API access is limited to 60 "
            "requests per hour and each repository costs about 10.",
            file=sys.stderr,
        )

    api = GitHubAPI(token=args.token)
    reports, drop, changes, incomplete = {}, set(), [], []

    for entry in entries:
        name = entry["full_name"]
        if args.redact:
            print("\nRechecking a listed entry...")
        else:
            print(f"\nRechecking {name} (listed as {entry['claimed_tier']})...")

        try:
            report = verify_repository(api, entry["owner"], entry["repo"])
        except VerificationIncomplete as e:
            # A service that did not answer is not a repository that stopped
            # qualifying. Leaving the entry exactly as it is costs a week;
            # removing it on a 429 costs the entry and its report.
            incomplete.append(name)
            print(f"  Could not verify this entry, leaving it untouched: {e}", file=sys.stderr)
            continue
        except RepositoryMissing:
            # Deleted, renamed away or made private. That is an answer.
            drop.add(name)
            changes.append({"name": name, "outcome": "removed", "tier": None})
            continue

        outcome = classify(entry["claimed_tier"], report["tier"])

        if outcome == "removed":
            drop.add(name)
        else:
            reports[name] = report
            save_report(report, output_dir)
            if not args.redact:
                print_summary(report)

        if outcome != "unchanged":
            changes.append({"name": name, "outcome": outcome, "tier": report["tier"]})

    # A run that could not verify most of what it looked at has no business
    # rewriting the list from its results.
    verified = len(entries) - len(incomplete)
    if args.apply and incomplete and verified < len(entries) * 0.8:
        print(
            f"\nOnly {verified} of {len(entries)} entries could be verified. "
            "Refusing to rewrite the list from a partial run.",
            file=sys.stderr,
        )
        return 1

    if args.apply:
        apply_changes(readme_path, reports, drop, output_dir)

    lowered = [c for c in changes if c["outcome"] == "lowered"]
    raised = [c for c in changes if c["outcome"] == "raised"]

    print(f"\n{'=' * 60}")
    print(f"  Rechecked {len(entries)} entries, {len(incomplete)} could not be verified")
    print(f"  {len(drop)} no longer qualify, {len(lowered)} lowered, {len(raised)} raised")
    print(f"{'=' * 60}\n")

    if args.apply:
        print("  README and reports updated." if changes else "  No changes needed.")
    elif changes and not args.redact:
        for change in changes:
            tier = change["tier"] or "no longer qualifies"
            print(f"  {change['outcome']:<9} {change['name']}: now {tier}")
        print("\n  Re-run with --apply to write these changes.")

    if changes and args.fail_on_mismatch:
        print("\nThe README no longer matches what was verified.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
