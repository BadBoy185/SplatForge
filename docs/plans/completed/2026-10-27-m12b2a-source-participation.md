# M12b2a — Source Participation

Status: COMPLETED; user manual UX acceptance passed 2026-10-27.
Owner/date: Codex, 2026-10-27. Base: M12b2 `4fb9da9`.

## Scope and contracts

Portable reversible source participation, application resolver, existing Prepare consumer,
List/Grid filters/counts/Details, preservation of originals/inventory/history. No M12b3
capture metadata/groups, Prepare UI, extraction, deletion, watchers or recompute.
Contracts: [project intent/CAS](../../PROJECT_FORMAT.md#authoritative-records),
[GUI ownership](../../GUI_DESIGN.md#presentation-architecture),
[verification](../../DEVELOPMENT.md#verification-workflow),
[view recipes](../../PIPELINE.md), [M12](../../M12.md).

## Targeted architecture audit (before persistence changes)

- `ProjectDocument` format 1 is editable portable intent. Revision starts at 0;
  `ProjectService.save` increments once. `LocalProjectStore` locks, compares current
  identity/revision/creation time, then atomically replaces JSON. Stale saves fail.
- Top-level unknown fields are refused (extra=forbid), not silently dropped. Method
  envelopes preserve arbitrary JSON extras and future schemas. The new optional,
  independently versioned participation envelope follows that preservation convention.
- Inventories are immutable JSONL; ingest/relink atomically publish a new inventory
  reference and project revision through the same writer/CAS. Exclusion needs neither.
- `MediaService.add` always allocates a fresh occurrence UUID, even for repeated
  path/content. Existing exclusions persist; a newly added occurrence is Included.
- Relink hashes and checks identical bytes, retains source UUID/revision, and changes
  locator/evidence in a new inventory. Exclusion follows the stable UUID, never path.
- `ViewsService.prepare(source_ids=None)` previously selected all inventory. Explicit
  sets were validated/sorted. `candidate_recipe_key` already includes consumed UUIDs,
  source revisions/content and numerical metadata, excluding locator, project revision,
  inventory revision/digest, label and participation envelope revision. Whole-inventory
  digest/reference are frozen provenance, not candidate recipe inputs. Reuse validates
  historical lineage; existing relink/cache tests cover this separation.
- GUI label/settings edits are drafts until Save, with Save/Discard/Cancel on switch.
  Ingest immediately persists through a distinct existing media mutation. Participation
  uses the existing project draft + Save path and owned-reader drain. Pending label/
  settings drafts receive the same Save/Discard/Cancel prompt first. Participation
  itself is shown only after successful save and committed readback; failures discard
  its transient draft and refresh committed metadata. No optimistic QML flag.
- Old CLI documents omit participation; default empty exclusions means all Included.
  Opening does not rewrite/migrate. Unknown extension JSON survives unrelated saves;
  unsupported participation versions are inspectable, but processing/mutation refuse.
- Single UUID selection is shared by List/Grid/preview. GUI Ctrl/Shift multi-selection
  is deferred to avoid changing that contract; application updates accept a batch set
  in one project Save. Filtering stays in memory, with existing lazy thumbnail bounds.

## Decisions and acceptance

Add optional `source_participation` schema 1 with sorted unique excluded UUIDs.
Keep format/state versions unchanged (additive read compatibility; older binaries
may refuse the new field). Preserve unknown/stale UUID intent with typed diagnostics;
never invent sources. Reject unknown IDs in mutations and excluded explicit Prepare
subsets. Resolve default/effective selection inside Prepare's existing writer lease.
An empty effective set fails before run creation. No global invalidation/currentness
flag: old outputs remain immutable historical evidence, with existing lineage.

Acceptance: old/new defaults, exclude/restore reopen, CAS/busy/write failures,
unknown/versioned data, relink/re-import, downstream identity/cache/history, independent
availability, filters/counts/List/Grid/Details/photo preview/video/empty states, project
switch, bounded 1500+ delegates. Native Windows Qt captures at 1024x640 and 1440x900,
Dark/Light. Focused tests + scoped Ruff + all-QML lint + docs + diff. Full H unrun.

## Evidence

M12b2 commit: `4fb9da96bca155fddf49f193bacc623f49edaf6f`,
`feat(gui): complete M12b2 sources workflow`. Exactly 39 files: 14 production Python,
9 QML, 10 test and 6 documentation files. Backend/feature/COLMAP/benchmark edits were
excluded, with mixed documentation staged by content. Index was empty after commit.
The accepted M12b2 code was byte-identical to its prior corrective evidence; those
tests were reused. Closure reran scoped Ruff, all-QML lint, six doc links and diff checks.

### Implementation map

| File(s) | Responsibility |
| --- | --- |
| `core/source_participation.py`, `core/project.py` | Versioned exclusion UUIDs, typed diagnostics, effective sources, optional project intent |
| `application/source_participation.py` | Validated atomic batch draft, preserving unknown JSON; existing ProjectService Save/CAS |
| `application/views.py` | Default/explicit run membership resolved under the writer lease before creating a run |
| `application/media.py`, `application/desktop.py` | Read the inventory referenced by the same document revision; committed participation facts/roles |
| `splatforge_gui/controller.py` | Adopt returned saved revision before queued Save continuation, preventing stale follow-up edits |
| `splatforge_gui/qml_bridge.py`, `presentation.py` | Existing Save/Discard/Cancel, committed readback, independent availability and counts |
| `splatforge_gui/qml_media.py` | In-memory filters preserving lazy thumbnail namespaces/limits and shared selection |
| `SourcesPage.qml`, `SourceDetailsDialog.qml` | Included/Excluded/All, Exclude/Restore, explicit labels, meaningful empty states and retained inspection |
| `test_source_participation.py`, `test_qml_source_participation.py` | Persistence, CAS/faults, actual CLI/Prepare/cache/history, Qt behavior/focus/performance |
| Project format, Pipeline, GUI design, M12, roadmap/map/active index | Authoritative contracts and bounded milestone routing |

### Persistence and downstream evidence

- Tests save/reopen and copy the project to another Unicode/spaced directory, proving
  portable exclusions, unchanged inventory reference/bytes, SQLite bytes and originals.
  Restore reopens Included. New repeated occurrences are Included; relink retains
  the excluded UUID/revision. Stale edits and a real before-replace storage fault
  leave the committed document intact. Unknown envelope/settings extras survive.
- Actual ViewsService + normal publication + injected tiny materializer: first run
  consumes photo/video (4 candidate views); excluding the video produces a 1-photo
  route whose frozen `sources` omits that UUID and whose candidate recipe differs.
  A label-only save reuses both candidate/selected caches. Restore reuses the original
  matching recipes. Every prior artifact and original run.json remains byte-identical.
- CLI `project show` opens participation; `views prepare --source-id` executes an
  Included subset and refuses an Excluded UUID. All-excluded refuses before creating
  a run. No state database write/recompute occurs during the intent change itself.
- Qt tests cover photo/video List/Grid, filters/counts, Details, excluded photo preview,
  restart, Save/Discard/Cancel, stale/write failure, held readers/busy, missing/available
  independence, keyboard focus/Space activation, unsupported version and 1500 sources.

### Verification commands (Codex)

Windows, Python 3.12.10, PySide6/Qt 6.12.0; default offline fake processing fixtures.
No installation, model download, GPU/backend opt-in or full H was performed.

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
.\.venv\Scripts\python.exe -u -m pytest -o addopts= -v -rs `
  tests/test_projects.py tests/test_media.py tests/test_views_core.py `
  tests/test_views_execution.py tests/test_views_cli.py tests/test_project_cli.py `
  tests/test_source_participation.py
.\.venv\Scripts\python.exe -u -m pytest -o addopts= -v -rs `
  tests/test_gui.py tests/test_qml.py tests/test_qml_workflows.py `
  tests/test_qml_interaction.py tests/test_gui_architecture.py `
  tests/test_qml_sources.py tests/test_qml_folder_browser.py `
  tests/test_qml_sources_corrective.py tests/test_desktop.py `
  tests/test_qml_source_participation.py
```

The first backend gate was 138 passed / 1 failed in 99.53 s. Its new CLI fixture
requested default JPEG while its injected materializer emitted PNG. The fixture now
explicitly requests PNG. Final retest of the new backend module: **10 passed, 13.02 s**.
No production backend change was needed after that gate.

The first broader GUI gate was 196 passed / 1 failed in 448.06 s. A direct source-model
replacement used by the established Grid preview fixture left registered summary
counts stale. Summary now follows source model changes, independent of filter counts.
The focused final source gate below is **16 passed, 92.93 s**, including that regression
and all 15 participation cases. The affected existing source consumers are also rerun.
Early development Qt checks found and repaired an empty browser intercepting the View
Excluded button; a new keyboard test was corrected to wait for delegate incubation.

```powershell
.\.venv\Scripts\python.exe -u -m pytest -o addopts= -v -rs tests/test_source_participation.py
.\.venv\Scripts\python.exe -u -m pytest -o addopts= -v -rs `
  tests/test_qml_folder_browser.py::test_grid_double_click_reuses_photo_popup_and_order `
  tests/test_qml_source_participation.py
.\.venv\Scripts\python.exe -u -m pytest -o addopts= -v -rs `
  tests/test_qml_sources.py tests/test_qml_folder_browser.py tests/test_qml_sources_corrective.py
```

Ignored logs: `sample_data/m12b2a-backend-final.log`, `m12b2a-backend-retest.log`,
`m12b2a-gui-final.log`, `m12b2a-source-final.log`, `m12b2a-source-consumers-final.log`.
Overlapping runs are not added as independent tests. Final consumer/lint/diff results
and unique passing case count are recorded below after completion.

### Native visual verification

`sample_data/m12b2a-native-capture.py` runs normal Windows Qt in its real application
event loop, with synthetic originals and injected deterministic probe metadata. It
produced 24 native captures at exact logical 1024x640 and 1440x900, DPR 1.0, Dark/Light.
Coverage: Included, Excluded and All; excluded photo/video List/Grid; photo/video
Details; all-excluded and Excluded-empty. Qt reported **no QML warnings**. Representative
captures were visually inspected for toolbar fit, labels, contrast, selection, card/
Details geometry and empty-state clarity. Keyboard focus/activation is behaviorally
tested. Photo decode stays lazy; the 1500-source tests prove delegate/request bounds.
The small fixture is not video playback/codec validation. Native output/metadata:
`sample_data/ui-review/m12b2a-native/manifest.json` and adjacent PNGs. The final count
synchronization and included-video wording were re-captured in the final 24-image run.

### User manual UX checklist

1. Exclude one photo from Included; find it in Excluded, confirm the original remains.
2. Restore it; confirm Included and the registered count is unchanged.
3. Exclude 2–3 sources, close/restart/reopen, confirm persistence.
4. Exclude/inspect/restore an MP4; no extraction/player is started.
5. Confirm Available can be Excluded and Missing can be Included; Restore is not Verify.
6. Switch List/Grid/All, inspect Details and preview an excluded photo; check empty states.
7. Save/Discard/Cancel an existing draft before exclusion. If safely reproducing a stale
   save/write refusal, confirm the error and unchanged committed participation.

### Remaining scope and full H

GUI Ctrl/Shift batch selection is deferred; the backend batch mutation is atomic.
Full currentness UI remains M12d: historical results retain their original lineage,
with no global invalidation flag. M12b3 capture metadata/groups remains next and unstarted;
M12c Prepare UI is later. No physical deletion, processing, packaging or watcher added.
M12b2a remains ACTIVE, unstaged and uncommitted pending manual UX acceptance.

Full H commands prepared only, **not executed** (backend opt-ins remain unset):

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\pyside6-qmllint.exe -I src/splatforge_gui/qml -I src/splatforge_gui/qml/theme `
  (Get-ChildItem src/splatforge_gui/qml -Recurse -Filter *.qml).FullName
.\.venv\Scripts\python.exe scripts/check_docs.py
git diff --check
```

Known unrelated Ruff `core/registry.py:52 E501` is untouched; scoped success is not
global Ruff/full-H success. No push. Entry-hash audit proves 29 wholly unrelated
files byte-identical; mixed roadmap/map/active-index/pipeline benchmark hunks are
preserved and separately inspected. Exact file list/integrity evidence is ignored
under `sample_data/m12b2-commit-scope.txt` and `sample_data/m12b2a-preservation.json`.

### Final affected verification (Codex, 2026-10-27)

| Check | Final evidence |
| --- | --- |
| New persistence/Prepare/CLI module | 10 passed, 13.02 s |
| Participation GUI + established Grid regression | 16 passed, 92.93 s |
| Existing Sources/List/Grid/preview/corrective consumers after count repair | 50 passed, 156.44 s |
| Unique selected cases across broader gates and superseding retests | 338 with passing evidence, no unresolved failures/skips; overlapping runs counted once |
| Scoped Ruff, 12 changed Python files (10 production, 2 test) | Passed |
| All-QML qmllint, absolute source paths and theme import path | Passed, no warnings |
| Eight scoped Markdown files | 0 errors |
| `git diff --check` | Passed; only Git's existing LF/CRLF notices |
| Native Windows Qt final captures | 24, exact sizes/DPR above, no QML warnings |
| Unrelated entry-hash comparison | 29 wholly unrelated files byte-identical; mixed documentation hunks retained |
| Git | HEAD `4fb9da9`, index empty; all 22 M12b2a files unstaged; no push |

Final unique-case audit: `sample_data/m12b2a-test-coverage.json`. Exact lint/docs/diff
commands and output: `sample_data/m12b2a-final-checks.log`. The broader gates' initial
failures above remain documented; clean affected retests supersede them. Full H and
global Ruff were not run. Manual acceptance remains the user's next useful step.

### Closure - 2026-10-27

User manual UX acceptance passed. Closed before starting M12b3; prior affected
evidence above covers unchanged implementation. Full H remains a user gate.
