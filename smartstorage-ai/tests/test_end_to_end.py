import json
import subprocess
import sys

from conftest import ROOT, snapshot
from smartstorage.disks import discover_disks
from smartstorage.models import MIB, Preferences
from smartstorage.pipeline import analyze_folders, plan_for_scan, run_all
from smartstorage.serialize import to_csv, to_json


def test_fixture_scan_plan_serialize_no_changes(tmp_path):
    out = tmp_path / "demo"
    subprocess.run([sys.executable, str(ROOT / "scripts" / "make_fixture.py"), "--out", str(out),
                    "--scale", "0.3"], check=True, capture_output=True)
    before = snapshot(out)
    scan_res = analyze_folders([str(out)], protected_roots=[str(out / "Önemli")])
    assert len(scan_res.files) >= 15
    assert any(f.estimated_compress_gain_bytes > 0 for f in scan_res.files)
    disks, _ = discover_disks()
    prefs = Preferences(scan_res.source_volume_id, 8 * MIB, True, False)
    problem = plan_for_scan(scan_res, disks, prefs)
    comp = run_all(problem, seed=3)
    assert [r.algorithm for r in comp.results] == ["greedy", "hill_climbing", "simulated_annealing"]
    for r in comp.results:
        assert r.feasible
        for fid, aid in r.plan.items():
            f = next(x for x in problem.files if x.file_id == fid)
            if f.protected:
                assert aid.endswith(":KEEP:-")
        to_csv(problem, r)
        json.loads(to_json(problem, r))
    impossible = plan_for_scan(scan_res, disks, Preferences(scan_res.source_volume_id, 10 * 1024 * MIB, True, False))
    assert all(r.status == "PROVEN_INFEASIBLE" for r in run_all(impossible).results)
    assert snapshot(out) == before


def test_benchmark_quick_runs(tmp_path):
    res = subprocess.run([sys.executable, str(ROOT / "scripts" / "benchmark.py"), "--quick",
                          "--seeds", "2", "--iterations", "300", "--out", str(tmp_path), "--no-plots"],
                         check=True, capture_output=True, text=True)
    assert (tmp_path / "benchmark_runs.csv").exists() and (tmp_path / "benchmark_summary.csv").exists()
