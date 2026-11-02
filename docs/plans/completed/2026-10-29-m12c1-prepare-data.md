# M12c1 — Prepare Data to a published image set

Status: DELIVERED — targeted/native checks and independent review complete;
manual acceptance open. Full verification was not run under the user's rule.
Owner/date: Codex, 2026-10-29.

## Goal and authorization

The user authorizes the next development slice with M12b4 manual acceptance still
open. Projects/Create and the latest Materials/Trim visual refinement are accepted;
this does not establish their functional manual acceptance or M12b4 acceptance.
The [M12b4 implementation](../active/2026-10-29-m12b4-folder-relink.md) is preserved.

The old final full pytest was identified by command, cwd, creation time and parent
tree and interrupted through its original session. All owned PIDs exited. **Остановлен
по запросу пользователя; полный результат отсутствует.** Logs and separate stop
metadata remain in ignored `sample_data/continuation-20261029/final/`; no runner
`result.json` was fabricated. Its partial progress is not a passing full gate.

The new [verification rule](../../../AGENTS.md#verification-authorization-all-agents-and-future-sessions)
applies to all agents and future sessions: no full pytest/full verify, broad long
suites or heavy benchmarks without a separate direct user request. No batching or
background workaround. This task authorizes short targeted checks only. An absent
full run does not block the explicitly authorized next development.

## Selection and contracts

[ROADMAP](../../../ROADMAP.md#m12--desktop-gui) names M12c Prepare Data & Image Review.
[UX sections 15–23](../../UX_UI_SPEC.md) own the workflow. The requirements audit
found no missing mandatory M12b implementation prerequisite after folder relinking;
open manual acceptance is tracked separately. No repeated broad M12b audit.

The first vertical scenario is Materials → Prepare Data → explicit processing →
published result counts and selected-image gallery → reopen the same saved result.
It delegates to existing ViewsService (candidate/quality/selection), with its current
participation and saved video interval resolution, publication, cache and lifecycle.
Only the saved frame-selection slot is needed; unsupported SfM slots must not block it.

Read contracts:

- [Architecture](../../../ARCHITECTURE.md#dependency-direction).
- [Pipeline views/quality/selection](../../PIPELINE.md) and existing immutable run contracts.
- [Project records](../../PROJECT_FORMAT.md#authoritative-records).
- [GUI presentation and navigation](../../GUI_DESIGN.md#screen-map-and-navigation).
- [Reference catalog](../../design/references/README.md), especially
  [prepared frames](../../design/references/07-prepared-frames.png). Existing
  [Materials review](../../design/references/03-materials-review.png) owns the entry style.

## Bounds and readiness

In scope: saved-method preparation plan with truthful included photo/video and used
video counts, supported output/resource estimates or explicit unknown; explicit run;
real structured progress/cancel; failure/retry/recovery routing; persisted successful
run chooser and bounded selected-image review. Save/Discard/Cancel protects dirty
intent. Stale project/revision and late GUI replies are refused. Run guards apply
under the existing writer. Reopen reads validated exact succeeded output bindings,
including cache-hit runs, rather than inferring success from a producer artifact.

Not in scope: all of M12c, manual image Exclude/Keep Anyway decisions, masks/tracking,
new quality presets or settings schema, new preprocessing methods, automatic result
currentness, reconstruction execution, production/runtime/benchmark changes or redesign.
Reference numbers/quality claims and unavailable estimates are never invented.

Ready when the scenario uses real existing services and saved publications, the
new states are usable, short meaningful tests cover immediate risks, real native
windows are captured and a fresh independent reviewer checks the entry-relative diff.
User manual acceptance remains a separate checklist, not inferred from these checks.

## Ownership and interfaces

All agents preserve the dirty entry tree. One editor per file; no nested delegation.
At most two implementation agents edit concurrently. Main owns all docs, integration,
native Qt resources and combined check scheduling. Each test run has a small explicit
selection and isolated cache/temp; no overlapping Qt/native jobs.

| Owner | Exclusive files/responsibility | Checks/resources |
| --- | --- | --- |
| Main | Rules/docs/state, integration, `scripts/capture_prepare.py`, entry audit | `sample_data/m12c1-20261029/`; Qt/native scheduling |
| Utility, Luna/high | Read-only exact M12c requirements/reference inventory | Completed; no tests/apps |
| Backend implementation, Sol/high | New `application/desktop_prepare.py`, adapter readback, bootstrap/facade wiring, minimal optional ViewsService revision guard, `test_desktop_prepare.py` | New backend tests only, bounded ~30 s; own `backend/` |
| GUI implementation, Sol/high | New `prepare_vm.py`, `PreparePage.qml`, `test_qml_prepare.py`; narrow controller/bridge/Sources integration | No test/app runs until main resource transfer |
| Fresh reviewer, Sol/high | Read-only final task diff and contracts | No edits, tests or apps |

Agreed service: `facade.service("prepare_data")`.

- `plan(root, *, expected_project_id, expected_revision) -> PreparePlan`.
- `run(root, request, *, expected_project_id, expected_revision) -> ViewsRunResult`.
- `results(root) -> tuple[PrepareSummary, ...]`, newest first, at most 25 succeeded
  exact view-route outputs; `summary(root, run_id)` when needed.
- `PrepareRequest`: candidate, selection, optional quality, limits, verification policy.
  `preparation_request(document)` resolves frame intent only.
- `PreparePlan`: project identity/revision, request, photo/video/used-video counts,
  optional candidate-count/byte/peak-workspace estimates and warnings.
- `PrepareSummary`: run ID/time, candidate/selected/rejected counts, optional measured/
  unavailable quality counts, method and warnings. Adapter-owned validated reads;
  GUI never opens project/artifact JSON.
- Existing `facade.gallery(root, run_id, offset)` supplies at most 100 selected
  thumbnails per page. Existing execution/progress/cancel/recover own lifecycle;
  retry means a new Prepare run using validated caches, never fake-route retry.

Requested role/model/effort is recorded, not claimed as actual serving metadata.

## Entry and verification plan

Branch `codex/m12b3-ux-review`; HEAD `4d83147acb01907ce02b1311977608f23d6eab17`;
index empty. All **507** nonignored entry files, hashes, diffs and status are saved in
ignored `sample_data/m12c1-20261029/`. Runtime/COLMAP/benchmark and existing GUI fixes
are outside the task and must survive byte-for-byte except explicitly owned hunks.

Use only the new bounded service/GUI cases and a few immediate regression node IDs;
record actual selection, duration, output and any interruption. Known slow files are
not run wholesale. Lint only changed Python/QML and check docs/links/diff. A short
native smoke uses generated sources and real services; no heavy backend/GPU workload.
No full pytest or full verify is run. Commands/results and final evidence follow.

## Delivered behavior

Materials' explicit local Prepare Data action opens a flat preparation/selected-grid
workspace. Check saved plan resolves only the saved frame-selection slot, Included
sources and video usage. Conservative resource bounds are labelled as bounds; source,
FFmpeg and disk availability remain execution checks. No new quality preset/settings
editor or pipeline algorithm was introduced. Prepare delegates to ViewsService;
the optional expected identity/revision guard runs under its existing writer.

The GUI drains owned readers, forwards early/late cancellation, keeps local errors,
offers restart and links unresolved work to existing recovery diagnostics. Results
are persisted exact succeeded run bindings, including cache reuse. The chooser and
up-to-100 selected images reopen from saved publications. They remain explicit
historical output, without automatically choosing reconstruction input. Manual
frame decisions, Rejected/All, Single/provenance inspector and masks remain later M12c.

Backend and GUI agents transferred all files/resources to main before integration.
Main preserved the entry-relative diff, fixed confirmed issues and owned subsequent
Qt/native runs. Five real agents participated: utility Luna/high, two implementation
Sol/high, fresh code reviewer Sol/high and UX reviewer Terra/medium (requested roles;
actual serving metadata unavailable). No nested agents or unapproved model changes.

## Short verification evidence

All paths below are relative to ignored `sample_data/m12c1-20261029/`. No full pytest,
full verify, broad long suite, heavy benchmark, GPU workload or installation ran.
No existing slow test file was run wholesale. Counts below overlap and are not summed.

Backend agent's final new-service check:

```powershell
.venv/Scripts/python.exe -m pytest -q -o addopts='' tests/test_desktop_prepare.py --basetemp=sample_data/m12c1-20261029/backend/pytest-run4 -p no:cacheprovider
```

**10 passed, 17.41 s**. Cases cover unknown unrelated SfM settings, legacy/typed frame
intent, participation/video intervals, exact settings forwarding, pre-delegate cancel,
writer-protected revision race, reopened/cache-hit results, corrupt/incomplete outputs
and quality lineage. Earlier attempts corrected missing test-directory setup and a
missing fake quality assessor; assertions and defaults were not weakened. Five-file
scoped Ruff passed. No native/Qt run by that agent.

Main initial bounded GUI selection:

```powershell
.venv/Scripts/python.exe -u -m pytest tests/test_qml_prepare.py -q -ra --tb=short -o cache_dir=sample_data/m12c1-20261029/gui-cache --basetemp=sample_data/m12c1-20261029/gui-tmp
```

**10 cases passed, exit 0**, `gui-tests.log`; approximately 48 s log-file wall interval.
The inherited quiet option plus `-q` suppressed pytest's summary, so no pytest-reported
duration is invented. These cases preceded the review fixes below; no repeat of the
whole selection was performed. The file now also contains the three new regressions.

Main post-review selection:

```powershell
.venv/Scripts/python.exe -u -m pytest -o addopts='' tests/test_qml_prepare.py::test_prepare_run_failure_keeps_published_history_and_replaces_running_message tests/test_qml_prepare.py::test_stale_gallery_failure_cannot_contaminate_new_context tests/test_qml_prepare.py::test_prepare_plan_errors_are_local_and_retryable -q -ra --tb=short -o cache_dir=sample_data/m12c1-20261029/review-fix-cache --basetemp=sample_data/m12c1-20261029/review-fix-tmp
```

**4 passed, 22.83 s**, `review-fix-tests.log`. Delayed failure is tested both after
choosing another run and after returning to Sources; no stale local/global error.
The processing-failure test also checks retained publication, terminal message and retry.

Main immediate consumers:

```powershell
.venv/Scripts/python.exe -u -m pytest -o addopts='' tests/test_qml_folder_relink.py::test_real_folder_relink_commits_all_occurrences_restores_viewer_and_reopens tests/test_materials_stability.py::test_projects_resume_keeps_current_batch_group_filter_and_saved_readback tests/test_gui_architecture.py::test_inward_imports_and_no_processing_libraries -q -ra --tb=short -o cache_dir=sample_data/m12c1-20261029/regression-cache --basetemp=sample_data/m12c1-20261029/regression-tmp
```

**4 passed, 21.90 s**, `regression-tests.log`. No skips/warnings in these short checks.
Qt checks used offscreen; all caches/temporary directories were isolated and Qt runs
serialized. Main scoped Ruff covered the 11 changed/new Python files; after fixes
only the four modified files needed another pass. Both changed QML files passed:

```powershell
& .venv/Scripts/pyside6-qmllint.exe -I src/splatforge_gui/qml -i src/splatforge_gui/qml/theme/qmldir --max-warnings 0 src/splatforge_gui/qml/pages/PreparePage.qml src/splatforge_gui/qml/pages/SourcesPage.qml
.venv/Scripts/python.exe scripts/check_docs.py
git diff --check
```

QML exit 0, no warnings. Main final documentation check: **51 Markdown files, zero
errors**. Whitespace check exit 0. Final preservation audit: all 507 entry snapshots
intact; **487 unchanged, 20 scoped changes, 8 new files**, none missing/corrupted.
Branch/HEAD match entry and index remains empty. No full verify was substituted.

## Real GUI and independent review

Main native command (follow-up only because confirmed defects were fixed):

```powershell
$env:QT_QPA_PLATFORM = 'windows'
$env:QT_SCALE_FACTOR = '1.25'
.venv/Scripts/python.exe -u scripts/capture_prepare.py --output sample_data/m12c1-20261029/native-02
```

**Passed, 10 captures, no QML warnings/exceptions**; manifest `passed: true`.
Actual 1440×849 / 1024×640 logical, 1800×1061 / 1280×800 raster, DPR 1.25; exposed
Windows windows with native title bar. Three generated PNG sources, two Included;
real ingest/plan/ViewsService/publication/quality/gallery/readback. The harness
temporarily moves only its contained generated photo to check source failure,
restores it and retries. It verifies original byte hashes and unchanged project
intent, the empty project, project switch and persisted reopen. There is no worker
hold or invented processing data. The first native run passed eight captures;
the second adds compact error/summary scroll assertions after the visual findings.

Fresh code reviewer confirmed one P2: a delayed old gallery failure could contaminate
a newer set or open a global error after Sources return. Main made local Prepare
errors token-bearing results, with stale success/failure discarded by both consumers;
legacy consumers retain their normal exception route. Main also kept processing
errors through automatic history reload. The reviewer independently read the updated
entry-relative diff and regressions: **no confirmed remaining finding**.

Separate UX reviewer found two captured defects: long path clipping and a retained
Preparing message after failure. Main added wrapping and a truthful terminal message.
The reviewer confirmed both fixed in native-02, including visible complete error and
counts after compact scrolling. Main's native harness actively scrolls and asserts
those controls are fully within the viewport; the UX reviewer inspected images only.

## Final boundary and manual acceptance

Implementation, targeted automation, native generated-data scenario and independent
review are complete for M12c1. This is not full M12c or user acceptance. M12b4 and old
Materials/Trim/M12b3 functional manual checklists remain unconfirmed. Full verification
is absent under the direct user rule; that absence does not block the authorized slice.

Manual checklist:

1. With Included photos/video and saved Trim intervals, Check saved plan and Prepare;
   confirm useful selected images and reopen the saved set.
2. Cancel during preparation, wait for confirmed stop, then restart; old sets survive.
3. Try missing source/retry, rapid set selection, Sources return and another project;
   no stale images/error and no changes to originals or source participation.
4. Inspect Dark/Light and compact scrolling at the user's normal scale.

Real user/video-codec breadth, video-reader playback during Prepare entry, keyboard/
focus traversal, screen reader, OS/per-monitor scaling and large-history I/O remain
unverified. No later slice, publication, cleanup or Git action follows automatically.
