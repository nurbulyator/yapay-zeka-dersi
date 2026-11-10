from smartstorage.actions import build_problem
from smartstorage.exact import exhaustive
from smartstorage.greedy import greedy, greedy_plan
from smartstorage.models import ResultStatus
from smartstorage.sample_data import greedy_trap_problem, tiny_problem
from smartstorage.scoring import evaluate

from conftest import disks, fi, prefs


def test_greedy_deterministic():
    p = greedy_trap_problem(3)
    a, b = greedy(p), greedy(p)
    assert a.plan == b.plan and a.status == b.status


def test_feasible_only_if_target_reached():
    p = build_problem([fi("a", 100, 60)], disks(), prefs(500, move=False))
    r = greedy(p)
    assert r.status == ResultStatus.PROVEN_INFEASIBLE.value and not r.plan
    r2 = greedy(build_problem([fi("a", 100, 60)], disks(), prefs(30, move=False)))
    assert r2.feasible and r2.evaluation.gain_bytes >= 30 * 1024 ** 2


def test_never_two_actions_or_capacity_overflow():
    for s in range(15):
        p = tiny_problem(s)
        plan, _ = greedy_plan(p)
        ev = evaluate(p, plan)
        assert ev.status != "INVALID" and ev.capacity_overage_bytes == 0


def test_prune_never_breaks_feasibility_and_helps():
    improved = 0
    for s in range(20):
        p = tiny_problem(s)
        raw, _ = greedy_plan(p, prune=False)
        pruned, _ = greedy_plan(p, prune=True)
        e_raw, e_pr = evaluate(p, raw), evaluate(p, pruned)
        if e_raw.feasible:
            assert e_pr.feasible and e_pr.total_cost <= e_raw.total_cost + 1e-9
            improved += e_pr.total_cost < e_raw.total_cost - 1e-9
    assert improved >= 1


def test_greedy_not_always_optimal_brute_force():
    gaps = 0
    for s in range(20):
        p = greedy_trap_problem(s)
        g, ex = greedy(p), exhaustive(p)
        if g.feasible:
            assert g.evaluation.total_cost >= ex.evaluation.total_cost - 1e-9
            gaps += g.evaluation.total_cost > ex.evaluation.total_cost + 1e-9
    assert gaps > 0  # documented non-optimal examples exist


def test_goal_zero_and_empty():
    r = greedy(build_problem([fi("a", 10, 5)], disks(10), prefs(0)))
    assert r.feasible and r.evaluation.total_cost == 0
    r = greedy(build_problem([], disks(10), prefs(10)))
    assert not r.feasible and "EMPTY_SCOPE" in r.reason_codes
    r = greedy(build_problem([fi("a", 100, 60, protected=True)], disks(10), prefs(10)))
    assert not r.feasible and "PROTECTED_ONLY" in r.reason_codes
    r = greedy(build_problem([fi("a", 100, 60)], disks(), prefs(10, compress=False, move=False)))
    assert r.status == ResultStatus.PROVEN_INFEASIBLE.value and "NO_ALLOWED_ACTIONS" in r.reason_codes
