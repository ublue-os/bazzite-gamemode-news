import importlib.util
import json
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(__file__))
_SCRIPT = os.path.join(_ROOT, ".github", "scripts", "build-announcements.py")


@pytest.fixture(scope="session")
def mod():
    spec = importlib.util.spec_from_file_location("build_announcements", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["build_announcements"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def releases():
    path = os.path.join(os.path.dirname(__file__), "fixtures", "bazzite-releases.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def stable_release(releases):
    return next(r for r in releases if not r["prerelease"])
