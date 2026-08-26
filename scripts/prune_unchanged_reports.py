#!/usr/bin/env python3
"""
prune_unchanged_reports.py - Discard report changes that carry no information.

Every verification run stamps a fresh `verified_at`, and star counts and push
dates drift on their own. Left alone, the weekly verify workflow would open a
pull request every single week whose entire diff is timestamps.

This restores any report under reports/ whose only differences are volatile
fields, so a pull request is opened when something that actually matters
changed: the tier, the coverage figure, the mutation score, the detected
tooling, the badges, or the recorded issues.

A report's `verified_at` therefore reads as "when this result was established",
not "when it was last looked at". The workflow run itself is the record that a
check happened.

Usage:
    python prune_unchanged_reports.py
    python prune_unchanged_reports.py --base HEAD --dry-run
"""

import argparse
import copy
import json
import re
import subprocess
import sys
from pathlib import Path

# Fields that change on their own without saying anything about test quality.
VOLATILE_TOP_LEVEL = ["verified_at"]
VOLATILE_METADATA = ["stars", "forks", "last_push", "days_since_push"]
# age_days is computed from "now" at verification time, so it grows by seven
# every week for an entry whose coverage figure has not moved. Leaving it in the
# comparison meant nothing was ever equal and every weekly run opened the noise
# pull request this script exists to suppress.
VOLATILE_COVERAGE = ["age_days"]
# A code-search total_count drifts as the repository grows.
VOLATILE_PARAMETERIZED = ["matches"]
# The activity issue embeds a day count whose own source field is stripped.
DAY_COUNT_IN_TEXT = re.compile(r"No activity for \d+ days")


def strip_volatile(report: dict) -> dict:
    """Return a copy of the report without the fields that drift on their own."""
    stripped = copy.deepcopy(report)
    for key in VOLATILE_TOP_LEVEL:
        stripped.pop(key, None)

    metadata = stripped.get("metadata")
    if isinstance(metadata, dict):
        for key in VOLATILE_METADATA:
            metadata.pop(key, None)

    coverage = stripped.get("coverage")
    if isinstance(coverage, dict):
        for key in VOLATILE_COVERAGE:
            coverage.pop(key, None)

    parameterized = stripped.get("parameterized_tests")
    if isinstance(parameterized, dict):
        # These describe the run that looked, not the repository it looked at.
        for key in ("terms_tried", "terms_available", "complete"):
            parameterized.pop(key, None)
        for framework in parameterized.get("frameworks") or []:
            if isinstance(framework, dict):
                for key in VOLATILE_PARAMETERIZED:
                    framework.pop(key, None)

    issues = stripped.get("issues")
    if isinstance(issues, list):
        stripped["issues"] = [
            DAY_COUNT_IN_TEXT.sub("No activity for over a year", issue)
            if isinstance(issue, str) else issue
            for issue in issues
        ]

    return stripped


def git(*args: str, cwd: Path) -> str:
    result = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout


def changed_reports(repo_root: Path, base: str) -> list[str]:
    """Paths of reports that differ from the base revision, tracked ones only."""
    out = git("diff", "--name-only", base, "--", "reports", cwd=repo_root)
    return [line for line in out.split("\n") if line.strip()]


def main():
    parser = argparse.ArgumentParser(
        description="Restore reports whose only changes are volatile fields"
    )
    parser.add_argument(
        "--base", default="HEAD", help="Revision to compare against (default HEAD)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be restored without touching anything",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    paths = changed_reports(repo_root, args.base)

    if not paths:
        print("No report changes.")
        return 0

    pruned, kept = [], []
    for path in paths:
        working_file = repo_root / path
        if not working_file.exists():
            kept.append(path)
            continue
        try:
            previous = json.loads(git("show", f"{args.base}:{path}", cwd=repo_root))
            current = json.loads(working_file.read_text())
        except (RuntimeError, json.JSONDecodeError):
            # A new or unreadable report is a real change; leave it alone.
            kept.append(path)
            continue

        if strip_volatile(previous) == strip_volatile(current):
            pruned.append(path)
        else:
            kept.append(path)

    if pruned and not args.dry_run:
        git("checkout", "--", *pruned, cwd=repo_root)

    verb = "Would restore" if args.dry_run else "Restored"
    print(f"{verb} {len(pruned)} report(s) with volatile-only changes:")
    for path in pruned:
        print(f"  {path}")
    print(f"Kept {len(kept)} report(s) with real changes:")
    for path in kept:
        print(f"  {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
