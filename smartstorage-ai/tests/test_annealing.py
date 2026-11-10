import math

from smartstorage.actions import build_problem
from smartstorage.annealing import SAConfig, hill_climbing, simulated_annealing
from smartstorage.exact import exhaustive
from smartstorage.greedy import greedy
from smartstorage.models import ResultStatus
from smartstorage.sample_data import ScenarioSpec, greedy_trap_problem, make_problem, tiny_problem
from smartstorage.scoring import evaluate_mapping

from conftest import disks, fi, prefs


def test_sa_deterministic_with_seed():
    p = greedy_trap_problem(6)
    a, b = simulated_annealing(p, 7), simulated_annealing(p, 7)
    assert a.plan == b.plan and a.diagnostics["accepted"] == b.diagnostics["accepted"]


def test_sa_never_returns_invalid_or_infeasible_as_success():
    for s in range(12):
        for p in (tiny_problem(s), greedy_trap_problem(s)):
            for algo in (simulated_annealing, hill_climbing):
                r = algo(p, s, SAConfig(iterations=800))
                if r.feasible:
                    ev = evaluate_mapping(p, r.plan)
                    assert ev.feasible and math.isclose(ev.total_cost, r.evaluation.total_cost)
                else:
                    assert r.plan == {}


def test_sa_beats_greedy_on_known_trap_case():
    p = greedy_trap_problem(6)
    g, sa, ex = greedy(p), simulated_annealing(p, 0), exhaustive(p)
    assert sa.evaluation.total_cost < g.evaluation.total_cost
    assert math.isclose(sa.evaluation.total_cost, ex.evaluation.total_cost)


def test_sa_no_worse_than_greedy_start():
    for s in range(10):
        p = greedy_trap_problem(s)
        g, sa = greedy(p), simulated_annealing(p, s)
        if g.feasible:
            assert sa.evaluation.total_cost <= g.evaluation.total_cost + 1e-9


def test_exhaustive_optimality_gap_small_on_tiny():
    gaps = []
    for s in range(10):
        p = tiny_problem(s)
        ex = exhaustive(p)
        sa = simulated_annealing(p, 1)
        if ex.feasible:
            assert sa.feasible
            assert sa.evaluation.total_cost >= ex.evaluation.total_cost - 1e-9
            gaps.append(sa.evaluation.total_cost / ex.evaluation.total_cost - 1)
    assert gaps and sum(gaps) / len(gaps) < 0.05


def test_hill_climbing_never_accepts_worse():
    p = greedy_trap_problem(4)
    r = hill_climbing(p, 3)
    assert r.diagnostics["uphill_accepted"] == 0
    hist = [h["current_energy"] for h in r.diagnostics["history"]]
    assert all(b <= a + 1e-9 for a, b in zip(hist, hist[1:]))
    sa = simulated_annealing(p, 3)
    assert sa.diagnostics["uphill_accepted"] > 0  # temperature really matters


def test_sa_finds_plan_when_greedy_fails():
    found = False
    for s in range(30):
        p = tiny_problem(s)
        g = greedy(p)
        if not g.feasible and exhaustive(p).feasible:
            assert g.status == ResultStatus.NO_FEASIBLE_FOUND.value  # not "proven"
            found = found or simulated_annealing(p, 0).feasible
    assert found


def test_proven_infeasible_vs_not_found():
    p = build_problem([fi("a", 100, 60)], disks(), prefs(10_000, move=False))
    r = simulated_annealing(p, 1, SAConfig(iterations=200))
    assert r.status == ResultStatus.PROVEN_INFEASIBLE.value


def test_temperature_schedule_and_runtime_large():
    p = make_problem(ScenarioSpec("x", 1000, 2, 3, seed=5))
    r = simulated_annealing(p, 1)
    temps = [h["temperature"] for h in r.diagnostics["history"]]
    assert temps[0] > temps[-1] >= SAConfig().min_t
    assert r.feasible and r.duration_ms < 5000
