"""Immutable data contracts (SPEC_v2 §5)."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

KIB = 1024
MIB = 1024 ** 2
GIB = 1024 ** 3


class ActionKind(str, Enum):
    KEEP = "KEEP"
    COMPRESS = "COMPRESS"
    MOVE = "MOVE"
    DELETE = "DELETE"


#: Stable ordering used for deterministic candidate sorting.
KIND_ORDER = {
    ActionKind.KEEP: 0,
    ActionKind.COMPRESS: 1,
    ActionKind.MOVE: 2,
    ActionKind.DELETE: 3,
}


class PlanStatus(str, Enum):
    """Status of ONE plan (Evaluation.status)."""
    FEASIBLE = "FEASIBLE"
    INFEASIBLE = "INFEASIBLE"
    INVALID = "INVALID"


class ResultStatus(str, Enum):
    """Status of a SEARCH outcome (OptimizationResult.status)."""
    FEASIBLE = "FEASIBLE"
    PROVEN_INFEASIBLE = "PROVEN_INFEASIBLE"
    NO_FEASIBLE_FOUND = "NO_FEASIBLE_FOUND"
    INVALID_CONFIG = "INVALID_CONFIG"


class ReasonCode(str, Enum):
    EMPTY_SCOPE = "EMPTY_SCOPE"
    NO_ALLOWED_ACTIONS = "NO_ALLOWED_ACTIONS"
    NO_DESTINATION = "NO_DESTINATION"
    PROTECTED_ONLY = "PROTECTED_ONLY"
    INSUFFICIENT_THEORETICAL_GAIN = "INSUFFICIENT_THEORETICAL_GAIN"
    DESTINATION_CAPACITY = "DESTINATION_CAPACITY"
    SCAN_INCOMPLETE = "SCAN_INCOMPLETE"
    UNSTABLE_FILE = "UNSTABLE_FILE"
    NO_FEASIBLE_FOUND = "NO_FEASIBLE_FOUND"
    INVALID_CONFIG = "INVALID_CONFIG"
    GOAL_NOT_MET = "GOAL_NOT_MET"
    INVALID_ASSIGNMENT = "INVALID_ASSIGNMENT"


class SkipReason(str, Enum):
    """Why a file is KEEP-only (FileInfo.skip_reason)."""
    PROTECTED = "PROTECTED"
    RISKY_SUFFIX = "RISKY_SUFFIX"
    HARDLINK = "HARDLINK"
    CLOUD_PLACEHOLDER = "CLOUD_PLACEHOLDER"
    RECENTLY_MODIFIED = "RECENTLY_MODIFIED"
    UNREADABLE = "UNREADABLE"
    ZERO_SIZE = "ZERO_SIZE"
    OTHER_VOLUME = "OTHER_VOLUME"
    UNSTABLE_FILE = "UNSTABLE_FILE"


class Priority(str, Enum):
    SAFE = "safe"
    BALANCED = "balanced"
    FAST = "fast"


@dataclass(frozen=True)
class DiskInfo:
    volume_id: str
    mountpoint: str
    total_bytes: int
    free_bytes: int
    writable: bool
    eligible_destination: bool
    removable: bool = False
    identity_confident: bool = True
    simulated: bool = False
    aliases: tuple[str, ...] = ()
    label: str = ""

    @property
    def display_name(self) -> str:
        return self.label or self.mountpoint


@dataclass(frozen=True)
class FileInfo:
    file_id: str
    path: str
    size_bytes: int
    suffix: str
    modified_timestamp: float
    volume_id: str
    importance: int = 5
    protected: bool = False
    eligible: bool = True
    estimated_compress_gain_bytes: int = 0
    skip_reason: str | None = None

    @property
    def name(self) -> str:
        # Works for both Windows and POSIX separators.
        return self.path.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]


@dataclass(frozen=True)
class CandidateAction:
    id: str
    file_id: str
    kind: ActionKind
    destination_volume_id: str | None
    source_gain_bytes: int
    destination_use_bytes: int
    estimated_seconds: float
    risk_score: float
    access_penalty: float
    total_cost: float


@dataclass(frozen=True)
class Preferences:
    source_volume_id: str
    goal_bytes: int
    allow_compress: bool
    allow_move: bool
    allowed_destination_volume_ids: tuple[str, ...] = ()
    protected_root_paths: tuple[str, ...] = ()
    priority: str = Priority.BALANCED.value
    destination_safety_fraction: float = 0.05
    allow_delete: bool = False


@dataclass(frozen=True)
class Evaluation:
    feasible: bool
    gain_bytes: int
    goal_shortfall_bytes: int
    capacity_overage_bytes: int
    total_cost: float
    status: str
    reason_codes: tuple[str, ...]
    destination_usage_bytes: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True)
class Problem:
    """Everything an optimizer needs. candidates[i] belongs to files[i];
    candidates[i][0] is always KEEP."""
    files: tuple[FileInfo, ...]
    candidates: tuple[tuple[CandidateAction, ...], ...]
    preferences: Preferences
    capacities: dict  # volume_id -> available bytes after reserve
    disks: tuple[DiskInfo, ...] = ()
    cost_model: dict = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()  # pre-search diagnostics

    @property
    def n_files(self) -> int:
        return len(self.files)


#: Plan representation: tuple of candidate indices, one per file (index into
#: Problem.candidates[i]). Index 0 is KEEP. Exported as dict[file_id, action_id].
Plan = tuple


@dataclass(frozen=True)
class OptimizationResult:
    algorithm: str
    plan: dict  # file_id -> action_id (empty if no feasible plan)
    evaluation: Evaluation | None
    duration_ms: float
    iterations: int
    seed: int | None
    warnings: tuple[str, ...]
    status: str
    reason_codes: tuple[str, ...] = ()
    diagnostics: dict = field(default_factory=dict)

    @property
    def feasible(self) -> bool:
        return self.status == ResultStatus.FEASIBLE.value


@dataclass(frozen=True)
class ScanResult:
    roots: tuple[str, ...]
    files: tuple[FileInfo, ...]
    total_bytes: int
    warnings: tuple[str, ...]
    skipped: tuple[tuple[str, str], ...]  # (path, reason)
    truncated: bool
    source_volume_id: str | None
    reason_codes: tuple[str, ...] = ()
    directories: tuple[str, ...] = ()
