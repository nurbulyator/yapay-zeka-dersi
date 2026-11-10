"""Path normalisation and containment checks (commonpath based, never prefix)."""
from __future__ import annotations

import os
from pathlib import Path


def norm(path: str | os.PathLike) -> str:
    """Absolute, normalised, case-folded (on Windows) path string."""
    return os.path.normcase(os.path.normpath(os.path.abspath(os.fspath(path))))


def is_within(child: str | os.PathLike, parent: str | os.PathLike) -> bool:
    """True if child == parent or child is inside parent.

    Uses os.path.commonpath so that C:\\Data does NOT contain C:\\Database.
    """
    c, p = norm(child), norm(parent)
    try:
        return os.path.commonpath([c, p]) == p
    except ValueError:  # different drives on Windows
        return False


def depth(path: str | os.PathLike) -> int:
    return len(Path(norm(path)).parts)


def is_volume_root(path: str | os.PathLike) -> bool:
    p = Path(norm(path))
    return p.parent == p
