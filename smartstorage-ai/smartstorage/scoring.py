"""Transparent cost model, plan evaluation, bounds and energy (SPEC_v2 §10–11).

All coefficients are heuristic scores, NOT measured probabilities.
"""
from __future__ import annotations

from typing import Iterable, Sequence

from .models import (MIB, ActionKind, CandidateAction, Evaluation, FileInfo,
                     OptimizationResult, PlanStatus, Priority, Problem,
                     ReasonCode, ResultStatus)

# ---------------------------------------------------------------- constants
IMPACT = {
    ActionKind.KEEP: 0.0,
    ActionKind.COMPRESS: 0.6,
    ActionKind.MOVE: 0.4,
    ActionKind.DELETE: 1.0,
}
RISK = {
    ActionKind.KEEP: 0.0,
    ActionKind.COMPRESS: 0.3,
    ActionKind.MOVE: 0.2,
    ActionKind.DELETE: 1.0,
}
ACCESS = {
    ActionKind.KEEP: 0.0,
    ActionKind.COMPRESS: 1.0,
    ActionKind.MOVE: 0.5,
    ActionKind.DELETE: 0.0,
}
THROUGHPUT_BPS = {
    ActionKind.COMPRESS: 50 * MIB,
    ActionKind.MOVE: 100 * MIB,
    ActionKind.DELETE: 100 * MIB,
}
PER_FILE_OVERHEAD_S = 0.05

PRESETS = {
    Priority.SAFE.value: {"w_impact": 1.0, "w_time": 0.5, "w_risk": 4.0, "w_access": 1.5},
    Priority.BALANCED.value: {"w_impact": 1.0, "w_time": 1.0, "w_risk": 2.0, "w_access": 1.0},
    Priority.FAST.value: {"w_impact": 1.0, "w_time": 2.0, "w_risk": 1.0, "w_access": 0.5},
}

PENALTY_FACTOR = 2.0
EPSILON = 1e-9


def cost_model(priority: str) -> dict:
    """Weights + constants recorded in every report."""
    if priority not in PRESETS:
        raise ValueError(f"unknown priority: {priority}")
    return {
        "priority": priority,
        "weights": dict(PRESETS[priority]),
        "impact": {k.value: v for k, v in IMPACT.items()},
        "risk_score": {k.value: v for k, v in RISK.items()},
        "access_penalty": {k.value: v for k, v in ACCESS.items()},
        "throughput_mib_s": {k.value: v / MIB for k, v in THROUGHPUT_BPS.items()},
        "per_file_overhead_s": PER_FILE_OVERHEAD_S,
        "time_unit": "minutes",
        "formula": "w_impact*importance*impact + w_time*minutes + w_risk*risk + w_access*access",
    }


def estimate_seconds(kind: ActionKind, size_bytes: int) -> float:
    """Nominal time proxy — not a runtime guarantee."""
    if kind == ActionKind.KEEP:
        return 0.0
    return PER_FILE_OVERHEAD_S + size_bytes / THROUGHPUT_BPS[kind]


def action_cost(importance: int, kind: ActionKind, seconds: float, risk: float,
                access: float, weights: dict) -> float:
    if kind == ActionKind.KEEP:
        return 0.0
    return (weights["w_impact"] * importance * IMPACT[kind]
            + weights["w_time"] * (seconds / 60.0)
            + weights["w_risk"] * risk
            + weights["w_access"] * access)


# ---------------------------------------------------------------- validity
def is_allowed(problem: Problem, f: FileInfo, c: CandidateAction) -> bool:
    """Hard permission check, independent of the UI and of generation."""
    prefs = problem.preferences
    if c.file_id != f.file_id:
        return False
    if c.kind == ActionKind.KEEP:
        return c.source_gain_bytes == 0 and c.destination_use_bytes == 0
    if f.protected or not f.eligible or f.volume_id != prefs.source_volume_id:
        return False
    if c.kind == ActionKind.COMPRESS:
        return (prefs.allow_compress and c.destination_volume_id is None
                and 0 < c.source_gain_bytes < f.size_bytes)
    if c.kind == ActionKind.MOVE:
        d = c.destination_volume_id
        return (prefs.allow_move and d is not None and d != prefs.source_volume_id
                and d in prefs.allowed_destination_volume_ids and d in problem.capacities
                and c.source_gain_bytes == f.size_bytes
                and c.destination_use_bytes == f.size_bytes)
    if c.kind == ActionKind.DELETE:
        return (prefs.allow_delete and c.destination_volume_id is None
                and c.source_gain_bytes == f.size_bytes and c.destination_use_bytes == 0)
    return False


def evaluate(problem: Problem, plan: Sequence[int]) -> Evaluation:
    """Canonical evaluation of a plan (tuple of candidate indices)."""
    reasons: list[str] = []
    valid = len(plan) == problem.n_files
    gain = 0
    cost = 0.0
    usage: dict[str, int] = {}
    if valid:
        for f, cands, idx in zip(problem.files, problem.candidates, plan):
            if not isinstance(idx, int) or not 0 <= idx < len(cands):
                valid = False
                break
            c = cands[idx]
            if not is_allowed(problem, f, c):
                valid = False
                break
            gain += c.source_gain_bytes
            cost += c.total_cost
            if c.kind == ActionKind.MOVE:
                usage[c.destination_volume_id] = usage.get(c.destination_volume_id, 0) + c.destination_use_bytes
    if not valid:
        return Evaluation(False, 0, problem.preferences.goal_bytes, 0, 0.0,
                          PlanStatus.INVALID.value, (ReasonCode.INVALID_ASSIGNMENT.value,))
    overage = sum(max(0, u - problem.capacities.get(d, 0)) for d, u in usage.items())
    goal = problem.preferences.goal_bytes
    shortfall = max(0, goal - gain)
    if overage:
        reasons.append(ReasonCode.DESTINATION_CAPACITY.value)
    if shortfall:
        reasons.append(ReasonCode.GOAL_NOT_MET.value)
    feasible = not overage and not shortfall
    return Evaluation(
        feasible=feasible, gain_bytes=gain, goal_shortfall_bytes=shortfall,
        capacity_overage_bytes=overage, total_cost=cost,
        status=PlanStatus.FEASIBLE.value if feasible else PlanStatus.INFEASIBLE.value,
        reason_codes=tuple(reasons), destination_usage_bytes=tuple(sorted(usage.items())),
    )


def plan_to_mapping(problem: Problem, plan: Sequence[int]) -> dict[str, str]:
    return {f.file_id: problem.candidates[i][idx].id
            for i, (f, idx) in enumerate(zip(problem.files, plan))}


def mapping_to_plan(problem: Problem, mapping: dict[str, str]) -> tuple[int, ...] | None:
    """Convert dict[file_id, action_id] to indices; None if anything mismatches."""
    if set(mapping) != {f.file_id for f in problem.files}:
        return None
    out = []
    for f, cands in zip(problem.files, problem.candidates):
        ids = [c.id for c in cands]
        if mapping[f.file_id] not in ids:
            return None
        out.append(ids.index(mapping[f.file_id]))
    return tuple(out)


def evaluate_mapping(problem: Problem, mapping: dict[str, str]) -> Evaluation:
    plan = mapping_to_plan(problem, mapping)
    if plan is None:
        return Evaluation(False, 0, problem.preferences.goal_bytes, 0, 0.0,
                          PlanStatus.INVALID.value, (ReasonCode.INVALID_ASSIGNMENT.value,))
    return evaluate(problem, plan)


def all_keep(problem: Problem) -> tuple[int, ...]:
    return (0,) * problem.n_files


# ---------------------------------------------------------------- bounds
def upper_bounds(problem: Problem) -> tuple[int, int]:
    """(UB ignoring capacity, capacity-aware UB) on attainable source gain."""
    ub = 0
    unbounded_total = 0
    move_extra = 0
    for f, cands in zip(problem.files, problem.candidates):
        max_gain = max(c.source_gain_bytes for c in cands)
        ub += max_gain
        non_move_gain = max(
            (c.source_gain_bytes for c in cands if c.kind != ActionKind.MOVE),
            default=0,
        )
        max_move_gain = max(
            (c.source_gain_bytes for c in cands if c.kind == ActionKind.MOVE),
            default=0,
        )
        unbounded_total += non_move_gain
        move_extra += max(0, max_move_gain - non_move_gain)
    cap_total = sum(problem.capacities.values())
    ub_cap = unbounded_total + min(cap_total, move_extra)
    return ub, ub_cap


def proof_of_infeasibility(problem: Problem) -> tuple[str, ...]:
    """Reason codes PROVING that no plan reaches the goal (empty if unproven)."""
    goal = problem.preferences.goal_bytes
    if goal <= 0:
        return ()
    ub, ub_cap = upper_bounds(problem)
    if ub < goal:
        return (ReasonCode.INSUFFICIENT_THEORETICAL_GAIN.value,)
    if ub_cap < goal:
        return (ReasonCode.INSUFFICIENT_THEORETICAL_GAIN.value,
                ReasonCode.DESTINATION_CAPACITY.value)
    return ()


# ---------------------------------------------------------------- energy
def penalty_alpha(problem: Problem) -> float:
    """alpha = 2 * r_max * goal, r_max = max cost/gain over non-KEEP candidates."""
    goal = problem.preferences.goal_bytes
    r_max = 0.0
    for cands in problem.candidates:
        for c in cands[1:]:
            if c.source_gain_bytes > 0:
                r_max = max(r_max, c.total_cost / c.source_gain_bytes)
    if r_max == 0.0:
        r_max = 1.0 / MIB
    return PENALTY_FACTOR * r_max * max(goal, 1)


def energy(problem: Problem, gain: int, cost: float, alpha: float) -> float:
    goal = problem.preferences.goal_bytes
    if goal <= 0:
        return cost
    return cost + alpha * max(0, goal - gain) / goal


class PlanState:
    """Incremental evaluator: O(k) per neighbour instead of O(n)."""

    def __init__(self, problem: Problem, plan: Sequence[int]):
        self.problem = problem
        self.choice = list(plan)
        self.gain = 0
        self.cost = 0.0
        self.usage: dict[str, int] = {d: 0 for d in problem.capacities}
        for cands, idx in zip(problem.candidates, self.choice):
            self._add(cands[idx], +1)

    def _add(self, c: CandidateAction, sign: int) -> None:
        self.gain += sign * c.source_gain_bytes
        self.cost += sign * c.total_cost
        if c.kind == ActionKind.MOVE:
            self.usage[c.destination_volume_id] += sign * c.destination_use_bytes

    def try_changes(self, changes: Iterable[tuple[int, int]]):
        """Return (gain, cost, capacity_ok) after hypothetical changes."""
        gain, cost = self.gain, self.cost
        du: dict[str, int] = {}
        for i, new in changes:
            old_c = self.problem.candidates[i][self.choice[i]]
            new_c = self.problem.candidates[i][new]
            gain += new_c.source_gain_bytes - old_c.source_gain_bytes
            cost += new_c.total_cost - old_c.total_cost
            if old_c.kind == ActionKind.MOVE:
                du[old_c.destination_volume_id] = du.get(old_c.destination_volume_id, 0) - old_c.destination_use_bytes
            if new_c.kind == ActionKind.MOVE:
                du[new_c.destination_volume_id] = du.get(new_c.destination_volume_id, 0) + new_c.destination_use_bytes
        ok = all(self.usage[d] + v <= self.problem.capacities[d] for d, v in du.items())
        return gain, cost, ok

    def apply(self, changes: Iterable[tuple[int, int]]) -> None:
        for i, new in changes:
            cands = self.problem.candidates[i]
            self._add(cands[self.choice[i]], -1)
            self.choice[i] = new
            self._add(cands[new], +1)

    @property
    def feasible(self) -> bool:
        return (self.gain >= self.problem.preferences.goal_bytes
                and all(u <= self.problem.capacities[d] for d, u in self.usage.items()))


# ---------------------------------------------------------------- results
def build_result(problem: Problem, algorithm: str, best_plan: Sequence[int] | None,
                 duration_ms: float, iterations: int, seed: int | None,
                 warnings: Iterable[str] = (), diagnostics: dict | None = None
                 ) -> OptimizationResult:
    """Common result construction: only a re-evaluated feasible plan is FEASIBLE."""
    warnings = tuple(problem.warnings) + tuple(warnings)
    if ReasonCode.INVALID_CONFIG.value in problem.reason_codes:
        return OptimizationResult(algorithm, {}, None, duration_ms, iterations, seed, warnings,
                                  ResultStatus.INVALID_CONFIG.value, problem.reason_codes,
                                  diagnostics or {})
    ev = evaluate(problem, best_plan) if best_plan is not None else None
    if ev is not None and ev.feasible:
        return OptimizationResult(algorithm, plan_to_mapping(problem, best_plan), ev,
                                  duration_ms, iterations, seed, warnings,
                                  ResultStatus.FEASIBLE.value, problem.reason_codes,
                                  diagnostics or {})
    proof = proof_of_infeasibility(problem)
    if proof:
        status = ResultStatus.PROVEN_INFEASIBLE.value
        reasons = tuple(dict.fromkeys(problem.reason_codes + proof))
    else:
        status = ResultStatus.NO_FEASIBLE_FOUND.value
        reasons = tuple(dict.fromkeys(problem.reason_codes + (ReasonCode.NO_FEASIBLE_FOUND.value,)))
    return OptimizationResult(algorithm, {}, ev, duration_ms, iterations, seed, warnings,
                              status, reasons, diagnostics or {})
