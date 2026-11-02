# M12b4 — Locate a moved source folder

Status: ACTIVE — implemented/reviewed; manual acceptance open; final full run stopped.
Owner/date: Codex, 2026-10-29.

## Goal and selection

Subsequent user instruction, 2026-10-29: the left-running final pytest was stopped
through its verified original session. **Остановлен по запросу пользователя; полный
результат отсутствует.** Original log and separate interruption/process evidence are
retained in `sample_data/continuation-20261029/final/`; no runner result was invented.
The user authorizes the next bounded development slice with M12b4 manual acceptance
still open. The new [verification rule](../../../AGENTS.md#verification-authorization-all-agents-and-future-sessions)
supersedes automatic full gates and earlier leave-running notes below; those are
dated history. No full/long run is authorized by "continue".

Close the previous combined-tree technical gates, then let a user restore external
source references after moving a folder, in one explicit reviewed operation.
The user accepted only the latest Materials/Trim visual refinement; the unperformed
manual functional checks remain open. Projects/Create and Materials/Trim appearance
must be preserved. No commit, staging, publication, stash or cleanup is authorized.

The Sources audit found an obligatory M12b gap: [UX section 13 and scenario G](../../UX_UI_SPEC.md)
require folder relinking. The single-source application/CLI relink is implemented,
but no GUI or atomic folder operation exists. M12b3's narrower exclusions do not
close the broader M12b. M12c therefore remains unstarted.

## Relevant contracts

- [Engineering constitution](../../../AGENTS.md) and [agent workflow](../../AGENT_WORKFLOW.md).
- [Source identity and participation](../../PROJECT_FORMAT.md#source-participation-intent-m12b2a).
- [GUI composition](../../GUI_DESIGN.md#selected-materials-workspace--2026-10-28)
  and [density](../../GUI_DESIGN.md#visual-density-calibration--2026-10-29).
- [Full and affected verification](../../DEVELOPMENT.md#verification-workflow).
- [M12 scope](../../M12.md), [roadmap](../../../ROADMAP.md#m12--desktop-gui).

## Bounded scenario and non-goals

Choose the recorded old folder and a replacement folder; preserve each relative
subpath; preview full-content identity matches and per-file problems; explicitly
Relink only a complete valid mapping. Hash again at Apply, guard source stability,
and publish one immutable inventory with the existing atomic revision check.
No partial folder commit. Progress and Cancel apply to preview and apply; cancellation
before publication leaves locators unchanged. Opening another project revokes stale
preview replies. Unsaved intent must be saved/discarded before the inventory mutation.

No automatic drive search, recursive content search, renamed-file inference, source
replacement, copying/deleting originals, new processing methods/presets, runtime or
benchmark work, Prepare UI, masks or redesign. A different folder hierarchy is an
explicit mismatch rather than a guessed mapping. The existing single-file CLI stays
compatible. Recovery uses the existing transactional inventory publication contract.

## Acceptance

- Multiple nested photo/video occurrences can be relinked with one confirmation;
  preview names exact scope, matched/total and unavailable/different-content cases.
- No write during preview or a failed/cancelled/stale apply. A successful apply
  preserves occurrence UUID/revision/content/probe, groups, participation, video usage
  and historical artifacts; originals stay byte-identical and readonly to the app.
- Path checks cover Unicode/spaces, drive changes, case collisions, containment and
  symlink/junction traversal. All matching uses full SHA-256, not filenames alone.
- GUI uses existing task, Save, busy, cancellation and project-switch safeguards;
  loading/empty/error/success/retry are usable at compact size in both themes.
- Meaningful application/adapters/GUI regressions, native screenshots/scenario and
  independent final review; final full gate for this boundary after fixes.

## Ownership and shared interfaces

No product implementation may begin until the pre-implementation full gate finishes.
The main agent owns requirements, interface decisions, documents, integration and
full pytest/Qt/native-run scheduling. All agents preserve existing dirty work and
must request a transfer before editing another owner's file. No nested delegation.

| Owner | Exclusive responsibility | Resources |
| --- | --- | --- |
| Main | Entry snapshot, registry E501 wrap, documentation, integration, full gates | `sample_data/continuation-20261029/`; full suite after tester transfer |
| Tester (Sol/medium) | Read-only old-failure/order/Qt-lifetime diagnosis initially | Isolated `diagnostics/`; sole Qt test runner until transfer |
| Utility (Luna/high) | Read-only M12 scope inventory | No app/test runs |
| Implementation (Sol/high), to assign | Folder application/adapters and their tests | Exact files/interfaces agreed before edits |
| GUI implementation (Sol/high), after gate | GUI bridge/dialog/controller integration and GUI tests | Isolated `gui/`; Qt runs only after main transfer |
| Fresh reviewer (Sol/high), to assign | Read-only final task diff and requirements | Frozen task diff; no implementation ownership |

Agreed application API (before implementation): `facade.service("folder_relink")`
provides `preview(root, old_folder, new_folder, *, cancellation, progress)` and
`apply(root, preview, *, cancellation, progress)`. Frozen typed preview contains
project UUID/revision, inventory reference and content digest, old/new folders and
one row per scoped occurrence (UUID, relative path, candidate, status, diagnostic).
It exposes total/matched/can_apply. Apply rebuilds the mapping from committed data,
checks provenance and exact scope, and rehashes instead of trusting preview status.
Result contains committed revision/inventory and source summaries for session
availability. Progress carries completed/total/filename/phase. Path validation is
in an injected adapter, not GUI filesystem inspection. Existing single-source API
and inventory persistence stay unchanged. Cancellation is checked inside the final
validation callback before publication; completion after the commit is success.

Application owner: new `application/media_relink.py`, `adapters/relink_paths.py`,
`tests/test_folder_relink.py`, plus wiring-only additions to `bootstrap.py`.
GUI implementation owner (transferred only with post-gate GO): new
`folder_relink_vm.py`, `FolderRelinkDialog.qml`, `test_qml_folder_relink.py`; narrow controller,
bridge, session-evidence and Sources action integration. Neither owner edits the
other's files. Native/Qt and default full runs remain serialized by the main agent.
Main owns the native capture harness and evidence, documents and integration. Both
implementation agents are read-only until the pre-gate result; at most these two
agents edit code concurrently afterward.

## Entry and verification evidence

Branch `codex/m12b3-ux-review`, HEAD `4d83147acb01907ce02b1311977608f23d6eab17`;
index empty. All 498 entry files and hashes, working/index diffs and status are saved
in ignored `sample_data/continuation-20261029/`. Runtime/COLMAP/benchmark work remains
outside the task. Prior full result: 1967 passed, 18 failed, 74 skipped; target passes
do not close it. Prior visual affected result: 155 passed, 1 opt-in skip.

Main initial full Ruff after the authorized condition line wrap: passed.
Main initial documentation check: 49 Markdown files, zero errors. Full pytest has
not yet been rerun. Exact commands/results and final task diff will follow here.

### Pre-implementation diagnosis and freeze

Tester checked all 18 prior failed node IDs in both orders with the earlier
TaskExecutor scenario: 19 passed in 100.95 s / 102.87 s. The reverse run exposed a
nonfatal Qt lifetime exception despite passing assertions. All old assertions now
pass; this did not justify declaring the complete suite passed.

The confirmed extra defect was `requestClose` scheduling a bound signal callback
without an owning QObject. Deleting the viewmodel before the delayed retry caused
`Signal source has been deleted` in the next event loop. A minimal reproduction
and timer-only four-case experiment establish the cause; exploratory TaskExecutor
and inspection-forwarding hypotheses were rejected. Main added the owner context
to the three bridge continuations. Tester added four lifetime regressions: 4 passed
in 3.44 s; the original calls restored only in an ignored runtime overlay cause
3 failures / 1 pass, without altering the working tree or assertions.

Tester final reverse combined check: **23 passed, 110.61 s, exit 0, no skips/warnings
or captured stderr**, one valid QApplication and zero residual windows before each
case. No inspection/TaskExecutor source or shared fixture change was needed. The
fresh reviewer found no confirmed defect in the exact entry-relative gate-fix delta.
Tester relinquished all test/app resources to main. Detailed failure map and exact
diagnostic commands: ignored `sample_data/continuation-20261029/diagnostics/REPORT.md`.

Main then froze source/test/script hashes and started the unfiltered default suite:

```powershell
.venv/Scripts/python.exe -u -m pytest -vv -ra --tb=short --durations=30 -o cache_dir=sample_data/continuation-20261029/pre/pytest-cache -o faulthandler_timeout=120 --basetemp=sample_data/continuation-20261029/pre/pytest-tmp --junitxml=sample_data/continuation-20261029/pre/pytest.xml
```

Qt uses `offscreen`; all `SPLATFORGE_TEST_*` are unset only in that child process.
The wrapper `sample_data/continuation-20261029/run_full.py pre` records command,
full log, JUnit timing, before/after code hashes and exit code. The suite is **running**;
no new relink implementation has started. Main full Ruff after the lifetime fix
passes; documentation check after plan addition: 50 files, zero errors. Initial
46-file qmllint initially exited 0 with one standalone Theme singleton import
warning. Explicitly importing the existing Theme qmldir corrected the invocation:
`pyside6-qmllint -I src/splatforge_gui/qml -i src/splatforge_gui/qml/theme/qmldir --max-warnings 0 <all 46 QML paths>`
then passed with exit 0 and no warnings. No QML or lint setting was changed.

### Pre-implementation full gate result

Main: **1989 passed, 74 skipped, 51 warnings, 4461.99 s, exit 0**. The wrapper
recorded 4463.20 s including startup/teardown, all **423** source/test/script/config
hashes unchanged, no additions/removals during the full run. Skips are unconfigured
opt-in integrations. All 51 warnings are pytest `record_property` incompatibility
with the newly requested xunit2 timing report; no product or Qt warning category was
reported. The next final run will use the supported legacy JUnit report format
instead, without changing test selection, assertions or repository configuration.

Full Ruff passed on this exact code. All 46 QML files passed with `--max-warnings 0`;
main documentation check after the run: **50 Markdown files, zero errors**. The old
technical gates are closed for this pre-implementation snapshot, not for future
folder relink edits. Commands/log/JUnit/freeze audit are in `pre/` under the evidence
directory. Independent gate-fix review found no confirmed remaining issue.

Main issued explicit post-gate GO and file-ownership transfers to the application
and GUI implementation agents. Application tests use isolated `backend/` resources;
GUI agent exclusively owns offscreen Qt checks until transfer to main. Main owns
`scripts/capture_folder_relink.py`, native windows, documentation and final full gate.

### Integrated implementation and affected checks

The two implementation agents wrote their assigned application/adapter and GUI
files after the explicit GO. They then stopped at usage limits. Main confirmed
there were no remaining test/app processes, took exclusive ownership of all their
files and Qt/native resources, and completed integration. The fixture-only first
backend failure lacked required CandidatePoolSettings values; main supplied the
explicit test settings while retaining the numerical-recipe equality assertion.
No assertions, skips or production defaults were weakened.

Delivered: inward-owned typed preview/apply service; injected lexical/path guard;
full SHA and stable read leases; immutable inventory CAS; facade wiring; existing
controller task/cancel and reader-drain integration; session availability evidence;
shared-control QML dialog and Materials menu action. No global token/layout, schema,
pipeline recipe, processing/runtime or benchmark change.

Main checks after integration, with isolated evidence/cache/temp directories:

- `python -m pytest tests/test_folder_relink.py tests/test_qml_folder_relink.py`
  (project `.venv`, verbose diagnostics): **45 passed, 83.88 s**, no skips/warnings;
  `affected-fixed.log`. Real service → GUI → commit/readback → viewer restoration →
  switch/reopen regression included. Main subsequently added the long-path and real
  apply-error regressions below; these counts overlap later results.
- `test_folder_relink.py::test_long_nested_unicode_locators_relink_without_truncation`:
  **1 passed, 1.05 s**, `long-02.log`. More than 260 characters, spaces and Unicode;
  all source names and resulting identity survive unchanged.
- Final consumer command:

```powershell
.venv/Scripts/python.exe -u -m pytest tests/test_qml_folder_relink.py::test_real_apply_content_change_reports_error_restores_readers_and_can_retry tests/test_qt_lifetime.py tests/test_materials_stability.py tests/test_qml_folder_browser.py tests/test_gui_architecture.py -vv -ra --tb=short -o cache_dir=sample_data/continuation-20261029/consumers-cache --basetemp=sample_data/continuation-20261029/consumers-tmp
```

Result: **48 passed, 96.24 s, exit 0**, no skips; `consumers.log`. One pytest
cache-directory rename warning (`WinError 5`), not a test/product diagnostic. The
full wrapper pre-creates its cache directory. The new real bytes-change test checks
no write on Apply failure, restored readers, cleared stale rows/counts and successful
retry. Application cases also cover offline old drive, nested/repeated/excluded
occurrences, content/stability/revision races, cancellation before publication,
publication fault/retry, forged preview and unsafe/colliding/reparse paths.

### Native GUI evidence and independent reviews

Main ran real exposed Windows Qt windows using only generated three-photo fixtures:

```powershell
$env:QT_QPA_PLATFORM = 'windows'
$env:QT_SCALE_FACTOR = '1.25'
.venv/Scripts/python.exe -u scripts/capture_folder_relink.py --output sample_data/continuation-20261029/native-03
```

Result: **exit 0, 18 captures, no QML warnings or exceptions**, manifest `passed: true`.
Actual logical sizes are 1440×849 and 1024×640, raster 1800×1061 and 1280×800,
DPR 1.25, native title bar and exposed window verified. Both themes show empty
replacement input, mismatched and fully matched scope; additional captures show
controlled loading/cancellation, success, restored photo and persisted reopen.
Only the pending-worker hold is synthetic scheduling. Hashes, inventory publication,
one saved revision, excluded-source scope, source identity/intent and byte-preservation
checks use real services. The harness moves only its fresh generated fixture after
explicit containment checks. Two initial harness runs corrected QObject lookup and
wrapper retention; no product change was needed for those harness defects.

A fresh read-only reviewer inspected the actual entry-relative diff, including new
files. It found one P3: clearing the preview after success erased matched/total.
Main retained explicit summary counts, cleared them on failure/cancel/invalidation,
and made QML terminal labels state-specific. The real service integration reproduced
the issue before the fix and passed afterward. Final independent code review of
product/tests/harness: **no confirmed remaining finding**; no edits or app/test runs
by the reviewer. A separate UX reviewer inspected representative Dark/Light native
images at both sizes: **no confirmed visual defect**. This is agent review, not user
acceptance or independent manual operation.

Main full Ruff passed. All **47 QML files** passed with exit 0 and no warnings using
the same explicit qmldir import as the pre-gate. `git diff --check` passed (Git emits
existing LF/CRLF conversion notices, not whitespace errors).

Exact lint/document commands (main):

```powershell
.venv/Scripts/python.exe -m ruff check .
$qmlSources = @(rg --files src/splatforge_gui/qml -g '*.qml')
& .venv/Scripts/pyside6-qmllint.exe -I src/splatforge_gui/qml -i src/splatforge_gui/qml/theme/qmldir --max-warnings 0 @qmlSources
.venv/Scripts/python.exe scripts/check_docs.py
git diff --check
```

Documentation check after the compact state/plan updates: **50 Markdown files,
zero errors**. No source/test/script/configuration change followed the final freeze.

### Final combined-tree full gate

After fixes and the independent review, main froze source/test/script/configuration
hashes and started the unfiltered **2110-item** default suite:

```powershell
.venv/Scripts/python.exe -u -m pytest -vv -ra --tb=short --durations=30 -o cache_dir=sample_data/continuation-20261029/final/pytest-cache -o faulthandler_timeout=120 --basetemp=sample_data/continuation-20261029/final/pytest-tmp --junitxml=sample_data/continuation-20261029/final/pytest.xml -o junit_family=legacy
```

The wrapper is `sample_data/continuation-20261029/run_full.py final`; it records
the command/log/JUnit/exit/freeze audit in `final/`. Qt is offscreen, optional backend
opt-ins are unset only for its child. Supported legacy JUnit avoids the earlier
report-format warnings without changing assertions or selection. **Running**; no
final full success is claimed yet. Main owns the sole test process; only documentation
is updated during this freeze.

User-requested interim handoff: leave this single run working; the user will check
its result later. `final/pytest.log` is live; `final/result.json` appears on completion
and records exit code, timing and unchanged-tree audit. No final success is claimed,
and no repeat full run or next implementation slice is started. This plan stays
ACTIVE pending that result; the implementation/review/native evidence is delivered.

### Remaining acceptance boundaries

No automatic drive search, renamed-file inference or partial relink. Real user
photo/video codecs and video-reader lifetime, OS folder picker/Explorer, screen reader,
keyboard focus traversal and other display scales remain manual evidence gaps.
Generated screenshots do not cover every error/list-size/compact-theme combination.
The old Materials/Trim/M12b3 manual checklists are not marked performed by the user.
M12c is unstarted; no next slice, Git publication or cleanup follows automatically.
