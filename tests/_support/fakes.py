"""A GitHub, Codecov, Coveralls and Stryker stand-in built from a dict.

Every network-facing function in verify_repo takes its client as an argument,
which makes the whole verification pipeline testable without a token, a network
or a rate limit. Anything the fake is not told about answers the way the real
services answer for something that is not there: None.
"""

import json
import urllib.parse


class FakeAPI:
    """Serves canned responses and records what was asked for."""

    def __init__(
        self,
        *,
        metadata=None,
        tree=None,
        files=None,
        workflows=None,
        coverage=None,
        dashboard=None,
        searches=None,
        runs=None,
        jobs=None,
        authenticated=True,
        raise_on=None,
    ):
        self.metadata = metadata
        self.tree = tree
        self.files = files or {}
        self.workflows = workflows or {}
        self.coverage = coverage or {}
        self.dashboard = dashboard or {}
        self.searches = searches or {}
        self.runs = runs
        self.jobs = jobs
        self.authenticated = authenticated
        self.raise_on = raise_on or ()
        self.requests = 0
        self.asked = []

    # -- helpers -------------------------------------------------------------

    def _record(self, url):
        self.requests += 1
        self.asked.append(url)
        for fragment, error in self.raise_on:
            if fragment in url:
                raise error

    @staticmethod
    def _path_of(url):
        """The contents path out of a .../contents/<path>?ref=... URL."""
        path = url.split("/contents/", 1)[1].split("?", 1)[0]
        return urllib.parse.unquote(path)

    # -- the three methods verify_repo actually calls -------------------------

    def get(self, url):
        self._record(url)

        if "/git/trees/" in url:
            if self.tree is None:
                return {"truncated": True, "tree": []}
            return {
                "truncated": False,
                "tree": [{"path": p, "type": "blob"} for p in self.tree],
            }

        if "/search/code?" in url:
            query = urllib.parse.unquote(urllib.parse.parse_qs(url.split("?", 1)[1])["q"][0])
            term = query.split(" ", 1)[1] if " " in query else query
            return {"total_count": self.searches.get(term, 0)}

        if "/actions/workflows/" in url:
            return self.runs

        if "/actions/runs/" in url and "/jobs" in url:
            return self.jobs

        if "/contents/" in url and self._path_of(url) == ".github/workflows":
            return [{"name": n} for n in self.workflows]

        if "/contents/" in url:
            return self.files.get(self._path_of(url))

        if url.rstrip("/").endswith(f"/repos/{self.full_name}") if self.metadata else False:
            return self.metadata

        return self.metadata

    def get_text(self, url):
        self._record(url)
        path = self._path_of(url)
        if path.startswith(".github/workflows/"):
            return self.workflows.get(path.split("/", 2)[2])
        return self.files.get(path)

    def get_public_json(self, url):
        self._record(url)
        if "codecov" in url:
            return self.coverage.get("codecov")
        if "coveralls" in url:
            return self.coverage.get("coveralls")
        if "stryker" in url:
            branch = url.rstrip("/").rsplit("/", 1)[-1]
            return self.dashboard.get(branch)
        return None

    @property
    def full_name(self):
        return (self.metadata or {}).get("full_name", "")


def repo_metadata(**overrides):
    """Metadata shaped like the GitHub repository endpoint returns it."""
    data = {
        "full_name": "acme/widget",
        "description": "a widget",
        "language": "Java",
        "license": {"spdx_id": "MIT"},
        "stargazers_count": 120,
        "forks_count": 3,
        "archived": False,
        "fork": False,
        "pushed_at": "2026-08-20T00:00:00Z",
        "default_branch": "main",
    }
    data.update(overrides)
    return data


def codecov(coverage=95.0, branch="main", updatestamp="2026-08-20T00:00:00Z"):
    return {"branch": branch, "updatestamp": updatestamp, "totals": {"coverage": coverage}}


def coveralls(coverage=95.0, branch="main", created_at="2026-08-20T00:00:00Z"):
    return {"branch": branch, "created_at": created_at, "covered_percent": coverage}


def elements_report(killed=90, survived=10, ignored=0, no_coverage=0):
    """A mutation-testing-elements report with a known score."""
    mutants = (
        [{"status": "Killed"}] * killed
        + [{"status": "Survived"}] * survived
        + [{"status": "Ignored"}] * ignored
        + [{"status": "NoCoverage"}] * no_coverage
    )
    return {"schemaVersion": "1.0", "files": {"src/Thing.php": {"mutants": mutants}}}
