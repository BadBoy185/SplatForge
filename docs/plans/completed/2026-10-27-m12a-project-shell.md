# M12a — Project shell and Create/Open

Status: completed; user manual acceptance and default regression recorded.
Owner/date: Codex, 2026-10-27.

## Goal

Implement Home -> Create/Open -> persisted workspace -> Sources empty state from
the approved [UX/UI product specification](../../UX_UI_SPEC.md), sections 3–7.
The specification was committed alone as `429506a`; implementation stays unstaged.

## Non-goals

No new ingest/scanner/groups, Prepare/Reconstruction/Viewer/result selection,
training/export UX, ETA, engine or storage schema changes. Preserve existing file
and folder ingest actions without expanding their backend contracts.

## Relevant contracts

- [GUI presentation boundary](../../GUI_DESIGN.md#presentation-architecture).
- [Project ownership](../../PROJECT_FORMAT.md#storage-layout-and-ownership) and
  [safe creation](../../PROJECT_FORMAT.md#safe-writes-and-migrations).
- [Verification workflow](../../DEVELOPMENT.md#verification-workflow).
- [Engineering invariants](../../../AGENTS.md).

## Affected areas

Desktop view model/name helper, project controller, Home/Create/Sources QML and
focused GUI tests. The documentation map and active-plan index already contain
unrelated benchmark edits; preserve those and add only M12a/specification routing.
All implementation files were clean before this task.

## Acceptance criteria

Name + parent Location form, live final path, Windows-safe single-component names,
Unicode/spaces, no preview/Cancel I/O, backend-only creation and persisted readback.
Refusal/error keeps current workspace and excludes failed destinations from recents.
Successful create opens Sources, with no processing. Open supports CLI projects,
retains persisted identity and refuses invalid projects atomically. Existing draft,
busy, queued-worker/generation and save/drain behavior stays covered.

## Verification

Run affected checks only: `test_projects.py`, `test_project_cli.py`, `test_gui.py`,
`test_qml.py`, `test_qml_workflows.py`, `test_gui_architecture.py`, plus existing
`test_qml_interaction.py` because shell/navigation and open lifecycle changed.
Use offscreen Qt, changed-file Ruff, changed-QML qmllint, documentation links and
diff checks. Record final results here. The user explicitly owns full H/default
regression; Codex must not run it or stage/commit implementation.

## Decisions / unknowns

- 2026-10-27: GUI joins parent/name; ProjectService.create keeps its final-Path API.
- Adopt a new workspace only after a complete backend overview succeeds. QML does
  no directory creation or persistence parsing. Existing TaskExecutor ownership,
  queued signals and generation guards remain authoritative.
- Recents reuse QSettings paths and backend persisted names/identity/availability;
  no inferred pipeline status. Last-opened timestamps are deferred; the preferences
  allowlist/schema remains unchanged.
- Audit constraints retained for later slices: selected result and running operation
  are separate concepts; user groups do not imply calibration/processing grouping;
  currentness follows semantic lineage, not global project revision; Reconstruction
  Review is a normal UX step without a backend `user_viewed_result` training gate;
  cold-start ETA remains a backend gap and the UX requirement stays in force.

## Implementation handoff evidence (before user acceptance)

Implementation is ready for user review. Codex ran the following on `429506a` plus
the unstaged M12a files and the preserved pre-existing working-tree changes:

| Check | Evidence |
| --- | --- |
| Final affected pytest, seven files listed above | 174 passed, 0 failed/skipped, 261.55 s |
| Focused lifecycle checks after readiness correction | 26 passed, 101.28 s |
| Ruff on four changed GUI Python modules and three changed test files | Passed |
| qmllint on Main.qml, HomePage.qml, SourcesPage.qml | Passed without warnings |
| Scoped Markdown links and diff whitespace | Passed |
| Native Home/Create/Sources captures, Dark and Light | Six captures at 1024×640, DPR 1.0, no QML warnings |

Environment: Windows, Python 3.12.10, pytest 8.4.2, PySide6/Qt 6.12.0; pytest used
`QT_QPA_PLATFORM=offscreen`. Final test command:

```powershell
.\.venv\Scripts\python.exe -m pytest -o addopts= -v -rs tests/test_projects.py tests/test_project_cli.py tests/test_gui.py tests/test_qml.py tests/test_qml_workflows.py tests/test_gui_architecture.py tests/test_qml_interaction.py
```

Local ignored evidence: `sample_data/m12a-final-targeted-tests.log`,
`sample_data/m12a-lifecycle-tests.log` and `sample_data/ui-review/m12a-native/`.
Earlier development runs exposed and resolved a QML notification-order warning,
test waits that ended before queued Open completion, and the need to invalidate
reads requested against the retained workspace during a pending switch.

Manual user checks remain: native Browse/Open dialogs; Unicode/name/location preview
and Cancel; existing destination refusal while another project is open; recent
availability and reopen identity; Save/Discard/Cancel; appearance at 150% DPI.
Last-opened metadata was not added. A backend-created directory is retained after
a subsequent readback error, without adding it as a successful recent project;
there is no automatic deletion/rollback of user-visible directories.

Codex did not run H/default regression or stage/commit implementation. The user
owns this remaining gate, with optional backend integrations disabled in a separate
PowerShell session:

```powershell
Set-Location C:\Dev\SplatForge
$env:QT_QPA_PLATFORM = "offscreen"
Get-ChildItem Env:SPLATFORGE_TEST_* | ForEach-Object {
    Remove-Item -LiteralPath ("Env:" + $_.Name)
}
.\.venv\Scripts\python.exe -m pytest -o addopts= -v -rs --durations=20
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe scripts/check_docs.py
```

At handoff the plan remained active pending user evidence and the commit decision.
The dated closure below supersedes that pending status.

## User acceptance and closure — 2026-10-27

The user accepted native Home/Create parent/name/destination preview, real creation,
Sources transition, Cancel and reopen lifecycle. Sources/preview discoverability
issues are accepted follow-up scope for M12b1, not M12a blockers.

User-run default regression: 1714 passed, 72 expected opt-in integration skips
(missing SPLATFORGE_TEST_*); docs checker: 39 Markdown files, 0 errors; diff check
and QML lint passed. Ruff reported pre-existing E501 at core/registry.py:52.
Git status/diff show that file unchanged; blame attributes line 52 to 9062af66
(2026-10-19), before M12a. It is excluded from this implementation commit.
The full gate was not rerun by Codex.
