"""Fully synthetic scenarios: files with KNOWN compression gains and simulated
volumes with KNOWN capacities (SPEC_v2 §9 option B, §17).

Nothing here touches the real filesystem. Simulated gains are not physical
disk changes.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from random import Random

from .actions import build_problem
from .models import GIB, MIB, DiskInfo, FileInfo, Preferences, Problem

SOURCE_VID = "sim:C"

# (category, share, size range MiB, compress ratio range = gain fraction, suffixes)
_CATEGORIES = [
    ("logs", 0.20, (5, 600), (0.60, 0.90), (".log", ".txt")),
    ("documents", 0.15, (1, 60), (0.20, 0.50), (".txt", ".csv", ".json", ".xml")),
    ("datasets", 0.15, (20, 1500), (0.45, 0.80), (".csv", ".json", ".parquet")),
    ("media", 0.35, (30, 3000), (0.0, 0.0), (".mp4", ".mkv", ".jpg", ".mp3")),
    ("archives", 0.15, (10, 1200), (0.0, 0.02), (".zip", ".7z", ".iso")),
]
_FOLDERS = ["Belgeler", "Indirilenler", "Projeler", "Videolar", "Arsiv", "Loglar"]


def _fid(path: str) -> str:
    return hashlib.sha256(path.lower().encode()).hexdigest()[:16]


def synthetic_files(n: int, seed: int, protected_fraction: float = 0.1,
                    source_vid: str = SOURCE_VID) -> tuple[FileInfo, ...]:
    rng = Random(seed)
    files = []
    for k in range(n):
        r, acc = rng.random(), 0.0
        for cat, share, (lo, hi), (glo, ghi), sufs in _CATEGORIES:
            acc += share
            if r <= acc:
                break
        # log-uniform size
        size = int(MIB * lo * (hi / lo) ** rng.random())
        frac = rng.uniform(glo, ghi)
        gain = int(size * frac) if frac > 0 else 0
        suffix = rng.choice(sufs)
        folder = rng.choice(_FOLDERS)
        path = f"C:\\SimKullanici\\{folder}\\{cat}_{k:04d}{suffix}"
        imp_r = rng.random()
        importance = 1 if imp_r < 0.25 else (9 if imp_r > 0.85 else 5)
        protected = rng.random() < protected_fraction
        files.append(FileInfo(
            file_id=_fid(path), path=path, size_bytes=size, suffix=suffix,
            modified_timestamp=1_700_000_000.0 + k * 3600, volume_id=source_vid,
            importance=9 if protected else importance, protected=protected,
            eligible=not protected, estimated_compress_gain_bytes=gain,
            skip_reason="PROTECTED" if protected else None,
        ))
    return tuple(files)


def simulated_disks(dest_free_gib: tuple[float, ...] = (50.0,),
                    source_free_gib: float = 8.0) -> tuple[DiskInfo, ...]:
    disks = [DiskInfo(SOURCE_VID, "C:\\", 256 * GIB, int(source_free_gib * GIB), True,
                      False, simulated=True, label="C: (simüle kaynak)")]
    for k, free in enumerate(dest_free_gib):
        letter = "DEFGH"[k]
        disks.append(DiskInfo(f"sim:{letter}", f"{letter}:\\", 1024 * GIB, int(free * GIB),
                              True, True, simulated=True, label=f"{letter}: (simüle hedef)"))
    return tuple(disks)


@dataclass(frozen=True)
class ScenarioSpec:
    scenario_id: str
    n_files: int
    n_volumes: int                 # including the source volume
    goal_gib: float
    allow_compress: bool = True
    allow_move: bool = True
    seed: int = 7
    protected_fraction: float = 0.1
    dest_free_gib: tuple[float, ...] = field(default=())
    priority: str = "balanced"
    family: str = "grid"
    description: str = ""

    def resolved_dest_free(self) -> tuple[float, ...]:
        if self.dest_free_gib:
            return self.dest_free_gib
        return tuple([50.0, 10.0, 3.0][: max(0, self.n_volumes - 1)])


def make_problem(spec: ScenarioSpec) -> Problem:
    files = synthetic_files(spec.n_files, spec.seed, spec.protected_fraction)
    disks = simulated_disks(spec.resolved_dest_free())
    prefs = Preferences(
        source_volume_id=SOURCE_VID, goal_bytes=int(spec.goal_gib * GIB),
        allow_compress=spec.allow_compress, allow_move=spec.allow_move,
        allowed_destination_volume_ids=tuple(d.volume_id for d in disks[1:]),
        priority=spec.priority,
    )
    return build_problem(files, disks, prefs)


def benchmark_scenarios(include_1000: bool = True) -> list[ScenarioSpec]:
    specs = []
    sizes = [20, 100, 500] + ([1000] if include_1000 else [])
    for n in sizes:
        for v in (1, 2, 4):
            for g in (0, 1, 3):
                specs.append(ScenarioSpec(f"grid_n{n}_v{v}_g{g}", n, v, g, seed=100 + n))
    specs += [
        ScenarioSpec("compress_off", 100, 2, 3, allow_compress=False, seed=200, family="variant",
                     description="Sıkıştırma kapalı"),
        ScenarioSpec("move_off", 100, 2, 3, allow_move=False, seed=200, family="variant",
                     description="Taşıma kapalı"),
        ScenarioSpec("move_off_big_goal", 20, 2, 5, allow_move=False, seed=201, family="variant",
                     description="Taşıma kapalı, büyük hedef"),
        ScenarioSpec("target_full", 100, 2, 3, allow_compress=False, seed=200,
                     dest_free_gib=(0.3,), family="variant", description="Hedef disk neredeyse dolu"),
        ScenarioSpec("multi_target", 100, 4, 8, seed=202, dest_free_gib=(1.0, 2.5, 4.0),
                     family="variant", description="Farklı boş alanlı üç hedef"),
        ScenarioSpec("impossible", 100, 2, 500, seed=200, family="variant",
                     description="Ulaşılamaz hedef"),
        ScenarioSpec("safe_priority", 100, 2, 3, seed=200, priority="safe", family="variant"),
        ScenarioSpec("fast_priority", 100, 2, 3, seed=200, priority="fast", family="variant"),
    ]
    return specs


# ------------------------------------------------------------ tiny & traps
def tiny_problem(seed: int, n_files: int = 7, n_dest: int = 1,
                 goal_fraction: float = 0.45) -> Problem:
    """<= 8 files, 2–3 actions each: small enough for exhaustive search."""
    rng = Random(seed)
    files = []
    for k in range(n_files):
        size = rng.randint(50, 900) * MIB
        frac = rng.choice([0.0, 0.3, 0.6, 0.8])
        path = f"C:\\Tiny\\f{k}.dat"
        files.append(FileInfo(_fid(f"{seed}:{path}"), path, size, ".dat", 1.7e9,
                              SOURCE_VID, importance=rng.choice([1, 5, 9]),
                              estimated_compress_gain_bytes=int(size * frac)))
    total = sum(f.size_bytes for f in files)
    disks = simulated_disks(tuple(rng.choice([0.6, 1.0, 2.0]) for _ in range(n_dest)))
    prefs = Preferences(SOURCE_VID, int(total * goal_fraction), True, n_dest > 0,
                        tuple(d.volume_id for d in disks[1:]))
    return build_problem(files, disks, prefs)


def greedy_trap_problem(seed: int = 0) -> Problem:
    """Adversarial family for ratio-greedy: several mid-size files whose sizes
    form subset-sum style combinations around the goal, mixed importance and a
    tight destination. Greedy commits to the best ratio first and ends up with
    a costlier set; local search can swap into a cheaper combination."""
    rng = Random(10_000 + seed)
    files = []
    goal = 4 * GIB
    for k in range(10):
        size = int(rng.uniform(0.9, 2.6) * GIB)
        imp = rng.choice([1, 5, 9])
        frac = rng.choice([0.0, 0.55, 0.75])
        path = f"C:\\Tuzak\\dosya_{k}.bin"
        files.append(FileInfo(_fid(f"trap{seed}:{path}"), path, size, ".bin", 1.7e9,
                              SOURCE_VID, importance=imp,
                              estimated_compress_gain_bytes=int(size * frac)))
    disks = simulated_disks((rng.uniform(2.6, 4.5),))
    prefs = Preferences(SOURCE_VID, goal, True, True, ("sim:D",))
    return build_problem(files, disks, prefs)
