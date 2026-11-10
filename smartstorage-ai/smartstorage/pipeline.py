"""Convenience end-to-end pipeline used by the UI, scripts and tests."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .actions import build_problem
from .annealing import SAConfig, hill_climbing, simulated_annealing
from .estimate import estimate_files
from .greedy import greedy
from .importance import ImportanceRule
from .models import DiskInfo, OptimizationResult, Preferences, Problem, ScanResult
from .scanner import DEFAULT_MAX_FILES, scan


def analyze_folders(roots: Iterable[str], protected_roots: Iterable[str] = (),
                    importance_rules: Iterable[ImportanceRule] = (),
                    max_files: int = DEFAULT_MAX_FILES, now: float | None = None) -> ScanResult:
    """Read-only scan + bounded compression estimation."""
    res = scan(list(roots), max_files=max_files, protected_roots=protected_roots,
               importance_rules=importance_rules, now=now)
    files, warns = estimate_files(res.files)
    return ScanResult(res.roots, files, res.total_bytes, res.warnings + warns, res.skipped,
                      res.truncated, res.source_volume_id, res.reason_codes)


@dataclass(frozen=True)
class Comparison:
    problem: Problem
    results: tuple[OptimizationResult, ...]


def run_all(problem: Problem, seed: int = 42, config: SAConfig | None = None) -> Comparison:
    """Greedy, Hill Climbing and SA on identical inputs."""
    return Comparison(problem, (greedy(problem), hill_climbing(problem, seed, config),
                                simulated_annealing(problem, seed, config)))


def plan_for_scan(scan_result: ScanResult, disks: Iterable[DiskInfo], prefs: Preferences) -> Problem:
    return build_problem(scan_result.files, disks, prefs,
                         warnings=scan_result.warnings, reason_codes=scan_result.reason_codes)
