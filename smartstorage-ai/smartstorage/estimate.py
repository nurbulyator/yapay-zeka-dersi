"""Bounded, read-only compression gain estimation (SPEC_v2 §9, option A).

Reads at most three chunks (start/middle/end, <= 256 KiB total) per file,
compresses them with zlib level 6 and extrapolates. This is an ESTIMATE:
samples can over- or under-estimate full-file compressibility.
"""
from __future__ import annotations

import math
import os
import zlib
from dataclasses import replace
from typing import Iterable

from .models import KIB, MIB, FileInfo, SkipReason

SAMPLE_BYTES_PER_FILE = 256 * KIB
DEFAULT_TOTAL_BUDGET = 128 * MIB
MIN_FILE_SIZE = 4 * KIB
OVERHEAD_FACTOR = 1.02      # 2 % safety margin on the compressed size
OVERHEAD_BYTES = 4 * KIB    # archive header / metadata allowance

ALREADY_COMPRESSED = frozenset({
    ".zip", ".7z", ".rar", ".gz", ".bz2", ".xz", ".zst", ".cab", ".jpg", ".jpeg",
    ".png", ".gif", ".webp", ".heic", ".mp4", ".mkv", ".avi", ".mov", ".webm",
    ".mp3", ".aac", ".ogg", ".flac", ".m4a", ".pdf", ".docx", ".xlsx", ".pptx",
    ".odt", ".epub", ".apk", ".jar",
})


def credible_threshold(size_bytes: int) -> int:
    """Minimum gain for a COMPRESS candidate: max(1 MiB, 3 % of size)."""
    return max(MIB, math.ceil(size_bytes * 0.03))


def sample_offsets(size: int, budget: int = SAMPLE_BYTES_PER_FILE) -> list[tuple[int, int]]:
    if size <= budget:
        return [(0, size)]
    chunk = budget // 3
    mid = max(0, size // 2 - chunk // 2)
    return [(0, chunk), (mid, chunk), (size - chunk, chunk)]


def estimate_ratio_from_bytes(chunks: Iterable[bytes]) -> float:
    raw = comp = 0
    for c in chunks:
        if not c:
            continue
        raw += len(c)
        comp += len(zlib.compress(c, 6))
    if raw == 0:
        return 1.0
    return comp / raw


def gain_from_ratio(size: int, ratio: float) -> int:
    est_compressed = math.ceil(size * ratio * OVERHEAD_FACTOR) + OVERHEAD_BYTES
    gain = size - est_compressed
    return max(0, min(gain, size - 1))


def estimate_file_gain(path: str, size: int) -> int:
    """Estimated lossless gain in bytes (raises OSError on read problems)."""
    if size < MIN_FILE_SIZE:
        return 0
    chunks = []
    with open(path, "rb") as fh:  # read-only
        for off, length in sample_offsets(size):
            fh.seek(off)
            chunks.append(fh.read(length))
    return gain_from_ratio(size, estimate_ratio_from_bytes(chunks))


def estimate_files(files: Iterable[FileInfo], total_budget: int = DEFAULT_TOTAL_BUDGET,
                   skip_suffixes: frozenset = ALREADY_COMPRESSED
                   ) -> tuple[tuple[FileInfo, ...], tuple[str, ...]]:
    """Return files with ``estimated_compress_gain_bytes`` filled in.

    Only eligible files are sampled (never cloud placeholders, protected or
    risky files). Files that changed since the scan become UNSTABLE_FILE.
    """
    out: list[FileInfo] = []
    warnings: list[str] = []
    used = 0
    budget_hit = False
    errors = 0
    for f in files:
        if not f.eligible or f.suffix in skip_suffixes or f.size_bytes < MIN_FILE_SIZE:
            out.append(f)
            continue
        cost = min(f.size_bytes, SAMPLE_BYTES_PER_FILE)
        if used + cost > total_budget:
            budget_hit = True
            out.append(f)
            continue
        try:
            st = os.stat(f.path, follow_symlinks=False)
            if st.st_size != f.size_bytes or st.st_mtime != f.modified_timestamp:
                out.append(replace(f, eligible=False, skip_reason=SkipReason.UNSTABLE_FILE.value))
                continue
            gain = estimate_file_gain(f.path, f.size_bytes)
            used += cost
            out.append(replace(f, estimated_compress_gain_bytes=gain))
        except OSError:
            errors += 1
            out.append(replace(f, eligible=False, skip_reason=SkipReason.UNREADABLE.value))
    if budget_hit:
        warnings.append("Sıkıştırma örnekleme bütçesi doldu; bazı dosyalar için sıkıştırma tahmini yapılmadı.")
    if errors:
        warnings.append(f"{errors} dosya örneklenirken okunamadı; yalnızca KEEP önerilir.")
    return tuple(out), tuple(warnings)
