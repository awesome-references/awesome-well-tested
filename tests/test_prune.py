"""Tests for deciding whether a run has anything to say.

The weekly job opens a pull request when reports change. Without this, every run
opened one whose entire diff was timestamps.
"""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from _support import prune_unchanged_reports as prune


def git(*args, cwd):
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True
    ).stdout


BASE = {
    "repository": "acme/widget",
    "verified_at": "2026-01-01T00:00:00+00:00",
    "tier": "gold",
    "coverage": {"service": "Codecov", "coverage": 95.0},
    "metadata": {"stars": 10, "forks": 2, "last_push": "2026-01-01T00:00:00Z",
                 "days_since_push": 1, "language": "Java"},
}


class InAGitRepository(unittest.TestCase):
    """prune_unchanged_reports shells out to git, so it needs a real one."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.root = Path(self.dir.name)
        (self.root / "scripts").mkdir()
        self.reports = self.root / "reports"
        self.reports.mkdir()

        git("init", "-q", cwd=self.root)
        git("config", "user.email", "t@example.invalid", cwd=self.root)
        git("config", "user.name", "Test", cwd=self.root)
        self.write("acme_widget.json", BASE)
        self.write("acme_other.json", {**BASE, "repository": "acme/other"})
        git("add", "-A", cwd=self.root)
        git("commit", "-qm", "reports", cwd=self.root)

        # The module locates the repository relative to its own file.
        original = prune.__file__
        prune.__file__ = str(self.root / "scripts" / "prune_unchanged_reports.py")
        self.addCleanup(setattr, prune, "__file__", original)

    def write(self, name, payload):
        (self.reports / name).write_text(json.dumps(payload, indent=2) + "\n")

    def run_prune(self, *args):
        import io
        import sys

        out, original = io.StringIO(), sys.stdout
        sys.stdout = out
        try:
            code = self._main(*args)
        finally:
            sys.stdout = original
        return code, out.getvalue()

    def _main(self, *args):
        import sys

        original = sys.argv
        sys.argv = ["prune_unchanged_reports.py", *args]
        try:
            return prune.main()
        finally:
            sys.argv = original

    def changed(self):
        return [
            line[3:] for line in
            git("status", "--porcelain", "reports", cwd=self.root).splitlines()
        ]

    # -- the point of the thing ---------------------------------------------

    def test_a_run_that_only_restamped_is_restored(self):
        self.write("acme_widget.json", {**BASE, "verified_at": "2026-06-01T00:00:00+00:00"})
        code, output = self.run_prune()
        self.assertEqual(code, 0)
        self.assertIn("Restored 1", output)
        self.assertEqual(self.changed(), [])

    def test_drifting_stars_and_push_dates_are_restored(self):
        payload = json.loads(json.dumps(BASE))
        payload["metadata"].update({"stars": 4000, "days_since_push": 99,
                                    "last_push": "2026-06-01T00:00:00Z"})
        payload["verified_at"] = "2026-06-01T00:00:00+00:00"
        self.write("acme_widget.json", payload)
        self.run_prune()
        self.assertEqual(self.changed(), [])

    def test_a_tier_change_is_kept(self):
        self.write("acme_widget.json", {**BASE, "tier": "silver",
                                        "verified_at": "2026-06-01T00:00:00+00:00"})
        code, output = self.run_prune()
        self.assertIn("Kept 1", output)
        self.assertTrue(self.changed())

    def test_a_coverage_change_is_kept(self):
        payload = json.loads(json.dumps(BASE))
        payload["coverage"]["coverage"] = 81.0
        self.write("acme_widget.json", payload)
        self.run_prune()
        self.assertTrue(self.changed())

    def test_a_new_report_is_kept(self):
        self.write("acme_new.json", {**BASE, "repository": "acme/new"})
        git("add", "-A", cwd=self.root)
        code, output = self.run_prune()
        self.assertIn("Kept", output)

    def test_nothing_changed_says_so(self):
        code, output = self.run_prune()
        self.assertEqual(code, 0)
        self.assertIn("No report changes", output)

    def test_a_dry_run_changes_nothing_on_disk(self):
        self.write("acme_widget.json", {**BASE, "verified_at": "2026-06-01T00:00:00+00:00"})
        code, output = self.run_prune("--dry-run")
        self.assertIn("Would restore", output)
        self.assertTrue(self.changed())

    def test_one_restored_report_does_not_restore_another(self):
        self.write("acme_widget.json", {**BASE, "verified_at": "2026-06-01T00:00:00+00:00"})
        self.write("acme_other.json", {**BASE, "repository": "acme/other", "tier": "bronze"})
        self.run_prune()
        self.assertEqual(self.changed(), ["reports/acme_other.json"])


if __name__ == "__main__":
    unittest.main()
