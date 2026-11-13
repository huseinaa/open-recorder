"""Every module imports. The recorder runs as its own process, so a syntax error in it would
otherwise only show up as the Record button doing nothing."""
import importlib
import pkgutil

import pytest

import open_recorder

MODULES = sorted(m.name for m in pkgutil.walk_packages(open_recorder.__path__, "open_recorder.")
                 if not m.name.endswith("__main__"))


@pytest.mark.parametrize("name", MODULES)
def test_module_imports(name):
    importlib.import_module(name)
