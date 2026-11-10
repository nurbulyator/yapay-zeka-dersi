"""Reproducible benchmark: Greedy vs Hill Climbing vs Simulated Annealing.

Outputs (results/):
  benchmark_runs.csv     one row per (scenario, algorithm, seed)
  benchmark_summary.csv  per scenario/algorithm: feasible rate (with denominator),
                         mean/std cost over FEASIBLE runs only, gap to optimum
  *.png                  plots (only if matplotlib is installed)

Usage:  python scripts/benchmark.py [--quick] [--seeds 10] [--iterations 3000]
"""
from __future__ import annotations

import argparse
import csv
import statistics
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from smartstorage.annealing import SAConfig, hill_climbing, simulated_annealing  # noqa: E402
from smartstorage.exact import exhaustive, state_count  # noqa: E402
from smartstorage.greedy import greedy  # noqa: E402
from smartstorage.models import ActionKind  # noqa: E402
from smartstorage.sample_data import (ScenarioSpec, benchmark_scenarios,  # noqa: E402
                                      greedy_trap_problem, make_problem, tiny_problem)

RUN_FIELDS = ["scenario_id", "family", "algorithm", "seed", "n_files", "n_volumes", "goal_bytes",
              "status", "feasible", "estimated_gain_bytes", "total_cost", "n_changed_files",
              "runtime_ms", "optimum_cost", "gap_to_optimum"]


def _row(sid, family, n_vol, problem, res, optimum):
    ev = res.evaluation
    feasible = res.feasible
    cost = ev.total_cost if feasible else None
    changed = 0
    if feasible:
        changed = sum(1 for a in res.plan.values() if f":{ActionKind.KEEP.value}:" not in a)
    gap = None
    if feasible and optimum is not None:
        gap = 0.0 if optimum == 0 else cost / optimum - 1
    return {
        "scenario_id": sid, "family": family, "algorithm": res.algorithm, "seed": res.seed,
        "n_files": problem.n_files, "n_volumes": n_vol, "goal_bytes": problem.preferences.goal_bytes,
        "status": res.status, "feasible": feasible,
        "estimated_gain_bytes": ev.gain_bytes if feasible else 0,
        "total_cost": None if cost is None else round(cost, 6), "n_changed_files": changed,
        "runtime_ms": round(res.duration_ms, 3),
        "optimum_cost": None if optimum is None else round(optimum, 6),
        "gap_to_optimum": None if gap is None else round(gap, 6),
    }


def run(quick: bool, seeds: int, iterations: int, out_dir: Path) -> list[dict]:
    cfg = SAConfig(iterations=iterations)
    cases = []  # (sid, family, n_volumes, problem)
    for spec in benchmark_scenarios(include_1000=not quick):
        if quick and spec.n_files > 100:
            continue
        cases.append((spec.scenario_id, spec.family, spec.n_volumes, make_problem(spec)))
    n_trap = 8 if quick else 20
    n_tiny = 8 if quick else 20
    cases += [(f"trap_{s:02d}", "greedy_trap", 2, greedy_trap_problem(s)) for s in range(n_trap)]
    cases += [(f"tiny_{s:02d}", "tiny_exact", 2, tiny_problem(s)) for s in range(n_tiny)]

    rows = []
    for sid, family, n_vol, problem in cases:
        optimum = None
        if state_count(problem) <= 200_000:
            ex = exhaustive(problem)
            optimum = ex.evaluation.total_cost if ex.feasible else None
            rows.append(_row(sid, family, n_vol, problem, ex, optimum))
        rows.append(_row(sid, family, n_vol, problem, greedy(problem), optimum))
        for s in range(seeds):
            rows.append(_row(sid, family, n_vol, problem, hill_climbing(problem, s, cfg), optimum))
            rows.append(_row(sid, family, n_vol, problem, simulated_annealing(problem, s, cfg), optimum))
        print(f"  {sid:<22} n={problem.n_files:<5} tamamlandı")
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "benchmark_runs.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=RUN_FIELDS)
        w.writeheader()
        w.writerows(rows)
    return rows


def summarize(rows: list[dict], out_dir: Path) -> list[dict]:
    groups: dict[tuple, list[dict]] = {}
    for r in rows:
        groups.setdefault((r["scenario_id"], r["family"], r["algorithm"]), []).append(r)
    summary = []
    for (sid, family, algo), rs in groups.items():
        feas = [r for r in rs if r["feasible"]]
        costs = [r["total_cost"] for r in feas]
        gaps = [r["gap_to_optimum"] for r in feas if r["gap_to_optimum"] is not None]
        summary.append({
            "scenario_id": sid, "family": family, "algorithm": algo, "n_files": rs[0]["n_files"],
            "runs": len(rs), "feasible_runs": len(feas),
            "feasible_rate": round(len(feas) / len(rs), 4),
            "mean_cost_feasible": round(statistics.mean(costs), 6) if costs else None,
            "std_cost_feasible": round(statistics.pstdev(costs), 6) if len(costs) > 1 else (0.0 if costs else None),
            "best_cost": round(min(costs), 6) if costs else None,
            "mean_gap_to_optimum": round(statistics.mean(gaps), 6) if gaps else None,
            "optimal_runs": sum(1 for g in gaps if g <= 1e-9) if gaps else None,
            "mean_runtime_ms": round(statistics.mean(r["runtime_ms"] for r in rs), 3),
            "statuses": "|".join(sorted({r["status"] for r in rs})),
        })
    with open(out_dir / "benchmark_summary.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(summary[0]))
        w.writeheader()
        w.writerows(summary)
    return summary


def headline(summary: list[dict]) -> dict:
    """Aggregate numbers for README / slides."""
    out = {}
    for family in ("greedy_trap", "tiny_exact"):
        for algo in ("greedy", "hill_climbing", "simulated_annealing"):
            rs = [s for s in summary if s["family"] == family and s["algorithm"] == algo
                  and s["mean_gap_to_optimum"] is not None]
            if rs:
                out[(family, algo)] = {
                    "mean_gap_pct": round(100 * statistics.mean(s["mean_gap_to_optimum"] for s in rs), 2),
                    "optimal_runs": sum(s["optimal_runs"] for s in rs),
                    "feasible_runs": sum(s["feasible_runs"] for s in rs),
                }
    return out


def plots(rows: list[dict], summary: list[dict], out_dir: Path) -> list[str]:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib yok; grafikler atlandı (CSV dosyaları üretildi).")
        return []
    made = []
    colors = {"greedy": "#9a6b2f", "hill_climbing": "#5b7fa6", "simulated_annealing": "#2f8a5b"}
    labels = {"greedy": "Greedy", "hill_climbing": "Hill Climbing", "simulated_annealing": "Sim. Annealing"}

    # 1) mean gap to optimum on trap + tiny families
    fams = ["greedy_trap", "tiny_exact"]
    fam_tr = {"greedy_trap": "Greedy tuzak senaryoları", "tiny_exact": "Küçük senaryolar (tam arama)"}
    fig, ax = plt.subplots(figsize=(8, 4.5))
    width = 0.25
    for k, algo in enumerate(colors):
        vals = []
        for fam in fams:
            rs = [s["mean_gap_to_optimum"] for s in summary if s["family"] == fam
                  and s["algorithm"] == algo and s["mean_gap_to_optimum"] is not None]
            vals.append(100 * statistics.mean(rs) if rs else 0)
        xs = [i + (k - 1) * width for i in range(len(fams))]
        bars = ax.bar(xs, vals, width, color=colors[algo], label=labels[algo])
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v + 0.3, f"%{v:.1f}", ha="center", fontsize=9)
    ax.set_xticks(range(len(fams)), [fam_tr[f] for f in fams])
    ax.set_ylabel("Optimuma göre ortalama ek maliyet (%)")
    ax.set_title("Kalite: optimum maliyetten sapma (düşük = iyi)")
    ax.legend(frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(out_dir / "cost_gap_comparison.png", dpi=150)
    plt.close(fig)
    made.append("cost_gap_comparison.png")

    # 2) runtime vs n_files (grid family, 2 volumes, goal 3)
    fig, ax = plt.subplots(figsize=(8, 4.5))
    for algo in colors:
        pts = sorted((s["n_files"], s["mean_runtime_ms"]) for s in summary
                     if s["family"] == "grid" and s["algorithm"] == algo
                     and s["scenario_id"].endswith("_v2_g3"))
        if pts:
            ax.plot([p[0] for p in pts], [p[1] for p in pts], marker="o", color=colors[algo],
                    label=labels[algo])
    ax.set_xlabel("Dosya sayısı")
    ax.set_ylabel("Ortalama çalışma süresi (ms)")
    ax.set_title("Çalışma süresi ve dosya sayısı (2 hacim, hedef 3 GiB)")
    ax.legend(frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(out_dir / "runtime_vs_n_files.png", dpi=150)
    plt.close(fig)
    made.append("runtime_vs_n_files.png")

    # 3) SA convergence on one trap scenario
    p = greedy_trap_problem(6)
    res = simulated_annealing(p, 0)
    hist = res.diagnostics["history"]
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.plot([h["iteration"] for h in hist], [h["current_energy"] for h in hist],
            color="#5b7fa6", label="Mevcut durum enerjisi")
    ax.plot([h["iteration"] for h in hist], [h["best_feasible_cost"] for h in hist],
            color="#2f8a5b", lw=2.5, label="En iyi uygun plan maliyeti")
    g = greedy(p)
    if g.feasible:
        ax.axhline(g.evaluation.total_cost, color="#9a6b2f", ls="--", label="Greedy maliyeti")
    ex = exhaustive(p)
    if ex.feasible:
        ax.axhline(ex.evaluation.total_cost, color="#444", ls=":", label="Gerçek optimum")
    ax2 = ax.twinx()
    ax2.plot([h["iteration"] for h in hist], [h["temperature"] for h in hist],
             color="#c0504d", alpha=0.35, label="Sıcaklık T")
    ax2.set_ylabel("Sıcaklık T")
    ax.set_xlabel("İterasyon")
    ax.set_ylabel("Maliyet / enerji")
    ax.set_title("Benzetimli Tavlama yakınsaması (tuzak senaryosu)")
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, frameon=False, fontsize=8)
    ax.spines[["top"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(out_dir / "sa_convergence.png", dpi=150)
    plt.close(fig)
    made.append("sa_convergence.png")
    return made


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="SmartStorage AI karşılaştırma deneyi")
    ap.add_argument("--quick", action="store_true", help="küçük senaryolar, hızlı")
    ap.add_argument("--seeds", type=int, default=10)
    ap.add_argument("--iterations", type=int, default=3000)
    ap.add_argument("--out", type=Path, default=PROJECT_ROOT / "results")
    ap.add_argument("--no-plots", action="store_true")
    args = ap.parse_args(argv)
    t0 = time.perf_counter()
    print("Deney başlıyor...")
    rows = run(args.quick, args.seeds, args.iterations, args.out)
    summary = summarize(rows, args.out)
    made = [] if args.no_plots else plots(rows, summary, args.out)
    print(f"\n{len(rows)} koşum, {time.perf_counter() - t0:.1f} s. Çıktılar: {args.out}")
    for (fam, algo), v in headline(summary).items():
        print(f"  {fam:<12} {algo:<20} ortalama sapma %{v['mean_gap_pct']:<6} "
              f"optimum bulunan koşum {v['optimal_runs']}/{v['feasible_runs']}")
    for m in made:
        print(f"  grafik: {m}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
