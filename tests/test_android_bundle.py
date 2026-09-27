"""The phone app bundles an explicit list of the bot's modules (mobile/plugins/withBotRuntime.js).

A module the runtime imports but the list leaves out builds fine and then fails on the phone at
start, so this test fails first: add the new module to BOT_MODULES (or its package to BOT_PACKAGES).
"""

import modulefinder
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _bundled():
    js = (ROOT / "mobile" / "plugins" / "withBotRuntime.js").read_text(encoding="utf-8")
    modules = re.search(r"const BOT_MODULES = \[(.*?)\];", js, re.S).group(1)
    packages = re.search(r"const BOT_PACKAGES = \[(.*?)\];", js, re.S).group(1)
    return set(re.findall(r"'(\w+)\.py'", modules)), set(re.findall(r"'(\w+)'", packages))


def _imported_repo_modules():
    # Only the repo is on the search path: third-party and stdlib imports are skipped, and imports
    # inside functions are followed too.
    finder = modulefinder.ModuleFinder(path=[str(ROOT)])
    finder.run_script(str(ROOT / "local_runtime.py"))
    found = set()
    for name, mod in finder.modules.items():
        if name == "__main__" or not mod.__file__:
            continue
        found.add(name.split(".")[0])
    return found


def test_phone_bundle_has_every_module_the_runtime_imports():
    modules, packages = _bundled()
    missing = {
        name
        for name in _imported_repo_modules()
        if name not in modules and name not in packages and name != "local_runtime"
    }
    assert not missing, f"add to BOT_MODULES / BOT_PACKAGES in mobile/plugins/withBotRuntime.js: {sorted(missing)}"


def test_bundle_list_names_real_files():
    modules, packages = _bundled()
    assert "local_runtime" in modules
    for name in modules:
        assert (ROOT / f"{name}.py").is_file(), name
    for name in packages:
        assert (ROOT / name / "__init__.py").is_file(), name
