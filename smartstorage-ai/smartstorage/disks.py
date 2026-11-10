"""Volume discovery, identity and destination capacity (SPEC_v2 §7).

Identity = os.stat(path).st_dev (volume serial number on Windows). Files and
mountpoints use the same function, so a file's volume can be compared with a
destination's volume without guessing. Mountpoints sharing an identity are
merged into one capacity bucket. On any doubt, the volume is NOT a MOVE
destination.
"""
from __future__ import annotations

import os
from typing import Iterable

from .models import DiskInfo, MIB

MIN_RESERVE_BYTES = 256 * MIB
_SKIP_FSTYPES = {"squashfs", "tmpfs", "devtmpfs", "proc", "sysfs", "overlay",
                 "cdfs", "udf", "iso9660"}


def volume_id_for_path(path: str) -> str | None:
    """Canonical volume id of the volume containing ``path``; None if unknown."""
    try:
        st = os.stat(path, follow_symlinks=False)
    except OSError:
        return None
    return f"dev:{st.st_dev:x}"


def reserve_bytes(free_bytes: int, safety_fraction: float) -> int:
    return max(MIN_RESERVE_BYTES, int(free_bytes * safety_fraction))


def available_capacity(disk: DiskInfo, safety_fraction: float = 0.05) -> int:
    """free - reserve, clamped to >= 0."""
    return max(0, disk.free_bytes - reserve_bytes(disk.free_bytes, safety_fraction))


def _is_removable(opts: str, fstype: str) -> bool:
    o = opts.lower()
    return "removable" in o or "cdrom" in o or fstype.lower() in {"cdfs", "udf", "iso9660"}


def build_disks(raw: Iterable[dict], allow_removable: bool = False) -> tuple[DiskInfo, ...]:
    """Build de-duplicated DiskInfo objects from raw partition records.

    Each raw record: mountpoint, total, free, writable, removable, volume_id
    (None if unknown). Pure function so it can be unit-tested without psutil.
    """
    by_id: dict[str, dict] = {}
    unknown: list[DiskInfo] = []
    for r in raw:
        vid = r.get("volume_id")
        if vid is None:
            unknown.append(DiskInfo(
                volume_id=f"unknown:{r['mountpoint']}", mountpoint=r["mountpoint"],
                total_bytes=int(r["total"]), free_bytes=int(r["free"]),
                writable=bool(r["writable"]), eligible_destination=False,
                removable=bool(r.get("removable")), identity_confident=False,
            ))
            continue
        if vid in by_id:
            by_id[vid]["aliases"].append(r["mountpoint"])
        else:
            by_id[vid] = dict(r, aliases=[])
    out: list[DiskInfo] = []
    for vid, r in by_id.items():
        removable = bool(r.get("removable"))
        eligible = bool(r["writable"]) and (allow_removable or not removable)
        out.append(DiskInfo(
            volume_id=vid, mountpoint=r["mountpoint"], total_bytes=int(r["total"]),
            free_bytes=int(r["free"]), writable=bool(r["writable"]),
            eligible_destination=eligible, removable=removable,
            identity_confident=True, aliases=tuple(r["aliases"]),
            label=r.get("label", ""),
        ))
    out.sort(key=lambda d: d.mountpoint.lower())
    return tuple(out) + tuple(unknown)


def discover_disks(allow_removable: bool = False) -> tuple[tuple[DiskInfo, ...], tuple[str, ...]]:
    """Enumerate local volumes with psutil. Returns (disks, warnings)."""
    import psutil  # local import keeps core importable without psutil

    warnings: list[str] = []
    raw = []
    try:
        parts = psutil.disk_partitions(all=False)
    except Exception as exc:  # pragma: no cover - platform specific
        return (), (f"Disk listesi alınamadı: {exc}",)
    for p in parts:
        if p.fstype.lower() in _SKIP_FSTYPES and os.name != "nt":
            continue
        try:
            usage = psutil.disk_usage(p.mountpoint)
        except (OSError, PermissionError):
            warnings.append(f"{p.mountpoint}: kullanım bilgisi okunamadı (sürücü hazır değil olabilir).")
            continue
        vid = volume_id_for_path(p.mountpoint)
        if vid is None:
            warnings.append(f"{p.mountpoint}: hacim kimliği belirlenemedi; bu hacme taşıma devre dışı.")
        raw.append({
            "mountpoint": p.mountpoint, "total": usage.total, "free": usage.free,
            "writable": "ro" not in p.opts.split(",") and os.access(p.mountpoint, os.W_OK),
            "removable": _is_removable(p.opts, p.fstype), "volume_id": vid,
        })
    disks = build_disks(raw, allow_removable=allow_removable)
    for d in disks:
        if d.aliases:
            warnings.append(f"{d.mountpoint} ve {', '.join(d.aliases)} aynı hacim; tek kapasite olarak sayılıyor.")
    return disks, tuple(warnings)


def find_disk(disks: Iterable[DiskInfo], volume_id: str) -> DiskInfo | None:
    for d in disks:
        if d.volume_id == volume_id:
            return d
    return None


def disk_for_path(disks: Iterable[DiskInfo], path: str) -> DiskInfo | None:
    vid = volume_id_for_path(path)
    return find_disk(disks, vid) if vid else None
