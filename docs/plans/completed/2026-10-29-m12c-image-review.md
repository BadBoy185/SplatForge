# M12c — Prepared image review and saved decisions

Status: completed implementation; manual acceptance open. Owner: main agent, 2026-10-29.

## Goal and scope

After M12c1, review all materialized candidates in Selected / Rejected / All,
inspect one frame independently of page-local batch selection, and save reversible
Exclude / Keep Anyway / Reset to automatic decisions. No pre-existing M12c2 number
or mandatory internal ordering was found in the current roadmap/specification.
This plan selects one complete Image Review scenario without claiming all M12c.

No masks/tracking, new preparation algorithm/preset, source exclusion, reconstruction
execution or redesign. M12b4 and M12c1 manual acceptance stay open.

## Contracts and decisions

- [UX sections 22–23](../../UX_UI_SPEC.md), [GUI](../../GUI_DESIGN.md#prepare-data-and-selected-images-m12c1),
  [reference #7](../../design/references/07-prepared-frames.png),
  [pipeline](../../PIPELINE.md#stage-inputs-and-outputs),
  [persistence](../../PROJECT_FORMAT.md#authoritative-records).
- All means every candidate in the exact prepared run, including candidates omitted
  by fixed-FPS selection. Selected/Rejected partition the **effective** membership.
  Automatic membership/reason and manual override are shown separately.
- Exclude forces omission; Keep Anyway forces inclusion; Reset removes the override
  and restores the automatic decision, including automatic rejection.
- Decisions bind project + exact preparation run + candidate/automatic artifact
  identity and digest + stable view UUID. No names, page indices or cross-run reuse.
- Persist through the existing writer/CAS mechanism. Publish a new validated,
  immutable reviewed selection with canonical decisions and upstream lineage; never
  mutate automatic output. The explicit effective run is the downstream input.
  Changed selection semantics invalidate actual consumers, preserving historical runs.
- Page limit 100. Batch selection is explicitly current-page only and clears on
  page/filter/run change. Preview/focus do not change that batch set.
- For quick preview Exclude, capture next UUID (else previous) from the pre-action
  full filtered order, including page boundaries. Advance only after confirmed save;
  close on empty. Block action delivery during save/loading/transition.
- Tokenize both success and error. Project/run/filter changes revoke pending reads.
  Save/readback failure is an error, never a success notification.

## Entry and preservation

Branch `codex/m12b3-ux-review`, HEAD `4d83147acb01907ce02b1311977608f23d6eab17`;
index empty. Existing dirty runtime/COLMAP/benchmark and prior GUI work retained.
515 entry files plus hashes/status/working/index diffs saved outside Git under
`sample_data/m12c-review-20261029/entry/`. No Git mutation or cleanup authorized.

## Ownership and resources

| Owner | Exclusive files / responsibility |
| --- | --- |
| Main | Contracts/docs/plan/state, bootstrap, controller, qml_media, GalleryModel role, existing M12c1 test fixture, native harness/captures and integration |
| implementation backend · Sol/high | New core/application/adapter frame_review, necessary backend project/route/validation/consumer extensions, test_frame_review.py |
| implementation GUI · Sol/high | prepare_vm.py, PreparePage.qml, new review VM/components, test_qml_frame_review.py |
| utility · Luna/high | Read-only bounded requirements audit, completed |
| fresh reviewer · Sol/high | Final task-only diff read-only; no implementation |
| UX reviewer · Terra/medium | Actual final screenshots/scenarios read-only |

One file has one editor; at most two code-editing subagents, three active subagents.
No nested delegation. Main exclusively owns native/Qt app runs and shared caches;
backend may run its own short non-Qt service tests with independent temporary roots.
Requested model/effort is known; serving metadata/cost remains unconfirmed.

Public API agreed before edits: `frame_review.page(root, run_id, filter, offset,
limit, anchor_view_id)` returns a frozen page with project revision, exact run,
effective run, review digest, counts and UUID items; each item carries automatic
membership, override, effective membership, reason, path and full-filter neighbor
UUIDs. `apply` validates expected project/revision/review digest and a complete batch,
then returns committed revision/digest/effective run. GUI delegates business rules.

## Acceptance and verification

Verify reopen, force-include vs reset, exact binding isolation, page/filter/preview
and batch identity, boundary/last/empty advance, atomic save failure, stale reads,
fingerprinted downstream input, immutable originals/automatic artifacts and M12c1
progress/cancel/retry/history compatibility. Use short targeted tests, scoped Ruff,
QML lint/docs checks, bounded native Dark/Light captures and independent review.
Full pytest/full verify, broad long suites and heavy benchmarks are explicitly
forbidden by the user; no splitting/delegating/background workaround.

## Evidence and final status

The selected scenario is implemented. Manual acceptance remains open, including
M12b4/M12c1. No further slice, cleanup or Git publication is started.

### Short checks

All commands use `.venv/Scripts/python.exe` at the repository root, with
`-q -o addopts=` for pytest. Each run has a fresh `--basetemp` under
`sample_data/m12c-review-20261029/` and separate backend/GUI/main caches.
No skips were reported in these checks. Durations below are pytest-reported.

| Owner / command selection | Result |
| --- | --- |
| Backend: `-m pytest tests/test_frame_review.py` before downstream/history cases were added | 9 passed, 23.09 s |
| Backend: `tests/test_frame_review.py::test_pairs_service_consumes_explicit_effective_run_and_keeps_automatic_history` | 1 passed, 4.75 s |
| Backend after review: `tests/test_frame_review.py::test_prepare_history_survives_twenty_five_review_publications` | 1 passed, 16.17 s |
| Main: `-m pytest tests/test_qml_frame_review.py` | 13 passed, 71.54 s; investigated while running, normal case progress confirmed |
| Main: five M12c1 nodes listed below | 7 passed, 41.90 s |
| Main after counter correction: GUI save-failure node + M12c1 entry node (Dark/Light) | 3 passed, 18.39 s |
| Main after error-copy correction: `test_qml_frame_review.py::test_save_failure_does_not_report_success_or_leave_stale_actions` | 1 passed, 6.33 s |
| Main: architecture inward-imports, dependency-boundaries, client-heavy-import nodes | 5 passed, 1.11 s |

M12c1 nodes: `test_prepare_entry_plan_run_history_and_source_restore`,
`test_prepare_cancel_before_run_handle_drains_and_can_restart`,
`test_prepare_run_failure_keeps_published_history_and_replaces_running_message`,
`test_stale_gallery_failure_cannot_contaminate_new_context`,
`test_stale_prepared_gallery_cannot_replace_returned_source` from
`tests/test_qml_prepare.py`. New GUI checks cover pre-action UUID neighbors in
Selected/All at a page boundary, last/empty fallback, batch vs preview, page clearing,
read drain, stale filter/project replies and failed writes. Service checks cover
forced include/reset, exact-run cache-hit isolation, invalid/stale batches, unknown
schemas, immutable bytes, save failure and orphan publication recovery.

Ruff was scoped to the 23 task-changed Python files. One final harness E501 wrap
was corrected and that file rechecked; all scoped files pass. GUI owner checked both
changed QML files with zero qmllint warnings; main rechecked PreparedFrameReview
after final error copy. Documentation/link/diff/preservation checks are recorded in
the final handoff. Backend outputs are in agent tool results; main GUI output logs
are retained under the evidence root. Counts overlap after fixes, so they are not a
single distinct-test total. Full pytest/full verify, broad long suites and heavy
benchmarks were **not run**, per the user's rule.

Final main checks: all 10 changed Markdown files have zero link/anchor errors;
tracked task diff and all 35 task files have zero whitespace issues. Preservation
manifest confirms unchanged branch/HEAD/index, intact 515-file entry snapshot,
unchanged unrelated entry files and no unexpected changes or removed entry files.

### Independent review and corrections

Fresh read-only Sol/high reviewer inspected the task-only entry-relative diff and
actual files. A confirmed P1 exposed review runs consuming the 25-result automatic
history limit. LocalPrepareReader now classifies automatic selection producer
metadata **before** LIMIT; cache-hit automatic runs retain their producer identity.
The regression makes 25 actual review publications over one tiny materialized
candidate pair plus a cached preparation run, and confirms both histories and saved
manual state survive. Only two automatic summaries require artifact validation.

Main also found an error-state counter ambiguity: the inspector fell back to
automatic counts as though they were effective review counts. Automatic and Review
are now explicit; unknown effective membership is unavailable. A real native CAS
failure then exposed misleading empty text; it now says frames unavailable/reload.
Only affected checks were repeated. Reviewer re-read these corrections and the final
35-file inventory, documentation, logs and native manifests: no remaining confirmed
code or evidence finding. Final additions record the checks themselves only.

### Native and visual evidence

Main ran `scripts/capture_frame_review.py --output <evidence>/native-01`, then
`--output <evidence>/native-02` after the counter correction. They produced 10 and
12 captures respectively, with manifest pass, no QML warnings or uncaught exceptions.
Four generated PNG originals feed the real ingest, quality, automatic selection,
review publication and readback services. One uniform photo is genuinely rejected
by the configured sharpness threshold. Keep Anyway, reset-to-rejection, independent
batch/preview, exclude advance, switch/reopen, source bytes and original candidate/
automatic publication bytes are asserted. No real user media or new runtime is used.

Native-02 adds a real competing metadata revision before Exclude: the backend refuses
the stale expected revision, the saved digest/effective run remain unchanged, and
explicit reload recovers. Following the error-copy fix, main reran **only** this
conflict/reload scenario against the owned generated project, yielding two corrected
captures and passing `native-error-03/manifest.json`. The ignored harness is
`sample_data/m12c-review-20261029/capture_conflict.py`.

Final screenshot examples (paths relative to the repository):

- `sample_data/m12c-review-20261029/native-02/Dark-selected-grid.png`
- `sample_data/m12c-review-20261029/native-02/Dark-batch-distinct-from-preview.png`
- `sample_data/m12c-review-20261029/native-02/Light-compact-preview.png`
- `sample_data/m12c-review-20261029/native-error-03/Light-save-conflict.png`
- `sample_data/m12c-review-20261029/native-error-03/Light-save-conflict-reloaded.png`

The exposed QQuick windows were 1440×900 and 1024×640, raster sizes equal to logical
sizes, DPR 1.0. Main inspected final captures. Independent Terra/medium UX reviewer
inspected all native-01 states and reference #7 separately; no confirmed visual
defects in those captured layouts. Runtime keyboard/focus/hover tooltips, screen
reader, other scales/per-monitor DPI, real user media/video breadth and large
history I/O remain unverified. Final native-error screenshots add error evidence;
they are main-reviewed, not a new claim of independent live operation. This evidence
does not constitute user acceptance.

### Manual acceptance and next boundary

1. Open a prepared run, compare Automatic vs Review in Selected/Rejected/All, and
   inspect a rejected frame's actual reason.
2. Keep Anyway, then Reset: automatic rejection must return. Exclude an automatic
   selection, reopen the project and verify counts and decisions.
3. Select page checkboxes, view another frame, run a batch action and confirm only
   checked UUIDs change. Check page/filter clearing and quick preview advance at
   page boundaries/last/empty results.
4. Verify failed save/reload, rapid result/project/Sources switching, and Dark/Light
   at the user's normal scale. Originals and previous results must remain present.

Remaining M12c includes source scopes/full provenance tooling, presets and separately
contracted masks/tracking. M12d currentness/lineage and reconstruction presentation
remain later roadmap work; no automatic downstream execution or global input choice
was added. Explicit effective run references already work with selected-view consumers.
