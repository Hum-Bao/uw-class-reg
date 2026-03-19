"""Load the local selenium.py module under a non-conflicting alias."""

import importlib
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType
from typing import Any, cast
import sys

LOADER_MODULE_NAME = "uw_class_reg_selenium"
SELENIUM_MODULE_PATH = Path(__file__).with_name("selenium.py")


def _import_external_selenium_package() -> None:
    """Import the third-party selenium package without the local file shadowing it."""
    project_root = SELENIUM_MODULE_PATH.parent.resolve()
    existing_module = sys.modules.get("selenium")
    existing_path = getattr(existing_module, "__file__", "") if existing_module else ""
    if (
        existing_path
        and Path(existing_path).resolve() == SELENIUM_MODULE_PATH.resolve()
    ):
        sys.modules.pop("selenium", None)

    original_sys_path = list(sys.path)
    try:
        sys.path = [
            path for path in sys.path if Path(path or ".").resolve() != project_root
        ]
        importlib.import_module("selenium")
    finally:
        sys.path = original_sys_path


def _load_local_selenium_module() -> ModuleType:
    """Load selenium.py under an alias so it doesn't shadow the selenium package."""
    existing_module = sys.modules.get(LOADER_MODULE_NAME)
    if isinstance(existing_module, ModuleType):
        return existing_module

    _import_external_selenium_package()

    spec = spec_from_file_location(LOADER_MODULE_NAME, SELENIUM_MODULE_PATH)
    if spec is None or spec.loader is None:
        message = f"Could not load module from {SELENIUM_MODULE_PATH}"
        raise ImportError(message)

    module = module_from_spec(spec)
    sys.modules[LOADER_MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


def get_fresh_session_token() -> str:
    """Proxy to the local selenium.py get_fresh_session_token function."""
    module = _load_local_selenium_module()
    function = cast("Any", getattr(module, "get_fresh_session_token"))
    return cast("str", function())


def get_fresh_session_token_hybrid(*, verbose: bool = True) -> str:
    """Proxy to the local selenium.py hybrid auth function."""
    module = _load_local_selenium_module()
    function = cast("Any", getattr(module, "get_fresh_session_token_hybrid"))
    return cast("str", function(verbose=verbose))
