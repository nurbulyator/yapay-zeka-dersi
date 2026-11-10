import os
import random

from smartstorage.estimate import (MIN_FILE_SIZE, credible_threshold, estimate_file_gain,
                                   estimate_files, gain_from_ratio, sample_offsets)
from smartstorage.models import MIB, SkipReason
from smartstorage.scanner import scan

from conftest import OLD


def _write(p, data):
    p.write_bytes(data)
    os.utime(p, (OLD, OLD))


def test_compressible_text_has_gain_random_does_not(tmp_path):
    text = tmp_path / "a.log"
    _write(text, b"INFO request ok user=42 duration=13ms\n" * 100_000)
    rnd = tmp_path / "b.bin"
    _write(rnd, random.Random(1).randbytes(3 * MIB))
    g_text = estimate_file_gain(str(text), text.stat().st_size)
    g_rnd = estimate_file_gain(str(rnd), rnd.stat().st_size)
    assert g_text > credible_threshold(text.stat().st_size)
    assert g_rnd == 0


def test_bounds_and_small_files(tmp_path):
    assert gain_from_ratio(1000, 0.0) < 1000
    assert gain_from_ratio(1000, 2.0) == 0
    small = tmp_path / "s.txt"
    _write(small, b"a" * (MIN_FILE_SIZE - 1))
    assert estimate_file_gain(str(small), small.stat().st_size) == 0
    offs = sample_offsets(10 * MIB)
    assert sum(n for _, n in offs) <= 256 * 1024 and len(offs) == 3


def test_already_compressed_suffix_skipped(tmp_path):
    z = tmp_path / "x.zip"
    _write(z, b"a" * (2 * MIB))
    res = scan([str(tmp_path)])
    files, _ = estimate_files(res.files)
    assert files[0].estimated_compress_gain_bytes == 0


def test_unstable_file_detected(tmp_path):
    f = tmp_path / "u.txt"
    _write(f, b"a" * (2 * MIB))
    res = scan([str(tmp_path)])
    _write(f, b"a" * (3 * MIB))  # changes size after scan
    files, _ = estimate_files(res.files)
    assert files[0].skip_reason == SkipReason.UNSTABLE_FILE.value and not files[0].eligible


def test_read_error_does_not_crash(tmp_path):
    f = tmp_path / "gone.txt"
    _write(f, b"a" * (2 * MIB))
    res = scan([str(tmp_path)])
    f.unlink()
    files, warnings = estimate_files(res.files)
    assert not files[0].eligible
