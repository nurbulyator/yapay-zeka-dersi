# SMARTSTORAGE AI — IMPLEMENTATION MASTER SPECIFICATION (v2)

> **Version 2.** This document supersedes `SPEC_v1_original.md`. All v1 requirements remain in force unless a passage marked **[v2]** changes them. The changelog below lists every change with its rationale; the body integrates the changes in place.

## v2 CHANGELOG — WHAT CHANGED AND WHY

| # | Area | Change | Why |
|---|------|--------|-----|
| C1 | UI / demo | New **synthetic scenario mode** in the UI with simulated volumes (C:/D:/E:) and known capacities, alongside real-folder mode. | Most student laptops have a single volume, and removable targets are disallowed by default. Without it MOVE and the capacity constraint could never be shown in a live demo. |
| C2 | Scanner scope | The project's own `test_data/` directory is an explicit exception to the "app's own repository" deny rule. Fixture output can also be written anywhere user-content is allowed. | In v1 the fixture lived in `test_data/` inside the repository, which the scanner was required to deny, so the demo folder could not be scanned. |
| C3 | Goals / fixture scale | The goal input accepts MiB granularity (`step=0.01 GiB`, MiB shown). The real-folder fixture is about 100–200 MiB with MiB-scale goals. GiB-scale goals belong to synthetic scenarios. | Generating several GiB of junk files on a laptop is impractical, and the 1 MiB COMPRESS threshold needs files of a realistic size. |
| C4 | SA energy | Goal shortfall is normalised by the **goal** instead of by GiB, and `alpha` is calibrated automatically from the instance (see §11). | With MiB-scale goals, `alpha * shortfall / GiB` was negligible, so SA drifted to the zero-cost all-KEEP plan. |
| C5 | Security | `.streamlit/config.toml` binds the server to `localhost` and disables usage-statistics telemetry. | Streamlit listens on all network interfaces by default, so anyone on the same Wi-Fi could have driven the scanner on the user's machine. Telemetry also contradicts "no internet at runtime". |
| C6 | Cloud placeholders | Files with `FILE_ATTRIBUTE_OFFLINE`, `RECALL_ON_OPEN` or `RECALL_ON_DATA_ACCESS` (OneDrive Files On-Demand and similar) are never content-sampled and are KEEP-only. | On Windows 11 "Documents" is often OneDrive-backed. Reading bytes from a cloud-only file **downloads it**, and its logical size does not occupy local disk. |
| C7 | Hard links | Files with `st_nlink > 1` are KEEP-only. | Moving or compressing one link of a hard-linked file frees no space while another link exists. |
| C8 | Volume identity | Primary method: `os.stat(path).st_dev`, which is the volume serial number on Windows. Mountpoints sharing an `st_dev` are merged into one capacity bucket. The ctypes `GetVolumeNameForVolumeMountPointW` route is optional. | `st_dev` is portable, needs no ctypes and identifies a file's volume and a mountpoint's volume with the same call. |
| C9 | Size semantics | README and reports state that freed space is estimated from the logical size. Allocated size can differ (cluster slack, NTFS-compressed or sparse files). | Honest reporting. |
| C10 | Cost coefficients | Concrete preset weights, impacts, throughputs, risks and access penalties are fixed in §10 and recorded in every report. | v1 left `w_time`, `w_risk`, `w_access` and `access_penalty` unspecified. |
| C11 | Stability | "Very recently changed" means modified less than **10 minutes** before the scan. Such files are KEEP-only. | v1 named the rule without a threshold. |
| C12 | Status codes | Unified: `Evaluation.status` ∈ {FEASIBLE, INFEASIBLE, INVALID} describes one plan. `OptimizationResult.status` ∈ {FEASIBLE, PROVEN_INFEASIBLE, NO_FEASIBLE_FOUND, INVALID_CONFIG} describes a search outcome. | v1 used different, overlapping status sets in §5 and §16, yet required distinguishing "proven impossible" from "not found". |
| C13 | Importance scale | Importance is displayed as `1/9`, `5/9`, `9/9`, matching the {1, 5, 9} scale. | The v1 explanation example said "önem 1/10". |
| C14 | Third algorithm | **Hill Climbing** is added: the same neighbourhood and energy as SA, with temperature 0 (only non-worsening moves accepted). | It is an ablation that isolates the contribution of the temperature schedule. It is the classic academic comparison and makes "why SA?" answerable with data. |
| C15 | Problem class | README and slides explain that the problem generalises the (multiple-choice, multi-constraint) knapsack problem, so it is NP-hard. A capacity-aware upper bound (§11) strengthens infeasibility proofs. | This justifies heuristic search and anticipates the question "why not solve it exactly?". |
| C16 | Greedy pruning | After reaching the goal, greedy runs a **prune pass** that reverts redundant actions to KEEP (most expensive first) while the goal still holds. | Pure ratio-greedy often overshoots with a superfluous last action. A stronger baseline makes the SA comparison fair. |
| C17 | Greedy traps | The benchmark includes adversarial "greedy trap" scenarios plus exhaustive optima on tiny instances, and reports optimality gaps. | On easy data SA often ties greedy. Gaps to the true optimum are the honest way to show where each method stands. |
| C18 | Agent framing | README and slides contain a short answer to "where is the agent?" (PEAS, the perceive–decide–act loop). | This is an anticipated examiner question. |


> **Purpose:** Give this entire document to a coding AI as the authoritative engineering specification. Implement a fully runnable repository from scratch, with tests, sample data, a local web UI, benchmark and README. **Do not train or download any AI/ML model.** Core artificial intelligence is an agent using search/optimization: Greedy baseline and Simulated Annealing.
>
> **Language:** User interface, README, explanations and output messages in Turkish. Code identifiers in English. This specification is in English. **Target:** Windows 11 + Python 3.11/3.12. **Time-box:** 14-day university-level MVP. **Execution default:** read-only/dry-run. **Priority:** Correctness, safety and an actually working application over aspirational features.

## 0. INSTRUCTIONS TO THE CODING AGENT

You are the lead Python developer, AI-agent engineer, security-conscious filesystem programmer and test engineer. Produce a complete, standalone project. Follow all specifications below. Do not substitute a chatbot, transformer, LLM, classifier, embedding model, a model training workflow, or external/cloud AI APIs for the required planner. Do not just describe the project; implement its source files, run tests, report failures and fix them. If not all work fits in one execution: build a working minimum first, then iterate. Do not falsely claim tests passed or files were created if unverified.

**Order of authority:** Safety rules > correctness and feasibility > required MVP behavior > UX > optional improvements. Where a detail is underspecified, select the least risky viable option, document the choice in README and tests; do not turn a software feature request into unrestricted filesystem modification.

**Explicit non-goals:** No model training, no background Windows service, no natural-language command parsing, no cloud sync, no automatic deletion of user data, no arbitrary user-written executable action plugins, no Windows registry changes, no system-wide file cleanup, no synthetic “actual freed space” reporting.

## 1. PRODUCT VISION AND DEFINITIONS

**Product:** SmartStorage AI — Adaptive Local Storage Optimization Agent.

**One-line user story:** “I select a folder on my Windows computer and a source volume; I choose the amount of extra source-volume free space I want, allowed action types and protected folders; the system shows a feasible, low-disruption, explainable plan of KEEP / COMPRESS / MOVE decisions, without silently changing files.”

**Core distinction:** A *candidate action* is an action on **one file**; a *plan* maps **every eligible file** to exactly **one** candidate action. For 1000 scanned files, a plan has 1000 choices, generally many KEEP. Algorithmic comparison operates on plans.

**Goal:** Minimize total weighted disruption cost **subject to** meeting source volume additional free-space target, respecting permissions, protecting critical files, and satisfying capacity constraints on each target volume. If impossible, report `INFEASIBLE` with reasoning instead of fabricating success.

**Source volume:** The disk volume whose additional free bytes we target. **Scope roots:** Explicit user-selected existing directories on that source volume. **Destination volume:** A distinct writable local volume. Multiple mount points / drive letters for one actual volume must not be treated as different capacity buckets; uncertainty should disable MOVE rather than overclaim a gain.

**Unit:** All internal capacity values are integer bytes. UI displays GiB, using 1 GiB = 1024^3 bytes. Labels should say GiB rather than GB where precision matters.

## 2. USER EXPERIENCE / ACCEPTANCE WALKTHROUGH

1. User runs `streamlit run app.py` locally.
2. Top panel shows app title, “Yerel / Önizleme modu — Dosyalar değiştirilmez”.
3. **[v2/C1]** User picks a mode: **Gerçek klasör** (real folder, the steps below) or **Sentetik senaryo** (synthetic files and simulated volumes with known capacities, no filesystem access). Both modes run identical algorithms.
3a. User specifies existing folder path(s) with text input; use `Path.resolve(strict=True)` and validate. Streamlit in browser cannot reliably open arbitrary native folder picker; prefer text path input with validation and a convenience example. Do not imply remote browser path maps to their machine.
4. App enumerates eligible volumes and displays usage. If volume identity is uncertain, show warning; allow analysis but restrict MOVE.
5. User selects target freed capacity in GiB using `st.number_input` (slider optional; max based on data). **[v2/C3]** Step 0.01 GiB, and the MiB equivalent is shown next to the input. Target is **additional free space**, not target total free space; label must make this clear.
6. User toggles `Sıkıştırmaya izin ver`, `Başka hacme taşımaya izin ver`; chooses destination volumes if present; selects `Güvenlik / Dengeli / Hız` priority and protected subdirectories. Important setting can be applied to selected folders (low/normal/high) with optional per-file override later.
7. User clicks **Tara**. App summarizes file count, total bytes, filtered files, warnings.
8. User clicks **Plan oluştur**. Greedy and Simulated Annealing execute against identical candidates and preferences. App returns feasibility, estimated gain, total cost, action counts, proposed actions, estimated destination consumed capacity, warnings, deterministic explanations, and a comparison table.
9. User can download CSV and JSON plan reports without modifying files.
10. Changing constraints invalidates old results; no “Apply” button on real user directories.

## 3. TECHNOLOGIES / OFFLINE RUNTIME

- Language: Python 3.11+.
- UI: Streamlit (local app).
- Disk discovery: `psutil`.
- Data/report: standard `dataclasses`, `pathlib`, `json`, `csv`; `pandas` optional for UI tables.
- Safe compression **estimation**: `zlib` on bounded byte samples; no archive creation in MVP. `zipfile` optional only for sandbox test demonstration.
- Algorithms: pure Python `random.Random(seed)`, `math.exp`, no SciPy dependency.
- Tests: `pytest`; benchmark: standard time `perf_counter`.
- No internet at runtime; installation of third-party packages may use `pip` at setup.
- **[v2/C5]** Ship `.streamlit/config.toml` with `server.address = "localhost"`, `server.headless = true` and `browser.gatherUsageStats = false`. Never expose the scanner to the network.
- `matplotlib` is optional and used only by `scripts/benchmark.py` for plots. The benchmark must still produce CSV output without it.
- Do not elevate privileges. Any inaccessible files are skipped with warnings.

Exact `requirements.txt` can use compatible version ranges, e.g. `streamlit>=1.32,<2`, `psutil>=5.9,<8`, `pandas>=2,<3`, `pytest>=8,<10`. Pin known working versions if environment allows, but do not invent compatibility claims. Include `python --version` and `pip install -r requirements.txt` in README.

## 4. MANDATORY REPOSITORY TREE

```text
smartstorage-ai/
  app.py
  README.md
  requirements.txt
  .gitignore
  .streamlit/config.toml   # [v2/C5] localhost only, no telemetry
  docs/                    # SPEC_v1_original.md, SPEC_v2.md, source documents
  smartstorage/
    __init__.py
    models.py          # immutable dataclasses, enums, typing
    scanner.py         # read-only selected roots traversal
    disks.py           # psutil volume discovery / identity / mapping
    estimate.py        # compression gain estimation (bounded I/O)
    importance.py      # folder rules, hard protection
    actions.py         # candidate generation + validation
    scoring.py         # objective, constraints, plan evaluation
    greedy.py          # deterministic baseline
    annealing.py       # seeded simulated annealing + hill climbing (T=0 ablation) [v2/C14]
    exact.py           # [v2] exhaustive oracle for tiny instances
    pathutil.py        # [v2] normalized path containment helpers (commonpath-based)
    explain.py         # explainable Turkish descriptions
    serialize.py       # CSV / JSON-safe plan output
    sample_data.py     # fully synthetic filesystem test fixtures or scenario objects
  scripts/
    make_fixture.py
    benchmark.py
  tests/
    test_scanner.py
    test_disks.py
    test_estimate.py
    test_actions.py
    test_scoring.py
    test_greedy.py
    test_annealing.py
    test_serialization.py
    test_end_to_end.py
    test_importance.py   # [v2]
    test_app_smoke.py    # [v2] import-only smoke test of app.py
  test_data/             # generated, ignored by git
  results/               # generated benchmark outputs
```

Must include `if __name__ == '__main__'` guards where scripts are executable. No circular imports. Make all core algorithms separately testable without invoking Streamlit.

## 5. DATA CONTRACTS (TYPE DESIGN)

Implement dataclasses / enums; names may be refactored coherently but fields/semantics required.

```python
class ActionKind(str, Enum):
    KEEP = "KEEP"
    COMPRESS = "COMPRESS"
    MOVE = "MOVE"

@dataclass(frozen=True)
class DiskInfo:
    volume_id: str              # canonical, stable within current scan
    mountpoint: str
    total_bytes: int
    free_bytes: int
    writable: bool
    eligible_destination: bool

@dataclass(frozen=True)
class FileInfo:
    file_id: str                # stable key e.g. sha256(normalized absolute path)
    path: str
    size_bytes: int
    suffix: str
    modified_timestamp: float
    volume_id: str
    importance: int            # {1, 5, 9}; user folder rules, 5 default
    protected: bool
    eligible: bool
    estimated_compress_gain_bytes: int = 0

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
    allowed_destination_volume_ids: tuple[str, ...]
    protected_root_paths: tuple[str, ...]
    priority: str             # safe / balanced / fast
    destination_safety_fraction: float = 0.05

@dataclass(frozen=True)
class Evaluation:
    feasible: bool
    gain_bytes: int
    goal_shortfall_bytes: int
    capacity_overage_bytes: int
    total_cost: float
    status: str               # FEASIBLE / INFEASIBLE / INVALID   (one plan)  [v2/C12]
    reason_codes: tuple[str, ...]
```

**[v2/C12] Status semantics.** `Evaluation.status` describes a single plan: `INVALID` means a malformed assignment (wrong file, a missing choice, a forbidden action), `INFEASIBLE` means a valid assignment that misses the goal or exceeds a capacity, and `FEASIBLE` means everything holds. `OptimizationResult.status` describes a search outcome:

- `FEASIBLE`: a feasible plan was found and returned.
- `PROVEN_INFEASIBLE`: an upper bound (§11) proves that no plan can reach the goal.
- `NO_FEASIBLE_FOUND`: the search found nothing, which is not proof of impossibility.
- `INVALID_CONFIG`: the input itself is invalid.

**[v2]** `FileInfo` gains `skip_reason: str | None` (why the file is KEEP-only, e.g. `PROTECTED`, `RISKY_SUFFIX`, `HARDLINK`, `CLOUD_PLACEHOLDER`, `RECENTLY_MODIFIED`, `UNREADABLE`, `ZERO_SIZE`, `OTHER_VOLUME`, `UNSTABLE_FILE`). `DiskInfo` gains `removable: bool`, `identity_confident: bool`, `simulated: bool` and `aliases: tuple[str, ...]` (other mountpoints of the same volume).

`Plan` may use immutable tuple/list indexed by file or a `dict[file_id, action_id]`; standardize representation. Return `OptimizationResult(algorithm, plan, evaluation, duration_ms, iterations, seed, warnings)`.

All scoring code must validate that each chosen action belongs to exactly the corresponding file, that all files have a choice, and that each candidate is allowed. Avoid relying solely on UI checks.

## 6. FILESYSTEM SCANNING RULES

- Operate only under explicit permitted roots. Reject non-existent paths and regular files where folder required.
- Normalize paths with `Path.resolve()`; compare via `os.path.commonpath`, not naive string prefix (`C:\Data` must not include `C:\Database`). Windows path casing needs normalization.
- Default deny dangerous scopes: volume root `C:\`, Windows directory, Program Files, Program Files (x86), ProgramData, app's own repository, virtualenv, recycle bin, system volume information. Provide `excluded_reason` and skip. Allow only user-content areas in prototype.
- **[v2/C2]** Exception: `<project>/test_data/` (and its subdirectories) may be scanned even though it lies inside the app's repository. When a user root *contains* the repository, the repository subtree is skipped during traversal and reported.
- **[v2/C6]** Cloud placeholders: if `st_file_attributes` has `FILE_ATTRIBUTE_OFFLINE (0x1000)`, `FILE_ATTRIBUTE_RECALL_ON_OPEN (0x40000)` or `FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS (0x400000)`, never read the content; the file is KEEP-only with `skip_reason=CLOUD_PLACEHOLDER`.
- **[v2/C7]** Hard links: `st_nlink > 1` means KEEP-only with `skip_reason=HARDLINK`.
- **[v2/C11]** Files modified less than 10 minutes before the scan are KEEP-only (`RECENTLY_MODIFIED`). Zero-byte files are KEEP-only (`ZERO_SIZE`).
- Do not follow directory symlinks/junctions/reparse points. Avoid cross-volume recursion or unintended root expansion.
- Determine source volume; if a file belongs to another volume encountered by mount-point traversal, skip or report it.
- Skip symbolic links, unreadable files, very recently changed/locked files when uncertain, large binaries with unknown semantics, and configured risky suffixes for any mutable action; still permit KEEP where safe.
- Treat paths, modified timestamps and sizes as *snapshots*, which may become stale; present plan as estimated and require revalidation in any future executor.
- No need to read all file bytes to build inventory; compression sampling is bounded (e.g. <=256KiB in total per eligible file with a max total budget), and handles exceptions without crashing.
- Limit scan to a configurable max file count (default 2000 for UI responsiveness) and max scan time if implemented. Clearly signal truncation; optimization only applies to scanned files.
- Ensure all file operations are read-only in MVP.

## 7. VOLUME / CAPACITY SEMANTICS

**Critical invariant:** `source_gain_bytes` from MOVE only when source and destination are distinct real volumes. Drive letters and partitions are not physical disks; problem is **source volume freed capacity**. A move within the same volume contributes zero gain. In MVP, such moves should not be produced.

`psutil.disk_partitions(all=False)` provides candidate mountpoints, but cannot always guarantee volume identity in every environment. **[v2/C8]** The primary identity is `os.stat(mountpoint).st_dev` (the volume serial number on Windows). A file's volume is `os.stat(file, follow_symlinks=False).st_dev`, so files and volumes are compared with the same function. Mountpoints with equal `st_dev` are merged into one capacity bucket (`aliases`). If `stat` fails, `identity_confident=False` and the volume is never a MOVE destination. `GetVolumeNameForVolumeMountPointW` via `ctypes` is optional. Do not guess volume identity. Removable and optical volumes are not destinations by default.

Destination capacity constraint: for each target volume `d`, sum of destination bytes from chosen MOVE actions <= `free_bytes(d) - reserve_bytes(d)`, where `reserve_bytes = max(256 MiB, floor(free_bytes * safety_fraction))` unless this would make available capacity negative (clamp to 0). **Compute the sum across the whole plan**, not one action at a time only.

Do not add target volume free space into the source disk freed space. Do not promise global data reduction for MOVE. For compression on the source: estimated gain is hypothetical only upon safe replacement of source by its validated compressed form, which MVP DOES NOT execute. Expose this as “potansiyel/tahmini” only.

## 8. IMPORTANCE / HARD PROTECTION

Do not infer personal importance from age or filename alone. Implement rules:

- Protected path: `protected=True`, only KEEP allowed.
- User directory rule `importance=9` high; `5` normal; `1` low. Closest matching parent directory wins; explicit protected rule dominates everything.
- No user configuration: importance=5.
- Optional initial hard exclusions: `.db`, `.sqlite`, `.mdb`, `.pst`, `.ost`, `.exe`, `.dll`, `.sys`, `.vhdx`, `.vmdk`, `.lock`, program configuration outside sandbox. Important: suffix lists are heuristics and do not guarantee file safety; conservative mode always.

The cost calculation uses importance **among allowed actions**; protection is a strict feasibility constraint, not a high score.

## 9. COMPRESSION ESTIMATION

**MVP option A (recommended):** Read up to three bounded chunks (start/middle/end) up to total 256KiB per file; compress chunks with `zlib.compress(level=6)`; derive ratio estimate with overhead margin. Skip too-small files (<4KiB) and files already compressed or unsuitable (`.zip`, `.7z`, `.rar`, `.jpg`, `.jpeg`, `.png`, `.mp4`, `.mkv`, `.mp3`, `.pdf` conservatively) unless fixture tests explicitly override. Be honest that sample-based ratios can be inaccurate and sample chunks can over/underestimate full-file compression.

**MVP option B:** For deterministic benchmarking use explicit synthetic per-file compression gains directly in generated scenario objects. Same algorithms run on real scanned metadata and on synthetic data; do not conflate simulated true gains with actual physical disk changes.

Clamp: `0 <= gain_bytes < file.size_bytes`. If gain estimated <max(1 MiB, 3% original) do not generate COMPRESS. Estimated time may be based on bytes / configured throughput assumption; it is a nominal cost proxy, not guaranteed runtime. For equal file size and importance, compression and moving may have different costs and benefits.

## 10. ACTION GENERATION (DETERMINISTIC)

For each FileInfo (stable file ID order):

1. ALWAYS emit KEEP: gain=0, cost=0, dest=None.
2. If protected or not eligible => stop.
3. If allow_compress and positive credible compress gain => emit COMPRESS with source_gain=gain, dest=None, compression time estimate and access/risk penalty.
4. If allow_move: for each permitted destination volume d different from source, writable and confidently identified => emit MOVE(source_gain=file.size_bytes, destination_use=file.size_bytes, target=d), provided the individual file can fit in the *nominal* available capacity; the final plan evaluator still checks aggregate capacity.
5. Compute all costs in `scoring.py` from fixed transparent coefficients. Choose one action per file, never combine COMPRESS+MOVE on same file in MVP. More complex actions are future modules, not covertly added.
6. Sort candidates consistently by `(file_id, kind, destination_volume_id)` for deterministic runs.

**[v2/C10] Fixed default coefficients (heuristic, not probabilities; recorded in every report):**

| Constant | Value |
|---|---|
| impact KEEP / COMPRESS / MOVE | 0 / 0.6 / 0.4 |
| risk_score COMPRESS / MOVE | 0.3 / 0.2 |
| access_penalty COMPRESS / MOVE | 1.0 (file must be extracted to use) / 0.5 (location changes) |
| nominal throughput COMPRESS / MOVE | 50 MiB/s / 100 MiB/s, plus 0.05 s overhead per file |
| time unit | minutes (`estimated_seconds / 60`) |

| Preset | w_impact | w_time | w_risk | w_access |
|---|---|---|---|---|
| safe (Güvenlik) | 1.0 | 0.5 | 4.0 | 1.5 |
| balanced (Dengeli) | 1.0 | 1.0 | 2.0 | 1.0 |
| fast (Hız) | 1.0 | 2.0 | 1.0 | 0.5 |

`total_cost = w_impact * importance * impact + w_time * minutes + w_risk * risk_score + w_access * access_penalty`.

v1 text, retained for context: **Suggested default risk/impact constants (heuristic, not probabilities):** KEEP impact 0, COMPRESS impact 0.6, MOVE impact 0.4; risk_score based on deterministic flags of operation and target (MOVE to removable target can be disallowed). `base_cost = importance * impact + w_time * time_unit + w_risk * risk_score + w_access * access_penalty`; weights determined by selected safe/balanced/fast preset and recorded in reports. Use documented normalizations so huge byte sizes don't dwarf other terms.

## 11. OBJECTIVE FUNCTION / OPTIMIZATION CORRECTNESS

For plan P, let:

- `gain(P) = sum(source_gain_bytes(chosen[file]))`.
- `used(P, d) = sum(destination_use_bytes of MOVE actions targeting d)`.
- `cost(P) = sum(total_cost(chosen[file]))`.
- `goal = preferences.goal_bytes`.

**Hard feasibility:** Correct action assignment; no protected/forbidden action; every destination capacity constraint; `gain(P) >= goal`.

**Canonical evaluation:** Validity of assignment and destination capacity checked separately. `feasible(P)` only if hard requirements and goal are satisfied. On feasible plans, lower cost is better. For annealing over infeasible intermediate plans, define finite energy

`energy(P) = cost(P) + alpha * max(0, goal - gain(P))/goal + beta * sum_d max(0, used(P,d) - capacity(d))/GiB`  **[v2/C4]**

**[v2/C4] Calibration:** `alpha = penalty_factor * r_max * goal`, where `r_max = max(total_cost / source_gain_bytes)` over all non-KEEP candidates and `penalty_factor = 2`. Then the penalty for any shortfall `s` is at least `2 * r_max * s`, which exceeds the cost of any set of actions that would close it. Dropping a useful action is therefore never energy-improving. Capacity violations are rejected outright, never merely penalised, so the `beta` term is always 0 in practice. Never return an infeasible plan as successful.

**[v2/C15] Capacity-aware upper bound.** With `cg_i` the credible compress gain of file *i* (0 if none) and `M` the set of files with at least one MOVE candidate:
`UB = sum_i max_gain_i`, and
`UB_cap = sum_i cg_i + min(sum_d capacity(d), sum_{i in M} (size_i - cg_i))`.
If `min(UB, UB_cap) < goal`, the instance is `PROVEN_INFEASIBLE` (reason `INSUFFICIENT_THEORETICAL_GAIN`, plus `DESTINATION_CAPACITY` if only `UB_cap` fails). The bound proves impossibility; it never proves feasibility.

**[v2/C15] Complexity note.** Choosing one action per file to cover a gain target at minimum cost under several destination capacities generalises the 0/1 knapsack problem, so the problem is NP-hard. This justifies heuristic search and limits brute force to tiny instances. Better design: never propose a candidate that violates a hard permission/capacity constraint; permit goal shortfall during search with penalty. Keep a separate `best_feasible` tracker. Do not compare raw feasible cost with infeasible penalized energy as if both were business costs.

**Special cases:** `goal_bytes==0` => all KEEP is optimal with cost 0. If max attainable gain even ignoring capacity is below target => early infeasible explanation. Empty folder => infeasible for positive goal. All protected => infeasible. One-volume source with compression disallowed => infeasible for positive goal.

## 12. GREEDY BASELINE — REQUIRED ALGORITHM

Implement deterministic greedy that:

- Starts with all KEEP.
- Creates all non-KEEP candidates sorted descending by `gain / (cost+epsilon)`; secondary preference greater gain; tertiary lexical `(file_id, action_id)`.
- Attempts each action if: file is currently KEEP, action is allowed, planned aggregate target capacity remains satisfied, and target shortfall >0.
- Records selected action, updates gain and destination usage, stops at target.
- If it cannot reach the target, result is `NO_FEASIBLE_FOUND`, or `PROVEN_INFEASIBLE` if the §11 bound proves impossibility; never a misleading success. **[v2/C12]**
- **[v2/C16] Prune pass:** after the goal is reached, visit the chosen non-KEEP actions in descending cost order and revert each one to KEEP if the goal still holds without it. Record `pruned` in the result's diagnostics.
- Return an `OptimizationResult` for all cases.

This greedy ratio is a *baseline*, not a proof of optimality. For tiny instances run brute-force enumeration in tests to show non-optimal examples.

## 13. SIMULATED ANNEALING — REQUIRED ALGORITHM

Implement a real Simulated Annealing (SA) solver (not random search renamed SA). Required behavior:

```
function simulated_annealing(files, action_sets, prefs, disks, seed, iterations):
    rng = Random(seed)
    current = greedy_plan if valid assignment else all_KEEP
    best_feasible = current if current satisfies ALL constraints else None
    temperature = initial_temperature
    repeat iterations times:
        candidate = copy(current)
        select 1 (sometimes 2) distinct file(s)
        select another allowed action for each selected file
        if candidate violates permissions / destination capacity: continue
        delta = energy(candidate) - energy(current)
        if delta <= 0 OR rng.random() < exp(-delta / max(temperature, tiny)):
            current = candidate
        if current feasible and (best_feasible absent or cost(current) < cost(best_feasible)):
            best_feasible = deep_copy(current)
        temperature = max(min_temperature, temperature * cooling_rate)
    return best_feasible if any, else INFEASIBLE result
```

**Quality enhancement mandatory:** A single-action neighbor from a fully feasible greedy plan can repeatedly break the goal; include `two_action` swap and/or an intelligent repair strategy so SA can find equivalent-gain lower-cost alternatives. Track accepted transitions and best-feasible cost history for diagnostic plots.

Use `seed` from UI. Reasonable defaults `iterations=3000`, `T0=5`, `cooling=0.995`, `minT=1e-4`, adjustable via an Advanced panel.

**[v2/C14] Hill Climbing ablation.** Implement `hill_climbing(problem, seed, iterations)`. It uses exactly the SA neighbourhood, start state, capacity rejection and energy, but accepts only `delta <= 0` (temperature 0). It is reported as a third algorithm everywhere SA is reported (UI comparison table, benchmark).

**[v2] Neighbourhood mix (defaults):** a single-file change with probability 0.4, a swap (revert one changed file to KEEP and activate one KEEP file) with probability 0.5, and a random two-file change with probability 0.1. **Goal-aware repair (mandatory):** in a single-file move, when the goal is not met, activate a KEEP file with probability 0.5; when the goal is met, revise an already-changed file (switch it to another action or revert it to KEEP) with probability 0.5. Rationale, measured during development: without the repair move, SA with T0=5 drifted on 500–1000-file instances. It activated hundreds of superfluous files at high temperature and ended *worse* than Hill Climbing. With the repair move, SA matches Hill Climbing on large instances and stays far better on greedy-trap instances. Do not promise to outperform greedy in every run. Use per-iteration incremental evaluation or modest file limit for interactive runtime; avoid expensive deep copy of thousands of file records each step. Core implementation may optimize ~2000 file choices in memory.

When greedy returns infeasible but feasible combinations exist, SA should still be able to search. If needed, use a non-greedy/random valid starting plan or repair mechanism; do not declare mathematical infeasibility solely because greedy failed. The final UI must distinguish `No feasible plan found by search` from `Proven impossible` unless upper bound establishes impossibility.

## 14. EXPLANATION ENGINE

Pure deterministic templates in Turkish; NO LANGUAGE MODEL. Per action examples:

- COMPRESS: “`logs.txt`: Kayıpsız sıkıştırma önerildi. Tahmini kaynak alan kazancı 380 MiB; önem 1/10; işlem maliyeti 2,3. Kazanç tahminidir; dosya henüz değiştirilmedi.”
- MOVE: “`video.mp4`: C: kaynak hacminden D: hedef hacmine taşıma önerildi. Kaynakta tahmini 1,8 GiB yer açılır; D: üzerinde 1,8 GiB kapasite gerekir.”
- KEEP: “`family_photos`: Koruma kuralı nedeniyle olduğu yerde bırakıldı.”
- **[v2/C13]** Importance is displayed as `önem 1/9`, `5/9`, `9/9`, not `/10`.
- No solution: “İzinli işlemler ve mevcut hedef hacim kapasiteleriyle 10 GiB hedefe ulaşılabilecek plan bulunamadı.”

Always label simulated values “tahmini”, “potansiyel”, “önerilen”. Never say physical capacity has already changed in dry-run.

## 15. STREAMLIT UI SPECIFICATION

Use `st.set_page_config(page_title="SmartStorage AI", layout="wide")`.

Suggested sections:

1. **Başlık & güvenlik:** local, read-only, scope warning.
2. **Tarama ayarları:** absolute source folder path; optional 2nd root. Validate path. “Tara” button.
3. **Diskler:** tabular mounted volume, total/free GiB; warn about volume identity uncertainty.
4. **Tercihler:** target additional GiB, allow compression, allow move, destination multiselect, protected subpath entry/list, priority selectbox.
5. **Analiz:** file number, total size, supported candidates, warning count; optional expandable file metadata table.
6. **Algoritmalar:** button “Plan oluştur”, optional seed/iterations, Greedy vs SA side-by-side.
7. **Öneriler:** plan status, source gain estimated, cost, risk, number of affected files, destination capacity impact, action table.
8. **Dışa aktar:** CSV + JSON with timestamps and parameters; file path privacy warning.

Store scan/results with Streamlit session state keyed by configuration hashes; invalidate stale optimization if inputs change. Catch exceptions and show useful user-facing errors without raw stack traces by default. Core functionality must be importable / tested without Streamlit.

## 16. CSV / JSON REPORT CONTRACT

`plan.csv` columns:

```
file_id,path,size_bytes,importance,action,target_volume_id,
source_gain_estimate_bytes,destination_use_bytes,
action_cost,risk_score,reason
```

`report.json` includes:

```
{
  "project": "SmartStorage AI",
  "mode": "DRY_RUN",
  "timestamp": "ISO-8601 local with timezone",
  "source_volume_id": "...",
  "goal_bytes": 0,
  "preferences": {},
  "algorithm": "greedy | simulated_annealing",
  "status": "FEASIBLE | PROVEN_INFEASIBLE | NO_FEASIBLE_FOUND | INVALID_CONFIG",
  "estimated_gain_bytes": 0,
  "total_cost": 0.0,
  "destination_usage_bytes": {},
  "action_counts": {},
  "runtime_ms": 0.0,
  "seed": null,
  "warnings": [],
  "reason_codes": [],
  "cost_model": {},
  "actions": []
}
```

**[v2/C10]** `cost_model` records the preset weights and constants that produced the costs.

Make sure CSV cannot execute formula injection if opened in spreadsheet software: sanitize formula-leading untrusted file path/name fields, or use safe quoting/prefixing. Treat output file paths as potentially sensitive; do not upload externally.

## 17. SYNTHETIC DATA / BENCHMARKS

**Real scan:** metadata-only; model current state. **Synthetic scenario:** precisely known expected savings, costs, capacities. Use both.

Generate deterministic scenarios with 20, 100, 500 and optionally 1000 files; 1, 2 and 4 volumes; allowed compression ratios; protected subtrees; 0/1/3 GiB goals (choose sizes so some feasible and some infeasible). Use fixed seeds. Include cases where compression disallowed, move disallowed, one target disk full, and multiple target volumes with different free capacity.

Benchmark:

- Greedy one run per scenario; SA 10 seeds per scenario; **[v2/C14]** Hill Climbing with the same 10 seeds.
- **[v2/C17]** Include at least one adversarial "greedy trap" scenario family and a tiny exhaustive family. Report `gap_to_optimum = cost / optimum - 1` where the optimum is known.
- Record `scenario_id, algorithm, seed, n_files, n_volumes, goal_bytes, feasible, estimated_gain_bytes, total_cost, n_changed_files, runtime_ms`.
- Compute SA mean/std cost on *feasible runs only*, and feasible rate; do not mislead by dropping failures without stating denominator.
- Create at least two plots: cost comparison and runtime vs n_files (matplotlib optional; Streamlit built-in bar/line adequate).
- For tiny toy sets (<=8 files, 2-3 actions each), exhaustively enumerate assignments to calculate true optimum and compare algorithm gaps. Do not brute-force 1000-file problems.

## 18. REQUIRED TEST MATRIX

At minimum these tests must exist and pass:

**Scanner:** empty root, nested roots, special Turkish characters in filename, permission error behavior (mock if needed), skipped symlink/junction, no content modifications.

**Disks:** one accessible volume, no known distinct target, duplicate mountpoint identity, full target, volume identification uncertainty handling.

**Actions:** every file has KEEP; protected only KEEP; compress disabled means no COMPRESS; move disabled means no MOVE; move never within same volume; zero compression benefit suppresses COMPRESS; distinct target volumes generate distinct valid actions.

**Scoring:** exactly one action per file; source gain correct; aggregate capacity constraint; high-importance cost greater for same action given equal circumstances; KEEP cost zero; goal=0 all KEEP best; hard constraint cannot be overridden with favorable cost.

**Optimizers:** Greedy deterministic; returns feasible only if target actually reached; SA deterministic given fixed seed; SA never returns an invalid/infeasible plan as success; SA improved or equal to greedy *in selected known synthetic test case* (not universal claim); exhaustive tiny scenario validates optimum gap.

**Integration:** fixture creation -> scan -> generate actions -> greedy -> annealing -> serialize, no unintended filesystem changes. `pytest -q` runs all tests.

**[v2]** **Scanner extras:** hard-link file is KEEP-only; cloud-placeholder attribute is never sampled (mocked); recently-modified file is KEEP-only; `test_data/` exception works while the rest of the repository is denied.

**[v2]** **Optimizers extras:** Hill Climbing never accepts a worsening move; the capacity-aware upper bound yields `PROVEN_INFEASIBLE` in a capacity-limited case; greedy prune never breaks feasibility.

**UI smoke:** Launch command documented and import of app does not trigger destructive actions. If browser UI automation unavailable, manually document test steps; don't falsely claim automated UI test.

## 19. FAILURE CODES / EDGE CASES

Implement human-readable codes (enumerated if practical):

- `EMPTY_SCOPE`: no eligible files.
- `NO_ALLOWED_ACTIONS`: all KEEP / user disabled all actions.
- `NO_DESTINATION`: user allows MOVE but no distinct safe writable target.
- `PROTECTED_ONLY`: all target data protected.
- `INSUFFICIENT_THEORETICAL_GAIN`: sum of per-file maximum gains < target (upper bound; capacity ignored).
- `DESTINATION_CAPACITY`: plan exceeds free space after reserve.
- `SCAN_INCOMPLETE`: restricted file count or unreadable paths; no global certainty.
- `UNSTABLE_FILE`: changed between scan and estimate.
- `NO_FEASIBLE_FOUND`: search did not find a feasible plan, not mathematical proof.
- `INVALID_CONFIG`: missing folder, invalid target, source mismatch.

Provide UI warning text in Turkish and structured codes in JSON. Be careful: the sum of per-file maximum source gains is merely an upper bound; if below goal proof of impossibility, if above goal it **does not prove feasibility**.

## 20. MILESTONE-BASED BUILD ORDER / DELIVERY

**Milestone 1 — runnable skeleton:** requirements, README, app.py, importable modules; launch app showing safe local banner; pytest smoke. Commit/log result.

**Milestone 2 — perception and data:** scanner, disk inventory, safe path validation, generated fixture, typed models, scanner tests.

**Milestone 3 — agent action space:** importance rules, estimate, action generation, feasibility and costing, unit tests; verify only allowed paths considered.

**Milestone 4 — search:** Greedy, SA, tiny exhaustive oracle, tests, benchmark; show real solver results before UI polish.

**Milestone 5 — UI/results:** forms, scan, planning, warnings, Turkish explanations, CSV/JSON export, accessible layouts.

**Milestone 6 — end-to-end and documentation:** integration tests, sample screenshots if genuinely produced, benchmark CSV, source verification, one-command run instructions, reproducible demo with an impossible-target case.

At **each milestone**, run relevant tests and fix errors before moving on. Avoid mock functions returning hardcoded fake optimization results in the finished program.

## 21. README CONTENT REQUIREMENTS

README in Turkish must include:

1. What problem is being solved, goals and key limitations.
2. Difference between smart agent and model training; Greedy vs SA overview.
3. Required Python version and exact installation/start commands for Windows PowerShell and CMD.
4. Example fixture command, sample folder path and demo steps.
5. Explanation of target *additional free space* and KiB/MiB/GiB.
6. Description of dry-run safety, no actual freeing and no auto deletion.
7. Explanation of volume identity and conservative MOVE handling.
8. Formula definitions, heuristic risk/cost disclaimer, compression prediction limitations.
9. Tests/benchmark commands and interpretation (feasible rate, cost, runtime).
10. Known limitations; realistic product roadmap (not part of MVP).
11. **[v2/C15, C18]** Why the problem is NP-hard (the knapsack generalisation); "where is the agent?" (PEAS, the perceive–decide–act loop); Greedy vs Hill Climbing vs SA in one table.
12. **[v2/C6, C7, C9]** OneDrive placeholder and hard-link handling; logical vs allocated size.

## 22. EVALUATION / PEAS / ACADEMIC POSITIONING

**PEAS:**

- **Performance:** Meet additional source free-space target, minimize total intervention cost, respect protected files and capacities, provide actionable explanations, fast planning.
- **Environment:** Local filesystem metadata, target/source volumes, user preferences; partially observed true user importance and real compressibility.
- **Actuators:** MVP generates *proposed* KEEP/COMPRESS/MOVE plan, CSV/JSON; no actual disk mutation by default.
- **Sensors:** Directory traversal, file metadata, bounded content sampling, psutil volume metadata, user preference inputs.

**Problem formulation:** States = assignment of one action per file; actions in search = modify an assignment (one-/two-file neighbor); goal test = permissions, destination capacity and freed-space target; objective = minimize weighted total cost; local search = Simulated Annealing; reference = Greedy. For small instances exact brute force verifies results.

**Academic integrity:** Do not claim artificial neural network or reinforcement learning. This is a classical search-based intelligent agent. Do not claim all computed risks are statistically measured or all proposed changes will actually free exactly the predicted bytes. Instructor approval cannot be guaranteed.

## 23. OPTIONAL EXTENSIONS — NOT MVP

Only after all mandatory tests pass:

- Non-destructive test-data-only ZIP generation and copy-to-target with checksums, showing *no real free space* until validated safe replacement (replacement is outside MVP).
- Duplicate-hash report (never auto delete duplicates).
- History of user preference profiles in local JSON.
- Smart per-folder importance editor.
- Additional preview action types with explicit estimators, validators and effects.
- Safe transactional execution with rollback; requires separate engineering/security review, not casual addition.

## 24. DEFINITION OF DONE

Project is done only if all checkboxes hold:

- [ ] Works locally using `streamlit run app.py`.
- [ ] No pretrained/trained ML model, cloud API or LLM required.
- [ ] Reads only user-selected, safe local roots; no unsafe writes/deletes.
- [ ] Shows source volume and eligible destination volumes; same-volume move never gains space.
- [ ] User can set goal GiB, protected roots, action toggles and priorities.
- [ ] Contains typed data models, candidate actions, target capacities, transparent cost and gain.
- [ ] Greedy algorithm is real and deterministic.
- [ ] SA implements temperature schedule and probabilistic acceptance with seed; not a cosmetic random loop.
- [ ] Only feasible plans are labeled FEASIBLE; unreachable/unknown case explained.
- [ ] Compares Greedy, Hill Climbing and SA on identical inputs and displays estimate and runtime. **[v2/C14]**
- [ ] Synthetic scenario mode in the UI demonstrates MOVE and destination capacity on a single-volume laptop. **[v2/C1]**
- [ ] Streamlit is bound to localhost with telemetry disabled. **[v2/C5]**
- [ ] CSV/JSON reports and deterministic Turkish explanations available.
- [ ] All tests run with `pytest -q`; summary recorded truthfully.
- [ ] Synthetic fixture and benchmark commands work; results reproducible.
- [ ] README and sample academic demo are sufficient for a novice to run the application.

## 25. FINAL COMMAND FOR CODING AI

**Now implement the project end-to-end, not merely a plan.** Create files in the repository tree above; implement safety-first file scanning, typed models, volume-aware action generation, transparent estimators and cost function, a deterministic Greedy baseline, a genuine seeded Simulated Annealing search with best-feasible tracking, a Streamlit GUI in Turkish, plan reports, synthetic fixtures, unit/integration tests, and benchmark runner. Test the real code. Return the actual folder/file outputs plus exact Windows installation/run instructions, tests run and outcomes, and any remaining limitations. If some environment-specific API is unavailable, provide conservative fallback without claiming unsupported operations work. **Do not execute destructive file actions.**
