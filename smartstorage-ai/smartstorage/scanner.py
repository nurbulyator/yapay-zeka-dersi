"""Read-only traversal of user-selected roots (SPEC_v2 §6).

Never opens files for writing, never follows symlinks/junctions/reparse
points, never leaves the source volume, and only enters user-content areas.
"""
from __future__ import annotations

import hashlib
import os
import stat as stat_mod
import time
from pathlib import Path
from typing import Iterable, Sequence

from .importance import RISKY_SUFFIXES, ImportanceRule, apply_rules
from .models import FileInfo, ReasonCode, ScanResult, SkipReason
from .pathutil import is_volume_root, is_within, norm

#: Project root (folder containing the ``smartstorage`` package).
PROJECT_ROOT = Path(__file__).resolve().parent.parent
#: [v2/C2] The only part of the project that may be scanned.
TEST_DATA_DIR = PROJECT_ROOT / "test_data"

DEFAULT_MAX_FILES = 2000
RECENT_SECONDS = 600  # [v2/C11] 10 minutes

# Windows file attribute flags (stat.FILE_ATTRIBUTE_* exist only on Windows).
FILE_ATTRIBUTE_REPARSE_POINT = 0x400
FILE_ATTRIBUTE_OFFLINE = 0x1000
FILE_ATTRIBUTE_RECALL_ON_OPEN = 0x40000
FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x400000
CLOUD_ATTRS = (FILE_ATTRIBUTE_OFFLINE | FILE_ATTRIBUTE_RECALL_ON_OPEN
               | FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS)

SKIP_DIR_NAMES = {"$recycle.bin", "system volume information", ".git",
                  "__pycache__", "node_modules", ".venv", "venv"}


class ScopeError(ValueError):
    """Raised for a rejected scan root. ``code`` is a ReasonCode value."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _env_paths(*names: str) -> list[str]:
    out = []
    for n in names:
        v = os.environ.get(n)
        if v:
            out.append(v)
    return out


def dangerous_roots() -> list[str]:
    """System areas that are never scanned (default deny)."""
    if os.name == "nt":
        paths = _env_paths("SystemRoot", "windir", "ProgramFiles", "ProgramFiles(x86)",
                           "ProgramW6432", "ProgramData", "APPDATA", "LOCALAPPDATA")
        drive = os.environ.get("SystemDrive", "C:") + "\\"
        paths += [drive + "Windows", drive + "Program Files", drive + "Program Files (x86)",
                  drive + "ProgramData", drive + "$Recycle.Bin",
                  drive + "System Volume Information", drive + "Recovery"]
        return paths
    return ["/bin", "/boot", "/dev", "/etc", "/lib", "/lib32", "/lib64", "/proc",
            "/run", "/sbin", "/sys", "/usr", "/var", "/snap", "/System", "/Library",
            "/Applications", "/private/var"]


def _is_venv(path: str) -> bool:
    return os.path.isfile(os.path.join(path, "pyvenv.cfg"))


def excluded_reason(path: str) -> str | None:
    """Reason why a directory may not be scanned/entered, or None if allowed."""
    if is_volume_root(path):
        return "Bir hacmin kök dizini (ör. C:\\) taranamaz; bir kullanıcı klasörü seçin."
    for d in dangerous_roots():
        if is_within(path, d):
            return f"Sistem/program klasörü korunuyor: {d}"
    base = os.path.basename(norm(path))
    if base in SKIP_DIR_NAMES:
        return f"Özel klasör atlandı: {os.path.basename(path)}"
    if _is_venv(path):
        return "Python sanal ortamı (virtualenv) atlandı."
    if is_within(path, PROJECT_ROOT) and not is_within(path, TEST_DATA_DIR):
        return "Uygulamanın kendi klasörü taranmaz (yalnızca test_data/ hariç)."
    return None


def validate_root(path_str: str) -> Path:
    """Validate a user-supplied root folder. Returns the resolved Path."""
    if not path_str or not str(path_str).strip():
        raise ScopeError(ReasonCode.INVALID_CONFIG.value, "Klasör yolu boş.")
    raw = str(path_str).strip().strip('"')
    p = Path(raw).expanduser()
    if not p.is_absolute():
        raise ScopeError(ReasonCode.INVALID_CONFIG.value,
                         f"Mutlak yol girin (ör. C:\\Users\\...): {raw}")
    try:
        resolved = p.resolve(strict=True)
    except (FileNotFoundError, OSError):
        raise ScopeError(ReasonCode.INVALID_CONFIG.value, f"Klasör bulunamadı: {raw}")
    if not resolved.is_dir():
        raise ScopeError(ReasonCode.INVALID_CONFIG.value, f"Bu bir klasör değil: {raw}")
    if p.is_symlink():
        raise ScopeError(ReasonCode.INVALID_CONFIG.value,
                         f"Sembolik bağlantı/junction kök olarak kabul edilmez: {raw}")
    reason = excluded_reason(str(resolved))
    if reason:
        raise ScopeError(ReasonCode.INVALID_CONFIG.value, reason)
    return resolved


def file_id_for(path: str) -> str:
    return hashlib.sha256(norm(path).encode("utf-8", "surrogatepass")).hexdigest()[:16]


def _attrs(st: os.stat_result) -> int:
    return int(getattr(st, "st_file_attributes", 0) or 0)


def _is_link_like(entry: os.DirEntry, st: os.stat_result) -> bool:
    if entry.is_symlink():
        return True
    is_junction = getattr(entry, "is_junction", None)
    if is_junction is not None and is_junction():
        return True
    return False


def _dedupe_roots(roots: Sequence[Path]) -> list[Path]:
    """Drop roots nested inside other roots (keep outermost), keep order."""
    out: list[Path] = []
    for r in sorted(set(roots), key=lambda x: len(norm(x))):
        if not any(is_within(r, o) for o in out):
            out.append(r)
    return out


def scan(roots: Sequence[str], *, max_files: int = DEFAULT_MAX_FILES,
         protected_roots: Iterable[str] = (),
         importance_rules: Iterable[ImportanceRule] = (),
         now: float | None = None, recent_seconds: float = RECENT_SECONDS,
         risky_suffixes: frozenset = RISKY_SUFFIXES,
         max_seconds: float | None = None) -> ScanResult:
    """Read-only metadata scan. Raises ScopeError for invalid roots."""
    if not roots:
        raise ScopeError(ReasonCode.INVALID_CONFIG.value, "En az bir klasör seçin.")
    resolved = _dedupe_roots([validate_root(r) for r in roots])
    now = time.time() if now is None else now
    t_start = time.perf_counter()

    root_devs = {}
    for r in resolved:
        root_devs[str(r)] = os.stat(r).st_dev
    devs = set(root_devs.values())
    if len(devs) > 1:
        raise ScopeError(ReasonCode.INVALID_CONFIG.value,
                         "Seçilen klasörler farklı hacimlerde. Tek bir kaynak hacim seçin.")
    source_dev = devs.pop()
    source_volume_id = f"dev:{source_dev:x}"

    files: list[FileInfo] = []
    directories = [str(r) for r in resolved]
    skipped: list[tuple[str, str]] = []
    warnings: list[str] = []
    reason_codes: set[str] = set()
    seen: set[str] = set()
    truncated = False

    for root in resolved:
        stack = [str(root)]
        while stack:
            if truncated:
                break
            current = stack.pop()
            try:
                with os.scandir(current) as it:
                    entries = sorted(it, key=lambda e: e.name.lower())
            except (PermissionError, OSError) as exc:
                skipped.append((current, f"Klasör okunamadı: {type(exc).__name__}"))
                reason_codes.add(ReasonCode.SCAN_INCOMPLETE.value)
                continue
            subdirs = []
            for entry in entries:
                if max_seconds is not None and time.perf_counter() - t_start > max_seconds:
                    truncated = True
                    break
                path = entry.path
                try:
                    st = os.stat(path, follow_symlinks=False)
                except OSError as exc:
                    skipped.append((path, f"Bilgi okunamadı: {type(exc).__name__}"))
                    reason_codes.add(ReasonCode.SCAN_INCOMPLETE.value)
                    continue
                if _is_link_like(entry, st):
                    skipped.append((path, "Sembolik bağlantı/junction izlenmedi."))
                    continue
                attrs = _attrs(st)
                if stat_mod.S_ISDIR(st.st_mode):
                    if attrs & FILE_ATTRIBUTE_REPARSE_POINT:
                        skipped.append((path, "Yeniden ayrıştırma noktası (reparse point) izlenmedi."))
                        continue
                    if st.st_dev != source_dev:
                        skipped.append((path, "Başka bir hacme bağlanmış klasör; hacim dışına çıkılmadı."))
                        continue
                    reason = excluded_reason(path)
                    if reason:
                        skipped.append((path, reason))
                        continue
                    directories.append(path)
                    subdirs.append(path)
                    continue
                if not stat_mod.S_ISREG(st.st_mode):
                    skipped.append((path, "Normal dosya değil."))
                    continue
                key = norm(path)
                if key in seen:
                    continue
                if len(files) >= max_files:
                    truncated = True
                    break
                seen.add(key)
                files.append(_make_file(path, st, attrs, source_dev, source_volume_id,
                                        now, recent_seconds, risky_suffixes))
            # reverse so that pop() visits subdirectories in sorted order
            stack.extend(reversed(subdirs))
        if truncated:
            break

    if truncated:
        reason_codes.add(ReasonCode.SCAN_INCOMPLETE.value)
        warnings.append(f"Tarama sınırına ulaşıldı ({max_files} dosya); "
                        "plan yalnızca taranan dosyaları kapsar.")
    if skipped:
        warnings.append(f"{len(skipped)} öğe atlandı (bağlantı, izin veya kapsam dışı).")

    files_t = apply_rules(files, importance_rules, protected_roots)
    if not files_t:
        reason_codes.add(ReasonCode.EMPTY_SCOPE.value)
    return ScanResult(
        roots=tuple(str(r) for r in resolved), files=files_t,
        total_bytes=sum(f.size_bytes for f in files_t), warnings=tuple(warnings),
        skipped=tuple(skipped), truncated=truncated, source_volume_id=source_volume_id,
        reason_codes=tuple(sorted(reason_codes)), directories=tuple(directories),
    )


def _make_file(path: str, st: os.stat_result, attrs: int, source_dev: int,
               source_volume_id: str, now: float, recent_seconds: float,
               risky_suffixes: frozenset) -> FileInfo:
    suffix = os.path.splitext(path)[1].lower()
    skip: str | None = None
    if st.st_dev != source_dev:
        skip = SkipReason.OTHER_VOLUME.value
    elif attrs & CLOUD_ATTRS or attrs & FILE_ATTRIBUTE_REPARSE_POINT:
        skip = SkipReason.CLOUD_PLACEHOLDER.value
    elif getattr(st, "st_nlink", 1) > 1:
        skip = SkipReason.HARDLINK.value
    elif st.st_size == 0:
        skip = SkipReason.ZERO_SIZE.value
    elif suffix in risky_suffixes:
        skip = SkipReason.RISKY_SUFFIX.value
    elif now - st.st_mtime < recent_seconds:
        skip = SkipReason.RECENTLY_MODIFIED.value
    elif not os.access(path, os.R_OK):
        skip = SkipReason.UNREADABLE.value
    return FileInfo(
        file_id=file_id_for(path), path=path, size_bytes=int(st.st_size), suffix=suffix,
        modified_timestamp=float(st.st_mtime),
        volume_id=f"dev:{st.st_dev:x}" if st.st_dev != source_dev else source_volume_id,
        importance=5, protected=False, eligible=skip is None, skip_reason=skip,
    )
