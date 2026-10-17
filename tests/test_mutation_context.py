"""Tests for the mutation-context converter.

Every case is a row in a module-level table; a new case is a new row. The
fixtures are the smallest reports that exercise a status, not real runs; the
real numbers of 2026-10-16 appear once, as the worked example the docs quote.
"""

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from _support import mutation_context as mc

HERE = Path(__file__).resolve().parent
SCHEMA = HERE.parent / "docs" / "mutation-context.schema.json"


def pit_xml(statuses, mutator="org.pitest.mutationtest.engine.gregor.mutators.MathMutator"):
    items = "".join(
        f'<mutation detected="{str(s in mc.PIT_DETECTED).lower()}" status="{s}">'
        f"<sourceFile>A.java</sourceFile><mutator>{mutator}</mutator></mutation>"
        for s in statuses
    )
    return f'<?xml version="1.0" encoding="UTF-8"?><mutations>{items}</mutations>'


# (id, statuses in the XML, expected results without the "total" key)
PIT_CASES = [
    ("all-killed", ["KILLED"] * 3,
     dict(killed=3, survived=0, no_coverage=0, timed_out=0, errors=0)),
    ("one-of-each", ["KILLED", "SURVIVED", "NO_COVERAGE", "TIMED_OUT", "MEMORY_ERROR", "RUN_ERROR"],
     dict(killed=1, survived=1, no_coverage=1, timed_out=1, errors=2)),
    ("empty-report", [],
     dict(killed=0, survived=0, no_coverage=0, timed_out=0, errors=0)),
]

# (id, mutmut stats, expected results)
MUTMUT_CASES = [
    ("manuscripta-2026-10-16",
     {"killed": 4824, "survived": 566, "total": 5390, "no_tests": 0, "skipped": 0,
      "suspicious": 0, "timeout": 0, "check_was_interrupted_by_user": 0, "segfault": 0},
     dict(total=5390, killed=4824, survived=566, no_coverage=0, timed_out=0, errors=0,
          skipped=0, equivalent=0)),
    ("every-bucket",
     {"killed": 5, "survived": 2, "total": 14, "no_tests": 1, "skipped": 1,
      "suspicious": 1, "timeout": 2, "check_was_interrupted_by_user": 1, "segfault": 1},
     dict(total=14, killed=5, survived=2, no_coverage=1, timed_out=2, errors=2,
          skipped=2, equivalent=0)),
    ("total-missing-is-summed",
     {"killed": 3, "survived": 1},
     dict(total=4, killed=3, survived=1, no_coverage=0, timed_out=0, errors=0,
          skipped=0, equivalent=0)),
]

# (id, tool, results, expected metrics)
METRIC_CASES = [
    ("crypt-data-2026-10-16", "pitest",
     dict(total=866, killed=860, survived=4, no_coverage=0, timed_out=2, errors=0,
          skipped=0, equivalent=0),
     dict(tool_score=0.9954, strict_score=0.9931, test_strength=0.9954,
          timeout_ratio=0.0023, error_ratio=0.0)),
    ("manuscripta-with-equivalents", "mutmut",
     dict(total=5390, killed=4824, survived=171, no_coverage=0, timed_out=0, errors=0,
          skipped=0, equivalent=395),
     dict(tool_score=0.895, strict_score=0.9658, test_strength=0.895,
          timeout_ratio=0.0, error_ratio=0.0)),
    ("pit-counts-errors-as-detected-strict-does-not", "pitest",
     dict(total=10, killed=5, survived=1, no_coverage=1, timed_out=1, errors=2,
          skipped=0, equivalent=0),
     dict(tool_score=0.8, strict_score=0.5, test_strength=0.8889,
          timeout_ratio=0.1, error_ratio=0.2)),
    ("mutmut-skipped-leave-both-denominators", "mutmut",
     dict(total=10, killed=6, survived=1, no_coverage=1, timed_out=0, errors=0,
          skipped=2, equivalent=0),
     dict(tool_score=0.6, strict_score=0.75, test_strength=0.8571,
          timeout_ratio=0.0, error_ratio=0.0)),
    ("empty-report-is-all-zero", "pitest",
     dict(total=0, killed=0, survived=0, no_coverage=0, timed_out=0, errors=0,
          skipped=0, equivalent=0),
     dict(tool_score=0.0, strict_score=0.0, test_strength=0.0,
          timeout_ratio=0.0, error_ratio=0.0)),
]

# (id, survivors, equivalent, expected (survived, equivalent) or the error text)
EQUIVALENT_CASES = [
    ("none", 4, 0, (4, 0)),
    ("some", 566, 395, (171, 395)),
    ("all", 3, 3, (0, 3)),
    ("more-than-survived", 3, 4, "exceeds the survivors"),
    ("negative", 3, -1, "must not be negative"),
]


class ReadingPit(unittest.TestCase):

    def test_statuses_land_in_their_buckets(self):
        for case_id, statuses, expected in PIT_CASES:
            with self.subTest(case_id):
                with tempfile.TemporaryDirectory() as tmp:
                    path = Path(tmp) / "mutations.xml"
                    path.write_text(pit_xml(statuses), encoding="utf-8")
                    results, mutators = mc.read_pit(path)
                self.assertEqual(results["total"], len(statuses))
                for key, value in expected.items():
                    self.assertEqual(results[key], value, key)
                self.assertEqual(results["skipped"], 0)
                self.assertEqual(results["equivalent"], 0)
                self.assertEqual(mutators, ["MathMutator"] if statuses else [])

    def test_mutators_are_the_distinct_simple_names(self):
        xml = pit_xml(["KILLED"], "a.b.NullReturnValsMutator") + ""
        xml = xml.replace("</mutations>",
                          pit_xml(["SURVIVED"], "a.b.MathMutator").split("<mutations>")[1])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mutations.xml"
            path.write_text(xml, encoding="utf-8")
            _, mutators = mc.read_pit(path)
        self.assertEqual(mutators, ["MathMutator", "NullReturnValsMutator"])

    def test_unknown_status_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mutations.xml"
            path.write_text(pit_xml(["KILLED", "BOGUS"]), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "BOGUS"):
                mc.read_pit(path)


class ReadingMutmut(unittest.TestCase):

    def test_stats_land_in_their_buckets(self):
        for case_id, stats, expected in MUTMUT_CASES:
            with self.subTest(case_id):
                with tempfile.TemporaryDirectory() as tmp:
                    path = Path(tmp) / "mutmut-cicd-stats.json"
                    path.write_text(json.dumps(stats), encoding="utf-8")
                    results = mc.read_mutmut(path)
                self.assertEqual(results, expected)

    def test_unknown_key_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "stats.json"
            path.write_text(json.dumps({"killed": 1, "exploded": 2}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "exploded"):
                mc.read_mutmut(path)


class Metrics(unittest.TestCase):

    def test_scores(self):
        for case_id, tool, results, expected in METRIC_CASES:
            with self.subTest(case_id):
                self.assertEqual(mc.metrics(results, tool), expected)

    def test_equivalent_moves_out_of_the_survivors(self):
        for case_id, survived, equivalent, expected in EQUIVALENT_CASES:
            with self.subTest(case_id):
                results = dict(mc.empty_results(), total=survived + 1, killed=1,
                               survived=survived)
                if isinstance(expected, str):
                    with self.assertRaisesRegex(ValueError, expected):
                        mc.apply_equivalent(results, equivalent)
                else:
                    mc.apply_equivalent(results, equivalent)
                    self.assertEqual((results["survived"], results["equivalent"]), expected)


class TheContextFile(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.pit = self.root / "mutations.xml"
        self.pit.write_text(pit_xml(["KILLED", "KILLED", "SURVIVED", "TIMED_OUT"]),
                            encoding="utf-8")
        self.schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    def run_main(self, *argv, env=None):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, env or {}, clear=False):
            for key in ("GITHUB_REPOSITORY", "GITHUB_SHA"):
                if env is None or key not in env:
                    os.environ.pop(key, None)
            with redirect_stdout(out), redirect_stderr(err):
                code = mc.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_every_required_key_of_the_schema_is_written(self):
        code, out, _ = self.run_main("--pit", str(self.pit), "--tool-version", "1.30.0",
                                     "--repo", "acme/widget", "--commit", "0123456",
                                     "--measured-at", "2026-10-16T11:52:00Z",
                                     "--mutators", "DEFAULTS", "--target", "acme.*",
                                     "--exclude", "*.generated.*")
        self.assertEqual(code, 0)
        context = json.loads(out)
        self.assertEqual(set(context), set(self.schema["required"]))
        for block in ("tool", "scope", "results", "metrics"):
            self.assertEqual(set(context[block]),
                             set(self.schema["properties"][block]["required"]), block)
        self.assertEqual(context["tool"], {"name": "pitest", "version": "1.30.0"})
        self.assertEqual(context["mutators"], ["DEFAULTS"])
        self.assertEqual(context["scope"], {"targets": ["acme.*"], "excludes": ["*.generated.*"]})
        self.assertEqual(context["results"]["total"], 4)
        self.assertEqual(context["metrics"]["tool_score"], 0.75)
        self.assertEqual(context["metrics"]["strict_score"], 0.5)
        self.assertEqual(context["measured_at"], "2026-10-16T11:52:00Z")
        self.assertEqual(context["run_type"], "full")

    def test_mutators_default_to_the_ones_found(self):
        code, out, _ = self.run_main("--pit", str(self.pit), "--tool-version", "1.30.0",
                                     "--repo", "acme/widget", "--commit", "0123456")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["mutators"], ["MathMutator"])

    def test_repository_and_commit_come_from_github_actions(self):
        code, out, _ = self.run_main("--pit", str(self.pit), "--tool-version", "1.30.0",
                                     env={"GITHUB_REPOSITORY": "acme/widget",
                                          "GITHUB_SHA": "abcdef0123"})
        self.assertEqual(code, 0)
        context = json.loads(out)
        self.assertEqual((context["repository"], context["commit"]),
                         ("acme/widget", "abcdef0123"))
        self.assertRegex(context["measured_at"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

    def test_without_them_the_script_exits_2(self):
        with self.assertRaises(SystemExit) as caught:
            self.run_main("--pit", str(self.pit), "--tool-version", "1.30.0")
        self.assertEqual(caught.exception.code, 2)

    def test_mutmut_with_equivalents_writes_the_file(self):
        stats = self.root / "stats.json"
        stats.write_text(json.dumps({"killed": 4824, "survived": 566, "total": 5390}),
                         encoding="utf-8")
        out = self.root / "mutation-context.json"
        code, stdout, _ = self.run_main("--mutmut", str(stats), "--tool-version", "3.5.0",
                                        "--equivalent", "395", "--repo", "astrapi69/manuscripta",
                                        "--commit", "7cf657f", "--out", str(out))
        self.assertEqual((code, stdout), (0, ""))
        context = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(context["tool"], {"name": "mutmut", "version": "3.5.0"})
        self.assertEqual(context["mutators"], [])
        self.assertEqual(context["results"]["survived"], 171)
        self.assertEqual(context["results"]["equivalent"], 395)
        self.assertEqual(context["metrics"]["tool_score"], 0.895)
        self.assertEqual(context["metrics"]["strict_score"], 0.9658)

    def test_a_bad_report_is_an_error_not_a_traceback(self):
        bad = self.root / "bad.xml"
        bad.write_text("<mutations><mutation status='KILLED'>", encoding="utf-8")
        code, out, err = self.run_main("--pit", str(bad), "--tool-version", "1.30.0",
                                       "--repo", "acme/widget", "--commit", "0123456")
        self.assertEqual((code, out), (1, ""))
        self.assertTrue(err.startswith("error: "), err)

    def test_too_many_equivalents_is_an_error(self):
        code, _, err = self.run_main("--pit", str(self.pit), "--tool-version", "1.30.0",
                                     "--equivalent", "5", "--repo", "acme/widget",
                                     "--commit", "0123456")
        self.assertEqual(code, 1)
        self.assertIn("exceeds the survivors", err)


class TheSchema(unittest.TestCase):

    def test_is_valid_json_with_the_buckets_the_script_writes(self):
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        self.assertEqual(schema["properties"]["schema_version"]["const"], mc.SCHEMA_VERSION)
        self.assertEqual(set(schema["properties"]["results"]["required"]), set(mc.RESULT_KEYS))
        self.assertEqual(set(schema["properties"]["metrics"]["required"]),
                         set(mc.metrics(mc.empty_results(), "pitest")))


if __name__ == "__main__":
    unittest.main()
