import os
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from smartstorage.models import GIB, MIB, DiskInfo, FileInfo, Preferences  # noqa: E402

OLD = time.time() - 30 * 86400


def make_tree(base: Path, spec: dict[str, bytes]) -> Path:
    """Create files {relative_path: content} with old mtimes."""
    for rel, content in spec.items():
        p = base / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
        os.utime(p, (OLD, OLD))
    return base


def snapshot(base: Path) -> dict:
    """(size, mtime_ns, content hash) for every file — detects any modification."""
    import hashlib
    out = {}
    for p in sorted(base.rglob("*")):
        if p.is_file() and not p.is_symlink():
            st = p.stat()
            out[str(p)] = (st.st_size, st.st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest())
    return out


def fi(fid: str, size_mib: float, gain_mib: float = 0, importance: int = 5,
       protected: bool = False, eligible: bool = True, vol: str = "sim:C") -> FileInfo:
    return FileInfo(fid, f"C:\\T\\{fid}.dat", int(size_mib * MIB), ".dat", 1.7e9, vol,
                    importance=importance, protected=protected,
                    eligible=eligible and not protected,
                    estimated_compress_gain_bytes=int(gain_mib * MIB),
                    skip_reason="PROTECTED" if protected else None)


def disks(*dest_free_gib: float):
    out = [DiskInfo("sim:C", "C:\\", 100 * GIB, 5 * GIB, True, False, simulated=True)]
    for k, free in enumerate(dest_free_gib):
        L = "DEFG"[k]
        out.append(DiskInfo(f"sim:{L}", f"{L}:\\", 500 * GIB, int(free * GIB), True, True,
                            simulated=True))
    return tuple(out)


def prefs(goal_mib: float, compress=True, move=True, dests=("sim:D",), priority="balanced",
          allow_delete=False):
    return Preferences("sim:C", int(goal_mib * MIB), compress, move, tuple(dests), (), priority,
                       allow_delete=allow_delete)


@pytest.fixture
def tree(tmp_path):
    return lambda spec: make_tree(tmp_path / "root", spec)
