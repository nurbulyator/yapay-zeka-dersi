import csv
import io
import json
from dataclasses import replace

from smartstorage.annealing import simulated_annealing
from smartstorage.greedy import greedy
from smartstorage.sample_data import greedy_trap_problem
from smartstorage.serialize import CSV_COLUMNS, report_dict, sanitize_cell, to_csv, to_json


def test_csv_columns_and_rows():
    p = greedy_trap_problem(1)
    r = greedy(p)
    rows = list(csv.DictReader(io.StringIO(to_csv(p, r))))
    assert list(rows[0].keys()) == CSV_COLUMNS
    assert len(rows) == p.n_files
    assert {row["action"] for row in rows} <= {"KEEP", "COMPRESS", "MOVE"}


def test_formula_injection_sanitized():
    assert sanitize_cell("=HYPERLINK(1)") == "'=HYPERLINK(1)"
    assert sanitize_cell("+cmd") == "'+cmd"
    assert sanitize_cell("@x") == "'@x"
    assert sanitize_cell("normal.txt") == "normal.txt"
    p = greedy_trap_problem(1)
    evil = replace(p.files[0], path="=cmd|' /C calc'!A0")
    p2 = replace(p, files=(evil,) + p.files[1:])
    text = to_csv(p2, greedy(p2))
    assert "\n=cmd" not in text and ",=cmd" not in text


def test_json_report_contract():
    p = greedy_trap_problem(2)
    r = simulated_annealing(p, 5)
    d = json.loads(to_json(p, r))
    for key in ["project", "mode", "timestamp", "source_volume_id", "goal_bytes", "preferences",
                "algorithm", "status", "estimated_gain_bytes", "total_cost",
                "destination_usage_bytes", "action_counts", "runtime_ms", "seed", "warnings",
                "actions", "cost_model", "reason_codes"]:
        assert key in d
    assert d["mode"] == "DRY_RUN" and d["project"] == "SmartStorage AI"
    assert d["seed"] == 5 and sum(d["action_counts"].values()) == p.n_files
    assert "+" in d["timestamp"] or "Z" in d["timestamp"] or "-" in d["timestamp"][19:]


def test_infeasible_report_has_no_actions():
    from conftest import disks, fi, prefs
    from smartstorage.actions import build_problem
    p = build_problem([fi("a", 100, 60)], disks(), prefs(10_000, move=False))
    d = report_dict(p, greedy(p))
    assert d["status"] == "PROVEN_INFEASIBLE" and d["actions"] == [] and d["estimated_gain_bytes"] == 0
