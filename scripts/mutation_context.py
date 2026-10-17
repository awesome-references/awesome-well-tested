#!/usr/bin/env python3
"""Write a mutation-context.json from a mutation tool's own report.

A mutation score without its context is not comparable (docs/mutation-context.md).
This script reads what the tool wrote, PIT's ``mutations.xml`` or mutmut's
``mutmut-cicd-stats.json``, and writes the context file the schema in
``docs/mutation-context.schema.json`` describes: the result breakdown in one
vocabulary for both tools, and the derived metrics.

The two scores it derives answer different questions:

- ``tool_score`` is what the tool reports. For PIT that is detected / total,
  and detected includes timeouts and errors; for mutmut it is killed / total.
- ``strict_score`` is killed / (total - equivalent - skipped): only an assertion
  kills, and mutants the repository has argued to be equivalent leave the
  denominator. The count comes from ``--equivalent``; the argument stays in
  the repository.

Standard library only, like the other scripts here.
"""

import argparse
import datetime as _dt
import json
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

SCHEMA_VERSION = "1.0"

# PIT counts these four as "detected"; the score it prints is their share.
PIT_DETECTED = ("KILLED", "TIMED_OUT", "MEMORY_ERROR", "RUN_ERROR")
PIT_STATUSES = PIT_DETECTED + ("SURVIVED", "NO_COVERAGE")

# mutmut's export-cicd-stats keys, mapped onto the schema's buckets.
MUTMUT_BUCKETS = {
    "killed": "killed",
    "survived": "survived",
    "no_tests": "no_coverage",
    "timeout": "timed_out",
    "suspicious": "errors",
    "segfault": "errors",
    "skipped": "skipped",
    "check_was_interrupted_by_user": "skipped",
}

RESULT_KEYS = ("total", "killed", "survived", "no_coverage", "timed_out", "errors",
               "skipped", "equivalent")


def empty_results():
    return {key: 0 for key in RESULT_KEYS}


def read_pit(path):
    """Return (results, mutators) from a PIT mutations.xml."""
    root = ET.parse(path).getroot()
    results = empty_results()
    mutators = set()
    for mutation in root.iter("mutation"):
        status = mutation.get("status", "")
        if status not in PIT_STATUSES:
            raise ValueError(f"unknown PIT status {status!r} in {path}")
        results["total"] += 1
        if status == "KILLED":
            results["killed"] += 1
        elif status == "SURVIVED":
            results["survived"] += 1
        elif status == "NO_COVERAGE":
            results["no_coverage"] += 1
        elif status == "TIMED_OUT":
            results["timed_out"] += 1
        else:
            results["errors"] += 1
        mutator = mutation.findtext("mutator")
        if mutator:
            mutators.add(mutator.rsplit(".", 1)[-1])
    return results, sorted(mutators)


def read_mutmut(path):
    """Return results from mutmut's mutmut-cicd-stats.json."""
    with open(path, encoding="utf-8") as handle:
        stats = json.load(handle)
    results = empty_results()
    for key, value in stats.items():
        if key == "total":
            results["total"] = int(value)
            continue
        bucket = MUTMUT_BUCKETS.get(key)
        if bucket is None:
            raise ValueError(f"unknown mutmut status {key!r} in {path}")
        results[bucket] += int(value)
    if results["total"] == 0:
        results["total"] = sum(results[k] for k in RESULT_KEYS if k != "total")
    return results


def apply_equivalent(results, equivalent):
    """Move ``equivalent`` mutants out of the survivors."""
    if equivalent < 0:
        raise ValueError("equivalent must not be negative")
    if equivalent > results["survived"]:
        raise ValueError(
            f"equivalent ({equivalent}) exceeds the survivors ({results['survived']})"
        )
    results["survived"] -= equivalent
    results["equivalent"] = equivalent
    return results


def _ratio(numerator, denominator):
    return round(numerator / denominator, 4) if denominator else 0.0


def metrics(results, tool):
    total = results["total"]
    detected = results["killed"] + results["timed_out"] + results["errors"]
    if tool == "pitest":
        tool_score = _ratio(detected, total)
    else:
        tool_score = _ratio(results["killed"], total)
    strict_denominator = total - results["equivalent"] - results["skipped"]
    covered = total - results["no_coverage"] - results["skipped"]
    return {
        "tool_score": tool_score,
        "strict_score": _ratio(results["killed"], strict_denominator),
        "test_strength": _ratio(detected, covered),
        "timeout_ratio": _ratio(results["timed_out"], total),
        "error_ratio": _ratio(results["errors"], total),
    }


def build_context(*, tool, tool_version, results, mutators, repository, commit,
                  measured_at, run_type, targets, excludes):
    return {
        "schema_version": SCHEMA_VERSION,
        "repository": repository,
        "commit": commit,
        "measured_at": measured_at,
        "run_type": run_type,
        "tool": {"name": tool, "version": tool_version},
        "mutators": list(mutators),
        "scope": {"targets": list(targets), "excludes": list(excludes)},
        "results": dict(results),
        "metrics": metrics(results, tool),
    }


def now_utc():
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Write a mutation-context.json from PIT's mutations.xml or "
                    "mutmut's mutmut-cicd-stats.json (docs/mutation-context.md).",
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--pit", metavar="MUTATIONS_XML",
                        help="PIT report, e.g. build/reports/pitest/mutations.xml")
    source.add_argument("--mutmut", metavar="STATS_JSON",
                        help="mutmut report, e.g. mutants/mutmut-cicd-stats.json")
    parser.add_argument("--tool-version", required=True,
                        help="the mutation tool's version, e.g. 1.30.0 or 3.5.0")
    parser.add_argument("--mutators", action="append", default=[],
                        help="the mutator group in effect, e.g. DEFAULTS or STRONGER "
                             "(PIT; repeatable). Without it the distinct mutators found "
                             "in the report are listed")
    parser.add_argument("--target", action="append", default=[],
                        help="a mutated package or path, repeatable")
    parser.add_argument("--exclude", action="append", default=[],
                        help="an excluded class, method or file, repeatable")
    parser.add_argument("--equivalent", type=int, default=0,
                        help="survivors the repository has argued to be equivalent")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"),
                        help="owner/name; defaults to $GITHUB_REPOSITORY")
    parser.add_argument("--commit", default=os.environ.get("GITHUB_SHA"),
                        help="the measured commit; defaults to $GITHUB_SHA")
    parser.add_argument("--measured-at", default=None,
                        help="ISO 8601 UTC timestamp; defaults to now")
    parser.add_argument("--run-type", choices=("full", "incremental"), default="full")
    parser.add_argument("--out", metavar="FILE",
                        help="write here instead of standard output")
    args = parser.parse_args(argv)
    if not args.repo or not args.commit:
        parser.error("--repo and --commit are required outside GitHub Actions "
                     "(no GITHUB_REPOSITORY / GITHUB_SHA in the environment)")
    return args


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        if args.pit:
            tool = "pitest"
            results, found = read_pit(args.pit)
        else:
            tool = "mutmut"
            results, found = read_mutmut(args.mutmut), []
        apply_equivalent(results, args.equivalent)
    except (OSError, ValueError, ET.ParseError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    context = build_context(
        tool=tool,
        tool_version=args.tool_version,
        results=results,
        mutators=args.mutators or found,
        repository=args.repo,
        commit=args.commit,
        measured_at=args.measured_at or now_utc(),
        run_type=args.run_type,
        targets=args.target,
        excludes=args.exclude,
    )
    text = json.dumps(context, indent=2) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
