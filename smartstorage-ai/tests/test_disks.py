from smartstorage.actions import build_problem
from smartstorage.disks import available_capacity, build_disks, discover_disks, MIN_RESERVE_BYTES
from smartstorage.models import GIB, MIB, ActionKind, DiskInfo, ReasonCode

from conftest import fi, prefs


def raw(mp, vid, free_gib=10, writable=True, removable=False):
    return {"mountpoint": mp, "total": 100 * GIB, "free": int(free_gib * GIB),
            "writable": writable, "removable": removable, "volume_id": vid}


def test_one_accessible_volume_means_no_move():
    ds = build_disks([raw("C:\\", "sim:C")])
    p = build_problem([fi("a", 100, 0)], ds, prefs(50, compress=False, dests=("sim:C",)))
    assert all(len(c) == 1 for c in p.candidates)
    assert ReasonCode.NO_DESTINATION.value in p.reason_codes


def test_duplicate_mountpoint_identity_is_merged():
    ds = build_disks([raw("D:\\", "dev:1"), raw("C:\\mnt\\d", "dev:1"), raw("C:\\", "sim:C")])
    ids = [d.volume_id for d in ds]
    assert ids.count("dev:1") == 1
    d = next(d for d in ds if d.volume_id == "dev:1")
    assert d.aliases == ("C:\\mnt\\d",)


def test_unknown_identity_is_never_destination():
    ds = build_disks([raw("X:\\", None)])
    assert not ds[0].identity_confident and not ds[0].eligible_destination
    p = build_problem([fi("a", 10)], ds, prefs(5, compress=False, dests=(ds[0].volume_id,)))
    assert all(c.kind != ActionKind.MOVE for cs in p.candidates for c in cs)


def test_removable_not_destination_by_default():
    ds = build_disks([raw("E:\\", "dev:e", removable=True)])
    assert not ds[0].eligible_destination
    ds2 = build_disks([raw("E:\\", "dev:e", removable=True)], allow_removable=True)
    assert ds2[0].eligible_destination


def test_full_target_reserve_clamped_to_zero():
    d = DiskInfo("sim:D", "D:\\", 100 * GIB, 100 * MIB, True, True)
    assert available_capacity(d) == 0
    d2 = DiskInfo("sim:D", "D:\\", 100 * GIB, 20 * GIB, True, True)
    assert available_capacity(d2, 0.05) == 20 * GIB - max(MIN_RESERVE_BYTES, int(20 * GIB * 0.05))
    ds = (DiskInfo("sim:C", "C:\\", GIB, GIB, True, False), d)
    p = build_problem([fi("a", 50)], ds, prefs(10, compress=False))
    assert all(len(c) == 1 for c in p.candidates)


def test_discover_disks_runs_on_this_machine():
    ds, warnings = discover_disks()
    assert isinstance(ds, tuple)
    for d in ds:
        assert d.total_bytes >= 0 and d.free_bytes >= 0
