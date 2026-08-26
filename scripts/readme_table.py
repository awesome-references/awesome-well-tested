#!/usr/bin/env python3
"""
readme_table.py - Read and rewrite the entry tables in README.md.

The list lives in markdown tables, one per language, and several scripts need to
read entries out of them or write entries back. Doing that with string
replacement is how rows end up under the wrong heading, so everything here works
on parsed cells and re-renders whole tables.

awesome-lint requires aligned pipes, so rendering always pads.
"""

import re
from pathlib import Path

SEPARATOR = re.compile(r"^\|[\s:|-]+\|$")
REPO_LINK = re.compile(r"\[[^\]]+\]\(https://github\.com/([^/)]+)/([^/)#]+?)/?\)")
TIER_BADGE = re.compile(r"!\[(Gold|Silver|Bronze)\]\(badges/", re.IGNORECASE)

# How a report's raw keys are spelled in the list.
COVERAGE_TOOL_NAMES = {
    "jacoco": "JaCoCo",
    "kover": "Kover",
    "phpunit": "PHPUnit",
    "istanbul": "Istanbul/nyc",
    "pytest-cov": "pytest-cov",
    "coverage.py": "coverage.py",
    "simplecov": "SimpleCov",
    "go_cover": "go cover",
    "tarpaulin": "tarpaulin",
}
MUTATION_TOOL_NAMES = {
    "pit": "PIT",
    "stryker": "Stryker",
    "infection": "Infection",
    "mutmut": "mutmut",
    "cosmic-ray": "cosmic-ray",
    "mutant": "mutant",
    "cargo-mutants": "cargo-mutants",
    "go-mutesting": "go-mutesting",
}
# Beyond this the figure is annotated with the year it was measured. A year is
# long enough that most projects have moved on, and short enough that an annual
# release cycle does not get flagged.
STALE_AFTER_DAYS = 365

# Long enough to identify a branch, short enough not to set the table width.
BRANCH_NAME_LIMIT = 24

PARAMETERIZED_SHORT = {
    "JUnit 5 @ParameterizedTest": "JUnit 5",
    "JUnit 4 @Parameterized": "JUnit 4",
    "PHPUnit @dataProvider": "PHPUnit",
    "pytest.mark.parametrize": "pytest",
    "Hypothesis (property-based)": "Hypothesis",
    "fast-check (property-based)": "fast-check",
    "proptest (property-based)": "proptest",
    "quickcheck (property-based)": "quickcheck",
    "RSpec shared examples": "RSpec",
    "Jest/Vitest .each": "Jest/Vitest",
    "Kotest property testing": "Kotest",
    "jqwik (property-based)": "jqwik",
    "Spock @Unroll": "Spock",
    "xUnit [Theory]/[InlineData]": "xUnit",
    "NUnit [TestCase]": "NUnit",
    "FsCheck (property-based)": "FsCheck",
    "Rantly (property-based)": "Rantly",
    "rstest": "rstest",
}


def split_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def render_table(rows: list[list[str]]) -> list[str]:
    """Render parsed rows back to aligned markdown."""
    width_count = max(len(r) for r in rows)
    rows = [r + [""] * (width_count - len(r)) for r in rows]
    widths = [
        max(3, max(len(rows[n][c]) for n in range(len(rows)) if n != 1))
        for c in range(width_count)
    ]
    out = []
    for n, row in enumerate(rows):
        if n == 1:
            cells = ["-" * widths[c] for c in range(width_count)]
        else:
            cells = [row[c].ljust(widths[c]) for c in range(width_count)]
        out.append("| " + " | ".join(cells) + " |")
    return out


def _is_placeholder(row: list[str]) -> bool:
    return not row or not row[0] or row[0].startswith("<!--")


def transform_tables(text: str, transform) -> str:
    """Run `transform(section, header, body_rows)` over every entry table.

    The callback returns the body rows to keep. Tables without a Repository
    column, and everything outside a table, are passed through untouched.
    """
    lines = text.split("\n")
    out, i, section = [], 0, None
    while i < len(lines):
        if lines[i].startswith("## "):
            section = lines[i][3:].strip()
        if (
            lines[i].startswith("|")
            and i + 1 < len(lines)
            and SEPARATOR.match(lines[i + 1])
        ):
            block = []
            while i < len(lines) and lines[i].startswith("|"):
                block.append(lines[i])
                i += 1
            rows = [split_row(line) for line in block]
            header = rows[0]
            if "Repository" in header:
                body = [r for r in rows[2:] if not _is_placeholder(r)]
                body = transform(section, header, body)
                if not body:
                    # An empty section keeps its placeholder, so the table stays
                    # readable and the next entry has somewhere to go.
                    body = [["<!-- entries go here -->"] + [""] * (len(header) - 1)]
                rows = rows[:2] + body
            out.extend(render_table(rows))
        else:
            out.append(lines[i])
            i += 1
    return "\n".join(out)


def parse_entries(text: str) -> list[dict]:
    """Every listed entry: owner, repo, claimed tier and the section it sits in."""
    entries = []
    section = None
    for line in text.split("\n"):
        if line.startswith("## "):
            section = line[3:].strip()
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
                "full_name": f"{repo_match.group(1)}/{repo_match.group(2)}",
                "claimed_tier": tier_match.group(1).lower(),
                "section": section,
            }
        )
    return entries


def row_full_name(row: list[str]) -> str | None:
    match = REPO_LINK.search(row[0]) if row else None
    return f"{match.group(1)}/{match.group(2)}" if match else None


def cells_from_report(report: dict, header: list[str]) -> dict:
    """The cell values a report implies, keyed by column heading."""
    tier = report["tier"]
    coverage_info = report["coverage"]
    coverage_text = f"{coverage_info['coverage']:g}%"

    # Both services report the last build they saw, on whatever branch that was.
    # A figure from a release branch, or one measured years before the code it
    # is quoted against, is still worth listing - but not without saying so.
    qualifiers = []
    if coverage_info.get("is_default_branch") is False and coverage_info.get("branch"):
        branch = coverage_info["branch"]
        # Dependabot and release-automation branch names run to fifty characters
        # and would set the width of the whole table.
        if len(branch) > BRANCH_NAME_LIMIT:
            branch = branch[: BRANCH_NAME_LIMIT - 1] + "\u2026"
        qualifiers.append(branch)
    age = coverage_info.get("age_days")
    measured_at = coverage_info.get("measured_at") or ""
    if age is not None and age > STALE_AFTER_DAYS and len(measured_at) >= 4:
        qualifiers.append(measured_at[:4])
    if qualifiers:
        coverage_text += f" ({', '.join(qualifiers)})"

    tool_key = report.get("primary_coverage_tool")
    coverage_tool = COVERAGE_TOOL_NAMES.get(tool_key, tool_key) or report["coverage"]["service"]

    mutation = ", ".join(
        MUTATION_TOOL_NAMES.get(k, k) for k in (report.get("mutation_tools") or {})
    ) or "n/a"

    score = report.get("mutation_score")
    if score is None:
        score_text = "n/a"
    elif report.get("mutation_score_source") == "readme-badge":
        # High enough for Gold or not, the number came from the repository's own
        # README, and the column says so.
        score_text = f"{score:g}% (self-reported)"
    elif report.get("mutation_score_source") == "ci-threshold":
        score_text = f">= {score:g}%"
    else:
        score_text = f"{score:g}%"

    parameterized = report.get("parameterized_tests")
    if parameterized and parameterized.get("frameworks"):
        param_text = ", ".join(
            PARAMETERIZED_SHORT.get(f["framework"], f["framework"])
            for f in parameterized["frameworks"]
        )
    elif parameterized is None:
        param_text = "n/a"
    else:
        param_text = "no"

    values = {
        "Tier": f"![{tier.capitalize()}](badges/{tier}.svg)",
        "Coverage": coverage_text,
        "Mutation Score": score_text,
        "Param. Tests": param_text,
        "Coverage Tool": coverage_tool,
        "Mutation Tool": mutation,
        "Language": report["metadata"].get("language") or "",
    }
    return {k: v for k, v in values.items() if k in header}


def update_row(row: list[str], header: list[str], cells: dict) -> list[str]:
    """Apply cell values to a row, leaving columns we have no opinion on alone."""
    updated = list(row) + [""] * (len(header) - len(row))
    for column, value in cells.items():
        updated[header.index(column)] = value
    return updated


def read_readme(path: str | Path) -> str:
    return Path(path).read_text()


def write_readme(path: str | Path, text: str) -> None:
    text = re.sub(r"\n{3,}", "\n\n", text).rstrip() + "\n"
    Path(path).write_text(text)
