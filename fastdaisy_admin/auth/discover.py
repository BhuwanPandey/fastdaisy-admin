"""
These discovers are from fastapi-cli project.
"""

import importlib
import sys
from logging import getLogger
from pathlib import Path

from fastdaisy_admin import Admin
from fastdaisy_admin.exceptions import FastDaisyAdminException

logger = getLogger(__name__)


def get_default_path() -> Path:
    potential_paths = (
        "app.py",
        "main.py",
        "api.py",
        "app/app.py",
        "app/main.py",
        "app/api.py",
    )

    for full_path in potential_paths:
        path = Path(full_path)
        if path.is_file():
            return path

    raise FastDaisyAdminException("Could not find a default file to run, please provide an explicit path")


def get_module_data_from_path(path: Path) -> tuple[str, Path]:
    use_path = path.resolve()
    module_path = use_path
    if use_path.is_file() and use_path.stem == "__init__":
        module_path = use_path.parent
    module_paths = [module_path]
    extra_sys_path = module_path.parent
    for parent in module_path.parents:
        init_path = parent / "__init__.py"
        if init_path.is_file():
            module_paths.insert(0, parent)
            extra_sys_path = parent.parent
        else:
            break

    module_str = ".".join(p.stem for p in module_paths)
    return (module_str, extra_sys_path)


def get_admin(mod_data: str) -> Admin:
    try:
        mod = importlib.import_module(mod_data)
    except (ImportError, ValueError) as e:
        logger.error(f"Import error: {e}")
        logger.warning("Ensure all the package directories have an [blue]__init__.py[/blue] file")
        raise
    object_names = dir(mod)
    object_names_set = set(object_names)
    for preferred_name in ["api", "admin"]:
        if preferred_name in object_names_set:
            obj = getattr(mod, preferred_name)
            if isinstance(obj, Admin):
                return obj
    for name in object_names:
        obj = getattr(mod, name)
        if isinstance(obj, Admin):
            return obj
    raise FastDaisyAdminException("Could not find Admin in module")


def get_admin_data(path: Path | None) -> Admin:
    if not path:
        path = get_default_path()

    logger.debug(f"Using path [blue]{path}[/blue]")
    logger.debug(f"Resolved absolute path {path.resolve()}")

    if not path.exists():
        raise FastDaisyAdminException(f"Path does not exist {path}")

    mod_data, extra_sys_path = get_module_data_from_path(path)
    sys.path.insert(0, str(extra_sys_path))
    admin_obj = get_admin(mod_data=mod_data)
    return admin_obj
