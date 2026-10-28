# M12b3 - Capture Metadata & Logical Source Groups

Status: ACTIVE - corrective pass implemented and verified; awaiting new manual UX acceptance.
Owner: Codex, 2026-10-28. Full H remains the user's later gate after acceptance.
Base: accepted M12b2a `40375875ff1cb170baa98783d62a5582180a8d60`.
Review snapshot: user-authorized isolated commit on `codex/m12b3-ux-review`; see below.

## Scope and contracts

Saved capture evidence, portable user organization, grouped Sources browsing and
human Details. No Prepare UI/processing, session inference, camera regrouping,
video decoder, dependency installation or full H. Primary UX: [Sources specification](../../UX_UI_SPEC.md),
[GUI ownership](../../GUI_DESIGN.md#presentation-architecture),
[project CAS/inventory](../../PROJECT_FORMAT.md#authoritative-records),
[recipes](../../PIPELINE.md#stage-inputs-and-outputs),
[verification](../../DEVELOPMENT.md#verification-workflow), [M12](../../M12.md).

## Audit before implementation

- `SourceOccurrence.source_id` is an occurrence UUID; reimport creates another UUID.
  Relink verifies identical bytes and retains source UUID/revision/probe/groups.
- `source_group_id` is processing provenance, independently allocated per occurrence
  unless explicitly supplied. It enters candidate recipes, Views/PairSet provenance
  and cross-group diagnostics. It is not a mutable UI label or device identity.
- `camera_group_id` is declared calibration identity, independently allocated unless
  supplied. It enters candidate recipes, views, feature/mapping camera contracts.
  EXIF make/model is insufficient evidence of shared intrinsics or a physical unit.
- Immutable JSONL inventories advance on ingest/relink. `NormalizedProbe` already
  stores dimensions, photo orientation and video codec/duration/rates/rotation.
  `FFprobeAdapter` uses the owned bounded process runner; bounded JPEG/PNG TIFF
  helpers currently extract orientation only. Pillow is already a base dependency.
- Participation is independently versioned project intent. Prepare resolves Included
  UUIDs under its writer lease. Candidate recipes explicitly whitelist numerical
  source fields: no project/inventory revision, label, locator or presentation fields.
  Downstream consumes immutable Views/PairSets, not current organization intent.
- GUI overview reads the saved inventory, never EXIF. SourceBrowserModel owns one
  filtered UUID selection; ListView/GridView are virtualized. Photo thumbnails retain
  192px / 8 jobs / 100 queued / 128 cached bounds and project-generation revocation.

## Chosen model and boundaries

- Optional versioned capture evidence on `NormalizedProbe`, plus ingest original
  filename on the occurrence. Existing numerical orientation/rotation fields retain
  their meaning. Optional fields default to unknown; old inventories open unchanged.
  EXIF parsing reads at most 1 MiB of headers without decoding pixels; malformed
  descriptive fields are ignored individually. Container tags are a bounded allowlist.
  No filename heuristics, GPS coordinates, EXIF dump or physical-unit/session claim.
- Optional independently versioned `logical_source_groups` in `project.json`:
  stable UUID/label entries and occurrence UUID assignments. Application batch drafts
  use existing ProjectService Save/CAS/atomic replacement. Delete ungroups sources;
  unknown references remain inspectable but mutations reject invalid targets.
  Unknown envelope extensions survive unrelated saves; unsupported versions do not
  block processing because organization is not a processing contract.
- Derived sections prefer explicit user group, then captured Make+Model, then Videos
  or Unknown device. They never persist automatic sessions/groups. A compact group
  navigator scopes either virtualized List or Grid, with truthful filtered counts;
  All groups retains section ordering/labels. Empty user groups remain selectable.
  This avoids nested unbounded grids and preserves one-source selection. Backend
  assignment is batch capable; GUI controls operate on one selected source.
- Compact overview roles contain device/group labels, not full EXIF maps. Selected
  Details is fetched asynchronously from saved inventory only. Open performs no
  migration/save, source scan or metadata backfill. New evidence is captured within
  ingest's existing metadata phase, before its checked/succeeded progress events.
- Rename/assign/delete only change project organization intent: zero numerical
  invalidation; no edits to inventories, camera/source groups or historical artifacts.

## Acceptance and verification

Focused capture/probe/persistence/groups/CAS/failure/relocation/relink/participation
tests; actual Prepare reuse/history regression; Qt List/Grid/group actions/Details,
filters, project switch and 1500+ bounded delegates. Scoped Ruff, all-QML lint, docs,
diff. Native Windows Qt Dark/Light at 1024x640/1440x900, DPR 1 and 1.5 if available.
Record actual commands/results and inspect captures. Full H stays with the user after
manual acceptance. Keep M12b3 unstaged/uncommitted and compare unrelated entry hashes.

## Evidence

Initial tree: branch `feat/m12-qml-premium-ui`, HEAD `4fb9da9`, index empty,
51 dirty/untracked files. Ignored snapshot: `sample_data/m12b3-entry/`.
M12b2a closed/committed separately (22 files); scoped Ruff/all-QML/docs/diff passed.
Its accepted implementation was unchanged; earlier focused test evidence is retained
in the [completed plan](../completed/2026-10-27-m12b2a-source-participation.md).
Unrelated COLMAP/benchmark work remains outside the commit. No push.

### Delivered file map

| Files | Responsibility |
| --- | --- |
| `core/capture_metadata.py`, `core/media.py` | Optional immutable descriptive evidence; original ingest filename |
| `adapters/capture_metadata.py`, `adapters/ffprobe.py`, `application/media.py` | Bounded EXIF/container allowlist within existing ingest metadata phase |
| `core/logical_source_groups.py`, `core/project.py`, `application/logical_source_groups.py` | Versioned UUID groups/assignments, canonical serialization and validated batch drafts |
| `application/desktop.py` | Compact device/group overview; selected-only saved Details, without original reads |
| `splatforge_gui/qml_media.py`, `qml_bridge.py`, `presentation.py` | Filtered sections/counts, async stale-result protection, committed Save/readback, human metadata |
| `SourcesPage.qml`, `SourceGroupsDialog.qml`, `SourceDetailsDialog.qml` | Scoped grouped List/Grid, UUID section identity, organization actions, progressive Details |
| `test_capture_metadata.py`, `test_logical_source_groups.py`, `test_qml_capture_groups.py` | 33 new passing cases across metadata, persistence, numerical identity and actual Qt behavior |
| Project format, GUI design, M12, roadmap and indexes | Authoritative contract/status routing; unrelated benchmark hunks retained |

Exactly 25 task files (15 Python, 3 QML, 7 documentation) are listed in ignored
`sample_data/m12b3-task-files.json`. M12b3 is unstaged/uncommitted on `4037587`.

### Persistence, numerical identity and backward compatibility

- JPEG/PNG fixtures contain actual Make/Model/lens/time/offset/focal/35mm/exposure/
  aperture/ISO EXIF. Normal FFprobeAdapter with an injected process boundary feeds
  normal MediaService inventory publication. Saved metadata survives deleting the
  original; selected Details and overview still report the saved device. Video
  container allowlist/rate/rotation/duration persists; GPS coordinates are not stored.
- Missing/partial/malformed descriptive evidence stays unknown. Filename `DJI_9999`
  does not identify a device. Time without an offset stays naive. Old inventories
  without an ingest original filename report that field as Not recorded.
- Explicit legacy M12b2 and M12b2a-with-exclusions shapes open without modifying
  project/inventory/state bytes. A subsequent user Save adds default envelopes while
  preserving exclusions. New projects, reimport UUIDs, relocation, relink, unknown
  references/versions/extensions, stale CAS and actual atomic-save faults are covered.
- Actual ViewsService publication first creates candidate/selected artifacts. Create,
  assign, rename and delete each retain both cache hits and the original candidate
  recipe; original run JSON and artifact bytes remain unchanged. The whole inventory,
  including source/camera groups, remains identical. Even an unsupported organization
  version leaves numerical reuse available. Exclude still changes the consumed set
  and candidate recipe. A separate regression changes descriptive capture fields and
  ingest filename, proving the explicit numerical recipe whitelist ignores them.
- Qt tests exercise actual group controls, single-source assignment, independent
  filters/counts, empty groups, failed Save without invented committed UI, saved
  photo/video Details, delayed responses across project switch and 1503-source
  virtualization in both themes. Duplicate group labels retain distinct UUID section
  keys; List section grouping never uses a mutable display label as identity.

### Verification actually executed by Codex

Windows, Python 3.12.10, PySide6/Qt 6.12.0, Pillow from the existing project environment.
No dependency installation, backend/GPU opt-in, model download or full H.

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
.\.venv\Scripts\python.exe -u -m pytest -o addopts= -v -rs `
  tests/test_media.py tests/test_ffprobe.py tests/test_projects.py `
  tests/test_source_participation.py tests/test_capture_metadata.py `
  tests/test_logical_source_groups.py tests/test_views_core.py `
  tests/test_views_execution.py tests/test_media_import_progress.py `
  tests/test_media_ingest_cancel.py tests/test_desktop.py
.\.venv\Scripts\python.exe -u -m pytest -o addopts= -v -rs `
  tests/test_qml_sources.py tests/test_qml_folder_browser.py `
  tests/test_qml_sources_corrective.py tests/test_qml_source_participation.py `
  tests/test_qml_capture_groups.py tests/test_gui_architecture.py
.\.venv\Scripts\python.exe -u -m pytest -o addopts= -v -rs `
  tests/test_capture_metadata.py tests/test_logical_source_groups.py
.\.venv\Scripts\python.exe -u -m pytest -o addopts= -v -rs `
  tests/test_qml_capture_groups.py `
  tests/test_qml_sources_corrective.py::test_selected_source_details_human_fields_and_collapsed_provenance
```

| Gate | Actual result |
| --- | --- |
| Affected backend consumers | 213 passed, 1 skipped, 136.39 s |
| Affected Qt Sources/architecture consumers | 98 passed, 314.00 s |
| Final metadata/groups/legacy matrix/numerical regressions | 23 passed, 12.06 s |
| Final Qt UUID sections/groups/Details retest | 14 passed, 73.85 s |
| Current selected case-ID audit across superseding runs | 314 unique passed, 1 skipped; no unresolved failures |
| Scoped Ruff (15 changed Python files) | Passed |
| All-QML qmllint, source and theme import paths | Passed, no warnings |
| Repository documentation checker | 43 Markdown files, 0 errors |
| `git diff --check` | Passed; existing LF/CRLF notices only |
| Entry integrity | 29 wholly unrelated files byte-identical; 4 mixed documentation files retain benchmark additions |
| Git | HEAD `4037587`, index empty, M12b3 uncommitted, no push |

The only skip is `test_ffprobe.py::test_real_ffprobe_generated_png`, requiring the
explicit `SPLATFORGE_TEST_FFPROBE` opt-in. Initial development found an unhandled
Pillow `struct.error` for truncated TIFF; optional parsing now handles it and the
regression passes. Two initial fixture assertions were corrected (fake backend
version identity, required CandidatePoolSettings values). Two new Qt cases clicked
before fresh delegates settled; they now test real keyboard activation. Settled
native mouse activation is separately asserted. All superseding results above pass.
Early evidence is retained rather than presented as a clean first run.

Logs: `sample_data/m12b3-backend-consumers.log`, `m12b3-qt-consumers.log`,
`m12b3-backend-final.log`, `m12b3-qt-final-addendum.log`. Exact lint/docs/diff commands:
`sample_data/m12b3-final-checks.log`. Current collection and final case outcomes:
`sample_data/m12b3-final-collection.log`, `m12b3-test-coverage.json`. Integrity and
task hashes: `sample_data/m12b3-preservation.json`.

### Native Windows Qt visual review

Ignored `sample_data/m12b3-native-capture.py` runs the actual Windows platform/event
loop with tiny synthetic EXIF originals and injected deterministic video probing.
It asserts actual mouse selection, exposure, preserved originals and cleared metadata/
thumbnail state after switching to another project. It does not process media.

Final output: 49 captures each under `sample_data/ui-review/m12b3-native-0.8/` and
`m12b3-native-1.2/`, with manifests recording requested/actual size, platform, DPR and
zero QML warnings. Qt's existing host scaling means scale factors 0.8/1.2 produce
actual DPR 1.0/1.5. At DPR 1.0 both exact 1024x640 and 1440x900 were captured. At DPR
1.5 exact 1024x640 works; Windows limits the requested 1440x900 to 1283x703 on this
display. Large 150% captures are not claimed as exact 1440x900.

Dark/Light cover mixed DJI/iPhone/long Sony/unknown metadata, All List/Grid, a long
user group containing Included and Excluded sources, Excluded scope, empty group,
group controls, photo Details at top and photographic fields below, video Details,
and project switch to empty Sources. Representative full-size captures and contact
sheets were visually inspected. The first capture exposed clipped Grid Details at
1024x640; card height now follows its viewport. Human Status was moved before
photographic fields, redundant neutral status removed, and Details scrolling made
discoverable. Final inspected captures show accessible actions, readable contrast,
elided long browser labels/full Details, correct thumbnails/video placeholders and
no stale content after switch. Keyboard/focus and delegate/request/cache bounds
also have actual Qt assertions. This is agent visual verification, not user acceptance.

### User manual UX acceptance checklist

1. Import JPEG/PNG photos from two devices and photos without EXIF; compare sections
   and Details. A device name must come from metadata, not its filename.
2. Switch List/Grid and browse individual device sections and All groups; scroll a
   large collection and check long names at 1024x640 in both themes.
3. Select a source, open Groups, create Exterior Drone, move it there, rename the
   group, move it again, Ungroup and delete an empty group. Check persisted readback.
4. Exclude one member of a group; compare Included/Excluded/All counts and restore
   it. The group and captured device must remain independent.
5. Reopen a project with an unavailable original; confirm saved device/time metadata
   remains available and availability honestly starts Not checked this session.
6. Inspect photo time/ISO/exposure/aperture below Status and collapsed technical
   provenance. Inspect a video: duration/resolution, honest placeholder, no playback.
7. Switch to another project and back: no stale selection, device evidence or image.
8. Accept the M12b3 UX before running full H or requesting its commit. M12c is unstarted.

### Initial implementation limitations and full H commands (historical)

Input formats remain JPEG/PNG/MP4/MOV; no HEIC decoder or dependency was added.
Descriptive EXIF beyond the bounded header scan can remain unknown; there is no
automatic backfill for old inventories. Complete Make+Model describes a reported
model, not a serial-number/physical-unit/session identity. GUI retains one-source
editing while the application contract is batch capable. Video posters/player/frame
extraction, bulk selection, group-based pairing and Prepare UI remain outside scope.
The 150% large-window display limitation is above. Full H and global Ruff are unrun;
the existing unrelated `core/registry.py:52 E501` is untouched.

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\pyside6-qmllint.exe -I src/splatforge_gui/qml -I src/splatforge_gui/qml/theme `
  (Get-ChildItem src/splatforge_gui/qml -Recurse -Filter *.qml).FullName
.\.venv\Scripts\python.exe scripts/check_docs.py
git diff --check
```

## Manual UX corrective pass

The user did not accept the initial implementation. This is work inside M12b3;
M12c is unstarted and no stage/commit/push is authorized. Earlier evidence above
describes the initial implementation, not acceptance. The initial single-selection,
manual-only grouping and missing Preview mutation limitations are superseded here.

### Findings, root causes and corrections

The manual review found ten issues: missing Check Source Files progress/ETA; stale
Grid availability after List verification; noisy text actions; missing inline
Exclude/Restore; no selected-set mutations; no Ctrl/Shift selection/batch grouping;
missing folder-derived logical groups; centered List availability; missing compact
Preview Exclude; and no Preview auto-advance after exclusion.

- Verification iterated a known inventory without any application progress callback.
  The shell consequently waited for pipeline-run observations that this operation
  never produced. MediaService now publishes checking/checked/succeeded observations
  through the existing source-operation reporter and M6.5 HybridThroughputEstimator.
  Total is the resolved source count; completed advances only after the verification
  record is persisted; filename, phase and elapsed time are actual work observations.
  Cold ETA is Estimating, stable live evidence permits an approximate range, variable
  or stalled evidence suppresses it, and the display expires evidence after five
  seconds. Existing polling ages observations only. Generation and per-job tokens
  reject stale progress. Cancel/failure never emit success. Success retains x/x checked.
- The inactive Grid detached its model, while source refresh reset the entire Qt
  model, including same-UUID availability-only updates. Retained/pooled Grid delegates
  could keep stale record roles across this lifecycle. Both presentations now stay
  attached to the authoritative SourceBrowserModel. Same-ID updates emit record-role
  dataChanged; only membership/order changes reset the projection. Hidden thumbnail
  access is independently gated, preserving lazy decoding and project isolation.
- SourceBrowserModel owns a set of stable UUIDs and an anchor. Plain click replaces;
  Ctrl toggles; Shift selects an inclusive range in current visible ordering;
  Ctrl+Shift adds the range; Ctrl+A selects visible rows. List/Grid retains selection,
  filter/group changes clear it, refresh intersects with visible UUIDs, project changes
  clear it. Delegates read a constant-time selected role, never search peer delegates.
- Exclude/Restore on a selected source uses the selected set, otherwise just the
  clicked source. The batch bar uses that same participation draft/Save path. Create
  Group now creates and assigns in one draft; Move/Ungroup uses one batch draft.
  Every command performs one ProjectService Save/CAS, drains readers and waits for
  authoritative readback. Failed saves discard drafts without optimistic UI state.
- Add Folder previews supported relative parent counts. Root files stay unassigned;
  child paths become flat labels such as Drone / Flight 1. Equal labels use fresh
  UUIDs and case-insensitive (2)/(3) suffixes. The inventory commit accepts the prepared
  organization intent and publishes it with the inventory reference in one existing
  metadata CAS. No separate group Save/recovery mechanism is needed. Failure/cancel
  leaves no committed groups/assignments; relink/reopen retains saved intent.
- List places status immediately beside right-edge Preview/Details/participation icons.
  Grid uses the same SourceActions component at the thumbnail's upper right. Icon-only
  controls have accessible names, focus, hover and tooltip behavior, and child clicks
  do not activate the source delegate. Contextual batch controls appear only for
  multiple sources. At minimum height the check explanation yields to batch controls
  so thumbnails and icon actions remain visible. Rename/Delete remain secondary.
- Preview participation always edits its current photo alone, regardless of browser
  selection. Before mutation it snapshots ordered photo UUID neighbors within the
  visible filter/group scope. After committed readback it tries next neighbors, then
  previous neighbors, then closes if none survive; this also advances in All. It never
  increments a post-filter index. Counter/title/description/status refresh together,
  the previous image is cleared before decode, and a new image token rejects late
  replies. Pending mutation disables repeated Preview actions until readback. Failed
  Save keeps the current image; explicit scope/project change closes Preview. No
  video decoder, unbounded predecode, filesystem Delete or processing UI was added.

The authoritative contracts are in [GUI_DESIGN](../../GUI_DESIGN.md#m12b3-capture-metadata-and-groups)
and [PROJECT_FORMAT](../../PROJECT_FORMAT.md#capture-evidence-and-logical-source-groups-m12b3).
Group/device labels, selection, presentation and availability remain independent of
processing source/camera UUIDs. Existing actual Views cache-reuse tests remain required;
folder labels never become captured device evidence or numerical recipe fields.

### Corrective file map

| Files | Purpose |
| --- | --- |
| application/media.py, media_progress.py; GUI controller.py, presentation.py | Real verification observations, live-only ETA and stale-job guards |
| adapters/media_storage.py; application/logical_source_groups.py | Atomic inventory-plus-folder intent and selected-set Create/assign |
| GUI qml_media.py, qml_bridge.py | Authoritative role refresh, UUID selection, shared mutations and guarded Preview navigation |
| SourcesPage, SourceActions, SourceGroupsDialog, ImportPreviewDialog | Compact source actions, selection, contextual batches and folder preview |
| SourcePreviewDialog, SplatButton, Main, info/exclude SVG | Current-photo mutation, focus tooltips and progress percentage |
| test_media_verification_progress, test_folder_source_groups, test_qml_m12b3_corrective | Work/ETA, atomic grouping, real Qt interactions and failures |
| test_qml_source_participation | Existing regression updated for intentional filter selection clearing |
| GUI_DESIGN, PROJECT_FORMAT, this plan | Authoritative contracts and corrective evidence; ACTIVE retained |

### Corrective verification evidence

Entry: branch feat/m12-qml-premium-ui, HEAD 40375875ff1cb170baa98783d62a5582180a8d60,
empty index, 55 existing dirty/untracked files. Entry hashes/full diff are ignored
under sample_data/m12b3-corrective. No unrelated cleanup or registry.py E501 repair.

Codex ran the affected backend set: **93 passed in 41.43 s**. Exact command:

```powershell
.venv/Scripts/python.exe -m pytest tests/test_capture_metadata.py tests/test_logical_source_groups.py tests/test_folder_source_groups.py tests/test_media.py tests/test_media_import_progress.py tests/test_media_verification_progress.py tests/test_media_ingest_cancel.py tests/test_source_participation.py tests/test_gui_architecture.py -o addopts='' -q -ra --tb=short
```

This includes actual ViewsService cache reuse across organization changes, persisted
capture/relocation/relink, atomic project failures and participation regressions.
No numerical implementation or recipe projection changed in this corrective pass.

Early corrective runs are retained: a PySide inherited notify/property redeclaration
caused a native engine crash; subclass-owned multi-selection notifications fix it.
A test removed a fixture while a thumbnail reader held it open; it now drains owned
readers first. The first broad Qt run was 68 passed / 6 failed: four old assertions
expected selection retention after filter changes; two new accessibility assertions
used the root context without QtQuick imports. Tests now follow the new contract and
use the item's QML context. Superseding final outcomes are recorded below.

The next focused run was 32 passed / 2 failed and exposed a real Grid input conflict:
the modifier-reading MouseArea could intercept nested icon events. It was removed;
Qt Controls now owns event delivery and the selection command reads that event's
keyboard modifiers. All four real pointer/keyboard regressions then passed (25.92 s).
The final affected run below includes those tests and supersedes the intermediate runs.

Final Codex verification (2026-10-28): **239 passed, no skips** across the following
three disjoint affected selections. This is not full H.

| Selection | Result | Local log |
| --- | --- | --- |
| Backend command above | 93 passed, 41.43 s | sample_data/m12b3-corrective/backend.log |
| Qt source command below | 81 passed, 422.81 s | sample_data/m12b3-corrective/qt-final.log |
| CLI/general desktop command below | 65 passed, 36.02 s | sample_data/m12b3-corrective/consumers.log |
| Scoped Ruff, all 22 M12b3 Python files | Passed | sample_data/m12b3-corrective/ruff.log |
| All-QML qmllint | Passed, no warnings | sample_data/m12b3-corrective/qmllint.log |
| Documentation checker | 43 Markdown files, 0 errors | sample_data/m12b3-corrective/docs.log |
| Whitespace/scope audit | Passed; empty index, unchanged HEAD | sample_data/m12b3-corrective/preservation.json |

```powershell
.venv/Scripts/python.exe -u -m pytest tests/test_qml_m12b3_corrective.py tests/test_qml_capture_groups.py tests/test_qml_source_participation.py tests/test_qml_sources_corrective.py tests/test_qml_sources.py -o addopts='' -q -ra --tb=short
.venv/Scripts/python.exe -u -m pytest tests/test_media_cli.py tests/test_qml.py tests/test_desktop.py -o addopts='' -q -ra --tb=short
$pythonFiles = Get-Content sample_data/m12b3-corrective/python-files.json | ConvertFrom-Json
.venv/Scripts/python.exe -m ruff check $pythonFiles
.venv/Scripts/pyside6-qmllint.exe -I src/splatforge_gui/qml -I src/splatforge_gui/qml/theme (Get-ChildItem src/splatforge_gui/qml -Recurse -Filter *.qml).FullName
.venv/Scripts/python.exe scripts/check_docs.py
git diff --check
```

The 24 exact corrective files are recorded in sample_data/m12b3-corrective/corrective-files.json.
All **30 unrelated entry files** match their original SHA-256, including COLMAP,
feature-budget/progress, benchmark/Tanks and Temples, active experiment and shared
documentation hunks. Existing M12b3 files were extended in place. HEAD remains
40375875ff1cb170baa98783d62a5582180a8d60; index is empty. Nothing was staged,
committed, pushed, reset, discarded, installed or downloaded by this pass.

### Corrective native visual verification

Codex captured the real Windows Qt platform with synthetic JPEG/video fixtures and
isolated UI settings: **43 captures**, Dark/Light at exact 1024x640 and 1440x900,
DPR 1, zero QML warnings. Manifest, captures and six reviewed contact sheets are
under sample_data/ui-review/m12b3-corrective. Native scripts/logs remain ignored under
sample_data/m12b3-corrective. Real verification is deliberately slowed by an injected
0.65-second source-evidence fixture to make cold/live ETA observable; no UI progress
is simulated. The normal reporter/estimator, controller signals and native shell render it.

Inspected List right-edge status/actions, Grid icon hierarchy, mouse single/Ctrl/Shift
selection and batch bar, folder-created scopes, Excluded cards, cold/live progress,
photo Preview before/after exclusion, long groups, hover tooltips and keyboard focus.
Initial visual review found clipped bottom Grid actions at minimum height; final Grid
uses upper-right thumbnail actions and yields the small check explanation to batch
controls, restoring useful thumbnails and fully visible buttons. Representative final
full-size captures and every contact sheet were inspected. Original fixtures remain
present. These are agent checks, not the user's manual UX acceptance.

Remaining boundaries: Preview reviews photos within the current visible source scope;
video remains a placeholder without playback. ETA is live-only and may legitimately
remain unavailable for very fast/heterogeneous checks. Existing M12b3 bounded metadata
and no-backfill limits remain. Full H and global Ruff were not run; the existing
unrelated core/registry.py:52 E501 remains untouched. M12c was not started.

### Manual review checklist for the user

1. With many sources, Check Source Files: x/total and percent advance, ETA starts
   Estimating then becomes approximate with evidence; Cancel never reports completion.
2. Verify in List, switch Grid, and reverse: Available/Missing/Needs attention agree.
3. Try Details/Preview/Exclude/Restore icons, tooltips, Tab/Space and absence of
   accidental Preview. Originals must remain untouched.
4. Click, Ctrl toggle, Shift range, Ctrl+A; switch List/Grid and preserve UUIDs.
   Change filter/group and confirm the selection clears. Exclude/Restore the set.
5. Select several sources, Create Group, Move/Ungroup and reopen; all assignments persist.
6. Add Folder with Drone/Phone/Videos and nested Flight folders. Check preview counts,
   persisted groups, collision suffixes and separation from captured device metadata.
7. At 1024x640 Dark/Light, check right-aligned List status, Grid thumbnails/actions
   and contextual bar; at 1440x900 also check long labels and mixed groups.
8. Preview B in A/B/C/D, Exclude, expect C. Exclude the last, expect previous; remove
   the only in-scope photo, expect clean close. Restore in Excluded uses the same rule.
   Browser multi-selection must never turn Preview's action into a batch mutation.

Full H commands above are prepared only; do not run until the user's next manual
acceptance. M12c remains unstarted. M12b3 remains ACTIVE, unstaged and uncommitted
pending manual UX acceptance.

## Isolated review snapshot (2026-10-28)

The user explicitly requested a separate commit of the current application state
and its plan for review, outside main. This authorizes staging/committing the M12b3
implementation and corrective pass on `codex/m12b3-ux-review`, superseding the earlier
unstaged/uncommitted restriction for this review snapshot only. It does not establish
manual UX acceptance, close M12b3, authorize a push/merge or start M12c/full H.

The commit includes the initial M12b3 slice, corrective changes, tests and current
authoritative contracts/plan. Shared roadmap/index files stage only M12b3 hunks.
Unrelated COLMAP, feature and Tanks and Temples changes remain in the working tree.
The existing 239-test affected evidence remains valid for unchanged implementation;
staged-tree checks and commit scope are recorded in ignored review-snapshot evidence.
