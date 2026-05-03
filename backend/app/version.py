"""InSync application version from package metadata (see ``pyproject.toml``)."""

import importlib.metadata
from functools import lru_cache

_PACKAGE_NAME = "insync"


@lru_cache
def get_app_version() -> str:
    try:
        return importlib.metadata.version(_PACKAGE_NAME)
    except importlib.metadata.PackageNotFoundError:
        return "0.0.0-dev"
