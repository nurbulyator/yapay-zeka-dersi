"""Deterministic greedy baseline (SPEC_v2 §12) with prune pass [v2/C16].

Ratio greedy is a baseline, not an optimality proof.
"""
from __future__ import annotations

import time

from .models import ActionKind, OptimizationResult, Problem
from .scoring import EPSILON, build_result


def greedy_plan(problem: Problem, prune: bool = True) -> tuple[tuple[int, ...], dict]:
    """Return (plan, diagnostics). The plan is always a valid assignment; it
    may miss the goal (then the caller reports it as not feasible)."""
    n = problem.n_files
    goal = problem.preferences.goal_bytes
    plan = [0] * n
    diag = {"selected": 0, "pruned": 0, "considered": 0}
    if goal <= 0:
        return tuple(plan), diag

    items = []
    for i, (f, cands) in enumerate(zip(problem.files, problem.candidates)):
        for j, c in enumerate(cands):
            if j == 0 or c.source_gain_bytes <= 0:
                continue
            items.append((-(c.source_gain_bytes / (c.total_cost + EPSILON)),
                          -c.source_gain_bytes, f.file_id, c.id, i, j))
    items.sort()
    diag["considered"] = len(items)

    usage = {d: 0 for d in problem.capacities}
    gain = 0
    for *_, i, j in items:
        if gain >= goal:
            break
        if plan[i] != 0:
            continue
        c = problem.candidates[i][j]
        if c.kind == ActionKind.MOVE:
            d = c.destination_volume_id
            if usage[d] + c.destination_use_bytes > problem.capacities[d]:
                continue
            usage[d] += c.destination_use_bytes
        plan[i] = j
        gain += c.source_gain_bytes
        diag["selected"] += 1

    if prune and gain >= goal:
        chosen = [i for i in range(n) if plan[i] != 0]
        chosen.sort(key=lambda i: (-problem.candidates[i][plan[i]].total_cost,
                                   problem.files[i].file_id))
        for i in chosen:
            g = problem.candidates[i][plan[i]].source_gain_bytes
            if gain - g >= goal:
                plan[i] = 0
                gain -= g
                diag["pruned"] += 1
    return tuple(plan), diag


def greedy(problem: Problem, prune: bool = True) -> OptimizationResult:
    t0 = time.perf_counter()
    plan, diag = greedy_plan(problem, prune=prune)
    ms = (time.perf_counter() - t0) * 1000
    return build_result(problem, "greedy", plan, ms, diag["considered"], None,
                        diagnostics=diag)
