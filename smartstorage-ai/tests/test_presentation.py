import importlib
import os
import sys
from types import SimpleNamespace

from conftest import ROOT
from conftest import disks, fi, prefs
from smartstorage.actions import build_problem
from smartstorage.models import ActionKind, DiskInfo, FileInfo, GIB
from smartstorage.scanner import scan


def test_simplified_ui_import_has_no_side_effects():
    sys.path.insert(0, str(ROOT))
    mod = importlib.import_module("presentation.app")
    assert callable(mod.main)


def test_item_rows_show_folders_files_and_shared_importance(tmp_path):
    root = str(tmp_path)
    nested_file = tmp_path / "Documents" / "notes.txt"
    (tmp_path / "Empty folder").mkdir()
    nested_file.parent.mkdir()
    nested_file.write_text("hello", encoding="utf-8")
    files = (
        FileInfo(
            file_id="sample",
            path=str(nested_file),
            size_bytes=1024,
            suffix=".txt",
            modified_timestamp=0,
            volume_id="test",
        ),
    )

    result = scan([root])
    rows = importlib.import_module("presentation.app").build_item_rows(
        root, files, 7, result.directories
    )

    assert all(row["Importance"] == 7 for row in rows)
    assert {row["Name"] for row in rows if row["Type"] == "Folder"} == {
        "Documents",
        "Empty folder",
        tmp_path.name,
    }
    assert rows[-1]["Name"] == "notes.txt"
    assert rows[-1]["Size"] == "1.0 KiB"


def test_file_tree_nests_files_and_empty_folders(tmp_path):
    root = tmp_path / "root"
    nested = root / "Documents"
    nested.mkdir(parents=True)
    (root / "root.txt").write_text("root", encoding="utf-8")
    (nested / "notes.txt").write_text("notes", encoding="utf-8")
    (root / "Empty").mkdir()
    result = scan([str(root)])

    tree = importlib.import_module("presentation.app").build_file_tree(
        str(root), result.files, result.directories
    )

    assert [file.name for file in tree["files"]] == ["root.txt"]
    documents = next(iter(tree["children"].values()))
    assert os.path.basename(documents["path"]) == "Documents"
    assert [file.name for file in documents["files"]] == ["notes.txt"]
    assert "Empty" in {
        os.path.basename(child["path"]) for child in tree["children"].values()
    }


def test_file_importance_inherits_folder_score_and_supports_overrides(tmp_path):
    module = importlib.import_module("presentation.app")
    folder = str(tmp_path / "Documents")
    nested = str(tmp_path / "Documents" / "Nested")
    file_path = str(tmp_path / "Documents" / "Nested" / "notes.txt")
    folder_overrides = {module._normalized(folder): 8}
    file_overrides = {}

    assert module.effective_folder_importance(nested, str(tmp_path), folder_overrides) == 8
    assert module.effective_file_importance(
        file_path, str(tmp_path), folder_overrides, file_overrides
    ) == 8

    file_overrides[module._normalized(file_path)] = 3
    assert module.effective_file_importance(
        file_path, str(tmp_path), folder_overrides, file_overrides
    ) == 3


def test_folder_score_change_preserves_real_overrides_and_updates_inherited_items(tmp_path):
    module = importlib.import_module("presentation.app")
    root = str(tmp_path)
    folder = str(tmp_path / "Documents")
    nested = str(tmp_path / "Documents" / "Nested")
    inherited_file = str(tmp_path / "Documents" / "inherited.txt")
    overridden_file = str(tmp_path / "Documents" / "custom.txt")
    scan_id = "scan"
    session_state = {
        "folder_importance_overrides": {
            module._normalized(folder): 5,
            module._normalized(nested): 5,
        },
        "file_importance_overrides": {
            module._normalized(inherited_file): 5,
            module._normalized(overridden_file): 3,
        },
        module._widget_key(scan_id, "folder", folder): 7,
        module._widget_key(scan_id, "folder", nested): 5,
        module._widget_key(scan_id, "file", inherited_file): 5,
        module._widget_key(scan_id, "file", overridden_file): 3,
    }

    module._change_folder_importance(
        SimpleNamespace(session_state=session_state),
        scan_id,
        root,
        folder,
        (root, folder, nested),
        (inherited_file, overridden_file),
    )

    assert session_state["folder_importance_overrides"] == {
        module._normalized(folder): 7,
    }
    assert session_state["file_importance_overrides"] == {
        module._normalized(overridden_file): 3,
    }
    assert session_state[module._widget_key(scan_id, "folder", nested)] == 7
    assert session_state[module._widget_key(scan_id, "file", inherited_file)] == 7
    assert session_state[module._widget_key(scan_id, "file", overridden_file)] == 3


def test_move_destination_on_source_drive_uses_test_simulation(monkeypatch, tmp_path):
    module = importlib.import_module("presentation.app")
    destination = tmp_path / "Destination"
    destination.mkdir()
    file_path = tmp_path / "old.txt"
    file_path.write_text("sample", encoding="utf-8")
    os.utime(file_path, (1_700_000_000, 1_700_000_000))
    scan_result = scan([str(tmp_path)])
    source_disk = DiskInfo(
        scan_result.source_volume_id, str(tmp_path), 10 * GIB, 5 * GIB, True, False
    )
    monkeypatch.setattr(module, "discover_disks", lambda: ((source_disk,), ()))
    monkeypatch.setattr(module, "disk_for_path", lambda available_disks, path: source_disk)

    problem = module.create_problem(
        scan_result,
        goal_gib=0.1,
        importance=5,
        allow_archive=False,
        allow_move=True,
        destination_path=str(destination),
        allow_delete=False,
    )

    target_id = problem.preferences.allowed_destination_volume_ids[0]
    target_disk = next(disk for disk in problem.disks if disk.volume_id == target_id)
    assert target_id != scan_result.source_volume_id
    assert target_disk.simulated
    assert target_disk.mountpoint == str(destination.resolve())
    assert any(candidate.kind == ActionKind.MOVE for candidate in problem.candidates[0])


def test_move_uses_validated_destination_drive(monkeypatch, tmp_path):
    module = importlib.import_module("presentation.app")
    source = tmp_path / "Source"
    destination = tmp_path / "Destination"
    source.mkdir()
    destination.mkdir()
    source_file = source / "old.txt"
    source_file.write_text("sample", encoding="utf-8")
    os.utime(source_file, (1_700_000_000, 1_700_000_000))

    scan_result = scan([str(source)])
    source_disk = DiskInfo(
        scan_result.source_volume_id, str(source), 10 * GIB, 5 * GIB, True, False
    )
    destination_disk = DiskInfo(
        "target-volume", str(destination), 10 * GIB, 2 * GIB, True, True
    )
    monkeypatch.setattr(
        module, "discover_disks", lambda: ((source_disk, destination_disk), ())
    )
    monkeypatch.setattr(
        module, "disk_for_path", lambda available_disks, path: destination_disk
    )

    problem = module.create_problem(
        scan_result,
        goal_gib=0.1,
        importance=5,
        allow_archive=False,
        allow_move=True,
        destination_path=str(destination),
        allow_delete=False,
    )

    assert problem.preferences.allowed_destination_volume_ids == ("target-volume",)
    assert any(candidate.kind == ActionKind.MOVE for candidate in problem.candidates[0])


def test_planner_receives_individual_file_importance(monkeypatch, tmp_path):
    module = importlib.import_module("presentation.app")
    root = tmp_path / "Source"
    root.mkdir()
    first = root / "first.txt"
    second = root / "second.txt"
    first.write_text("first", encoding="utf-8")
    second.write_text("second", encoding="utf-8")
    os.utime(first, (1_700_000_000, 1_700_000_000))
    os.utime(second, (1_700_000_000, 1_700_000_000))
    scan_result = scan([str(root)])
    monkeypatch.setattr(module, "discover_disks", lambda: ((), ()))
    scores = {
        module._normalized(str(first)): 2,
        module._normalized(str(second)): 9,
    }

    problem = module.create_problem(
        scan_result,
        goal_gib=0,
        file_importance=scores,
        allow_archive=False,
        allow_move=False,
        destination_path="",
        allow_delete=False,
    )

    assert {file.name: file.importance for file in problem.files} == {
        "first.txt": 2,
        "second.txt": 9,
    }


def test_delete_and_move_recommendations_have_clear_destinations():
    module = importlib.import_module("presentation.app")
    files = [fi("move", 100), fi("delete", 50)]
    problem = build_problem(
        files,
        disks(10),
        prefs(150, compress=False, dests=("sim:D",), allow_delete=True),
    )
    move_file_index = next(index for index, file in enumerate(problem.files)
                           if file.file_id == "move")
    delete_file_index = next(index for index, file in enumerate(problem.files)
                             if file.file_id == "delete")
    move_index = next(
        index for index, candidate in enumerate(problem.candidates[move_file_index])
        if candidate.kind == ActionKind.MOVE
    )
    delete_index = next(
        index for index, candidate in enumerate(problem.candidates[delete_file_index])
        if candidate.kind == ActionKind.DELETE
    )
    result = type("Result", (), {
        "plan": {
            "move": problem.candidates[move_file_index][move_index].id,
            "delete": problem.candidates[delete_file_index][delete_index].id,
        }
    })()

    rows = module.build_plan_rows(problem, result, r"D:\Storage")
    rows_by_file = {row["File"]: row for row in rows}

    assert rows_by_file["move.dat"]["Recommended operation"] == "Move"
    assert rows_by_file["move.dat"]["Destination"] == r"D:\Storage\move.dat"
    assert rows_by_file["delete.dat"]["Recommended operation"] == "Delete"
