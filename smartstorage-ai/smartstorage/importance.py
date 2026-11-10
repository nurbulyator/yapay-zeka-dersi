"""Folder-based importance rules and hard protection (SPEC_v2 §8).

Importance is NEVER inferred from file age or name. It comes only from
user-configured folder rules; the default is 5 (normal).
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterable

from .models import FileInfo, SkipReason
from .pathutil import depth, is_within

IMPORTANCE_LOW = 1
IMPORTANCE_NORMAL = 5
IMPORTANCE_HIGH = 9
VALID_IMPORTANCE = (IMPORTANCE_LOW, IMPORTANCE_NORMAL, IMPORTANCE_HIGH)

#: Heuristic only — suffix lists never guarantee safety (SPEC §8).
RISKY_SUFFIXES = frozenset({
    ".db", ".sqlite", ".sqlite3", ".mdb", ".accdb", ".pst", ".ost", ".exe",
    ".dll", ".sys", ".msi", ".vhd", ".vhdx", ".vmdk", ".lock", ".ini",
    ".lnk", ".bat", ".cmd", ".ps1",
})


@dataclass(frozen=True)
class ImportanceRule:
    path: str
    importance: int

    def __post_init__(self) -> None:
        if self.importance not in VALID_IMPORTANCE:
            raise ValueError(f"importance must be one of {VALID_IMPORTANCE}")


def resolve_importance(path: str, rules: Iterable[ImportanceRule],
                       protected_roots: Iterable[str]) -> tuple[int, bool]:
    """Return (importance, protected). Explicit protection dominates; among
    importance rules the closest (deepest) matching parent wins."""
    protected = any(is_within(path, root) for root in protected_roots)
    best: ImportanceRule | None = None
    for rule in rules:
        if is_within(path, rule.path):
            if best is None or depth(rule.path) > depth(best.path):
                best = rule
    importance = best.importance if best else IMPORTANCE_NORMAL
    if protected:
        importance = IMPORTANCE_HIGH
    return importance, protected


def apply_rules(files: Iterable[FileInfo], rules: Iterable[ImportanceRule] = (),
                protected_roots: Iterable[str] = ()) -> tuple[FileInfo, ...]:
    """Return new FileInfo objects with importance/protection applied."""
    rules = tuple(rules)
    protected_roots = tuple(protected_roots)
    out = []
    for f in files:
        imp, prot = resolve_importance(f.path, rules, protected_roots)
        if prot:
            out.append(replace(f, importance=imp, protected=True, eligible=False,
                               skip_reason=SkipReason.PROTECTED.value))
        else:
            out.append(replace(f, importance=imp, protected=False))
    return tuple(out)
