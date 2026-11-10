import os
from unittest import mock

import pytest

from conftest import snapshot
from smartstorage import scanner
from smartstorage.models import ReasonCode, SkipReason
from smartstorage.scanner import ScopeError, scan, validate_root


def test_empty_root(tmp_path):
    (tmp_path / "empty").mkdir()
    res = scan([str(tmp_path / "empty")])
    assert res.files == ()
    assert ReasonCode.EMPTY_SCOPE.value in res.reason_codes


def test_nested_dirs_and_turkish_names(tree):
    root = tree({"a/b/c/çalışma_notları_ğüşİÖ.txt": b"x" * 5000, "a/üst.txt": b"y" * 10})
    res = scan([str(root)])
    names = sorted(f.name for f in res.files)
    assert names == ["çalışma_notları_ğüşİÖ.txt", "üst.txt"]
    assert res.total_bytes == 5010


def test_nested_roots_are_deduplicated(tree):
    root = tree({"a/b/f.txt": b"1" * 100})
    res = scan([str(root), str(root / "a")])
    assert len(res.files) == 1
    assert len(res.roots) == 1


def test_deterministic_inventory(tree):
    root = tree({f"d{i}/f{j}.txt": b"z" * (i + j + 1) for i in range(3) for j in range(4)})
    a, b = scan([str(root)]), scan([str(root)])
    assert [f.file_id for f in a.files] == [f.file_id for f in b.files]


def test_symlink_not_followed(tree, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_bytes(b"s" * 100)
    root = tree({"real.txt": b"r" * 100})
    try:
        os.symlink(outside, root / "link_dir", target_is_directory=True)
        os.symlink(outside / "secret.txt", root / "link_file.txt")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported")
    res = scan([str(root)])
    assert [f.name for f in res.files] == ["real.txt"]
    assert any("bağlantı" in reason for _, reason in res.skipped)


def test_permission_error_is_reported_not_raised(tree):
    root = tree({"ok.txt": b"o" * 10, "locked/x.txt": b"x" * 10})
    real_scandir = os.scandir

    def fake(path):
        if str(path).endswith("locked"):
            raise PermissionError("denied")
        return real_scandir(path)

    with mock.patch.object(scanner.os, "scandir", side_effect=fake):
        res = scan([str(root)])
    assert [f.name for f in res.files] == ["ok.txt"]
    assert ReasonCode.SCAN_INCOMPLETE.value in res.reason_codes


def test_scan_does_not_modify_files(tree):
    root = tree({"a.txt": b"a" * 50_000, "b/c.log": b"line\n" * 10_000})
    before = snapshot(root)
    from smartstorage.pipeline import analyze_folders
    analyze_folders([str(root)])
    assert snapshot(root) == before


def test_rejects_missing_file_and_relative(tmp_path):
    with pytest.raises(ScopeError):
        validate_root(str(tmp_path / "nope"))
    f = tmp_path / "file.txt"
    f.write_text("x")
    with pytest.raises(ScopeError):
        validate_root(str(f))
    with pytest.raises(ScopeError):
        validate_root("relative/path")
    with pytest.raises(ScopeError):
        validate_root("")


def test_rejects_volume_root_and_project_but_allows_test_data(tmp_path):
    with pytest.raises(ScopeError):
        validate_root(os.path.abspath(os.sep))
    with pytest.raises(ScopeError):
        validate_root(str(scanner.PROJECT_ROOT))
    with pytest.raises(ScopeError):
        validate_root(str(scanner.PROJECT_ROOT / "smartstorage"))
    td = scanner.TEST_DATA_DIR / "_pytest_tmp"
    td.mkdir(parents=True, exist_ok=True)
    try:
        assert validate_root(str(td)) == td.resolve()
    finally:
        td.rmdir()


def test_commonpath_not_prefix(tmp_path):
    from smartstorage.pathutil import is_within
    assert is_within(tmp_path / "Data" / "x", tmp_path / "Data")
    assert not is_within(tmp_path / "Database" / "x", tmp_path / "Data")


def test_hardlink_recent_zero_and_risky_are_keep_only(tree):
    root = tree({"h.txt": b"h" * 9000, "zero.txt": b"", "prog.exe": b"e" * 9000,
                 "new.txt": b"n" * 9000, "normal.txt": b"q" * 9000})
    try:
        os.link(root / "h.txt", root / "h2.txt")
    except (OSError, NotImplementedError):
        pytest.skip("hard links not supported")
    os.utime(root / "new.txt", None)  # now = recently modified
    res = scan([str(root)])
    by = {f.name: f for f in res.files}
    assert by["h.txt"].skip_reason == SkipReason.HARDLINK.value
    assert by["zero.txt"].skip_reason == SkipReason.ZERO_SIZE.value
    assert by["prog.exe"].skip_reason == SkipReason.RISKY_SUFFIX.value
    assert by["new.txt"].skip_reason == SkipReason.RECENTLY_MODIFIED.value
    assert by["normal.txt"].eligible and by["normal.txt"].skip_reason is None


def test_cloud_placeholder_is_never_sampled(tree, monkeypatch):
    root = tree({"cloud.txt": b"c" * 200_000})


    real = scanner._make_file

    def patched(path, st, attrs, *a, **k):
        return real(path, st, scanner.FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS, *a, **k)

    monkeypatch.setattr(scanner, "_make_file", patched)
    res = scan([str(root)])
    f = res.files[0]
    assert f.skip_reason == SkipReason.CLOUD_PLACEHOLDER.value and not f.eligible
    from smartstorage import estimate
    with mock.patch.object(estimate, "estimate_file_gain", side_effect=AssertionError("read!")):
        files, _ = estimate.estimate_files(res.files)
    assert files[0].estimated_compress_gain_bytes == 0


def test_truncation_is_signalled(tree):
    root = tree({f"f{i:03d}.txt": b"x" for i in range(30)})
    res = scan([str(root)], max_files=10)
    assert len(res.files) == 10 and res.truncated
    assert ReasonCode.SCAN_INCOMPLETE.value in res.reason_codes


def test_protected_and_importance_rules(tree):
    from smartstorage.importance import ImportanceRule
    root = tree({"Önemli/a.txt": b"a" * 10, "Loglar/b.log": b"b" * 10, "c.txt": b"c" * 10})
    res = scan([str(root)], protected_roots=[str(root / "Önemli")],
               importance_rules=[ImportanceRule(str(root / "Loglar"), 1)])
    by = {f.name: f for f in res.files}
    assert by["a.txt"].protected and not by["a.txt"].eligible
    assert by["b.log"].importance == 1
    assert by["c.txt"].importance == 5
