from smartstorage.actions import build_problem
from smartstorage.models import ActionKind

from conftest import disks, fi, prefs


def kinds(p, i=None):
    rng = range(p.n_files) if i is None else [i]
    return [c.kind for k in rng for c in p.candidates[k]]


def test_every_file_has_keep_first():
    p = build_problem([fi("a", 100, 60), fi("b", 10), fi("c", 5, protected=True)], disks(10), prefs(50))
    for cands in p.candidates:
        assert cands[0].kind == ActionKind.KEEP and cands[0].total_cost == 0


def test_protected_only_keep():
    p = build_problem([fi("a", 100, 60, protected=True)], disks(10), prefs(50))
    assert kinds(p) == [ActionKind.KEEP]


def test_compress_disabled_no_compress():
    p = build_problem([fi("a", 100, 60)], disks(10), prefs(50, compress=False))
    assert ActionKind.COMPRESS not in kinds(p)


def test_move_disabled_no_move():
    p = build_problem([fi("a", 100, 60)], disks(10), prefs(50, move=False))
    assert ActionKind.MOVE not in kinds(p)


def test_delete_is_opt_in_and_cannot_change_protected_files():
    files = [fi("a", 100), fi("b", 100, protected=True)]
    default_problem = build_problem(files, disks(), prefs(50, move=False))
    delete_problem = build_problem(files, disks(), prefs(50, compress=False, move=False,
                                                        allow_delete=True))

    assert ActionKind.DELETE not in kinds(default_problem, 0)
    assert ActionKind.DELETE in kinds(delete_problem, 0)
    assert ActionKind.DELETE not in kinds(delete_problem, 1)


def test_move_never_within_same_volume():
    p = build_problem([fi("a", 100)], disks(10), prefs(50, dests=("sim:C",)))
    assert ActionKind.MOVE not in kinds(p)


def test_zero_or_tiny_compress_gain_suppressed():
    p = build_problem([fi("a", 100, 0), fi("b", 100, 0.5), fi("c", 100, 2.9)], disks(), prefs(1, move=False))
    assert ActionKind.COMPRESS not in kinds(p)  # 3 % of 100 MiB = 3 MiB threshold


def test_distinct_targets_generate_distinct_actions():
    p = build_problem([fi("a", 100)], disks(10, 20), prefs(50, compress=False, dests=("sim:D", "sim:E")))
    moves = [c for c in p.candidates[0] if c.kind == ActionKind.MOVE]
    assert {c.destination_volume_id for c in moves} == {"sim:D", "sim:E"}
    assert len({c.id for c in moves}) == 2


def test_unpermitted_destination_ignored():
    p = build_problem([fi("a", 100)], disks(10, 20), prefs(50, compress=False, dests=("sim:D",)))
    assert {c.destination_volume_id for c in p.candidates[0] if c.kind == ActionKind.MOVE} == {"sim:D"}


def test_file_larger_than_nominal_capacity_gets_no_move():
    p = build_problem([fi("a", 2048)], disks(1), prefs(50, compress=False))
    assert ActionKind.MOVE not in kinds(p)


def test_candidates_sorted_and_deterministic():
    files = [fi("b", 100, 60), fi("a", 100, 60)]
    p1 = build_problem(files, disks(10, 20), prefs(50, dests=("sim:E", "sim:D")))
    p2 = build_problem(list(reversed(files)), disks(10, 20), prefs(50, dests=("sim:D", "sim:E")))
    assert [f.file_id for f in p1.files] == ["a", "b"]
    assert [[c.id for c in cs] for cs in p1.candidates] == [[c.id for c in cs] for cs in p2.candidates]
