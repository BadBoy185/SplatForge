# Interface alignment and Materials workspace

Status: ACTIVE — Projects/Create layout is user-accepted. Materials redesign,
import and bounded stabilization are delivered. Saved-video-usage backend and the
Materials / Trim interface are delivered; independent review and bounded corrections
are recorded in the 2026-10-29 section below.
The latest Materials/Trim visual refinement is user-accepted in the 2026-10-29
continuation. Manual functional Materials/Trim and M12b3 scenarios are not thereby
recorded as performed by the user.
The previous combined-tree full gate is closed by the continuation's passing
pre-implementation run. The later folder-relink full run was stopped by direct user
request; its full result is absent. Earlier failures and Ruff evidence remain history.
The user authorized and received [M12c1](../completed/2026-10-29-m12c1-prepare-data.md)
with short targeted checks; the new verification rule requires a separate direct
request for every full/long run. Manual functional acceptance remains open.
Owner: Codex, 2026-10-29.
Verified entry branch/HEAD (also rechecked after the tool interruption):
`codex/m12b3-ux-review`, `4d83147acb01907ce02b1311977608f23d6eab17`.
This HEAD is only the review snapshot: the inspected working tree includes later
dirty shell/media/Plan/controller/tests and documentation changes. It is not a clean
snapshot checkout. Entry hashes/diff are retained locally under
`sample_data/design-preparation-entry-hashes.json` and `design-preparation-entry.diff`.
Preserve all pre-existing COLMAP/benchmark edits. No commit/push/merge.

## Continuation and visual acceptance — 2026-10-29

The user explicitly accepted the latest Materials/Trim visual refinement and
authorized closure of the outstanding technical gates followed by one bounded
next scenario. This supersedes earlier stop-for-visual-acceptance instructions.
It does not establish user completion of the functional manual checklists.
The [M12b4 folder relink plan](2026-10-29-m12b4-folder-relink.md) owns this continuation,
the new entry snapshot, pre-implementation full gate and final verification.
That mandatory broader-M12b gap is implemented; its later full run is now stopped
without a full result. The subsequently authorized M12c1 is delivered, without
claiming manual acceptance of the older work. Older dated results below are historical.

## Visual density and control refinement — 2026-10-29

Current authorized slice: refine the existing QML visual language using fresh native
Projects/Materials/Trim captures and catalog references 01–04. Preserve the accepted
Projects/Create arrangement, all Materials/Trim/M12b3 corrections and Dark/Light;
M12c remains unstarted. User acceptance and the previously open full gates stay open.

Entry rechecked: `codex/m12b3-ux-review`, HEAD
`4d83147acb01907ce02b1311977608f23d6eab17`, empty index. All 498 entry files and
SHA-256 hashes are saved under ignored `sample_data/visual-polish-20261029/entry/`
and `entry-hashes.json`; the same directory holds entry Git diffs and status.

| Owner | Exclusive files / resources |
| --- | --- |
| Main | Documentation, ignored capture/audit harness, combined verification; all native Qt runs, synthetic fixture, settings and caches |
| Implementation, Sol/high requested | Theme singleton; shared SplatButton/ComboBox/TextField/CheckBox/Badge; Materials SourcesPage, MaterialProperties/Viewer, VideoTrimProperties/Timeline; optional Main menu-token consistency only |
| UX reviewer, Terra/medium requested | Read-only actual reference/before/after image review; no app runs or edits |
| Fresh reviewer, Sol/high requested | Read-only final task-only code diff; no app runs or edits |

No nested delegation, no team configuration changes, no Git publication/cleanup.
Before any product edit, native Windows QtTest captures recorded actual 1440×844
logical / 1800×1055 raster and 1024×640 / 1280×800, DPR 1.25, both themes. Window
size/Windows scale preferred by the user are unknown; these match the last primary
review conditions. `before/manifest.json` records actual screen geometry and DPI.
Synthetic originals and one project are reused across comparison phases.

Observed diagnosis: panels are already square with modest 4 px control corners;
there are no observed decorative nested cards, gradients, shadows or blurred UI
text/icons. Repeated 36 px raised semibold controls, 48 px panel headings, 88 px
catalog rows and generous inspector spacing dominate the chrome. The enlarged
320×180 test video is deliberately low-resolution media, not UI-rendering blur.
Calibrate 32 px controls with visible focus, 40 px panel headings, 80 px rows,
normal secondary labels, aligned 20 px icons and smaller inspector gaps; retain
14 px body text and actual thumbnails. A 2 px control radius is a restrained style
choice, not a claimed correction of a large-radius defect. No global font-rendering
or palette inversion change is justified.

### Integrated visual result and review

Implementation changed exactly 11 QML files, listed in the ownership table above;
Main.qml, Projects/Create composition, Python product code and tests are unchanged.
The [GUI design](../../GUI_DESIGN.md#visual-density-calibration--2026-10-29) owns
the delivered values: 32 px controls / 10 px text inset / 20 px icons / 40 px panel
headings / 12 px inspector inset / 8 px metadata gap / 80 px source rows with
80×60 thumbnails / 48 px range rows. Controls use 2 px corners; popup menus retain
4 px. Body and secondary text remain 14/12 px. Ordinary button labels use normal
weight; primary stays semibold. Range selection is a flat surface and accent edge,
with an independent 2 px keyboard-focus outline. Palettes and font rendering did
not change. The actual photo remains fitted, with correct letterboxing.

Main owns ignored `sample_data/visual-polish-20261029/` evidence:

- `before/` and `after/`: **20 matching captures per phase**, same fixture, names,
  actual sizes/DPR/screen, themes, current material, 2.5 s video position, ranges
  1–2 and 3–5 and selected second range. Manifests contain no QML warnings.
- `comparison.html`, `REVIEW.md`, `materials-overview.png`, `trim-controls-dark.png`,
  `trim-controls-light.png`, `catalog-controls.png`, `timeline.png`: full screens
  and lossless crops. No retouched or generated replacement UI screenshots.
- `native-style/`: real group Move/Ungroup with selected A / viewed B and committed
  UUID checks, batch Exclude/Restore, original-byte checks, actual splitter drag
  to 260 px, measured 32 px control heights, distinct selection/Tab focus/hover,
  compact inspector scroll to lower actions, Use entire clip, Close and Restore.
- `native-trim/`: existing `scripts/capture_materials_trim.py` passed Play/Pause,
  ruler seek, scrub, used-only skip/stop, exact Save/reopen and photo/video switches.
  Saved exact endpoints were `501/500`–`999/500` and `3`–`2499/500`; no frame-accurate
  Qt seek claim. Actual large window was 1440×849, compact 1024×640, DPR 1.25.
- `native-lifecycle/`: existing `scripts/check_materials_video_lifecycle.py` passed
  closed review unload, Projects/resume paused with retained selection/generation,
  project switch reset and active-playback window close. Actual 1440×849, DPR 1.25.
- `missing-tool/`: process-scoped `SPLATFORGE_FFMPEG` named an absent owned `.exe`.
  Current Dark/Light and compact captures show the real optional-tool explanation;
  exact Include/Exclude still work. Installed tools were not changed. Exit 0.

The main native comparison and diagnostic windows use Windows Qt, not offscreen.
QT_SCALE_FACTOR supplies DPR 1.25; this is **not** proof of the user's OS scale.
Virtual WinDisc reports invalid physical DPI, so no physical-DPI inference is made.
grabWindow captures the client area; native title-bar flags remain enabled. The
Computer Use kernel still fails Windows 1385; QtTest input is agent-driven native
testing, not manual Windows/Explorer evidence. Before-state additions loaded the
frozen entry QML without reverting or changing the working tree.

UX reviewer independently inspected references and both themes before/after, plus
260 px and scrolled/closed compact captures: no new visual defect found. It caught
an initially mislabeled closed-overlay capture: focused input consumed Escape.
The harness now clicks actual Close, asserts visual-tree disappearance and recaptures
both phases; reviewer confirmed the correction. No product defect was involved.
A fresh independent code reviewer compared all 11 QML changes against entry,
checked consumers/adaptive layouts and found no confirmed defect. Implementation
stopped editing before the final native and affected checks. Three real agents were
used, no nested delegation; requested Terra/medium for UX and Sol/high for
implementation/reviewer. Actual serving-model metadata is unavailable. Main model
and team configuration were not changed.

### Verification of the visual slice

Main ran one combined affected suite on the final product tree, existing Windows
Python 3.12.10 / PySide6 and Qt 6.12.0, offscreen DPR 1, isolated caches/temp:
**155 passed, 1 skipped, 372.16 s, exit 0** (`affected-pytest.log`). The only skip
is the unconfigured real FFprobe opt-in (`SPLATFORGE_TEST_FFPROBE`); the separate
native fixture runs explicitly used the installed `C:/Tools/ffmpeg/bin/ffprobe.exe`.

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
$env:QT_SCALE_FACTOR = '1'
$env:XDG_CACHE_HOME = 'C:/Dev/SplatForge/sample_data/visual-polish-20261029/test-cache'
& .venv/Scripts/python.exe -m pytest `
  tests/test_projects_entry.py tests/test_materials_composition.py `
  tests/test_materials_selection_actions.py tests/test_materials_stability.py `
  tests/test_qml_trim_editor.py tests/test_video_trim.py tests/test_video_filmstrip.py `
  tests/test_thumbnail_suspension.py tests/test_qml_m12b3_corrective.py `
  tests/test_qml_sources_corrective.py `
  tests/test_qml.py::test_qml_engine_loads_dark_light_and_all_destinations `
  tests/test_ffprobe.py tests/test_capture_metadata.py `
  --basetemp=sample_data/visual-polish-20261029/test-tmp `
  -o cache_dir=sample_data/visual-polish-20261029/pytest-cache
```

Main all-QML qmllint: **46 files, exit 0, no warnings** (`qmllint.log`), using
`-I src/splatforge_gui/qml` and every `.qml` file. This is the final result; the
implementation agent's earlier scoped invocation reported an entry-reproduced
singleton warning. Full Ruff again reports only the unchanged unrelated E501
at `core/registry.py:52` (`ruff-full.log`). No Python product/test file was changed
by this slice. Full pytest was not rerun for this bounded visual change; its prior
failed full attempt and the full Ruff gate remain open as recorded below. Passing
affected tests does not close either gate or Materials/Trim/M12b3 user acceptance.

Main final `scripts/check_docs.py`: **49 Markdown files, 0 errors**;
`git diff --check`: exit 0 (`docs-final.log`, `diff-check-final.log`). Preservation
audit covers all 498 entry files: 484 unchanged, 14 scoped changes (11 QML and
GUI_DESIGN/PROJECT_STATE/this plan), no new nonignored, missing or unexpected files
and no corrupt entry snapshots. Branch/HEAD unchanged, index empty. Existing
ffprobe.py, thumbnails.py, qml_media.py, SourceGroupsDialog.qml and
VideoTrimSession.qml remain byte-identical to entry; the two visually touched
functional-fix files retain their reviewed handlers. `preservation.json` and final
`task.diff`/`task-files.json` contain the audit and complete task-only delta. User
review should evaluate density and ordinary-label weight, Dark/Light readability
and focus/selection, compact Trim, and the familiar Projects/Create arrangement.
Real user media/VFR/audio/codec breadth, Explorer drop, screen reader, OS/per-monitor
100/150/200% scaling and explicit user visual acceptance remain manual boundaries.
This plan and M12b3 stay ACTIVE; M12c remains unstarted.

## Independent Materials / Trim / M12b3 review — 2026-10-29

Scope: review the current dirty implementation, fix confirmed defects and prepare
manual acceptance. The accepted Projects/Create layout remains unchanged; M12c
is not started. The current request authorizes the full verification attempt for
this combined tree, superseding older task-specific instructions to defer full H.
Implementation, automatic checks, native agent review and user acceptance remain
separate. **User acceptance is open.**

Entry was verified as `codex/m12b3-ux-review` / `4d83147acb01907ce02b1311977608f23d6eab17`,
with an empty index. All 496 tracked/untracked entry files, hashes, staged and
unstaged diffs were saved under ignored `sample_data/materials-review-20261029/`.
The first two independent reviews inspected this frozen entry before product edits.
Historical selection/native-failure notes below do not replace fresh reproduction.

Ownership and resources:

| Owner | Exclusive changes / resources |
| --- | --- |
| Main | Group/catalog commands, Trim transport and their regression tests; metadata/Sources/theme consumer tests, documentation, task diff, combined checks |
| Implementation role | `thumbnails.py`, activity hook in `qml_media.py`, dedicated suspension tests |
| Tester role | Stream-duration normalization in `ffprobe.py`, `test_ffprobe.py`; isolated non-Qt tests; then exclusive capture-groups/participation consumer tests and serialized Qt reproduction |
| Initial code reviewer | Read-only Materials/Trim/M12b3 review |
| UX reviewer | Read-only native application scenarios, isolated synthetic projects and screenshots |
| Fresh final reviewer | Read-only task diff against entry and combined implementation |

Qt/application runs are serialized: initial native review, thumbnail tests, main
focused tests, final native review, full default tests, native source switch, entry
consumer reproduction/affected Qt checks, then the settled native frame check. No shared project is
used by competing processes. Named role selectors and explicit requested models/
efforts are supported: reviewer/implementation Sol high, tester Sol medium, UX
Terra medium. Actual serving-model metadata is not exposed; requests are not proof
of the serving model. No nested agents or orchestration changes.

Confirmed findings and corrections (P2 unless marked; behavior or resource lifetime):

| Trigger / actual defect | Affected code | Correction and regression evidence |
| --- | --- | --- |
| Highlight A, view B, Move to Group with one highlighted item: handler targeted B | `SourceGroupsDialog.qml` | Always use explicit selected UUIDs, show selected count, disable Move with no batch; group assignment and Ungroup are checked against committed project data |
| Current source participation differs from highlighted batch: catalog menu chose operation using current source | `SourcesPage.qml` | Separate explicit Exclude selected / Restore selected commands; mixed current/batch tests assert saved UUIDs |
| Play before loading completes: zero duration and nonseekable player latched intent without playing | `VideoTrimSession.qml` | Ignore NoMedia/Loading/InvalidMedia; zero-duration loaded streams can start without seeking; failed seek does not retain resume intent |
| Pause/error during a scrub: releasing it restored pre-Pause resume | `VideoTrimSession.qml` | Pause/error/workspace exit revoke unfinished scrub and resume intent; controlled-player tests preserve ordinary scrub resume |
| Hide Materials / close with thumbnail queue: all queued hidden photos continued decoding | `thumbnails.py`, activity hook in `qml_media.py` | Revoke queued/postponed requests and stale delivery, preserve cache URLs, retain active-worker ownership until real completion; controlled held-worker/close tests |
| Delayed video stream lacks duration: container duration was used as stream duration, creating a false Trim tail | `adapters/ffprobe.py` | Keep missing/N/A selected-stream duration unknown; exact fields retain their documented unknown-duration behavior; six probe normalization cases |
| Enter Trim in a native window without animation ticks: the initial filmstrip debounce stays running and no frames are requested | `VideoTimeline.qml` | Queue the initial bounded request with `Qt.callLater`, reading current viewport/context on delivery; retain populated-viewport debounce; regression stops the animation timer on entry |
| P3: unavailable FFmpeg sets a model message but the timeline silently shows no frames | `VideoTimeline.qml` | Display the existing optional-preview error in the timeline hint, wrapping at compact width; exact editing remains enabled |

The native group mismatch was captured before correction in
`ux-initial/group/group-mismatch.png`; the action consequence was then verified by
the committed-data regression. Seven new selection/transport cases fail against
entry QML; four suspension tests fail against verified entry imports; two duration
cases fail against the entry adapter. These checks did not roll back the working
tree. No assertions were weakened and no skips were added to hide failures.

The final native correction is intentionally small: first-frame scheduling does
not depend on a render tick in an occluded window; no repeated probe, polling,
new preview store or unbounded callback queue was introduced. Queued functions
resolve current context and reject hidden/inactive/unmapped timelines. A fresh
read-only reviewer independently inspected this delta without finding a confirmed
defect. The missing-tool hint is covered by a failed-before/passed-after GUI test.

### Verification of the combined tree

Windows Server 2022; existing Python 3.12.10 / PySide6 and Qt 6.12.0 `.venv`.
No dependency/model/codec installation or GPU/backend job. Main owns the full run;
backend opt-ins are unset. The following exact selections are not additive totals:

| Owner / command selection | Result / log under `sample_data/materials-review-20261029/` |
| --- | --- |
| Main focused combined Qt command below | 47 passed, 212.80 s; `focused-final.log` |
| Main final Trim/filmstrip delta command below | 7 passed, 22.53 s; `filmstrip-final.log`; reruns affected behavior after the last product edit |
| Tester `test_ffprobe.py test_video_usage.py test_media.py test_views_core.py` | 106 passed, 1 skipped, 15.45 s; `timing/pytest-fix.log`; opt-in real FFprobe test unconfigured |
| Main real CPU FFmpeg/VFR `test_video_usage_integration.py test_video_preview_integration.py` | 2 passed, 3.15 s; `vfr-integration.log`; separate projects/cache/temp, explicit existing FFmpeg/FFprobe, no Qt/GPU |
| Implementation `test_thumbnail_suspension.py` | 4 passed; `thumbnails/pytest-close-fixed.log`; earlier seven-case affected selection includes cache/namespace and 1500-source cases, `thumbnails/pytest.log` |
| Main full default pytest | 1967 passed, 18 failed, 74 skipped, 4431.69 s, exit 1; `full-pytest.log`; full gate open |
| Main corrected metadata consumer fixture, `test_capture_metadata.py` | 14 passed, 3.74 s; `metadata-fixed.log`; explicit selected-stream duration, all assertions retained |
| Tester verified-entry Qt reproduction | All 17 selected failures reproduced, 76.70 s; `consumer-tester/entry-reproduction.log` |
| Tester final `test_qml_capture_groups.py test_qml_source_participation.py` | 25 passed, 166.27 s; `consumer-tester/current-fixed.log`; scoped Ruff passed |
| Main `test_qml_sources.py test_qml_sources_corrective.py` | 33 passed, 2 test-only lookup failures, 119.25 s; `source-consumers-fixed.log`; final two-case rerun passed in 8.70 s (`source-footer-fixed.log`) |
| Main five previously noisy teardown scenarios with `-s` | 5 passed, 29.75 s; `signal-delta.log`; stdout/stderr visible, no deleted-signal/RuntimeError/fatal diagnostic |
| Main full Ruff | Same entry E501 at `core/registry.py:52`; unrelated file unchanged; `ruff-final.log` |
| Main final all-QML lint / scoped Python Ruff | All 46 QML files passed with no warnings; all 13 changed Python/test files passed; `qmllint-final.log`, `ruff-scoped-final.log` |
| Main docs / whitespace / entry preservation | 49 Markdown files, 0 errors; diff check exit 0; 496 entry hashes/snapshots verified, 478 unchanged/18 scoped changed + 2 new tests; no missing/unexpected paths; index empty, branch/HEAD unchanged |

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
$env:PYTHONFAULTHANDLER = '1'
.venv/Scripts/python.exe -u -m pytest tests/test_materials_selection_actions.py tests/test_video_trim.py tests/test_qml_trim_editor.py tests/test_materials_stability.py tests/test_video_filmstrip.py tests/test_qml_m12b3_corrective.py -o cache_dir=sample_data/materials-review-20261029/main-cache -o faulthandler_timeout=60 -vv -ra --tb=short
.venv/Scripts/python.exe -u -m pytest tests/test_qml_trim_editor.py tests/test_video_filmstrip.py -o cache_dir=sample_data/materials-review-20261029/main-cache -o addopts='' -q --tb=short
.venv/Scripts/python.exe -m pytest tests/test_ffprobe.py tests/test_video_usage.py tests/test_media.py tests/test_views_core.py -o cache_dir=sample_data/materials-review-20261029/timing/pytest-cache-fix --basetemp=sample_data/materials-review-20261029/timing/pytest-tmp-fix
.venv/Scripts/python.exe -u -m pytest -vv -ra --tb=short -o cache_dir=sample_data/materials-review-20261029/full-cache -o faulthandler_timeout=60 --basetemp=sample_data/materials-review-20261029/full-tmp
.venv/Scripts/python.exe -m ruff check .
```

The separate real VFR command used process-local paths
`SPLATFORGE_TEST_FFMPEG=C:/Tools/ffmpeg/bin/ffmpeg.exe` and
`SPLATFORGE_TEST_FFPROBE=C:/Tools/ffmpeg/bin/ffprobe.exe`:

```powershell
.venv/Scripts/python.exe -u -m pytest tests/test_video_usage_integration.py tests/test_video_preview_integration.py -o cache_dir=sample_data/materials-review-20261029/vfr-cache --basetemp=sample_data/materials-review-20261029/vfr-tmp -o addopts='' -q -ra --tb=short
```

It verifies nonzero source origin, changing VFR pixels, restricted publication,
original immutability and input-seeked preview. It does not establish native player
behavior with arbitrary distinct audio/video origins. Default-run opt-ins remain unset.

One new consumer-fixture failure was independently reproduced during the full run:
`test_capture_metadata.py::test_video_container_metadata_roundtrip_and_persistence`
expected saved duration 12.5 although only the container supplied it. This is caused
by the corrected normalization, not an entry failure. `metadata-entry.log` records
the exact assertion. A reviewer confirmed that supplying explicit stream duration
in this metadata-roundtrip fixture preserves every original assertion; the corrected
file passed all 14 tests after the frozen full attempt.

The other 17 full-attempt failures were independently reproduced against saved
entry imports. `consumer-tester/run_entry.py` asserts `ffprobe.__file__` and
`qml_app.__file__` live below entry/src, and disables pytest's `pythonpath` override.
All failed at the same assertions as the current full run, before any consumer
test edits; the selected test files still matched entry at that invocation. The
printed command is historical evidence: rerunning it after test edits is not the
same baseline experiment. The entry reproduction captured one nonfatal `Signal source has been
deleted`; it exited normally with test failures, without an access violation.
The final main follow-up reran the five previously noisy scenarios with capture
disabled (`-s`): all passed, and the complete log contains only progress/results.
No deleted-signal/RuntimeError/fatal diagnostic reproduced there. This is bounded
teardown evidence, not proof of every native race.

Consumer corrections preserve semantics: UUID-specific row Details/participation,
the actual catalog menu and check dialog, genuine project switch/reopen instead of
same-project Resume, exact quiet-secondary/ghost colors in both directions and a
selected border. No saved-data, original-byte, no-rehash, availability, modal-preview,
keyboard or disabled-action assertion was removed or relaxed. The main's first
consumer rerun exposed its own new popup lookup mistake; querying the owning Sources
page fixed both footer cases. Both final size cases passed with the dialog visibility,
pagination, action availability, bounds and hidden-technical-evidence assertions intact.
A fresh independent reviewer inspected the final test repairs without confirmed findings.

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
$env:PYTHONPATH = (Resolve-Path sample_data/materials-review-20261029/entry/src).Path
.venv/Scripts/python.exe sample_data/materials-review-20261029/consumer-tester/run_entry.py
$env:PYTHONPATH = (Resolve-Path src).Path
.venv/Scripts/python.exe -m pytest tests/test_qml_capture_groups.py tests/test_qml_source_participation.py -o cache_dir=sample_data/materials-review-20261029/consumer-tester/current-cache --basetemp=sample_data/materials-review-20261029/consumer-tester/current-tmp -vv --tb=short -ra
.venv/Scripts/python.exe -u -m pytest tests/test_capture_metadata.py -o cache_dir=sample_data/materials-review-20261029/metadata-cache --basetemp=sample_data/materials-review-20261029/metadata-fixed-tmp -o addopts='' -q --tb=short
.venv/Scripts/python.exe -u -m pytest tests/test_qml_sources.py tests/test_qml_sources_corrective.py -o cache_dir=sample_data/materials-review-20261029/source-consumers-cache --basetemp=sample_data/materials-review-20261029/source-consumers-tmp -vv -ra --tb=short -o faulthandler_timeout=60
.venv/Scripts/python.exe -u -m pytest tests/test_qml_sources.py::test_sources_actions_footer_and_no_empty_pagination -o cache_dir=sample_data/materials-review-20261029/source-consumers-cache --basetemp=sample_data/materials-review-20261029/source-footer-fixed-tmp -o addopts='' -vv -ra --tb=short
.venv/Scripts/python.exe -u -m pytest 'tests/test_qml_capture_groups.py::test_device_sections_scope_both_browsers_and_saved_details[Grid]' 'tests/test_qml_source_participation.py::test_exclude_restore_filters_details_preview_and_availability[photo-List]' 'tests/test_qml_sources.py::test_explicit_pickers_import_and_reopen_persisted_types[photos-3]' 'tests/test_qml_sources.py::test_explicit_pickers_import_and_reopen_persisted_types[videos-1]' 'tests/test_qml_sources.py::test_explicit_pickers_import_and_reopen_persisted_types[videos-2]' -o cache_dir=sample_data/materials-review-20261029/signal-cache --basetemp=sample_data/materials-review-20261029/signal-tmp -o addopts='' -s -q --tb=short
```

The full attempt's 421 source/test/script hashes remained unchanged throughout
(`full-run-freeze-audit.json`). Only five test files changed afterward. All 18 failed
nodes now have passing affected evidence; the 1967 passing full-run nodes remain
applicable. This is a reconciled verification record, not a claim that one final
full pytest command passed. **Full gate remains open:** exit 1 on the full command,
test-only follow-ups rather than a second full run, and the reproduced unrelated
full-Ruff E501. Backend integration skips remain explicit; none were added to hide
failures. M12c remains unstarted; Materials/Trim/M12b3 user acceptance remains open.

Final low-cost commands (main; results in the table above):

```powershell
.venv/Scripts/python.exe -m ruff check src/splatforge/adapters/ffprobe.py src/splatforge_gui/qml_media.py src/splatforge_gui/thumbnails.py tests/test_capture_metadata.py tests/test_ffprobe.py tests/test_qml_capture_groups.py tests/test_qml_source_participation.py tests/test_qml_sources.py tests/test_qml_sources_corrective.py tests/test_qml_trim_editor.py tests/test_video_trim.py tests/test_materials_selection_actions.py tests/test_thumbnail_suspension.py
$qmlFiles = (Get-ChildItem -LiteralPath src/splatforge_gui/qml -Recurse -Filter '*.qml').FullName
.venv/Scripts/pyside6-qmllint.exe -I src/splatforge_gui/qml -I src/splatforge_gui/qml/theme $qmlFiles
.venv/Scripts/python.exe scripts/check_docs.py
git diff --check
.venv/Scripts/python.exe sample_data/materials-review-20261029/audit_task.py
```

`task-files.json` lists the exact 20 source/test/document paths; `task-only.diff`
separates them from the dirty entry. `preservation.json` verifies the original
snapshot bytes as well as current containment/scope. No accepted Projects/Create,
COLMAP/runtime/benchmark or agent-configuration file changed in this task. No Git
mutation, source cleanup or implicit installation was performed.

Fresh combined Qt results include both old List/Grid selection cases, both old
Details/preview/keyboard cases and the missing/deleted/unbound expression guard.
They pass in an exit-0 process: neither old group-selection failure nor access
violation reproduced in these current scenarios. This is not universal native-crash
coverage. Initial offscreen auto-filmstrip evidence did not reproduce the native
timer condition; the final regression explicitly removes animation ticks instead.
One interim test-only failure came from a temporary Qt-owner wrapper being collected;
retaining the timeline owner fixed the test, without relaxing its assertion.

### Native GUI scenarios and evidence

Real exposed Windows Qt windows, QtTest input, disposable synthetic photo/moving
H.264 media and separate settings/projects. Normal GUI composition is
`DesktopViewModel` + `create_engine`, also used by `splatforge-gui`. This is native
agent evidence, not manual Windows input or user acceptance. The optional Computer
Use runtime fails before input with `CreateProcessWithLogonW 1385`; no system policy
or toolchain was changed. The command sandbox has the same failure; approved command
execution outside it was used.

Actual reviewed large size is **1440x844 logical / 1800x1055 physical**, limited by
host work area; minimum is **1024x640 / 1280x800**, actual DPR **1.25**. Dark and Light
captures use shared geometry. Earlier filename labels saying 1440 or requested
1440x900 do not establish a 900px actual viewport; manifests record actual values.
The additional source-switch diagnostics separately recorded actual 1440x900 and
DPR 1.0; they do not establish an OS/per-monitor scaling matrix.

| Sequence / observed behavior | Fresh evidence |
| --- | --- |
| Select photo A, view B, Groups, Move; saved readback assigns only A | `ux-final/group.log`, `ux-final/group/group-before-move.png` |
| Play advances; close preview unloads; Projects unloads; Return preserves generation/current/batch and reloads paused; switch to a second project using the same locator clears old UUIDs; close while playing stops/unloads | `ux-final/lifecycle/manifest.json`, `ux-final/lifecycle.log` |
| Same-project advancing video -> photo Ready with player unloaded/stopped -> same video paused -> explicit Play advancing; source UUID and error state match | `ux-final/source-switch.log`, `ux-final/source-switch/*.png`; native synthetic run exit 0, no QML warnings |
| Paused return's initial grab preceded painting; after 2 seconds the first frame is visible at position 0 without starting playback | `ux-final/source-switch-settled.log`, `ux-final/source-switch-settled/video-return-paused-settled.png`; inspected by main |
| Select/Include, subtract a middle section, seek/ruler/playhead, used-only skip then stop, exact Save/reopen, empty/reset, photo return, Settings focus; both themes and sizes | `ux-final/trim/manifest.json`, `ux-final/trim.log`, seven `ux-final/trim/*.png` captures; saved rational endpoints are in the manifest |
| Initial filmstrip automatically appears without explicit `requestFrames` after the scheduling fix | `ux-final/auto-delta.log`, `ux-final/auto-delta/automatic-frames.png`; before-fix `trim-repro.log` and `trim-repro/auto-filmstrip-before-request.png` |
| Actual playback reaches EndOfMedia, explicit Play advances again | `ux-final/natural-delta2.log`; signal and state sequence, not a screenshot-only claim |
| Missing photo and corrupt video show Retry; corrupt-video Play disabled; empty viewer clears inspector | `ux-final/errors/{photo-error,video-error,empty}.png`, `ux-final/errors.log`; raw OS photo-error wording is a minor presentation observation, no additional functional defect established |
| Missing FFmpeg: one failure, visible explanatory hint; Include still changes the draft; Dark/Light compact hint remains readable | `missing-tool-fixed.log`, `ux-final/missing-tool-fixed/missing-tool-{1440,1024-dark,1024-light}.png` |

Commands/harnesses (all evidence and copies remain ignored; no production script
was rewritten to suppress a failure):

```powershell
$env:QT_QPA_PLATFORM = 'windows'
$env:PYTHONPATH = (Join-Path (Get-Location).Path 'scripts')
$env:SPLATFORGE_FFMPEG = 'C:/Tools/ffmpeg/bin/ffmpeg.exe'
.venv/Scripts/python.exe scripts/check_materials_video_lifecycle.py --video sample_data/materials-review-20261029/ux-initial/synthetic.mp4 --ffprobe C:/Tools/ffmpeg/bin/ffprobe.exe --output sample_data/materials-review-20261029/ux-final/lifecycle
.venv/Scripts/python.exe -u sample_data/materials-review-20261029/ux-final/group_check.py
.venv/Scripts/python.exe -u sample_data/materials-review-20261029/ux-final/error_check.py
.venv/Scripts/python.exe sample_data/materials-review-20261029/ux-final/trim_review.py --video sample_data/materials-review-20261029/ux-initial/synthetic.mp4 --ffprobe C:/Tools/ffmpeg/bin/ffprobe.exe --output sample_data/materials-review-20261029/ux-final/trim
.venv/Scripts/python.exe sample_data/materials-review-20261029/ux-final/auto_delta.py --video sample_data/materials-review-20261029/ux-initial/synthetic.mp4 --photo sample_data/materials-review-20261029/ux-initial/synthetic.png --ffprobe C:/Tools/ffmpeg/bin/ffprobe.exe --output sample_data/materials-review-20261029/ux-final/auto-delta
.venv/Scripts/python.exe sample_data/materials-review-20261029/ux-final/natural_delta2.py --video sample_data/materials-review-20261029/ux-initial/synthetic.mp4 --ffprobe C:/Tools/ffmpeg/bin/ffprobe.exe --output sample_data/materials-review-20261029/ux-final/natural-delta2
.venv/Scripts/python.exe -u sample_data/materials-review-20261029/ux-final/source_switch_delta.py --video sample_data/materials-review-20261029/ux-initial/synthetic.mp4 --ffprobe C:/Tools/ffmpeg/bin/ffprobe.exe --output sample_data/materials-review-20261029/ux-final/source-switch
.venv/Scripts/python.exe -u sample_data/materials-review-20261029/ux-final/source_switch_settled.py --video sample_data/materials-review-20261029/ux-initial/synthetic.mp4 --ffprobe C:/Tools/ffmpeg/bin/ffprobe.exe --output sample_data/materials-review-20261029/ux-final/source-switch-settled
$env:SPLATFORGE_FFMPEG = 'C:/SplatForge-owned-missing-ffmpeg/ffmpeg.exe'
.venv/Scripts/python.exe sample_data/materials-review-20261029/noffmpeg_verified.py --video sample_data/materials-review-20261029/ux-initial/synthetic.mp4 --ffprobe C:/Tools/ffmpeg/bin/ffprobe.exe --output sample_data/materials-review-20261029/ux-final/missing-tool-fixed
```

The full Trim diagnostic first forced frames after recording the empty initial
state, so its later interaction matrix cannot establish automatic startup. The
separate `auto_delta.py` result establishes that after the fix. The first replay
diagnostic used an async seek and was inconclusive; only `natural_delta2.log` is
counted as natural end/replay. The first Projects/resume run timed out; subsequent
instrumented and final lifecycle runs passed. Its original cause remains unclassified.

Remaining manual boundaries: user media and production multi-video, moving VFR with
distinct stream/container origins in the native player, audio/codec breadth, real
Explorer drop, keyboard/screen-reader breadth, OS/per-monitor 100/150/200% scaling,
slow/unavailable external storage and exhaustive close/decode races. Exact origin/
fraction mappings and delayed-player transitions have automated coverage; native
synthetic evidence is not a claim about every real clip. Existing inventories are
not silently re-probed to correct historical timing ambiguity.

The historical 1935/17/73 result below remains historical; it is not today's gate.

### User manual acceptance boundary

No user acceptance is recorded by this review. Use a disposable project or safe
copy for missing-file/drop/close tests; originals remain read-only references.

1. Open Materials, select photos/videos, switch List/Grid and current media while
   playing: current content changes, old playback/image clears, batch UUIDs stay
   independent. Check Dark/Light and your normal Windows scale.
2. Play/Pause, seek, reach natural end and Play again: controls match actual player
   state; replay starts; leaving Materials stops playback and Return loads paused.
3. Trim: Include/Exclude, exact fractional bounds, invalid bounds and handles:
   canonical used ranges agree with the timeline; invalid edits do not mutate draft;
   explicit empty, entire clip and source participation remain distinct.
4. Save, return through Projects, close/reopen: saved ranges/group assignments agree
   with the displayed values; unsaved navigation offers Save/Discard/Cancel.
5. Highlight A, view B, Move/Ungroup/Exclude/Restore selected: only the highlighted
   batch changes, including a single highlighted UUID; current-only action edits B.
6. With an owned unavailable/corrupt fixture or missing preview tool, check clear
   local error/Retry and action availability; missing thumbnails do not disable Trim.
7. Close during playback/background preview, reopen and switch projects: no hangs,
   stale callbacks, old source/image or accidental loss of saved/draft state.
8. Remaining separate input check: real Explorer drop of supported files/folders,
   review/Cancel/Confirm, duplicates and unsupported items; no silent import or source
   file mutation. Native Qt MIME tests do not replace this check.

## Materials / Trim interface / Sol handoff — 2026-10-28

The subsequent request authorized one editor for the reference-led Trim interface.
The dirty working tree, including the completed backend, was the entry version.
Code edits for this slice are complete; no user acceptance is claimed. No commit,
push, merge, reset or discard. The source processing, project schema, Projects/Create
layout, import, COLMAP and benchmark implementations remain unchanged from entry.

Delivered behavior:

- Review/Trim above the same original-file player; photos explain the unavailable
  mode. The catalog/import/panel controls and permanent Projects button remain.
- Full original extent, ticks, real optional filmstrip, used bands, hatched gaps,
  separate playhead/temporary selection and selected canonical range boundaries.
  Click/drag ruler/playhead seeks on release; drag strip selects; existing-range
  handles apply to draft only on release. Escape cancels the unfinished gesture.
- Exact source-second fields (including fractions), Enter/Apply bounds, Set start/
  Set end, Include range, Exclude range, Remove from used and Use entire clip.
  Canonical backend rows own the list; exact reselection survives merge/reordering
  and unknown origins. Excluded transient selection stays available for Include.
  Entire clip, finite union and explicit empty union remain distinct.
- +/- up to 64x, Ctrl+wheel, horizontal wheel/scrollbar and Fit timeline. These and
  playhead movement do not edit intent. Space, Left/Right and I/O route after Qt
  controls: fields, sliders, checkboxes and dialogs own their keys. Materials focus
  is explicitly restored after Settings closes. Source Exclude remains independent.
- Play used ranges only defaults off. It skips gaps without rebasing time, stops
  after the last used range and restarts on explicit Play. One pending seek, one
  deadline, destination membership, pause/source/project/scrub cancellation and
  collapsed-ms-span handling prevent resume leaks and repeated seek loops.
- One asynchronous optional preview worker, at most 12 latest requests and 32
  160×90 rasters. FFmpeg input-seeks individual real frames in owned processes;
  no full scratch decode, publication, recipe change or implicit installation.
  Missing thumbnails leave the ruler/editor usable. Source/namespace tokens reject
  stale delivery; close drains the owned worker after cancellation.

Authoritative time/slot/transport details: [VIDEO_USAGE](../../VIDEO_USAGE.md).
New Python/QML boundary relative to the backend handoff:

- `videoUsage.state.contextKey` and read-only `timeline` projection (exact full
  bounds, approximate player-ms ranges/gaps and explicit unavailable reason).
- `intervalIndex(str)->int` selects a normalized canonical row using exact source
  time; `clearError()->void` dismisses only local validation/conversion errors.
- Constant `videoUsage.thumbnails`, notified `state`, `changed()`, `stop()` and
  `requestThumbnails(double,double,int)->void`. `VideoPreview.frame` is the inward
  application port, composed with the bounded FFmpeg preview adapter.
- `MaterialViewer` now requires `videoUsage`, exposes `trimMode`, `trimSession`,
  the existing `playback` alias and `handleKey(int,bool)`. SourcesPage is a focus
  scope and passes unconsumed keys. Trim session fields are transient presentation,
  never another persisted interval model. No existing persistence/edit slot changes.

Changed files (relative to this slice's saved entry hashes):

- QML: `components/MaterialViewer.qml`, `pages/SourcesPage.qml`, `Main.qml` (only
  Settings-close focus restoration); new `VideoTrimSession.qml`, `VideoTimeline.qml`,
  `VideoTrimProperties.qml`.
- Python: `gui/video_usage_vm.py`, `gui/qml_bridge.py`, `gui/qml_app.py`, `bootstrap.py`;
  new `gui/video_filmstrip.py`, `application/video_preview.py`,
  `adapters/video_preview.py`. Here `gui/` denotes `src/splatforge_gui/`, and
  application/adapters/bootstrap belong to `src/splatforge/`.
- New tests: `test_video_trim.py`, `test_qml_trim_editor.py`, `test_video_filmstrip.py`,
  `test_video_preview_integration.py`; native harness `scripts/capture_materials_trim.py`.
  Existing tests were not removed, skipped or weakened.
- Owners: VIDEO_USAGE, GUI_DESIGN, UX_UI_SPEC, reference catalog, this ACTIVE plan
  and the appended bounded visual review in root `design-qa.md`; README/ROADMAP/index
  routing now identifies delivered Trim while leaving user acceptance open.

Verification by this editor, Windows / Python 3.12.10 / PySide6 and Qt 6.12.0:

- **72 passed, 209.10 s**, `sample_data/trim-ui/affected-final.log`: explicit
  `test_video_trim`, `test_video_filmstrip`, `test_qml_trim_editor`, `test_qml_video_usage`,
  `test_materials_composition`, `test_materials_stability`, `test_materials_import`,
  `test_gui_architecture` via `python -m pytest <explicit files> -o addopts= -q --tb=short`.
  This precedes the final key-bubbling/focus correction, which the next run covers.
- **16 passed, 42.87 s**, `final-delta.log`: final Trim projection/session and exact
  UI tests, catalog modifier selection/List-Grid transfer, compact properties and
  Review keys yielding to group/Settings modals. Counts overlap the 72; do not sum.
  A final Loader type annotation removes lint warnings without changing behavior;
  the final native run also covers that Settings-close path.
- Final modifier/focus regression: **4 passed, 24.16 s**, `modifier-focus-final.log`;
  exact UI workflow plus Ctrl/Shift arrows yielding and both modal return paths.
  This covers the last no-modifier routing guard; counts overlap earlier runs.
- Final typed Settings-return guard: **2 passed, 13.12 s**, `final-typed-focus.log`,
  unchanged modal regression cases. No runtime behavior was relaxed for lint.
- New real FFmpeg preview/VFR integration: **1 passed, 0.72 s**, `real-preview.log`,
  explicit installed `SPLATFORGE_TEST_FFMPEG`/`SPLATFORGE_TEST_FFPROBE`. Tiny generated
  VFR video with +5-second origin and Unicode/spaces path; independently probed PTS,
  input-seeked actual colored frames, bounded JPEG dimensions and unchanged original.
  This verifies the new preview adapter; previous frame-publication results remain
  backend history, not a new processing run.
- Final native harness: `sample_data/trim-ui/native-reviewed/` and its manifest/log.
  Actual exposed Windows Qt window, DPR 1.0, 1440×900 and minimum 1024×640,
  Dark/Light. QtTest controls—not manual Windows input. Owned mixed photo/video
  project; existing read-only photo and six-second H.264 still-photo review fixture.
  Actual ruler/playhead drag, range inclusion/middle subtraction, playback gap jump,
  stop, focused checkbox Space, I/Escape, real shell Save and reopen with identical
  rational ranges, empty/reset, ordinary Review Play/Pause/photo Fit/zoom, Settings
  focus, Projects/resume and active-video project switch were asserted.
  Seven real captures are self-reviewed; zero runtime QML warnings. No audio or
  frame-accurate Qt seek claim. The real VFR preview test above supplies changing pixels.
- Scoped Ruff passes. All-QML qmllint exits 0; its only remaining warning is the
  unchanged standalone `theme/Theme.qml` singleton diagnostic, also reproduced by
  linting that unchanged file alone (`qmllint-unchanged-theme.log`). Final docs/diff
  checks and preservation audit are recorded with the final evidence below.

Development findings corrected within the new UI: initial binding-order/null access;
notifying conversions in a refresh binding; exact-field reselection using stale ms;
narrow-inspector overflow/row size loops; stale scrubs after source changes; premature
acknowledgment of an old gap position; global Space stealing a focused checkbox;
and lost Review arrow navigation after Settings. Early failing harness/test logs are
retained, not claimed as passes. No arbitrary sleep/retry/skip was added to hide them;
tests wait for actual state/signals. No unrelated full-suite repair was attempted.

Remaining limits / Sol priorities:

1. Qt playback/seek is approximate, and sub-ms ranges may be unplayable visually;
   exact persisted bounds and preparation stay independent. Check moving VFR with
   distinct stream/container origins, tightly spaced ranges, delayed seeks, Pause,
   replay/end-of-media and rapid same-locator source/project switches.
2. Check long timelines at high zoom, mouse/trackpad scrolling and high DPI; test
   keyboard Tab/Enter/Escape in the compact inspector and panel resizing while
   editing. Current native evidence is DPR 1.0, not a new 150% DPI/audio/codec matrix.
3. Check real missing/slow FFmpeg, cancellation/close with a frame worker in flight,
   source unavailability and unknown duration/origin. Finite exact editing remains
   available where validated; the UI never invents an origin/duration.
4. Explorer drop remains the earlier manual evidence gap, unrelated to Trim:
   in an owned project drag multiple supported photos/videos, a folder and a mixed
   Unicode/spaces set; expect review confirmation, duplicate handling and no mutation
   on Cancel. Test both empty/populated projects; unsupported text/files must not
   import. Do not treat synthetic Qt MIME events as an Explorer check.

No confirmed blocking Trim defect remains in the checked scope. User UX acceptance
and Sol's expanded review are open. The historical full result **1935 passed,
17 failed, 73 skipped** and pre-existing Ruff E501 remain open gates; this slice did
not rerun or declare the entire project green. Saved intervals, processing recipes,
source identity, immutable historical Views runs and conservative scratch decoding
are unchanged from the completed backend contract.

Final preservation/documentation evidence: **477 entry files**, zero missing;
**461 byte-identical**, **16 changed existing files** and **11 new files**, all within
the map above (`sample_data/trim-ui/preservation.json`, `handoff-hashes.json`).
All pre-existing COLMAP/benchmark work, original reference images, source interval
core/application processing and persistence, Projects/Create implementation and
`qml_media.py` lifetime fixes retain entry bytes. The only Main change is focus return
from Settings. Branch/HEAD unchanged, index empty. Scoped Ruff and docs checker pass
(47 Markdown files, zero errors); all-QML lint exits 0 with only the independently
reproduced unchanged Theme diagnostic; `git diff --check` passes.
Application edits and documentation edits stop for Sol review.

## Saved video usage backend / Astra handoff — 2026-10-28

Subsequent authorization starts the contract/persistence/processing slice after the
completed stabilization below. One editor; the dirty entry tree remains authoritative.
No visual timeline/Trim mode, masks, tracking, 360 processing or new reconstruction
behavior is introduced. Projects/Create, Materials QML, lifetime fixes and pre-existing
COLMAP/benchmark work are preserved. Entry hashes/diff and current evidence are under
ignored `sample_data/video-intervals/`.

Implemented:

- Independently versioned `video_usage` intent, exact source-presentation intervals,
  canonical union/subtraction, empty versus unrestricted/reset, identity binding and
  deterministic validation. Source Exclude remains independent. Authoritative
  [persistence contract](../../PROJECT_FORMAT.md#video-usage-intent) and
  [processing/time/cache contract](../../PIPELINE.md#used-video-intervals).
- Ordinary draft/dirty/Save/CAS/readback; no eager migration or second store. New
  probes retain stream start (exact start_pts preferred) and container playback start
  separately. Historical missing origins/durations stay unknown.
- Real candidate publication filters sampled PTS before moving images into output;
  excluded scratch frames are not published. Both selectors consume that restricted
  pool without rebasing source time. Full-stream decoding/budgeting remains conservative.
- Current-source Plan refuses a wholly unusable selection and loses readiness when
  usage changes; it cannot approve an unsaved interval draft. A compatible explicit
  historical views_run continues to validate its own contract. Recipes change only
  for relevant bound restrictions, Reset can reuse earlier unrestricted candidates,
  and compatible downstream candidate/quality digests retain existing reuse.
- Constant QObject `desktop.videoUsage`, notified `state`, `changed()` and exact slots
  for add/update/remove/exclude/clear/reset plus player/source conversion. Complete
  property, error and signature contract: [VIDEO_USAGE](../../VIDEO_USAGE.md).

Astra handoff: use the saved Materials fragments reference and the nonvisual API;
do not duplicate interval algebra, derive source time from FPS or store a parallel
QML restriction. Editing targets the current preview UUID, independent of batch
selection. Re-read canonical interval indexes after edits. Use existing Save and
unsaved navigation. Whole-file playback is unchanged. Legacy probes without an
observed container origin cannot map player coordinates; the API reports that
explicitly. An in-place historical probe refresh is not implemented in this slice.

Task files relative to entry:

- Core: new `core/video_usage.py`; `core/{media,project,views}.py` for nullable timeline
  metadata, intent envelope and relevant candidate recipe inputs.
- Application: new `application/video_usage.py`; `application/{views,desktop,
  desktop_workflow}.py` for publication, inventory-backed projection and Plan.
- Adapter: `adapters/ffprobe.py` records stream/container origins, no FFmpeg CLI change.
- GUI Python: new `video_usage_vm.py`; `qml_bridge.py`, `workflow_vm.py`, `controller.py`
  expose API and reject stale/unsaved current-source plans. No QML file changed.
- New `test_video_usage.py`, `test_video_usage_execution.py`, `test_qml_video_usage.py`,
  `test_video_usage_integration.py`; authoritative contracts/API, README/ROADMAP,
  design/reference catalog, documentation index and plans.

Current verification (this editor, Windows, Python 3.12.10, Qt/PySide6 6.12.0):

- **97 passed, 129.83 s**, `affected-final.log`: explicit modules `test_video_usage.py`,
  `test_video_usage_execution.py`, `test_qml_video_usage.py`, `test_views_execution.py`,
  `test_quality_execution.py`, `test_source_participation.py`,
  `test_plan_source_participation.py`, `test_gui_architecture.py`, using
  `python -m pytest <paths> -o addopts= -q --tb=short`. Earlier **86 passed, 23.98 s**
  (`affected-initial.log`) also covered `test_views_core.py` and `test_ffprobe.py`;
  counts overlap and must not be added.
- Final API correction: Discard previously restored intent but retained the last local
  validation error. A new assertion reproduced that exact failure
  (`discard-error-before.log`); the new VM clears errors on dirty=false (Discard or
  successful Save). **16 passed, 22.01 s**, `interval-regressions-final.log`, explicit
  `test_video_usage.py`, `test_video_usage_execution.py`, `test_qml_video_usage.py` on
  this final API. This narrow correction followed the broad run's start; its focused
  result covers that delta without repeating unchanged broad/backend cases.
- Real integration **1 passed, 2.54 s**, `real-vfr-final.log`: configured installed
  `C:/Tools/ffmpeg/bin/{ffmpeg,ffprobe}.exe`, explicit
  `SPLATFORGE_TEST_FFMPEG`/`SPLATFORGE_TEST_FFPROBE`, only
  `test_video_usage_integration.py`, owned fixture under `real-vfr-final/`.
  Generated a tiny MPEG-4 VFR clip with +5-second source origin, Unicode/spaces path;
  independently probed source frame PTS; published exactly the two admitted frames,
  retained source UUID/time_base/PTS, excluded end-boundary frames and verified
  original bytes. Strict source verification and real publication were used.
  Early failures were new-test summary/field-name mistakes, corrected without
  changing assertions; not processing failures or repeated full runs.
- Scoped Ruff passes. Full Ruff has one pre-existing E501 at `core/registry.py:52`;
  its entry bytes are unchanged. `ruff-full-final.log` records this open gate.
- Actual Qt meta-object inspection passed: constant `videoUsage`, QVariantMap `state`,
  `changed()` notify, all eight documented slots and return types (`qml-meta.json`).
  The first inspector wrongly enumerated only dynamic-method offsets; enumerating
  the full inherited meta-object confirmed the API, without an application change.
- The broad run exposed 17 existing Qt-test failures. A separate three-case diagnostic
  localized missing/hidden old toolbar selectors and obsolete post-import `neutral`
  expectations (`full-failures-targeted.log`). All 17 were then reproduced, **17 failed,
  85.26 s**, against a disposable reconstruction of the actual dirty entry code,
  not plain HEAD (`baseline-failures.log`, `baseline-node-ids.json`). Git archive plus
  the saved entry diff and unchanged-file copies reconstruct the baseline; all
  **375 Python/QML files match entry SHA-256**, package import paths were verified.
  Only two documentation bodies differ from entry and are not runtime inputs to these
  Qt tests (`baseline-entry-proof.json`). No checkout/reset/index/user-file replacement.
  Causes: old Details/participation/check/keyboard/pagination selectors, old availability
  expectations and old accent-background assertions for List/Grid. Tests were neither
  removed, skipped nor weakened; reconciling these pre-existing tests remains a separate
  GUI-test maintenance gate, not an interval regression or a new UI redesign.
- Full default `python -m pytest`: **1935 passed, 17 failed, 73 skipped, 4642.72 s
  (1:17:22)**, exit 1 (`full-pytest.log`, `full-pytest.exit`). Windows offscreen Qt,
  PYTHONFAULTHANDLER=1, no backend/GPU opt-ins. The 17 failed node IDs exactly match
  the verified entry-baseline failures; `full-results.json` records the comparison
  and all skipped nodes. Skips are opt-in external-tool/backend integrations; the
  requested real FFmpeg interval integration was separately provisioned and passed
  above. This broad result precedes the isolated final Discard-error correction;
  the final 16-case run verifies that local API delta. The full suite was not repeated
  after its failures were localized. This is not a green full-gate claim.

Preservation audit: all **469** entry files remain present; **450** retain exact
SHA-256. Exactly **19** existing files changed within the listed scope, plus **8** new
files. All QML, Projects/Create, `qml_media.py` lifetime fixes, COLMAP/feature adapters,
benchmark data/docs and unrelated test code remain byte-identical to entry.
`preservation.json` lists paths; `handoff-hashes.json` identifies the frozen task files.
Branch/HEAD remain `codex/m12b3-ux-review` /
`4d83147acb01907ce02b1311977608f23d6eab17`; index empty. No commit, push, merge,
reset or discard of working files. Final affected Ruff passes; documentation checker
reports 47 Markdown files, zero errors; `git diff --check` passes.

The backend slice and its local corrections are complete. No new confirmed blocking
backend regression for Astra's editor is known in the verified scope. Preparation
still uses conservative full-stream scratch decoding and requires bounded duration;
old probes with unknown playback origin cannot map player time until separately
refreshed/re-ingested. Ordinary whole-file playback remains unchanged. The explicit
pre-existing full-gate failures require separate GUI-test/lint maintenance, without
changing accepted Materials composition merely to satisfy obsolete assertions.
Application and documentation edits stop for handoff; visual Trim remains the next task.

This slice does not claim visual Trim completion or user UX acceptance. Explorer
drop remains the separate manual evidence gap recorded below and was not repeated.

## Materials stabilization handoff — 2026-10-28

Subsequent user authorization: one editor, bounded stabilization before any durable
video fragments. Entry working tree, not HEAD, is authoritative. The 74 affected
results in the previous import section are historical evidence only; current runs
are recorded here. Entry hashes/diff: ignored `sample_data/materials-stabilization/`.
Projects/Create and all QML composition remain unchanged in this stabilization.

### Old selection diagnostic: closed as test hit-testing and obsolete UI assumptions

Exact scenario: `test_qml_m12b3_corrective.py::test_desktop_selection_and_selected_unselected_icon_batch_rule`
for List and Grid. Historical logs: `sample_data/projects-entry/affected-final.log`
and `baseline-selection-verified.log` (List, 1 failed in 6.21 s). These predate the
redesign/import follow-ups; their baseline includes 112 px rows and permanent row
action buttons. The current code already passes the initial List Ctrl/Shift selection
sequence; the unchanged old test then fails on a now-menu-only participation selector.
Grid fails earlier when it requests a virtualized offscreen tile without scrolling.
Current pre-fix results: `selection-original-current.log`, 2 Python assertion failures.

A read-only baseline diagnostic traced requested coordinates and actual UUID selection
callbacks (`selection-baseline-hit-final.log`): requests for 0.png and 2.png reached
selection, but the third request at scene y=837 did not invoke selection at all.
The old helper assumed every delegate's coordinates were in its usable clipped
viewport. This reproduces the historical invalid hit path without changing the saved
baseline or the production selection algorithm. The earlier diagnostic attempt had
a helper-only Qt modifier type error and executed no complete scenario.

The regression now scrolls to the requested model UUID via `positionViewAtIndex`,
waits for an actual visible delegate whose center is inside the browser, and opens
the real row menu. No new fixed delay or retry-to-pass loop was introduced. All
original semantic assertions remain: Ctrl toggle, Shift range, Ctrl+A, List/Grid
retention, selection-aware Exclude for selected/unselected rows, atomic revisions,
Restore and originals retained. Current-preview assertions now follow the accepted
independent current-versus-batch contract. Production selection code did not change.

### Old native diagnostic: closed as unsafe test expression context

Historical crash: `sample_data/projects-entry/affected-final.log`, Windows access
violation in `value()` / `QQmlExpression.evaluate`, called by
`test_icon_details_preview_keyboard_and_no_event_bubbling` while querying the legacy
preview control's accessible name. The raw old List test on today's tree fails sooner
on a missing permanent Details selector, without native failure
(`native-original-current.log`, exit 1).

An isolated process then reproduced the exact dangerous boundary: the legacy preview
selector was `None`, and the unchanged expression helper evaluated `Accessible.name`
with a null QML context. It exited **-1073741819 / 0xC0000005**, with the same evaluator
frame (`native-null-context.log` and `.exit`, Python faulthandler enabled). This is a
test-harness/native binding failure, not an application processing crash. No whole
suite was repeatedly launched to diagnose it.

`value()` now asserts live object and live QML context before entering the evaluator.
A regression checks absent, deleted and unbound objects become ordinary Python test
failures. Accessibility assertions use the real QAccessible interface with activation
for the offscreen environment, restoring its previous active state afterward.
Without activation, Qt returned empty names even for valid MenuItems; enabling it
confirmed the current names. The UI scenario uses the current menu and embedded
inspector, preserving keyboard activation, non-bubbling, independent batch membership,
current-only exclusion, next surviving UUID and preview close assertions.

### Confirmed application correction and related boundaries

A new controlled in-flight worker test found one application defect: after closing
embedded preview, its already-running saved-properties request could publish a late
error into the empty inspector. Stopping the deferred timer alone did not revoke the
request. `MediaViewModel.closePreview()` now invalidates that embedded evidence token
and clears its projection. Secondary preview/details behavior is preserved. The
previously failing close case now passes; project replacement already rejected the
same late result correctly. No Python/QML slot signature or project format changed.

Additional deterministic tests hold old photo decoding until after a new project and
green image are selected, then release it and check current UUID, actual raster pixels
and error state. A retained-session scenario checks current material, batch UUIDs,
group, filter, generation and committed readback through Projects/resume/reopen.

Changed files relative to this stabilization entry:

- `src/splatforge_gui/qml_media.py`: embedded property-evidence revocation on close.
- `tests/test_qml_m12b3_corrective.py`: safe expression/accessibility helpers and
  current scrolling/menu/embedded-view regressions; obsolete fixed-coordinate helper
  removed, with its significant selection assertions retained.
- New `tests/test_materials_stability.py` and
  `scripts/check_materials_video_lifecycle.py` (targeted native check, no dependency
  installation; input video copied into owned temporary fixtures).
- GUI design, this plan and active-plan index. No QML/UI layout file changed.

Current verification, run by this stabilization editor on Windows / Python 3.12.10 /
PySide6 and Qt 6.12.0, without backend/GPU opt-ins:

- **39 passed, 280.74 s**, `sample_data/materials-stabilization/stability-final.log`:
  `python -u -m pytest tests/test_materials_stability.py tests/test_materials_workspace.py
  tests/test_qml_m12b3_corrective.py -o addopts= -o faulthandler_timeout=60 -vv --tb=short`,
  with `QT_QPA_PLATFORM=offscreen` and `PYTHONFAULTHANDLER=1`. Covers fixed late
  metadata, in-flight cross-project decoding, old diagnostics, current/batch actions,
  last-visible exclusion, groups, verification cancellation, failed saves and UI scope.
- **41 passed, 280.05 s**, `connected-final.log`, same environment/options. Explicit
  selection: `test_materials_composition.py`, `test_materials_import.py`, plus
  `test_qml_capture_groups.py::{test_actual_group_controls_create_rename_assign_ungroup_delete,
  test_filtered_group_counts_and_empty_group_are_truthful,
  test_group_save_failure_never_invents_committed_ui_state,
  test_late_details_and_thumbnails_cannot_cross_project_switch}` and
  `test_qml_source_participation.py::{test_all_excluded_empty_state_restart_and_project_switch,
  test_failed_save_keeps_committed_participation_and_drops_action_draft,
  test_existing_dirty_save_discard_cancel_before_participation,
  test_action_drains_readers_and_only_changes_ui_after_committed_save}`.
  These are actual node selections, not a full module/suite claim.
- **5 passed, 34.35 s**, `old-scenarios-final.log`, separate process exit **0**:
  null/deleted/unbound expression regression, old selection List/Grid, old
  Details/preview/keyboard List/Grid. This final targeted run followed replacing the
  old helper entirely with condition-based scrolling/readiness; no added sleep, skip,
  weakened membership assertion or test retry was used to force success.
- **80 distinct affected cases passed** in the two nonoverlapping main selections;
  the five final cases are a subset and are not added to the total. No skips/warnings
  in these final runs. Previous 74-case import evidence is not counted as new work.
- Scoped Ruff passed for the four changed Python files. Documentation checks:
  46 Markdown files, zero errors. `git diff --check` passed (existing LF/CRLF notices
  are not errors). No QML file changed, so its previous lint result is not presented
  as a new run. No full repository pytest: this is a bounded client/test correction,
  not milestone completion or a merge/release gate.

Targeted native playback check passed:

`python scripts/check_materials_video_lifecycle.py --video
"sample_data/ui-review/materials-1/fixture-cb851c/Playback fixture.mp4" --ffprobe
C:/Tools/ffmpeg/bin/ffprobe.exe --output sample_data/materials-stabilization/native`
with Windows QPA and scale factor 1. The harness creates two disposable projects
and copies the six-second H.264 fixture into its owned directory; both projects use
that same locator. Actual decoder position advanced while Playing. Closing preview,
leaving for Projects, switching project and closing the window stopped playback and
cleared the player source. Resume retained generation/current/batch and loaded paused.
The second project began with no old image/current/selection and could play its own
source UUID. `native-video.log` and `native/manifest.json` record the successful run,
native title-bar flags and zero QML warnings. This is automated native Qt evidence,
not a manual Windows or Explorer test. Early harness setup errors concerned source
field lookup and Qt's nonconvertible `QQuickMediaPlayer*` alias; they were corrected
using the existing primitive QML-property inspection pattern with live-context guards.

One targeted actual client-area capture, `native/closed-review.png`, was opened and
inspected at 1440×900 / DPR 1. It shows the correct no-current state after stopping
video, with an empty inspector and no stale property error. The previous large
screenshot matrix was not recreated; no visual layout changed.

Preservation audit: all **467** entry files remain present; **462** match entry
SHA-256. Exactly five existing files changed (one application module, one test module,
three documentation owners), plus the two new regression/native-harness files above.
All existing QML, Projects/Create, COLMAP/benchmark, core/application and unrelated
test files are byte-identical to entry. `preservation.json` records exact paths.
Branch/HEAD remain `codex/m12b3-ux-review` /
`4d83147acb01907ce02b1311977608f23d6eab17`; index empty. No commit, push, merge,
reset or discard. Handoff hashes identify the stable task files.

Both old diagnostics and the confirmed late-properties regression are closed for
this tree. No confirmed blocking application error for the next saved-video-fragment
slice remains within the checked Materials scope. This bounded pass is complete;
application edits stop for handoff. The overall plan remains ACTIVE for its separate
open gates and no user UX acceptance is recorded.

### Remaining evidence limits and next stage

Computer Use initialization was retried once in this pass and again failed before
Windows input with sandbox `CreateProcessWithLogonW 1385`. No system policy, security
setting, automation installation or alternate OS-input helper was used. Existing
external Qt MIME tests remain synthetic, not manual Explorer proof.

Concrete outstanding Explorer check, using disposable projects in both empty and
populated Materials: drag one/multiple JPG/PNG photos, one/multiple ordinary MP4/MOV
videos, a nested folder with spaces/Unicode in its name, and mixed files plus folders.
Expected: admitted-drag highlight; leave/Esc clears it; drop opens scan/confirmation;
Cancel leaves inventory unchanged; Confirm adds the reported files; overlapping
roots deduplicate discovery, already-registered paths show their explicit duplicate
warning, and a single folder shows nested-group preview. Unsupported-only PLY/TXT,
remote URLs and plain text must not import. Afterward verify normal row selection,
wheel/pan and video transport. This is a manual evidence gap, not a confirmed blocker.

Materials UX acceptance remains pending. Wider DPI/monitor/accessibility/audio/codec
coverage and the older unfinished full repository gate remain open. This stabilization
does not implement or accept saved intervals, masks, tracking or reconstruction.

## Materials import follow-up — 2026-10-28

The subsequent user request authorizes one editor to implement this bounded import
follow-up after Astra's Materials handoff. Earlier evidence below remains historical;
the checks here are new runs on the updated implementation. Entry SHA-256/diff:
ignored `sample_data/materials-import/entry-hashes.json` and `entry.diff`.
The [GUI owner](../../GUI_DESIGN.md#materials-import-entry--2026-10-28) defines the
current behavior. No general Materials redesign or processing/backend change.

Delivered:

- Visible compact icon/text Photos, Video, Folder actions in the catalog; a shared
  `MediaImportActions.qml` Flow permits wrapping without widening the panel.
- Centered Add your media, drag invitation and three working import buttons for an
  empty inventory; the same page-owned Actions open the existing dialogs.
- Page-local external URL DropArea, nonintrusive active feedback and shared existing
  worker scanner/confirmation for files, folders and mixed roots. One directory's
  grouping root matches Add folder; duplicate behavior stays explicit in preview.
- Rejected unrelated text, remote/relative URLs and unsupported-only files. Correct
  QUrl local decoding for spaces, Unicode and `#`. No implicit import on drag enter.
- Separate filtered-empty Reset filters, no-selection prompt and error/retry states;
  no empty Fit/zoom/navigation/0/0 or inactive technical section in properties.

Changed files for this follow-up (relative to its entry, not HEAD):

- `qml/pages/SourcesPage.qml`, `qml/components/MaterialViewer.qml`,
  `qml/components/MaterialProperties.qml`, new `qml/components/MediaImportActions.qml`.
- `qml/Main.qml`: the existing global DropArea is disabled only while an open
  project is on Materials; the page-local area owns that route.
- `qml/components/ImportPreviewDialog.qml`: truthful shared title “Import media”.
- `qml_bridge.py`: `canDropMedia(QVariantList) -> bool`, internal absolute-local-path
  parsing and Materials admission; `dropUrls` keeps its signature and uses the same
  scanner with a grouping root for a single dropped directory. No application or
  core contracts changed, and no filesystem traversal moved to QML.
- New `tests/test_materials_import.py`; adapted the two direct-import tests in
  `test_materials_composition.py`; existing `scripts/capture_materials.py` now captures
  the visible actions instead of the removed menu; new `capture_materials_import.py`.
- GUI design, this plan and active-plan index. Prior COLMAP/benchmark work is preserved.

Updated Python/QML and automation-facing contract:

- `addPhotos/addVideo/addFolder` are visible catalog Buttons again, rather than
  MenuItems. Empty-state counterparts are `empty-addPhotos/empty-addVideo/empty-addFolder`.
  `importMaterials` and its plus menu are removed; both button sets trigger the same
  three QML Actions. Row-action menu contracts from Astra's handoff remain unchanged.
- MaterialViewer adds `registeredCount`, `visibleCount`, `emptyContent` and
  `resetFiltersRequested`; `materialNavigation` names its context-dependent footer.
- `materialsDropArea` owns native URL events; `materialsDropFeedback` is visible only
  for its admitted active drag. There is no production-only screenshot/test switch.
- `canDropMedia` is a cheap admission query. Actual discovery and ingest remain
  asynchronous with the existing controller guards and confirmation/readback.

Verification scope: affected components and their import/lifecycle consumers, no
milestone completion or full repository gate. Windows, Python 3.12.10, Qt 6.12.0;
offscreen automated tests and separate exposed Windows-QPA capture. All results in
this section were run by this follow-up implementation chat, not reused from Astra.

- **73 passed, 240.49 s**, `sample_data/materials-import/final-tests.log`:
  `python -u -m pytest tests/test_materials_import.py tests/test_materials_composition.py
  tests/test_materials_workspace.py
  tests/test_qml_folder_browser.py::test_folder_picker_preview_counts_cancel_then_confirm_persisted
  tests/test_qml_folder_browser.py::test_sources_mixed_drop_scans_and_home_keeps_project_open
  tests/test_qml_folder_browser.py::test_scan_cancel_is_responsive_and_publishes_nothing
  tests/test_qml_folder_browser.py::test_zero_supported_disables_import
  tests/test_qml_folder_browser.py::test_cancel_ingest_after_preview_keeps_inventory_atomic
  tests/test_gui_architecture.py -o addopts= -o faulthandler_timeout=60 -vv --tb=short`,
  with `QT_QPA_PLATFORM=offscreen`. This run emitted 11 Python deprecation warnings
  from the old QPoint drag constructor, subsequently replaced with QPointF.
- **19 passed, 82.44 s**, no warnings/skips, `import-release.log`: the final
  `test_materials_import.py` rerun with the same pytest options. It includes one new
  test for drop over a decoded photo retaining current UUID and batch selection, and
  rechecks final empty-block sizing after visual adjustments. Earlier geometry
  assertions incorrectly required a single row even under wider offscreen font
  metrics; the final requirement checks that valid Flow wrapping stays fully visible.
  A startup error assigning Flow's read-only implicitHeight was fixed before these
  passing runs. Earlier failed attempts are not passing evidence.
- **74 distinct affected cases passed** across these overlapping runs. Unchanged
  grouping, playback/async and lifecycle checks in the 73-case run remain applicable;
  this count does not add duplicated cases. No full pytest or GPU/backend opt-ins.
- Scoped Ruff passed for `qml_bridge.py`, both affected tests and both capture
  scripts. All repository QML passed installed qmllint with source/theme imports.
  Documentation: 46 Markdown files, zero errors. `git diff --check` passed; Git's
  existing LF/CRLF notices are not whitespace failures.

Fresh exposed native window evidence, scale factor 1:

- `sample_data/ui-review/materials-import-final/`: 12 captures, both Dark and Light
  at logical/physical 1440×900 and 1024×640, each with empty project, active drop
  feedback and populated viewer plus visible catalog buttons. Run:
  `python scripts/capture_materials_import.py --project
  sample_data/ui-review/materials-1/fixture-cb851c/Workspace --output
  sample_data/ui-review/materials-import-final --photo 000001.jpg`.
- `sample_data/ui-review/materials-import-playback/`: 12 fresh captures from the
  adapted `capture_materials.py` using that same read-only project, photo and
  `--video "Playback fixture.mp4"`. Native pointer zoom/pan/Fit and video
  play/pause/seek assertions passed on this updated composition; also covers batch,
  minimum window, properties overlay, expanded/collapsed panels and Light.
- Both manifests record an exposed window, native title-bar flags and zero QML
  warnings. The still-based H.264 video is the previously labeled playback fixture;
  no audio or codec coverage is inferred. Capture tools write owned screenshots,
  review settings and a uniquely named empty test project only. Source files and
  the supplied populated project remain unmodified.
- Actual full-resolution images were opened and reviewed, including both themes,
  both sizes, drop highlight, visible import controls and zoom/video. The empty
  action row uses an explicit natural width, preventing an unstable narrow Flow;
  wrapping remains supported for genuinely narrower space or wider font metrics.
  Critical controls fit the inspected sizes. No user UX acceptance is claimed.

Preservation: all **464** entry files remain; **453** are byte-identical. Exactly
11 existing files changed as listed above, with three new component/test/harness
files. `sample_data/materials-import/preservation.json` records paths. All original
COLMAP/benchmark/core/application and unrelated source/test files match entry hashes;
accepted shell geometry and Projects/Create behavior are preserved. Branch/HEAD
remain `codex/m12b3-ux-review` / `4d83147acb01907ce02b1311977608f23d6eab17`, index
empty. No commit, push, merge, reset or discard.

This bounded import follow-up is complete and ready for stable review. Further
application edits stop at handoff. The overall plan remains ACTIVE for wider
diagnostics, Materials acceptance and the earlier incomplete full gate.

Remaining limits: real Explorer drag-and-drop could not be exercised because the
Computer Use node kernel fails before initialization with Windows sandbox
`CreateProcessWithLogonW 1385`. Supported external Qt MIME events were delivered to
the real QQuickWindow in tests; this is synthetic input, not manual Windows Explorer
evidence. No alternate OS-input helper or security-setting workaround was used.
Manual Explorer and wider native DPI/codec/accessibility validation remain open.

## Materials redesign handoff — 2026-10-28

This subsequent request authorizes step 5. The accepted shell and Create/Projects
remain byte-identical to this turn's entry. No commit, push, merge, reset or discard.
No backend, model, codec or toolchain installation. Entry SHA-256/diff evidence is
in ignored `sample_data/materials-redesign/entry-hashes.json` and `entry.diff`.
The [GUI contract](../../GUI_DESIGN.md#materials-composition-delivery--2026-10-28)
owns the delivered layout; the reference anchor is catalog Materials Review.

Changed implementation files relative to this turn's entry:

- `qml/pages/SourcesPage.qml`: panel-local import/actions, 88 px catalog rows,
  80×60 thumbnail areas, quiet normal rows, current marker, footer List/Grid,
  compact context menus, resizable/collapsible docks and minimum-window overlay.
- `qml/components/MaterialProperties.qml` (new): current-source metadata pairs,
  status, current-only Exclude/Restore, detailed evidence and inventory footer.
- `qml/components/MaterialViewer.qml`: compact Review/zoom heading, filename/index
  navigation and restore-panel controls; existing photo/video engines retained.
- `qml/components/SourceActions.qml`: one contextual menu instead of three permanent
  row buttons; menu focus remains reachable and selection-aware actions are preserved.
- `qml/components/PhotoViewport.qml`: suppress subpixel-rounding scrollbars at Fit.
- `qml_media.py`: `_preview_source()` adds stable string `identity` to its map,
  following the other source model projections. No Python slot signature changed.
- New `tests/test_materials_composition.py` and `scripts/capture_materials.py`.
  The harness reads an existing review project, writes only its screenshot/settings
  output directory, and plays/pauses/seeks the selected ordinary video.
- Documentation: GUI design, this plan and active-plan index. Existing historic
  evidence, benchmark documentation and plans are preserved.

Python/QML and automation-facing interface changes for Sol:

- New `previewSource.identity`, empty when no source (empty map as before).
- MaterialViewer adds `catalogCollapsed`, `propertiesCollapsed`, `catalogRequested`
  and `propertiesRequested`; playback/media interfaces are unchanged.
- MaterialProperties takes `vm` and emits `closeRequested`/`detailsRequested`.
  SourceActions adds read-only `interacting` for menu/focus visibility.
- `addPhotos/addVideo/addFolder` are MenuItems: open `importMaterials` first.
  Row `preview-/details-/participation-<UUID>` are MenuItems: open `actions-<UUID>`
  first (`tile-` prefix for Grid). They use `triggered`, rather than button `clicked`.
- `catalogOptions` → `checkSourceFiles` opens the local explanation/results dialog;
  `runSourceCheck` performs verification. `sourceParticipation` is now in that menu.
- `sourceDetails` and `currentMaterialParticipation` belong to the current-source
  inspector, which requires a displayed source. Below 1180 px open
  `restoreMaterialProperties`; `materialProperties` is the dock Loader and
  `materialPropertiesOverlay` is the compact Popup. Tests that call `selectSource`
  without opening review should use `activateSource`/`showSource`, or the row menu
  for a non-current source's details. Do not restore old permanent buttons to satisfy
  stale geometry/selector assertions.

Verification by this implementation chat, Windows / Python 3.12.10 / Qt 6.12.0:

- `python -u -m pytest tests/test_materials_composition.py tests/test_materials_workspace.py
  -o addopts= -o faulthandler_timeout=60 -vv --tb=short`: **23 passed, 132.61 s**,
  `sample_data/materials-redesign/final-tests.log`, `QT_QPA_PLATFORM=offscreen`.
  Covers current versus batch persistence, Ctrl/Shift/Ctrl+A and List/Grid,
  import pickers/readback, menus/details, verification disclosure, panel geometry,
  resize retention, photo limits, async stale delivery, close and keyboard ownership.
- Six additional distinct cases passed in `composition-tests.log`: existing group
  create/rename/assign/ungroup/delete; participation write/stale failure; dirty draft
  Save/Discard/Cancel. That 12-case run also contained six earlier composition tests.
  Total distinct scoped cases: **29 passed**. No skips. Earlier 13-case Materials
  run also passed; it is superseded by the final 23-case run, not added to the total.
- The final expanded-grid collapse correction was separately retested with
  `test_materials_composition.py::test_split_resize_retains_width_through_collapse`;
  `panel-final.log` records its result. Unchanged behavioral checks are reused.
- Scoped Ruff for `qml_media.py`, new test and capture harness; all repository QML
  through installed qmllint with source/theme imports; documentation and whitespace
  checks passed. Documentation check: 46 Markdown files, zero errors. The final
  panel correction test passed (1 case, 7.28 s). No full pytest, GPU/backend opt-ins or extended
  resolution/DPI matrix was run; those belong to Sol under the user's division of work.

Native visual evidence: `sample_data/ui-review/materials-redesign-final/`, produced by
`python scripts/capture_materials.py --project sample_data/ui-review/materials-1/fixture-cb851c/Workspace
--output sample_data/ui-review/materials-redesign-final --photo 000001.jpg
--video "Playback fixture.mp4"` with Windows QPA and scale factor 1. The manifest
records exposed native title-bar windows, logical/physical sizes and QML warnings.
The photos are existing read-only Ignatius sources; the six-second H.264 video is
an existing explicitly named playback fixture made from a still, not user footage
or evidence of frame preparation. Its playback position advances and native seek
is asserted; audio and other codecs are not claimed verified.

The 12 captures include photo, video and batch at 1440×900 and 1024×640; photo
zoom/pan; compact properties; expanded Grid; import menu; collapsed panels; and a
Light photo. Actual pixels were opened and inspected in this chat. The first capture
exposed incorrect compact Popup placement; it was fixed and a geometry regression
added. The final layout preserves aspect ratio and letterboxing, visible Projects,
current-versus-selected distinction and minimum-window controls. A Fit rounding
scrollbar and the expanded-grid collapse trap were corrected. No fake future tools.

Sol's concrete follow-up checks on the frozen tree:

1. Adapt legacy direct-button/inspector assumptions using the selector map above;
   run the wider source, folder, grouping, participation, retained-session and media
   lifetime suites. In particular revisit previously reported batch tests and the
   old `QQmlExpression` access violation; this scoped result does not close them.
2. Stress rapid scope/project/page changes while decoding and playing; close and
   cancellation ownership; hidden delegates/cache bounds; long names and missing
   sources; keyboard-only menu traversal and screen-reader labels.
3. Wider Light/Dark, 1280/1920, DPI 125/150/200%, per-monitor moves; both splitter
   limits, width reset, overlay focus and expanded Grid at narrow sizes. Native audio
   and additional installed codecs remain unverified.
4. Complete the older full gate when appropriate and obtain Materials UX acceptance.
   This bounded delivery does not close M12 or authorize masks/SAM3/tracking,
   durable video intervals, preparation tools or new 360 functionality.

Preservation audit: all 461 entry files remain present; 453 match their entry hashes.
Exactly eight existing files changed (five application/presentation files plus three
documentation owners), with three new implementation/test/harness files listed above.
All existing Projects/Create/shell, COLMAP, benchmark and unrelated test files match
entry SHA-256. `sample_data/materials-redesign/preservation.json` records exact paths.
Branch/HEAD are unchanged and the index is empty. This bounded implementation is
ready for Sol's stable-tree review; the broader plan remains ACTIVE for its open gates.

## Current preparation and next scope

Historical entry-slice scope, retained for provenance. The latest handoff above
supersedes this section's steps 1–4 boundary and deferral of Trim. For the current
cross-project checkpoint and agent process, see [project state](../../PROJECT_STATE.md)
and [agent workflow](../../AGENT_WORKFLOW.md). No new milestone is authorized by
the 2026-10-28 context/process recovery.

The earlier preparation authorization was documentation plus available reference copies
only; the subsequent request authorizes implementation of steps 1–4 below. It
supersedes the layout direction of the first implementation below, not
its persistence, media-lifetime or processing behavior. No application code, tests,
toolchain or model is changed by this preparation. Do not create a competing active
UI plan: this plan owns the next presentation sequence; M12b3 retains its historical
behavior evidence and pending acceptance.

Preparation:

- [x] Inspect actual AGENTS, GUI/UX owners, roadmap, all active plans, current code
  and post-snapshot working tree; distinguish delivered work from user acceptance.
- [x] Inspect all 13 supplied images; copy accessible originals without overwrite,
  verify hashes and record all twelve scenarios plus mask variant in the
  [reference catalog](../../design/references/README.md).
- [x] Record absent original-layout identification/current-app attachment; do not
  relabel a target mockup or historical native capture as the current application.
- [x] Specify Projects/Create/Open first, visible global return, retained draft/task
  behavior, shared tokens/layout/states, presentation reuse and deferred capabilities.
- [x] Align AGENTS, GUI design, UX specification, roadmap and plan routing.
- [x] Run documentation links/claims/diff and preservation checks; results below.

Implementation sequence (steps 1–4 authorized by the subsequent request):

1. Common native-window shell and necessary base components.
2. Projects/recent rows, empty/loading/unavailable states.
3. Create/Open/Locate using existing validation, identity, Save and readback.
4. Materials destination and visible Projects return from every project section.
5. Materials presentation redesign with preserved import/groups/selection/
   Exclude/Restore, asynchronous media and Plan behavior.
6. Subsequent working sections in the roadmap; independently contracted trim,
   masks/tracking and M14 projection work remain later.

**This implementation boundary: 1–4 only.** Acceptance: launch → Projects → Create or Open →
Materials → Projects. Reuse the current Materials content for this gate. Verify
Cancel, validation, failed/nonempty creation, unsupported/missing Open, identity-safe
Locate, no-preview rows, same-session resume, dirty Save failure and active-task
return without cancellation. New/Open of another project stays blocked while active;
no multi-project execution or backend rewrite. Include keyboard and native Dark/Light
minimum/normal/high-DPI screenshots. Full verification/user acceptance of the earlier
work remains a separate unresolved gate, not silently satisfied by this entry slice.

Owners: [reference-led layout and first gate](../../GUI_DESIGN.md#reference-led-interface-contract--2026-10-28),
[navigation/session semantics](../../UX_UI_SPEC.md),
[save and ownership](../../PROJECT_FORMAT.md#storage-layout-and-ownership),
[verification](../../DEVELOPMENT.md#verification-workflow).
No product decision blocks steps 1–4: same-session retention uses existing lifecycle
mechanisms. A separately identified original reference and current-app attachment
would improve comparison fidelity; their absence is recorded, not filled with guesses.

### Preparation verification (Codex, 2026-10-28)

- `.venv/Scripts/python.exe scripts/check_docs.py`: 46 Markdown files, zero errors.
- `git diff --check`: passed. Git's existing LF/CRLF notices are not whitespace errors.
- Claims checked against Main/Home/Results/Train/Diagnostics, Theme, project-name
  helper, DesktopViewModel navigation/switch/create/recents and ProjectService plus
  PROJECT_FORMAT ownership. No fresh runtime/visual acceptance is inferred from code.
- SHA-256 comparison with the entry manifest: 434 existing files unchanged; exactly
  nine documentation files changed. All application code, tests, capture harness and
  unrelated COLMAP/benchmark work are unchanged by this preparation. Fifteen added
  reference files are 13 PNGs, catalog README and provenance/hash manifest. All 13
  copied images match the originals. No existing reference file was overwritten.
- Branch and HEAD unchanged; index empty. No commit/push/merge/reset/discard.
- Pytest, Ruff and qmllint were not rerun: this is documentation/reference-only work,
  not completion of a product milestone or the interrupted full gate. No app was
  launched or screenshot freshly captured. The prior native capture is explicitly
  historical; the separately mentioned current-app attachment remains unavailable.

Preparation is complete. The overall interface plan stays ACTIVE because the older
implementation acceptance/full verification and separately requested future work
remain outstanding. This is not a declaration that the redesign has shipped.

## Projects entry implementation — 2026-10-28

This delivery is limited to steps 1–4. The working tree at entry, including all
COLMAP/benchmark and prior Materials changes, is the baseline; HEAD is not a reset
point. Entry hashes and diff are retained in ignored `sample_data/projects-entry/`.
No Core/Application/backend or project schema change is needed.

- [x] Dedicated Projects startup, virtualized 72px rows, selection, real name/path/
  last-opened, empty/loading/unavailable states, full-path tooltip/copy.
- [x] New/Open/identity-checked Locate/Remove using existing services and preferences.
- [x] Centered Create with inline name/location errors, nonempty refusal, preserved
  inputs on failure, pending ownership, Tab/Enter/Escape and successful readback.
- [x] Visible Projects button in Materials/Reconstruction/Splat/Results, underlined
  project tabs, retained native title bar and stable page IDs 0–6.
- [x] Retained section/draft/selection/task, current-session indication, explicit Save,
  same-project identity check and no reload; legacy page settings cannot skip Projects.
- [x] Save/Discard/Cancel and active-work switch guards, save failure retention,
  replacement identity at the same path, cancelled Locate and safe recent removal.
- [x] Final scoped regression/lint/docs/diff verification recorded below.
- [x] Final native Dark/Light normal/minimum/high-DPI captures reviewed below.
- [ ] User UX acceptance (not performed by Codex).

Changed files for this slice: `qml/Main.qml`, `qml/pages/HomePage.qml`,
`qml/components/RecentProjects.qml`, new `qml/dialogs/CreateProjectDialog.qml`,
`qml_bridge.py`, new `tests/test_projects_entry.py`, adapted
`test_qml_workflows.py`, `test_qml_interaction.py`, `test_qml_recent_projects.py`,
`test_qml_m12b3_corrective.py`, `test_qml_sources_corrective.py`,
`test_qml_source_participation.py`, `test_materials_workspace.py` (explicit reload
versus retained-session return), new `scripts/capture_projects.py`,
`docs/GUI_DESIGN.md`, `docs/UX_UI_SPEC.md`, `docs/M12.md`, `ROADMAP.md`,
`docs/index.md`, this plan and `docs/plans/active/README.md`.
The `HomePage` filename remains internal compatibility naming; its visible surface
is Projects. Existing Materials, later processing forms and state storage are reused.

Verification scope: affected GUI/client/project contracts for a bounded entry slice,
not full repository/M12 completion. No GPU/backend opt-ins or tool/model installation.
The earlier interrupted full-suite gate stays unresolved. Native captures use real,
empty ProjectService-created fixtures in an isolated temporary directory and their
real successful-open timestamps; names describe review fixtures, not user assets.
Each manifest records fixture locations, logical/physical dimensions, DPR, native
window flags/exposure and QML warnings. Client-area screenshots omit OS decoration.
DPR 1.5 is supplied through Qt scaling on Windows; changing the user's global Windows
scale, per-monitor moves, Snap gestures and screen-reader testing are not claimed.

The initial synchronous QtTest screenshot helper stalled at Results; switching the
capture harness to a Qt event loop resolved it without a production renderer change.
An early test run was interrupted to enable unbuffered per-test logs; partial dots
are not a passing result. Early assertion failures reflected the new field metadata,
menu placement, Windows CON device semantics and the controller's existing validated
copy of draft; the corresponding tests were corrected, not production safeguards.

### Entry-slice verification and visual review (Codex)

Environment: existing Windows / Python 3.12.10 / PySide6 and Qt 6.12.0. Ordinary
sandbox process creation fails with Windows logon error 1385; permitted escalated
commands ran the same repository environment. No automatic-approval rejection occurred.

- **138 passed, 326.49 s** in `sample_data/projects-entry/entry-final.log`. Explicit
  selection: `test_projects_entry.py`, `test_qml_workflows.py`,
  `test_qml_recent_projects.py`, `test_qml_interaction.py`,
  `test_materials_workspace.py`, `test_gui_architecture.py`, `test_projects.py`, plus
  `test_qml.py::test_qml_engine_loads_dark_light_and_all_destinations`,
  `test_qml_sources_corrective.py::test_session_evidence_reopen_check_missing_and_failed_check`,
  `test_qml_source_participation.py::test_future_participation_version_is_inspectable_but_cannot_process`,
  `test_qml_m12b3_corrective.py::test_availability_updates_both_retained_presentations`.
  Command: `.venv/Scripts/python.exe -u -m pytest <explicit selection> -o addopts= -o faulthandler_timeout=60 -vv --tb=short -rs`
  with `QT_QPA_PLATFORM=offscreen`. No skips in this selection.
- **1 passed, 2.68 s** separately for
  `test_projects_entry.py::test_recent_keyboard_open_and_path_copy`: arrows, Enter,
  context menu and full-path clipboard access on the final menu/palette. Total:
  **139 distinct affected tests passed**. Pending Create cannot be dismissed with
  Escape; errors preserve input and restore focus; Tab order is exercised.
- The active-work test runs a deliberately slow owned fake-stage fixture through
  the real execution/progress/cancellation protocol. Projects leaves it running;
  another Open is refused; same-session return preserves generation; explicit Cancel
  is confirmed before teardown. This is safe lifecycle evidence, not GPU acceptance.
- Scoped Ruff for the changed Python files: passed. All repository QML files with
  source/theme imports through installed `qmllint.exe`: passed without warnings.
  `.venv/Scripts/python.exe scripts/check_docs.py`: 46 Markdown files, zero errors.
  `git diff --check`: passed; existing LF/CRLF notices are not errors.
- **100 final native client-area screenshots**, 50 each in ignored
  `sample_data/ui-review/projects-release-100/` and `projects-release-150/`, produced
  by `.venv/Scripts/python.exe scripts/capture_projects.py --output <directory>`
  and a second run with `QT_SCALE_FACTOR=1.5`. Both manifests report exposed native
  windows, native title-bar flags and zero QML warnings. Logical 1440×900/1024×640
  correspond to physical 1440×900/1024×640 at DPR 1 and 2160×1350/1536×960 at DPR 1.5.
  Coverage: first launch/empty, several real projects, unavailable project, selected
  row/actions, Create, invalid Windows name, actual nonempty-destination refusal,
  Materials and all other primary sections, retained dirty session, removed recents
  and long project name. Dark and Light use identical geometry.
- Opened representative full-resolution captures across both themes, both sizes,
  both DPRs and all entry/error/session states. Compared to catalog #3/#2 and #1.
  Projects keeps New/Open above rows and a quiet footer; 72px preview-free rows follow
  the catalog correction rather than copying invented thumbnails/readiness/sizes.
  Create retains the centered fields/destination/action-footer composition. Fixed
  the initially low-contrast Dark menu and its pointer-dependent placement, restored
  input focus after a backend error, and removed duplicate error text behind Create.
  Long names elide before navigation; full paths remain available. No final clipping
  of key entry controls was observed. Partial last rows at minimum size are ordinary
  scroll-list content; optional date columns are hidden there.
- Known limits: existing Materials toolbar/inspector and later section contents retain
  their previous composition, as required by this boundary. Create has no separate
  filesystem-operation cancellation contract and stays pending until completion.
  Actual Windows global 125/150/200% settings, per-monitor moves, Snap gestures and
  screen-reader use remain unverified; Qt's real DPR 1.5 path was verified instead.
  Manual user UX acceptance remains unchecked.

### Wider GUI diagnostics (not a passing full gate)

A wider 297-case selection was attempted to inspect existing Materials consumers.
It reached 35 passing and four failing case lines before a Windows access violation
inside the old `test_icon_details_preview_keyboard_and_no_event_bubbling` test's
`QQmlExpression.evaluate`; it did not complete. Two failures expected destructive
same-project reopen and were updated to distinguish resume from explicit reload;
those scenarios pass in the 138-case final selection above. Two batch-selection
failures are outside this entry slice. The List failure was independently reproduced
on the entry GUI reconstructed into `sample_data/projects-entry/baseline/`; all four
reconstructed shell/bridge file bytes match the saved entry SHA-256. Its verified
result is `baseline-selection-verified.log` (1 failed, 6.21 s). No unrelated Materials
behavior was changed to conceal these diagnostics. The access violation has not been
claimed fixed or proven caused by this entry slice. The older full-suite gate remains
open; affected success is not full-suite success.

Preservation audit: 458 entry files, zero missing; 18 changed existing files and three
new implementation/test/harness files for this slice. The other 440 entry files,
including all COLMAP/benchmark code/data/docs and existing Materials/media services,
match their entry SHA-256. Branch/HEAD unchanged, index empty; no commit, push, merge,
reset or discard. `changed-from-entry.json` records the exact existing-file list.
The overall interface plan stays ACTIVE for later presentation work, wider verification
and user acceptance; the bounded Projects implementation and agent visual review are
complete.


## Scope and contracts

Historical first-implementation scope (retained as evidence, not today's assignment):
implement the selected media-editor reference with existing Qt Quick components:
Materials / Reconstruction / Splat / Results; resizable catalog, embedded photo/video
viewer, contextual properties, image navigation/video transport. Preserve import,
UUID selection/groups, participation, draft/Save/readback and stale-reply protection.
Fix Plan participation and explicit historical Views input compatibility.

Owners: [GUI layout](../../GUI_DESIGN.md), [UX navigation](../../UX_UI_SPEC.md),
[participation and groups](../../PROJECT_FORMAT.md#source-participation-intent-m12b2a),
[pipeline inputs](../../PIPELINE.md#stage-inputs-and-outputs),
[verification](../../DEVELOPMENT.md#verification-workflow).

## First implementation acceptance and evidence

- [x] Working shell and panel-scoped scrolling; legacy page preferences preserved.
- [x] Catalog actions, batch/current distinction and persisted readback.
- [x] Bounded asynchronous photo Fit/zoom/pan/step and truthful detail limit.
- [x] Installed Windows Qt video playback, seek and in-viewer errors.
- [x] Properties and existing reconstruction/dataset/training/results accessible.
- [x] Plan regression and readiness invalidation.
- [ ] Affected checks, full repository gate, all-QML lint and docs/diff checks.
- [x] Inspect real native Dark/Light, 1440×900/1024×640, high-DPI captures covering
  photo, video, empty, batch and error. Record limitations separately.

## Deferred concrete slices after the entry flow

1. Persist video intervals using source timestamps and immutable source identity;
   define selection boundaries, timebase and downstream fingerprints.
2. Prepare/review frames before reconstruction with quality evidence, overrides,
   progress/cancel and an explicitly selected published Views input.
3. Image-coordinate masks with source/view scope, durable manual corrections and
   separate SAM3/tracking worker contracts; never silently overwrite corrections.
4. Sparse viewer with stable point/camera IDs, camera orientations, layers, picking,
   frame links and explicit component context independent of downstream selection.
5. Create Gaussian Splat after validated reconstruction/dataset selection; retain
   training history, export and external viewer handoff.

360/fisheye preprocessing and LiDAR viewer inputs remain unsupported; viewer state
must leave room for additional typed media/projection kinds without claiming support.

## Results

No manual user acceptance recorded. No commit, push, merge, reset or discard.

### Delivered file map

| Area | Files / responsibility |
| --- | --- |
| Shell | `qml/Main.qml`, `WorkspacePanel.qml`: primary tabs, More, full workspace, local parameter scroll; stable IDs 0–6 |
| Materials | `SourcesPage.qml`, `SourceActions.qml`: split/collapse, virtualized List/Grid, groups/filters, current/batch actions |
| Media | `MaterialViewer.qml`, `PhotoViewport.qml`, `SourcePreviewDialog.qml`: actual photo review and Qt Multimedia transport/errors |
| State and lifetime | `qml_media.py`, `qml_bridge.py`, `thumbnails.py`, `point_preview.py`: bounded/coalesced delivery, local metadata errors, close drain, teardown guard |
| Workflow | `workflow_vm.py`, `controller.py`, `application/desktop_workflow.py`, `application/pairs.py`: Included resolver, historical input validation, readiness/execute guard |
| Existing screens | `TrainPage.qml`, `WorkflowStrip.qml`: Splat naming and functional cube icon, no decorative sparkles |
| Verification | `test_materials_workspace.py`, `test_plan_source_participation.py`, adapted Qt tests, `scripts/capture_gui.py` |
| Owners | root AGENTS, GUI design, UX spec, M12 summary, roadmap, active-plan/index routing and root `design-qa.md` |

### Evidence produced by Codex

Windows; existing Python 3.12.10 / PySide6 and Qt 6.12.0 environment. No toolchain,
model or codec installation; backend/GPU integration opt-ins remain unset.

- Final media/lifetime/focus/geometry regression run: **13 passed, 58.13 s** in
  `sample_data/workspace-close-final.log`. Current-source/explicit-historical Plan
  final retest: **5 passed, 18.49 s**, including actual published Views validation.
- All-QML qmllint with source/theme imports: passed without warnings. Scoped Ruff:
  passed. Full Ruff retains one historical E501 in unchanged `core/registry.py:52`;
  the same issue is recorded in the dated M12 baseline. Docs: 45 files, zero errors.
  `git diff --check`: passed.
- Native Windows: **56 actual exposed-window captures**, 28 each at actual DPR 1.0
  and 1.5; 1440×900 / 1024×640, Dark/Light, photo Fit/zoom/pan, batch, H.264 Play/Pause,
  real slider seek, errors (photo and video), expanded Grid, empty and secondary
  screens. Manifests report native title bar and zero QML warnings. Audio and other
  codecs are unverified. Originals are existing read-only local photos; the video
  and corrupt files are explicitly named owned review fixtures, not product data.
  Original captures/manifests: `sample_data/ui-review/materials-1/` and `materials-1.5/`.
  The reference, representative originals and both overview sheets were inspected;
  visual conclusions are in [design QA](../../../design-qa.md).
- Original unrelated COLMAP/benchmark Python file hashes remain identical to entry;
  shared roadmap/index changes preserve the pre-existing benchmark additions.
- Early development checks exposed UI hit areas, Grid minimum-width overflow,
  hidden presentation requests, video source reset and timer/teardown races. The
  implementation and affected tests were repaired; early failures are not final
  passing evidence. The early 213-case GUI run was interrupted after the lifetime
  race was identified, so it is not reported as a passing suite.

### Full default-collection gate

The full run uses default selection with offscreen Qt and no backend opt-ins; `-vv`
only makes progress inspectable. The first quiet attempt was stopped without a
result. The verbose prefix was stopped to load final Qt changes in a fresh process.
To avoid repeating unchanged backend work, complete file results from that prefix
are retained; the remaining full collection plus affected GUI files run afresh.
A first response list using individual node IDs could not collect timestamp-generated
training-protocol IDs; it executed no tests and was replaced with stable file paths.

Exact final default collection: **1960 cases**. The coverage manifest in ignored
`sample_data/workspace-verification-coverage.json` records all IDs and per-file
counts. Retained prefix: 43 complete files / 565 cases. Fresh remainder: 98 files /
1395 cases, including all changed GUI responsibilities. Commands:

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
.venv/Scripts/python.exe -u -m pytest -o addopts= -o faulthandler_timeout=60 -vv -rs
.venv/Scripts/python.exe -u -m pytest -o addopts= -o faulthandler_timeout=60 -vv -rs '@sample_data/workspace-remaining-files.txt'
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe scripts/check_docs.py
```

The user explicitly stopped further verification and requested delivery. The remaining
run was interrupted; no final per-file coverage audit was performed. Full verification
is incomplete and must not be reported as passed. The implementation and native visual
evidence above remain delivered; manual user UX acceptance is not recorded.
