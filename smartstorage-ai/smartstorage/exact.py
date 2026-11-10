"""Exhaustive oracle for tiny instances (tests / benchmark only)."""
from __future__ import annotations

import itertools
import math
import time

from .models import OptimizationResult, Problem
from .scoring import PlanState, build_result

MAX_STATES = 2_000_000


def state_count(problem: Problem) -> int:
    return math.prod(len(c) for c in problem.candidates)


def exhaustive(problem: Problem, max_states: int = MAX_STATES) -> OptimizationResult:
    n_states = state_count(problem)
    if n_states > max_states:
        raise ValueError(f"too many states for brute force: {n_states}")
    t0 = time.perf_counter()
    best, best_cost = None, math.inf
    goal = problem.preferences.goal_bytes
    caps = problem.capacities
    for plan in itertools.product(*(range(len(c)) for c in problem.candidates)):
        st = PlanState(problem, plan)
        if st.gain >= goal and all(u <= caps[d] for d, u in st.usage.items()):
            if st.cost < best_cost - 1e-12:
                best, best_cost = plan, st.cost
    ms = (time.perf_counter() - t0) * 1000
    return build_result(problem, "exhaustive", best, ms, n_states, None,
                        diagnostics={"states": n_states})
