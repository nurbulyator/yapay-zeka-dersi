"""Seeded Simulated Annealing and Hill Climbing ablation (SPEC_v2 §13, [v2/C14]).

State: one candidate index per file. Neighbours: single-file change, swap
(one changed file back to KEEP + one KEEP file activated), random two-file
change. Capacity-violating neighbours are rejected outright; goal shortfall
is allowed during search with a calibrated penalty. Only a re-evaluated
feasible ``best_feasible`` plan is ever returned as success.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from random import Random

from .greedy import greedy_plan
from .models import OptimizationResult, Problem
from .scoring import PlanState, build_result, energy, penalty_alpha

TINY = 1e-12


@dataclass(frozen=True)
class SAConfig:
    iterations: int = 3000
    t0: float = 5.0
    cooling: float = 0.995
    min_t: float = 1e-4
    p_swap: float = 0.5
    p_single: float = 0.4   # remaining probability: random two-file change
    history_points: int = 200


class _IndexedSet:
    """O(1) add / remove / uniform random choice."""

    def __init__(self, items=()):
        self.items: list[int] = []
        self.pos: dict[int, int] = {}
        for x in items:
            self.add(x)

    def add(self, x: int) -> None:
        if x not in self.pos:
            self.pos[x] = len(self.items)
            self.items.append(x)

    def remove(self, x: int) -> None:
        k = self.pos.pop(x, None)
        if k is None:
            return
        last = self.items.pop()
        if k < len(self.items):
            self.items[k] = last
            self.pos[last] = k

    def choice(self, rng: Random) -> int:
        return self.items[rng.randrange(len(self.items))]

    def __len__(self) -> int:
        return len(self.items)


def _other_index(rng: Random, n_cands: int, current: int) -> int:
    k = rng.randrange(n_cands - 1)
    return k if k < current else k + 1


def _propose(rng: Random, problem: Problem, state: PlanState, mutable: list[int],
             active: _IndexedSet, inactive: _IndexedSet, cfg: SAConfig):
    cands = problem.candidates
    r = rng.random()
    if r < cfg.p_swap and len(active) and len(inactive):
        i = active.choice(rng)
        k = inactive.choice(rng)
        return [(i, 0), (k, 1 + rng.randrange(len(cands[k]) - 1))], "swap"
    if r < cfg.p_swap + cfg.p_single or len(mutable) < 2:
        # Goal-aware repair: when short of the goal, prefer activating a KEEP
        # file; when the goal is met, prefer revising an already-changed file
        # (switch action or revert to KEEP) instead of adding pure cost.
        short = state.gain < problem.preferences.goal_bytes
        if short and len(inactive) and rng.random() < 0.5:
            k = inactive.choice(rng)
            return [(k, 1 + rng.randrange(len(cands[k]) - 1))], "single"
        if not short and len(active) and rng.random() < 0.5:
            i = active.choice(rng)
            return [(i, _other_index(rng, len(cands[i]), state.choice[i]))], "single"
        i = mutable[rng.randrange(len(mutable))]
        return [(i, _other_index(rng, len(cands[i]), state.choice[i]))], "single"
    a, b = rng.sample(mutable, 2)
    return [(a, _other_index(rng, len(cands[a]), state.choice[a])),
            (b, _other_index(rng, len(cands[b]), state.choice[b]))], "double"


def _local_search(problem: Problem, seed: int, cfg: SAConfig, accept_worse: bool,
                  name: str) -> OptimizationResult:
    t_start = time.perf_counter()
    rng = Random(seed)
    goal = problem.preferences.goal_bytes
    start, _ = greedy_plan(problem)            # always a valid assignment
    state = PlanState(problem, start)
    alpha = penalty_alpha(problem)
    mutable = [i for i, c in enumerate(problem.candidates) if len(c) > 1]
    diag = {"start": "greedy", "start_feasible": state.feasible,
            "start_cost": round(state.cost, 6), "accepted": 0, "uphill_accepted": 0,
            "rejected_capacity": 0, "proposals": {"single": 0, "swap": 0, "double": 0},
            "alpha": alpha, "history": [], "config": cfg.__dict__.copy(),
            "temperature_used": accept_worse}

    best = tuple(state.choice) if state.feasible else None
    best_cost = state.cost if best is not None else math.inf
    if goal <= 0 or not mutable:
        ms = (time.perf_counter() - t_start) * 1000
        return build_result(problem, name, best if best is not None else start, ms, 0, seed,
                            diagnostics=diag)

    active = _IndexedSet(i for i in mutable if state.choice[i] != 0)
    inactive = _IndexedSet(i for i in mutable if state.choice[i] == 0)
    cur_e = energy(problem, state.gain, state.cost, alpha)
    t = cfg.t0 if accept_worse else 0.0
    every = max(1, cfg.iterations // max(1, cfg.history_points))

    for it in range(cfg.iterations):
        changes, kind = _propose(rng, problem, state, mutable, active, inactive, cfg)
        diag["proposals"][kind] += 1
        gain, cost, cap_ok = state.try_changes(changes)
        if not cap_ok:
            diag["rejected_capacity"] += 1
        else:
            delta = energy(problem, gain, cost, alpha) - cur_e
            accept = delta <= 0
            if not accept and accept_worse:
                accept = rng.random() < math.exp(-delta / max(t, TINY))
                if accept:
                    diag["uphill_accepted"] += 1
            if accept:
                state.apply(changes)
                for i, new in changes:
                    if new == 0:
                        active.remove(i)
                        inactive.add(i)
                    else:
                        inactive.remove(i)
                        active.add(i)
                cur_e += delta
                diag["accepted"] += 1
                if state.feasible and state.cost < best_cost - 1e-12:
                    best = tuple(state.choice)
                    best_cost = state.cost
        if accept_worse:
            t = max(cfg.min_t, t * cfg.cooling)
        if it % every == 0 or it == cfg.iterations - 1:
            diag["history"].append({
                "iteration": it, "temperature": t, "current_energy": cur_e,
                "best_feasible_cost": None if best is None else best_cost,
            })

    ms = (time.perf_counter() - t_start) * 1000
    return build_result(problem, name, best, ms, cfg.iterations, seed, diagnostics=diag)


def simulated_annealing(problem: Problem, seed: int = 42,
                        config: SAConfig | None = None) -> OptimizationResult:
    return _local_search(problem, seed, config or SAConfig(), True, "simulated_annealing")


def hill_climbing(problem: Problem, seed: int = 42,
                  config: SAConfig | None = None) -> OptimizationResult:
    """Same neighbourhood and energy as SA, temperature 0 (never accepts worse)."""
    return _local_search(problem, seed, config or SAConfig(), False, "hill_climbing")
