"""CSV / JSON plan reports (SPEC_v2 §16). Pure functions returning strings."""
from __future__ import annotations

import csv
import io
import json
from dataclasses import asdict
from datetime import datetime

from . import PROJECT_NAME
from .explain import explain_action
from .models import ActionKind, OptimizationResult, Problem

CSV_COLUMNS = ["file_id", "path", "size_bytes", "importance", "action", "target_volume_id",
               "source_gain_estimate_bytes", "destination_use_bytes", "action_cost",
               "risk_score", "reason"]
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r", "\n")


def sanitize_cell(value):
    """Neutralise spreadsheet formula injection for untrusted text."""
    if isinstance(value, str) and value.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


def _chosen(problem: Problem, result: OptimizationResult):
    """Yield (file, candidate) for every file. Infeasible result => all KEEP."""
    for f, cands in zip(problem.files, problem.candidates):
        aid = result.plan.get(f.file_id) if result.plan else None
        c = next((x for x in cands if x.id == aid), cands[0])
        yield f, c


def plan_rows(problem: Problem, result: OptimizationResult) -> list[dict]:
    rows = []
    for f, c in _chosen(problem, result):
        rows.append({
            "file_id": f.file_id, "path": f.path, "size_bytes": f.size_bytes,
            "importance": f.importance, "action": c.kind.value,
            "target_volume_id": c.destination_volume_id or "",
            "source_gain_estimate_bytes": c.source_gain_bytes,
            "destination_use_bytes": c.destination_use_bytes,
            "action_cost": round(c.total_cost, 6), "risk_score": c.risk_score,
            "reason": explain_action(problem, f, c),
        })
    return rows


def to_csv(problem: Problem, result: OptimizationResult) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CSV_COLUMNS, quoting=csv.QUOTE_MINIMAL)
    w.writeheader()
    for row in plan_rows(problem, result):
        w.writerow({k: sanitize_cell(v) for k, v in row.items()})
    return buf.getvalue()


def report_dict(problem: Problem, result: OptimizationResult) -> dict:
    counts = {k.value: 0 for k in ActionKind}
    actions = []
    for row in plan_rows(problem, result):
        counts[row["action"]] += 1
        if row["action"] != ActionKind.KEEP.value:
            actions.append(row)
    ev = result.evaluation
    usage = dict(ev.destination_usage_bytes) if (ev and result.feasible) else {}
    prefs = asdict(problem.preferences)
    diag = {k: v for k, v in result.diagnostics.items() if k != "history"}
    return {
        "project": PROJECT_NAME,
        "mode": "DRY_RUN",
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source_volume_id": problem.preferences.source_volume_id,
        "goal_bytes": problem.preferences.goal_bytes,
        "preferences": prefs,
        "algorithm": result.algorithm,
        "status": result.status,
        "estimated_gain_bytes": ev.gain_bytes if (ev and result.feasible) else 0,
        "total_cost": round(ev.total_cost, 6) if (ev and result.feasible) else 0.0,
        "destination_usage_bytes": usage,
        "destination_capacity_bytes": dict(problem.capacities),
        "action_counts": counts,
        "runtime_ms": round(result.duration_ms, 3),
        "iterations": result.iterations,
        "seed": result.seed,
        "warnings": list(result.warnings),
        "reason_codes": list(result.reason_codes),
        "cost_model": problem.cost_model,
        "diagnostics": diag,
        "note": "Tüm değerler tahminidir. Hiçbir dosya değiştirilmedi. Dosya yolları kişisel bilgi içerebilir.",
        "actions": actions,
    }


def to_json(problem: Problem, result: OptimizationResult) -> str:
    return json.dumps(report_dict(problem, result), ensure_ascii=False, indent=2)
