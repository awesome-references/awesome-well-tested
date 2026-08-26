"""Import shim so the scripts/ directory can be imported as a package.

The scripts are executables rather than an installed package, so they are loaded
by path. Loading has to be idempotent: a module that imports another one puts it
in sys.modules first, and loading a second copy afterwards would give the tests
a different `VerificationIncomplete` class than the code raising it - so an
except clause written against one would not catch the other.
"""

import importlib.util
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent.parent / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def _load(name):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        del sys.modules[name]
        raise
    return module


readme_table = _load("readme_table")
verify_repo = _load("verify_repo")
recheck_listed = _load("recheck_listed")
prune_unchanged_reports = _load("prune_unchanged_reports")
discover_candidates = _load("discover_candidates")
