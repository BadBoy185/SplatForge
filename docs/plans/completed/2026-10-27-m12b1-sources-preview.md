# M12b1 — Sources, explicit photo/video import and preview

Status: completed; user manual UX review accepted on 2026-10-27. Full H remains user-owned.
Owner/date: Codex, 2026-10-27. Base: M12a implementation `5ec109d`.

## Goal

Project -> Sources -> Add Photos / Add Video -> persisted inventory -> readable
source list -> photo preview -> clearly explained next step.

## Non-goals

No recursive/mixed-folder scanner (M12b2), device metadata/grouping, named groups,
batch relink, Prepare execution, selected/rejected review, reconstruction, export,
viewers, currentness, presets or ETA redesign. Directory-drop project-open routing
and existing top-level folder review remain unchanged. No source deletion.

## Relevant contracts

- [UX/UI specification](../../UX_UI_SPEC.md), sections 7–9, 12–14 and 18:
  this user-authorized bounded subset defers folder/device/group workflows.
- [GUI presentation architecture](../../GUI_DESIGN.md#presentation-architecture).
- [M12 shared projects](../../M12.md#architecture-and-shared-projects).
- [Project ownership](../../PROJECT_FORMAT.md#storage-layout-and-ownership).
- [M12 planning direction](../../../ROADMAP.md#m12--desktop-gui).
- [Verification workflow](../../DEVELOPMENT.md#verification-workflow).

## Affected areas

Sources QML, preview/detail dialogs, existing media/presentation view models,
additive facade metadata projection and focused GUI tests. Preserve unrelated
COLMAP/feature/benchmark/Tanks and Temples edits and their mixed documentation hunks.
M12a was separately audited/committed before these edits; index must stay empty.

## Acceptance criteria

Real async multiple photo/video ingest; persisted readback/reopen and identity/type;
failure leaves existing rows and permits retry; no optimistic rows or frame extraction.
Standard rows show filename/type/stored dimensions/duration/recorded availability;
hash/evidence remains inspectable in Details. Source check is explained and enabled
normally when available. No filesystem scan/hash on presentation refresh.
Preview has filename/index, X/Esc, bounded Previous/Next and arrow keys in current
visible source order; selection follows preview, stale work cannot replace it or
reopen a closed popup; failures stay in preview with technical details.
Actions/check/list/footer fit 1024x640 and normal desktop, with a virtualized list.
No empty result pickers or irrelevant pagination in ordinary Sources flow.

## Verification

Codex runs only targeted `test_media.py`, `test_gui.py`, `test_qml.py`,
`test_qml_workflows.py`, `test_qml_interaction.py`, `test_gui_architecture.py`,
new `test_qml_sources.py` and the affected facade `test_desktop.py` tests.
Offscreen Qt, changed-file Ruff, all-QML qmllint, scoped docs/diff checks;
native captures in Dark/Light at 1024x640 and 1440x900. User owns the full H gate.
No M12b1 stage/commit/push before user review.

## Decisions / unknowns

- 2026-10-27: Continue remains visibly disabled with "Prepare Data is not available
  yet". The existing next navigation destination is a technical reconstruction
  screen; this slice does not route users there or execute Prepare.
- Availability labels explicitly say "at last check". Ingest hashes alone are
  "Not checked recently"; metadata reuse never becomes fresh hash verification.
- Source Details retains recorded technical evidence. Published views are optional
  there only when real publications exist; pagination requires real paged content.
- Decode failures keep traceback in the existing Technical Details presentation;
  each preview request and close invalidate earlier responses.

## Final status

Implementation is ready for user review, with no M12b1 staging/commit/push.

Codex ran on M12a `5ec109d` plus this slice and the preserved unrelated tree:

| Check | Actual result |
| --- | --- |
| Eight-file affected pytest below | 178 passed, 0 failed/skipped, 327.13 s |
| Two additional narrow checks below | 2 passed, 7.01 s |
| Scoped Ruff: desktop.py, presentation.py, qml_bridge.py, qml_media.py, qml_models.py, test_qml_sources.py | Passed |
| qmllint, all QML sources | Passed, no output |
| Scoped docs links, six Markdown files | 0 errors |
| Final diff whitespace and scope | Passed; index empty |
| Native Qt windows, synthetic persisted fixture, DPR 1.0 | 25 captures; Dark/Light, 1024x640 and 1440x900; no QML warnings |

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
.\.venv\Scripts\python.exe -m pytest -o addopts= -v -rs tests/test_media.py tests/test_gui.py tests/test_qml.py tests/test_qml_workflows.py tests/test_qml_interaction.py tests/test_gui_architecture.py tests/test_qml_sources.py tests/test_desktop.py
.\.venv\Scripts\python.exe -m pytest -o addopts= -v -rs tests/test_qml_sources.py::test_preview_click_outside_closes tests/test_qml_sources.py::test_thousands_of_sources_use_bounded_delegates_without_decoding
```

The first run collected 22 new Sources cases; the two additional cases were added
while that gate ran. Together these exercise all 24 new cases, including actual
QML accepted handlers with single/multiple OS-style URL selections, real MediaService
inventory commits/readback, failure atomicity/retry, no hash on refresh, source check
assurance, preview failure/close/navigation/order/stale responses, viewport layout,
empty pagination suppression and 1500-row virtualization without image decoding.
Native picker interaction itself remains for the user's manual smoke; probes in
these deterministic tests/captures are injected fakes, not real video decoding.

Native visual review confirmed immediately visible actions/check/list/footer,
readable rows, X and first/middle/last navigation, meaningful disabled boundaries,
and non-clipped expanded Technical Details/error panels. Final captures use a normal Qt event loop beyond theme animation, with an extra
render settle. Enabled Check Source Files backgrounds were confirmed against theme
tokens (#18212b Dark, #f7f9fc Light); an intermediate synchronous capture had caught
an unfinished palette transition and was replaced. Earlier development failures
in picker enum/list conversion and QML Loader test ownership were corrected; the
final gate above is clean. The full H/default repository suite was not run by Codex.

Evidence (ignored): `sample_data/m12b1-final-targeted-tests.log`,
`sample_data/m12b1-extra-targeted-tests.log`,
`sample_data/ui-review/m12b1-native/manifest.json` and adjacent PNGs.
31 unrelated files match the initial SHA-256 snapshot; unrelated benchmark hunks in
the documentation map/active index remain intact. Documentation commits `429506a`
and `a3e7a05` remain ancestors. Registry.py remains unchanged with pre-existing E501
at line 52 (blame: `9062af66`); it is not part of either slice.

Remaining: user manual UX/native multi-file picker smoke and user-run H. Continue
is intentionally disabled until M12c provides Prepare Data; videos remain source
assets with no new video playback/frame extraction. No 150% DPI acceptance is
claimed from these DPR 1.0 captures. No M12b2 work has started.

## Closure — 2026-10-27

The user accepted the manual UX review and explicitly authorized the separate
M12b1 implementation commit and M12b2 continuation. Prior dated evidence above
is retained; this closure does not claim a new full H run.
