import pytest

from smartstorage.actions import build_problem
from smartstorage.models import ActionKind, PlanStatus
from smartstorage.scoring import (PlanState, action_cost, all_keep, evaluate, evaluate_mapping,
                                  is_allowed, plan_to_mapping, PRESETS, proof_of_infeasibility,
                                  upper_bounds)

from conftest import disks, fi, prefs


def idx(p, i, kind, dest=None):
    for j, c in enumerate(p.candidates[i]):
        if c.kind == kind and (dest is None or c.destination_volume_id == dest):
            return j
    raise KeyError


def test_exactly_one_action_per_file_required():
    p = build_problem([fi("a", 100, 60), fi("b", 100, 60)], disks(10), prefs(50))
    assert evaluate(p, (0,)).status == PlanStatus.INVALID.value
    assert evaluate(p, (0, 0, 0)).status == PlanStatus.INVALID.value
    assert evaluate(p, (0, 99)).status == PlanStatus.INVALID.value
    m = plan_to_mapping(p, (0, 0))
    m.pop("a")
    assert evaluate_mapping(p, m).status == PlanStatus.INVALID.value


def test_action_must_belong_to_its_file():
    p = build_problem([fi("a", 100, 60), fi("b", 100, 60)], disks(10), prefs(50))
    m = plan_to_mapping(p, (0, 0))
    m["a"] = p.candidates[1][1].id  # b's action assigned to a
    assert evaluate_mapping(p, m).status == PlanStatus.INVALID.value
    assert not is_allowed(p, p.files[0], p.candidates[1][1])


def test_source_gain_correct():
    p = build_problem([fi("a", 100, 60), fi("b", 200)], disks(10), prefs(250))
    plan = (idx(p, 0, ActionKind.COMPRESS), idx(p, 1, ActionKind.MOVE))
    ev = evaluate(p, plan)
    assert ev.gain_bytes == p.candidates[0][plan[0]].source_gain_bytes + 200 * 1024 ** 2
    assert ev.feasible


def test_aggregate_capacity_constraint():
    # D has 1 GiB free -> 1 GiB - 256 MiB reserve = 768 MiB available; two 500 MiB moves don't fit
    p = build_problem([fi("a", 500), fi("b", 500)], disks(1), prefs(900, compress=False))
    plan = (idx(p, 0, ActionKind.MOVE), idx(p, 1, ActionKind.MOVE))
    ev = evaluate(p, plan)
    assert ev.capacity_overage_bytes > 0 and not ev.feasible
    st = PlanState(p, all_keep(p))
    st.apply([(0, plan[0])])
    _, _, ok = st.try_changes([(1, plan[1])])
    assert not ok


def test_high_importance_costs_more():
    w = PRESETS["balanced"]
    for kind in (ActionKind.COMPRESS, ActionKind.MOVE):
        assert action_cost(9, kind, 10, 0.2, 0.5, w) > action_cost(1, kind, 10, 0.2, 0.5, w)


def test_keep_cost_zero_and_goal_zero_all_keep_optimal():
    p = build_problem([fi("a", 100, 60)], disks(10), prefs(0))
    ev = evaluate(p, all_keep(p))
    assert ev.feasible and ev.total_cost == 0


def test_hard_constraint_not_overridable_by_cost():
    p = build_problem([fi("a", 100, 60, protected=True), fi("b", 10)], disks(10), prefs(50))
    # forge a "free" compress action for the protected file
    from dataclasses import replace
    forged = replace(p.candidates[1][1], id="a:COMPRESS:-", file_id="a", total_cost=-100.0,
                     kind=ActionKind.COMPRESS, destination_volume_id=None,
                     source_gain_bytes=60 * 1024 ** 2, destination_use_bytes=0)
    p2 = replace(p, candidates=((p.candidates[0][0], forged),) + p.candidates[1:])
    assert evaluate(p2, (1, 0)).status == PlanStatus.INVALID.value


def test_upper_bounds_and_capacity_proof():
    p = build_problem([fi("a", 800), fi("b", 800)], disks(1.25), prefs(1200, compress=False))
    ub, ub_cap = upper_bounds(p)
    assert ub == 1600 * 1024 ** 2 and ub_cap < ub
    assert "DESTINATION_CAPACITY" in proof_of_infeasibility(p)


def test_invalid_config_negative_goal():
    p = build_problem([fi("a", 10)], disks(), prefs(-1))
    assert "INVALID_CONFIG" in p.reason_codes
