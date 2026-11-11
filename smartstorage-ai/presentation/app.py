"""Simplified, read-only storage planner for SmartStorage AI.

Run from the project root with: streamlit run presentation/app.py
"""
from __future__ import annotations

import hashlib
import os
import sys
import uuid
from dataclasses import replace
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from smartstorage.disks import available_capacity, discover_disks, disk_for_path
from smartstorage.models import (ActionKind, FileInfo, GIB, OptimizationResult, Preferences,
                                 Problem, ScanResult)
from smartstorage.pipeline import Comparison, analyze_folders, plan_for_scan, run_all
from smartstorage.scanner import ScopeError, TEST_DATA_DIR

DEMO_DIR = TEST_DATA_DIR / "demo_kullanici"
ALGORITHM_LABELS = {
    "greedy": "Greedy",
    "hill_climbing": "Hill Climbing",
    "simulated_annealing": "Simulated Annealing",
}


def _normalized(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def _format_size(size_bytes: int) -> str:
    value = float(size_bytes)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{size_bytes} B"


def build_file_tree(
    root: str,
    files: tuple[FileInfo, ...],
    directories: tuple[str, ...] = (),
) -> dict:
    root_path = os.path.abspath(root)
    root_key = _normalized(root_path)
    root_node = {"path": root_path, "children": {}, "files": []}
    nodes = {root_key: root_node}

    def ensure_folder(path: str) -> dict | None:
        path = os.path.abspath(path)
        key = _normalized(path)
        if key in nodes:
            return nodes[key]
        try:
            if os.path.commonpath((root_key, key)) != root_key:
                return None
        except ValueError:
            return None
        parent_path = os.path.dirname(path)
        if _normalized(parent_path) == key:
            return None
        parent = ensure_folder(parent_path)
        if parent is None:
            return None
        node = {"path": path, "children": {}, "files": []}
        parent["children"][key] = node
        nodes[key] = node
        return node

    for directory in directories:
        ensure_folder(directory)
    for file in files:
        parent = ensure_folder(os.path.dirname(file.path))
        if parent is not None:
            parent["files"].append(file)

    def sort_node(node: dict) -> None:
        node["files"].sort(key=lambda file: file.name.casefold())
        node["children"] = dict(sorted(
            node["children"].items(),
            key=lambda item: os.path.basename(item[1]["path"]).casefold(),
        ))
        for child in node["children"].values():
            sort_node(child)

    sort_node(root_node)
    return root_node


def effective_folder_importance(path: str, root: str, overrides: dict[str, int]) -> int:
    root_path = os.path.abspath(root)
    current = os.path.abspath(path)
    root_key = _normalized(root_path)
    try:
        if os.path.commonpath((root_key, _normalized(current))) != root_key:
            return 5
    except ValueError:
        return 5

    while True:
        key = _normalized(current)
        if key in overrides:
            return overrides[key]
        if key == root_key:
            return 5
        parent = os.path.dirname(current)
        if parent == current:
            return 5
        current = parent


def effective_file_importance(file_path: str, root: str, folder_overrides: dict[str, int],
                              file_overrides: dict[str, int]) -> int:
    return file_overrides.get(
        _normalized(file_path),
        effective_folder_importance(os.path.dirname(file_path), root, folder_overrides),
    )


def _widget_key(scan_id: str, item_type: str, path: str) -> str:
    path_hash = hashlib.sha256(_normalized(path).encode("utf-8")).hexdigest()[:16]
    return f"{scan_id}-{item_type}-importance-{path_hash}"


def _sync_inherited_widget_values(
    st,
    scan_id: str,
    root: str,
    folder_paths: tuple[str, ...],
    file_paths: tuple[str, ...],
) -> None:
    folder_overrides = st.session_state["folder_importance_overrides"]
    file_overrides = st.session_state["file_importance_overrides"]
    for path in folder_paths:
        if _normalized(path) not in folder_overrides:
            key = _widget_key(scan_id, "folder", path)
            st.session_state[key] = effective_folder_importance(path, root, folder_overrides)
    for path in file_paths:
        if _normalized(path) not in file_overrides:
            key = _widget_key(scan_id, "file", path)
            st.session_state[key] = effective_file_importance(
                path, root, folder_overrides, file_overrides
            )


def _is_within(path: str, parent: str) -> bool:
    try:
        return os.path.commonpath((_normalized(path), _normalized(parent))) == _normalized(parent)
    except ValueError:
        return False


def _clear_redundant_descendant_overrides(
    root: str,
    path: str,
    folder_paths: tuple[str, ...],
    file_paths: tuple[str, ...],
    folder_overrides: dict[str, int],
    file_overrides: dict[str, int],
) -> None:
    for folder_path in folder_paths:
        folder_key = _normalized(folder_path)
        if folder_key == _normalized(path) or not _is_within(folder_path, path):
            continue
        if folder_key in folder_overrides:
            inherited = effective_folder_importance(
                os.path.dirname(folder_path), root, folder_overrides
            )
            if folder_overrides[folder_key] == inherited:
                del folder_overrides[folder_key]
    for file_path in file_paths:
        file_key = _normalized(file_path)
        if not _is_within(file_path, path) or file_key not in file_overrides:
            continue
        inherited = effective_folder_importance(
            os.path.dirname(file_path), root, folder_overrides
        )
        if file_overrides[file_key] == inherited:
            del file_overrides[file_key]


def _change_folder_importance(
    st,
    scan_id: str,
    root: str,
    path: str,
    folder_paths: tuple[str, ...],
    file_paths: tuple[str, ...],
) -> None:
    key = _widget_key(scan_id, "folder", path)
    folder_overrides = st.session_state["folder_importance_overrides"]
    file_overrides = st.session_state["file_importance_overrides"]
    _clear_redundant_descendant_overrides(
        root, path, folder_paths, file_paths, folder_overrides, file_overrides
    )
    st.session_state["folder_importance_overrides"][_normalized(path)] = int(
        st.session_state[key]
    )
    _sync_inherited_widget_values(st, scan_id, root, folder_paths, file_paths)


def _reset_folder_importance(
    st,
    scan_id: str,
    root: str,
    path: str,
    folder_paths: tuple[str, ...],
    file_paths: tuple[str, ...],
) -> None:
    folder_overrides = st.session_state["folder_importance_overrides"]
    _clear_redundant_descendant_overrides(
        root,
        path,
        folder_paths,
        file_paths,
        folder_overrides,
        st.session_state["file_importance_overrides"],
    )
    folder_overrides.pop(_normalized(path), None)
    _sync_inherited_widget_values(st, scan_id, root, folder_paths, file_paths)


def _change_file_importance(st, path: str, scan_id: str) -> None:
    key = _widget_key(scan_id, "file", path)
    st.session_state["file_importance_overrides"][_normalized(path)] = int(
        st.session_state[key]
    )


def _reset_file_importance(st, path: str, root: str, scan_id: str) -> None:
    st.session_state["file_importance_overrides"].pop(_normalized(path), None)
    key = _widget_key(scan_id, "file", path)
    st.session_state[key] = effective_folder_importance(
        os.path.dirname(path),
        root,
        st.session_state["folder_importance_overrides"],
    )


def build_item_rows(
    root: str,
    files: tuple[FileInfo, ...],
    importance: int,
    directories: tuple[str, ...] = (),
) -> list[dict]:
    root_path = os.path.abspath(root)
    root_normalized = _normalized(root_path)
    folders = {root_path, *(os.path.abspath(path) for path in directories)}

    for file in files:
        folder = os.path.dirname(file.path)
        while True:
            normalized = _normalized(folder)
            try:
                inside_root = os.path.commonpath((root_normalized, normalized)) == root_normalized
            except ValueError:
                inside_root = False
            if not inside_root:
                break
            folders.add(folder)
            if normalized == root_normalized:
                break
            parent = os.path.dirname(folder)
            if parent == folder:
                break
            folder = parent

    rows = []
    for folder in sorted(folders, key=str.casefold):
        rows.append({
            "Name": os.path.basename(folder) or folder,
            "Type": "Folder",
            "Path": folder,
            "Size": "",
            "Importance": importance,
        })

    for file in sorted(files, key=lambda item: item.path.casefold()):
        rows.append({
            "Name": file.name,
            "Type": "File",
            "Path": file.path,
            "Size": _format_size(file.size_bytes),
            "Importance": importance,
        })
    return rows


def _root_matches(root: str, result: ScanResult) -> bool:
    return bool(result.roots) and _normalized(root) == _normalized(result.roots[0])


def _tree_paths(tree: dict) -> tuple[tuple[str, ...], tuple[str, ...]]:
    folders: list[str] = []
    files: list[str] = []

    def visit(node: dict) -> None:
        folders.append(node["path"])
        files.extend(file.path for file in node["files"])
        for child in node["children"].values():
            visit(child)

    visit(tree)
    return tuple(folders), tuple(files)


def _render_folder_contents(
    st,
    node: dict,
    root: str,
    scan_id: str,
    folder_paths: tuple[str, ...],
    file_paths: tuple[str, ...],
) -> None:
    path = node["path"]
    folder_overrides = st.session_state["folder_importance_overrides"]
    file_overrides = st.session_state["file_importance_overrides"]
    folder_key = _widget_key(scan_id, "folder", path)
    if folder_key not in st.session_state:
        st.session_state[folder_key] = effective_folder_importance(
            path, root, folder_overrides
        )

    display_name = os.path.basename(path) or path
    heading, reset = st.columns((4, 1))
    heading.markdown(f"**📁 {display_name}**")
    heading.caption("Folder score is inherited by items below unless changed.")
    parent_path = os.path.dirname(path)
    inherited_folder_score = (
        effective_folder_importance(parent_path, root, folder_overrides)
        if _normalized(path) != _normalized(root) else 5
    )
    if (folder_overrides.get(_normalized(path)) is not None
            and folder_overrides[_normalized(path)] != inherited_folder_score):
        reset.button(
            "Inherit",
            key=f"{folder_key}-inherit",
            help="Use the parent folder's importance score.",
            on_click=_reset_folder_importance,
            args=(st, scan_id, root, path, folder_paths, file_paths),
        )
    st.slider(
        f"Importance for folder: {display_name}",
        min_value=1,
        max_value=9,
        key=folder_key,
        on_change=_change_folder_importance,
        args=(st, scan_id, root, path, folder_paths, file_paths),
    )

    if node["files"]:
        with st.expander(f"Files in this folder ({len(node['files'])})"):
            for file in node["files"]:
                file_path = file.path
                file_key = _widget_key(scan_id, "file", file_path)
                inherited = effective_folder_importance(
                    path, root, folder_overrides
                )
                if file_key not in st.session_state:
                    st.session_state[file_key] = effective_file_importance(
                        file_path, root, folder_overrides, file_overrides
                    )

                file_col, score_col, reset_col = st.columns((4, 3, 1))
                file_col.markdown(f"**📄 {file.name}**")
                file_col.caption(
                    f"{_format_size(file.size_bytes)} · {file_path}"
                )
                score_col.slider(
                    f"Importance for file: {file.name}",
                    min_value=1,
                    max_value=9,
                    key=file_key,
                    on_change=_change_file_importance,
                    args=(st, file_path, scan_id),
                )
                if (file_overrides.get(_normalized(file_path)) is not None
                        and file_overrides[_normalized(file_path)] != inherited):
                    reset_col.button(
                        "Inherit",
                        key=f"{file_key}-inherit",
                        help=f"Use the containing folder's score ({inherited}/9).",
                        on_click=_reset_file_importance,
                        args=(st, file_path, root, scan_id),
                    )

    for child in node["children"].values():
        child_path = child["path"]
        child_name = os.path.basename(child_path) or child_path
        with st.expander(f"📁 {child_name}"):
            _render_folder_contents(
                st, child, root, scan_id, folder_paths, file_paths
            )


def render_folder_tree(st, tree: dict, root: str, scan_id: str) -> None:
    folder_paths, file_paths = _tree_paths(tree)
    _render_folder_contents(st, tree, root, scan_id, folder_paths, file_paths)


def create_problem(
    scan_result: ScanResult,
    *,
    goal_gib: float,
    importance: int = 5,
    file_importance: dict[str, int] | None = None,
    allow_archive: bool,
    allow_move: bool,
    destination_path: str,
    allow_delete: bool,
) -> Problem:
    if scan_result.source_volume_id is None:
        raise ValueError("The source drive could not be identified.")

    disks, disk_warnings = discover_disks()
    destination_volume_ids: tuple[str, ...] = ()
    if allow_move:
        if not destination_path.strip():
            raise ValueError("Enter an existing folder for moved files.")
        try:
            destination = Path(destination_path.strip().strip('"')).expanduser().resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ValueError("The destination folder does not exist or cannot be accessed.") from exc
        if not destination.is_dir():
            raise ValueError("The destination path must be an existing folder.")
        destination_disk = disk_for_path(disks, str(destination))
        if destination_disk is None:
            raise ValueError("Could not identify the drive containing the destination folder.")
        if destination_disk.volume_id == scan_result.source_volume_id:
            if not destination_disk.writable or not destination_disk.identity_confident:
                raise ValueError("The destination folder's drive is not writable or identifiable.")
            test_volume_id = "test-target:" + hashlib.sha256(
                _normalized(str(destination)).encode("utf-8")
            ).hexdigest()[:16]
            destination_disk = replace(
                destination_disk,
                volume_id=test_volume_id,
                mountpoint=str(destination),
                eligible_destination=True,
                simulated=True,
                label=f"Test destination: {destination}",
            )
            disks = tuple(disks) + (destination_disk,)
        elif (not destination_disk.writable or not destination_disk.eligible_destination
                or not destination_disk.identity_confident):
            raise ValueError("The destination drive is not a safe, writable destination.")
        if available_capacity(destination_disk) <= 0:
            raise ValueError("The destination drive has no available space after its safety reserve.")
        destination_volume_ids = (destination_disk.volume_id,)

    files = tuple(
        replace(
            file,
            importance=(file_importance or {}).get(_normalized(file.path), importance),
        )
        for file in scan_result.files
    )
    adjusted_scan = replace(
        scan_result,
        files=files,
        warnings=scan_result.warnings + tuple(disk_warnings),
    )
    preferences = Preferences(
        source_volume_id=scan_result.source_volume_id,
        goal_bytes=int(round(goal_gib * GIB)),
        allow_compress=allow_archive,
        allow_move=allow_move,
        allowed_destination_volume_ids=destination_volume_ids,
        allow_delete=allow_delete,
    )
    return plan_for_scan(adjusted_scan, disks, preferences)


def build_plan_rows(
    problem: Problem,
    result: OptimizationResult,
    destination_path: str = "",
) -> list[dict]:
    rows = []
    for file, candidates in zip(problem.files, problem.candidates):
        action_id = result.plan.get(file.file_id)
        candidate = next((item for item in candidates if item.id == action_id), None)
        if candidate is None:
            raise ValueError(f"No recommended action was found for {file.path}.")
        if candidate.kind == ActionKind.KEEP:
            action = "Keep"
            target = ""
        elif candidate.kind == ActionKind.COMPRESS:
            action = "Archive (estimated compression)"
            target = ""
        elif candidate.kind == ActionKind.MOVE:
            action = "Move"
            target = os.path.join(destination_path, file.name) if destination_path else ""
        else:
            action = "Delete"
            target = ""
        rows.append({
            "File": file.name,
            "Path": file.path,
            "Size": _format_size(file.size_bytes),
            "Importance": f"{file.importance}/9",
            "Recommended operation": action,
            "Destination": target,
            "Estimated source space freed": _format_size(candidate.source_gain_bytes),
        })
    return rows


def main() -> None:
    import pandas as pd
    import streamlit as st

    st.set_page_config(page_title="SmartStorage · Cleanup planner", layout="wide")
    st.title("Free up space")
    st.caption("Scan a folder, choose the space goal and allowed operations, then compare plans.")
    st.info("Preview only: creating a plan never moves, archives, or deletes files.")

    default_root = str(DEMO_DIR) if DEMO_DIR.is_dir() else ""
    root = st.text_input(
        "Folder to scan",
        value=st.session_state.get("folder_path", default_root),
        placeholder=r"C:\Users\you\Documents",
        key="folder_path",
        help="Choose the folder whose files you want to review.",
    )
    if st.button("Scan folder", type="primary"):
        try:
            with st.spinner("Reading file details and estimating archive savings…"):
                result = analyze_folders([root])
            st.session_state["folder_scan_result"] = result
            st.session_state["folder_scan_id"] = uuid.uuid4().hex
            st.session_state["folder_importance_overrides"] = {}
            st.session_state["file_importance_overrides"] = {}
            st.session_state.pop("cleanup_plan", None)
        except ScopeError as exc:
            st.session_state.pop("folder_scan_result", None)
            st.session_state.pop("cleanup_plan", None)
            st.error(exc.message)

    result = st.session_state.get("folder_scan_result")
    if result is None:
        st.caption("Enter a folder path and scan it to get started.")
        return
    if not _root_matches(root, result):
        st.info("The folder path changed. Scan this folder to refresh the file list.")
        return

    st.session_state.setdefault("folder_importance_overrides", {})
    st.session_state.setdefault("file_importance_overrides", {})
    st.session_state.setdefault("folder_scan_id", uuid.uuid4().hex)
    tree = build_file_tree(result.roots[0], result.files, result.directories)
    folders, _ = _tree_paths(tree)
    file_col, folder_col, size_col = st.columns(3)
    file_col.metric("Files", len(result.files))
    folder_col.metric("Folders", len(folders))
    size_col.metric("Total file size", _format_size(result.total_bytes))

    st.subheader("Set importance")
    st.caption(
        "Each file inherits its folder's score. Change a folder to update its contents, "
        "or change one file on its own. Use Inherit to remove an override."
    )
    render_folder_tree(st, tree, result.roots[0], st.session_state["folder_scan_id"])
    if result.truncated:
        st.warning("The file limit was reached; the plan will include only scanned files.")
    if result.warnings:
        with st.expander("Scan notes"):
            for warning in result.warnings:
                st.write(warning)

    st.subheader("Create a plan")
    goal_gib = st.number_input(
        "How much space do you want to free? (GiB)",
        min_value=0.0,
        max_value=1_000_000.0,
        value=1.0,
        step=0.1,
        key="goal_gib",
    )
    st.write("Choose which operations the planner may recommend. **Keep** is always available.")
    archive_col, move_col, delete_col = st.columns(3)
    allow_archive = archive_col.checkbox(
        "Archive / compress",
        value=True,
        help="Uses a small read-only sample to estimate compression savings. No archive is created.",
        key="allow_archive",
    )
    allow_move = move_col.checkbox(
        "Move to a folder",
        help="For testing, select any existing folder, including one on the source drive.",
        key="allow_move",
    )
    allow_delete = delete_col.checkbox(
        "Delete",
        help="Deletion may be recommended, but files are never deleted by this app.",
        key="allow_delete",
    )
    destination_path = ""
    if allow_move:
        destination_path = st.text_input(
            "Destination folder",
            placeholder=r"C:\Storage",
            key="destination_path",
        )
        st.caption(
            "Test mode: a folder on the source drive is modeled as a separate destination. "
            "A real move within the same drive does not free disk space. No files are moved."
        )

    signature = (
        st.session_state.get("folder_scan_id"),
        goal_gib,
        tuple(sorted(
            (file.file_id, effective_file_importance(
                file.path,
                result.roots[0],
                st.session_state["folder_importance_overrides"],
                st.session_state["file_importance_overrides"],
            ))
            for file in result.files
        )),
        allow_archive,
        allow_move,
        destination_path.strip(),
        allow_delete,
    )
    if st.button("Create plans with search algorithms", type="primary"):
        try:
            with st.spinner("Comparing Greedy, Hill Climbing, and Simulated Annealing…"):
                problem = create_problem(
                    result,
                    goal_gib=goal_gib,
                    file_importance={
                        _normalized(file.path): effective_file_importance(
                            file.path,
                            result.roots[0],
                            st.session_state["folder_importance_overrides"],
                            st.session_state["file_importance_overrides"],
                        )
                        for file in result.files
                    },
                    allow_archive=allow_archive,
                    allow_move=allow_move,
                    destination_path=destination_path,
                    allow_delete=allow_delete,
                )
                comparison = run_all(problem)
            st.session_state["cleanup_plan"] = {
                "signature": signature,
                "comparison": comparison,
                "destination_path": destination_path,
            }
        except ValueError as exc:
            st.session_state.pop("cleanup_plan", None)
            st.error(str(exc))

    plan_state = st.session_state.get("cleanup_plan")
    if plan_state is None:
        return
    if plan_state["signature"] != signature:
        st.info("Plan settings changed. Create a new plan to use the updated choices.")
        return

    comparison: Comparison = plan_state["comparison"]
    st.subheader("Compare plans")
    result_cols = st.columns(len(comparison.results))
    for column, algorithm_result in zip(result_cols, comparison.results):
        column.metric(
            ALGORITHM_LABELS.get(algorithm_result.algorithm, algorithm_result.algorithm),
            "Plan found" if algorithm_result.feasible else "No plan found",
            f"{algorithm_result.duration_ms:.0f} ms",
        )

    selected_label = st.radio(
        "Plan to view",
        [ALGORITHM_LABELS[item.algorithm] for item in comparison.results],
        horizontal=True,
    )
    selected = next(
        item for item in comparison.results
        if ALGORITHM_LABELS[item.algorithm] == selected_label
    )
    if not selected.feasible or selected.evaluation is None:
        st.warning(
            "This search did not find a plan that reaches the requested space goal. "
            "Try allowing more operations or choosing a smaller goal."
        )
        st.caption(f"Search status: {selected.status}")
        return

    metric_gain, metric_goal, metric_changes = st.columns(3)
    metric_gain.metric("Estimated space freed", _format_size(selected.evaluation.gain_bytes))
    metric_goal.metric("Space goal", _format_size(comparison.problem.preferences.goal_bytes))
    changed = sum(
        action_id.split(":")[1] != ActionKind.KEEP.value
        for action_id in selected.plan.values()
    )
    metric_changes.metric("Files with a suggested change", changed)
    st.caption("Archive savings are estimates. Review the recommendations before taking any action.")

    plan_rows = build_plan_rows(
        comparison.problem, selected, plan_state["destination_path"]
    )
    st.dataframe(pd.DataFrame(plan_rows), width="stretch", hide_index=True)


if __name__ == "__main__":
    main()
