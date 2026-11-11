"""Deterministic candidate generation and problem construction (SPEC_v2 §10)."""
from __future__ import annotations

from dataclasses import replace
from typing import Iterable

from .disks import available_capacity, find_disk
from .estimate import credible_threshold
from .models import (KIND_ORDER, ActionKind, CandidateAction, DiskInfo, FileInfo,
                     Preferences, Problem, ReasonCode, SkipReason)
from .scoring import ACCESS, PRESETS, RISK, action_cost, cost_model, estimate_seconds


def _candidate(f: FileInfo, kind: ActionKind, dest: str | None, gain: int,
               dest_use: int, weights: dict) -> CandidateAction:
    secs = estimate_seconds(kind, f.size_bytes)
    risk, access = RISK[kind], ACCESS[kind]
    return CandidateAction(
        id=f"{f.file_id}:{kind.value}:{dest or '-'}", file_id=f.file_id, kind=kind,
        destination_volume_id=dest, source_gain_bytes=gain, destination_use_bytes=dest_use,
        estimated_seconds=secs, risk_score=risk, access_penalty=access,
        total_cost=action_cost(f.importance, kind, secs, risk, access, weights),
    )


def destination_capacities(disks: Iterable[DiskInfo], prefs: Preferences) -> dict[str, int]:
    """Available bytes (after reserve) for each permitted, safe destination."""
    caps: dict[str, int] = {}
    if not prefs.allow_move:
        return caps
    for vid in prefs.allowed_destination_volume_ids:
        d = find_disk(disks, vid)
        if (d is None or vid == prefs.source_volume_id or not d.writable
                or not d.eligible_destination or not d.identity_confident):
            continue
        caps[vid] = available_capacity(d, prefs.destination_safety_fraction)
    return caps


def generate_candidates(f: FileInfo, prefs: Preferences, capacities: dict[str, int],
                        weights: dict) -> tuple[CandidateAction, ...]:
    out = [_candidate(f, ActionKind.KEEP, None, 0, 0, weights)]
    if f.protected or not f.eligible or f.volume_id != prefs.source_volume_id:
        return tuple(out)
    gain = f.estimated_compress_gain_bytes
    if prefs.allow_compress and 0 < gain < f.size_bytes and gain >= credible_threshold(f.size_bytes):
        out.append(_candidate(f, ActionKind.COMPRESS, None, gain, 0, weights))
    if prefs.allow_move:
        for vid in sorted(capacities):
            if vid != prefs.source_volume_id and f.size_bytes <= capacities[vid]:
                out.append(_candidate(f, ActionKind.MOVE, vid, f.size_bytes, f.size_bytes, weights))
    if prefs.allow_delete:
        out.append(_candidate(f, ActionKind.DELETE, None, f.size_bytes, 0, weights))
    out.sort(key=lambda c: (KIND_ORDER[c.kind], c.destination_volume_id or ""))
    return tuple(out)


def build_problem(files: Iterable[FileInfo], disks: Iterable[DiskInfo], prefs: Preferences,
                  warnings: Iterable[str] = (), reason_codes: Iterable[str] = ()) -> Problem:
    disks = tuple(disks)
    warn = list(warnings)
    reasons: list[str] = [r for r in reason_codes if r != ReasonCode.EMPTY_SCOPE.value]
    if prefs.goal_bytes < 0 or prefs.priority not in PRESETS:
        reasons.append(ReasonCode.INVALID_CONFIG.value)
        warn.append("Geçersiz yapılandırma: hedef negatif olamaz ve öncelik geçerli olmalı.")
        prio = prefs.priority if prefs.priority in PRESETS else "balanced"
    else:
        prio = prefs.priority
    model = cost_model(prio)
    weights = model["weights"]

    files_sorted = []
    other_volume = 0
    for f in sorted(files, key=lambda x: x.file_id):
        if f.volume_id != prefs.source_volume_id and f.eligible:
            other_volume += 1
            f = replace(f, eligible=False, skip_reason=SkipReason.OTHER_VOLUME.value)
        files_sorted.append(f)
    if other_volume:
        warn.append(f"{other_volume} dosya kaynak hacimde değil; yalnızca KEEP uygulanır.")

    caps = destination_capacities(disks, prefs)
    if prefs.allow_move and not caps:
        reasons.append(ReasonCode.NO_DESTINATION.value)
        warn.append("Taşımaya izin verildi ancak kaynak hacimden farklı, güvenli ve yazılabilir bir hedef hacim yok.")

    cands = tuple(generate_candidates(f, prefs, caps, weights) for f in files_sorted)
    if not files_sorted:
        reasons.append(ReasonCode.EMPTY_SCOPE.value)
    elif all(f.protected for f in files_sorted):
        reasons.append(ReasonCode.PROTECTED_ONLY.value)
    if files_sorted and all(len(c) == 1 for c in cands):
        reasons.append(ReasonCode.NO_ALLOWED_ACTIONS.value)

    return Problem(files=tuple(files_sorted), candidates=cands, preferences=prefs,
                   capacities=caps, disks=disks, cost_model=model,
                   warnings=tuple(warn), reason_codes=tuple(dict.fromkeys(reasons)))
