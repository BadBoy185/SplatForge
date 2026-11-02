# M12c — Direct Prepare Data settings

Status: delivered bounded implementation; human acceptance open. Owner: main agent,
2026-10-29. All M12c is not complete; no next slice starts in this task.

## Goal and boundary

The user replaces the planned Fast / Medium / High / Max Prepare profiles with
direct access to the existing working preparation methods and parameters. Deliver
one complete edit/save/plan/run/reopen scenario; no profiles, new algorithms,
experimental integration, masks/tracking or reconstruction work. Existing manual
acceptance of M12b4, M12c1, Image Review and scopes remains open.

Contracts: [AGENTS](../../../AGENTS.md), [workflow](../../AGENT_WORKFLOW.md),
[verification](../../DEVELOPMENT.md#verification-workflow),
[M3/M4 pipeline](../../PIPELINE.md#stage-inputs-and-outputs),
[saved frame intent](../../PROJECT_FORMAT.md#prepare-data-desktop-entry-m12c1),
[GUI](../../GUI_DESIGN.md#prepare-data-and-selected-images-m12c1),
[reference #7](../../design/references/07-prepared-frames.png), UX sections 15–19.

## Verified entry and capabilities

Branch `codex/m12b3-ux-review`, HEAD `4d83147acb01907ce02b1311977608f23d6eab17`,
empty index. All 530 nonignored entry files, hashes and Git diffs/status retained in
ignored `sample_data/m12c-settings-20261029/entry/`. Preserve the entire dirty entry,
including runtime/COLMAP/benchmark work. No Git mutation or dependency/model install.

| Capability | Actual status/parameters | Enabling and limits |
| --- | --- | --- |
| Fixed FPS | ViewsService two-stage route, exact target/candidate FPS | Exclusive method selector; candidate >= target; no quality stage |
| Sharpest Interval | ViewsService three-stage route, exact target/candidate FPS | Exclusive method selector; video candidate >= 2 * target; quality required |
| Minimum sharpness | Optional exact nonnegative threshold; default None | Independent Sharpest checkbox; no threshold invented when enabled |
| dHash suppression | Sharpest default enabled, Hamming 4, recent lookback 8 | Independent checkbox; within each video only, never across photos/sources |
| Analysis proxy | Pillow edge variance + dHash, max side 1024 (64..4096) | Required Sharpest analysis parameter; not saved-image resolution |
| JPEG / PNG | FFmpeg output, JPEG qscale2 (1..31), PNG compression6 (0..9) | Format selector plus applicable parameter; output retains supported dimensions |

At entry the desktop derived candidate density/encoding/analysis from defaults; the
working CLI/service already supports explicit settings. Registered/proposed features
do not imply a runnable route. A narrow utility inventory routes unready technology
to a documented backlog. No prior profile implementation was found in this entry.

## Agreed interfaces, persistence and normalization

- Keep typed selector settings in the existing frame-selection envelope. Persist the
  candidate/analysis options in a versioned `prepare_data` extension of that same
  existing extensible envelope. No second store or new top-level project format.
  Absent extension retains the existing legacy resolution. Unknown method/schema/
  extension refuses Prepare editing/execution, and survives unrelated saves.
- New pure application functions own field projection, exact interval-to-FPS parsing,
  validation, draft composition and resolved requests. GUI only stages/saves through
  the existing ProjectController/ProjectService. Preserve all other intent/envelope
  fields. Current form and historical run settings are distinct.
- One editable target interval in exact seconds; corresponding FPS is read-only.
  Candidate FPS is a separate sampling density. No float-derived timing identity.
  Photos have no active time controls. dHash suppression is video-only.
- Resolve inactive JPEG/PNG, Fixed-vs-Sharpest, disabled threshold/dHash parameters
  before route publication, with canonical resolved metadata as well as recipe keys.
  Photo-only video policies normalize in the new desktop request, retaining saved
  video intent for future mixed input. Never change a key while leaving different
  resolved artifact metadata under it; historical contract-1 artifacts stay exact.
- Run pins the validated saved request/revision. Form edits never process data or
  alter a running snapshot. Cancel/failure retains previous publications and exact
  review heads; save/validation failures never report success. All reads/errors need
  current request/project guards. Scopes/provenance and Trim remain independent.

## Exclusive ownership and resources

| Owner | Files/responsibility |
| --- | --- |
| Main | Contracts/docs/plan/state/backlog, new prepare_settings_vm.py and its tests, controller.py, prepare_vm.py, qml_bridge.py, frame_review_vm.py, Main.qml integration, native harness, existing fixture adaptations, Qt/app/cache runs and final verification |
| Backend implementation Sol/high | new application/prepare_settings.py, application/desktop_prepare.py, adapters/desktop_prepare.py, new tests/test_prepare_settings.py |
| GUI implementation Sol/high | new QML components/PrepareSettings.qml, pages/PreparePage.qml, new tests/test_qml_prepare_settings.py |
| Utility Luna/high | Read-only preparation technology inventory; complete |
| Fresh reviewer Sol/high | Final requirements/task-only diff, read-only |
| UX reviewer Terra/medium | Actual screenshots/scenarios, read-only |

Public pure application API agreed before parallel edits:
`prepare_settings_fields(document)`,
`prepare_settings_draft(document, fields, *, has_video=True)`,
`preparation_media_context(document, rows)` and
`resolve_preparation_request(document, *, has_video=None)`.
Existing `desktop_prepare.preparation_request` remains a compatible entrypoint.
Field map: method (`fixed_fps`/`sharpest_interval`), interval_seconds, candidate_fps,
image_format, jpeg_qscale, png_compression_level, min_sharpness_enabled,
min_sharpness, reject_duplicates, duplicate_hamming_threshold, duplicate_lookback,
quality_max_side. Numeric fields are exact strings, toggles are booleans.

GUI API: `vm.prepare.settings.state` contains fields, dirty/valid/error, canEdit/
canSave/supported, hasVideo and media counts, read-only targetFps; slots setField/save.
Main owns unsaved raw-form guards and save/discard integration. New QML uses existing
tokens/components, immediate basic settings and an explicit optional-functions section.

No nested delegation; max three active and two code-editing subagents; one file one
editor. Main exclusively owns Qt/native/shared project resources. Backend can run
only assigned short non-Qt tests with its own cache/temp root. GUI agent does not run
Qt/app; main runs tests. All requested roles explicitly specify model/effort; actual
serving metadata may remain unavailable.

Both implementation owners froze and transferred their files to main before final
integration/corrections. Five real subagents were used in total, with at most three
active and two editing concurrently. The requested role/model/effort values above
are known; actual serving metadata and task token/cost measurements are unavailable.

## Verification and finish

Short targeted checks: real launch parameters for all controls; toggles/None-vs-zero;
density/unsupported validation; photo/video/mixed input; save/reopen/error; canonical
active/inactive cache identity; frozen run request; existing Trim/review/scopes cases.
Scoped Ruff/QML/docs plus short native Dark/Light captures of basic/optional/error
states with generated media. Fresh independent final review and correction follow-up.
Full pytest/full verify/broad long suites/heavy benchmarks are forbidden, including
through agents/background/batches. No next slice starts automatically.

## Delivered scenario

The compact inspector exposes the existing two methods, one exact target interval
with read-only reciprocal FPS, independent candidate sampling and JPEG/PNG settings.
The optional disclosure exposes the two actual Sharpest policies and analysis size.
Fixed performs no quality stage. Sharpest needs quality even with both rejection
policies off; the existing assessor computes edge variance and dHash together, while
the dHash checkbox controls suppression. Off sharpness means None, distinct from
explicit zero. Photo context disables video-only timing/suppression, preserving
valid saved video intent. No algorithmic defaults, core keys or processing methods
were changed. The [pipeline contract](../../PIPELINE.md#direct-prepare-settings)
owns route and canonicalization details.

Save writes the existing project draft through ProjectService's revision guard.
Raw incomplete edits participate in the normal Save/Discard/Cancel/close guards.
Launch requires the validated saved revision and pins its request; running fields
cannot edit it. Form edits revoke old plan responses, including factory errors,
and never start processing. History reads have separate project/request guards.
A historical settings disclosure reads that
run's frozen request, independently of the current form. Original files, saved Trim,
source inclusion, prior automatic/effective artifacts and exact-run manual heads
are retained. No second intent store or rewrite of historical artifacts is added.

Header and next-set footer (validation, Save settings, Check plan, Prepare/Cancel)
stay visible while the inspector body scrolls, including 1024x640. This corrects the
independent UX review's concrete issue. It retains existing tokens/components and
reference #7's media-first composition.

The [technical backlog](../../TECHNOLOGY_STRATEGY.md#prepare-data-technical-backlog--2026-10-29)
records sourced proposals and adoption gates: extra quality metrics/learned IQA,
geometry/adaptive second-pass selection, separate masks/tracking and prototype
count/keep-all policies. None is presented as an implemented checkbox or installed.

## Short checks and retained evidence

Commands use `.venv/Scripts/python.exe` from the checkout. Isolated caches/temp
projects and logs are under ignored `sample_data/m12c-settings-20261029/`.
Full pytest/full verify, broad suites and heavy benchmarks were **not run**.
Selected results overlap and must not be added as a unique-suite total; no selected
pytest skips were reported. Checks cover generated or tiny test fixtures, not user
acceptance or broad codec/performance support.

| Runner / selection | Result and applicability |
| --- | --- |
| Backend agent: `-m pytest tests/test_prepare_settings.py -q --basetemp .../backend-pytest-01 -o cache_dir=.../backend-cache-01` | 27 passed, 3.57s: exact time, toggles/None/zero, bounds, inactive canonicalization, source/Trim context, unknown/legacy preservation and historical settings. |
| Backend agent: six selected existing `test_desktop_prepare.py` cases | 6 passed, 6.22s: saved slots/legacy, participation/Trim, request guards and historical lineage. |
| Backend agent: expanded settings selection and affected corrections | 28 passed/1 failed, 6.31s: fake fixture emitted PNG under JPEG declaration. Corrected fixture node passed, 3.07s. Final legacy wrapper node passed, 0.72s. New file has 30 cases, all exercised successfully across these runs; no combined 30-case rerun. |
| Main `gui-03.log`: three affected `test_qml_prepare_settings.py` nodes (direct controls/reopen, validation/toggles, navigation discard) plus `test_prepare_settings_vm.py` | 8 passed, 71.12s: launch request values, raw-save/close behavior, frozen running work, save failure/retry including return to baseline, stale plan factory error. Earlier `gui-01/02` expose corrected QWindow test-helper and production render-notification issues; their failures are not claimed as final passes. |
| Main `integration-04/05.log`: Sources/save guard, density/threshold case and existing M12c1 two-theme entry | Sources guard and density passed in 04; three other failures were outdated error regex/offscreen test clicks after footer movement. Updated affected test helpers/expectations; all three passed in 05, 12.46s. No hidden retry of a broad suite. |
| Main `gui-footer-06.log`: validation/toggles, photo-only controls, scopes/status/page readback, batch versus preview/reset | 4 passed, 31.14s against final pinned footer. |
| Main `compatibility-07.log`: Trim draft/save/discard, cancellation before handle, stale gallery failure after run/Sources switch, inward/heavy-import and dependency guards | 9 passed, 25.75s. |
| Main scoped Ruff / qmllint | 13 Python files passed (0.10s); 3 changed QML files passed with zero warnings (0.74s), with affected footer check also clean. |

Exact selected nodes beyond the new test files, all run with isolated `--basetemp`
and `-o cache_dir` below this evidence root:

```text
tests/test_qml_prepare_settings.py::test_direct_controls_save_plan_run_and_reopen_exact_request
tests/test_qml_prepare_settings.py::test_validation_and_independent_filters_never_invent_a_threshold
tests/test_qml_prepare_settings.py::test_invalid_raw_form_is_discarded_by_existing_navigation_choice
tests/test_qml_prepare_settings.py::test_photo_context_disables_time_and_video_similarity_only
tests/test_prepare_settings_vm.py::test_return_to_sources_during_settings_save_stays_in_prepare
tests/test_qml_prepare.py::test_prepare_entry_plan_run_history_and_source_restore
tests/test_qml_frame_scopes.py::test_scope_status_pagination_clear_and_captured_apply_readback
tests/test_qml_frame_review.py::test_batch_selection_is_independent_of_preview_and_reset_restores_automatic
tests/test_qml_video_usage.py::test_current_video_draft_error_save_discard_and_plan_invalidation
tests/test_qml_prepare.py::test_prepare_cancel_before_run_handle_drains_and_can_restart
tests/test_qml_prepare.py::test_stale_gallery_failure_cannot_contaminate_new_context
tests/test_desktop_prepare.py::test_request_resolves_only_saved_frame_slot_and_preserves_typed_settings
tests/test_desktop_prepare.py::test_legacy_request_preserves_real_supported_behavior_and_unknown_frame_refuses
tests/test_desktop_prepare.py::test_plan_uses_saved_participation_and_video_intervals_without_source_io
tests/test_desktop_prepare.py::test_run_delegates_exact_request_guard_and_cancellation_before_native_work
tests/test_desktop_prepare.py::test_sharpest_summary_preserves_frozen_policy_counts_and_quality_lineage
tests/test_gui_architecture.py::test_inward_imports_and_no_processing_libraries
tests/test_gui_architecture.py::test_client_entry_imports_do_not_load_heavy_libraries
tests/test_gui_architecture.py::test_dependency_boundaries
```

## Native and independent review

Main ran `scripts/capture_prepare_settings.py --output
sample_data/m12c-settings-20261029/native-03` in exposed native Qt windows. Twelve
captures cover basic settings, optional policies, threshold/density errors,
publications, historical settings and photo-only controls in Dark/Light, 1440x900
and 1024x640, DPR1.0. The manifest has no QML warnings or exceptions.

Three generated sources include two photos and a short installed-FFmpeg video with
nonzero original time. Real ViewsService runs publish Sharpest/PNG and Fixed/JPEG
with selected parameters. Assertions inspect pinned candidate/selection/quality
route settings, original PTS after saved Trim, original output dimensions despite
proxy analysis, inactive photo timing and frozen history. They also check retained
source participation, review head, source bytes and old artifact hashes. This is
real service execution with selected settings, not a raw child-process argv capture.
Earlier native-01/02 captures remain as correction evidence.

Fresh read-only Sol/high review inspected the task-only entry diff and actual
consumers, not only reports. Main confirmed and fixed two findings: a failed-save
staged draft could readopt a rejected value after the user returned to baseline;
Sources navigation during Save could throw. Affected regression cases passed.
Independent Terra/medium screenshot review found scrolling hid the heading/actions;
the pinned footer/header and final five native-03 captures resolved it with no new
concrete visual finding. Reviewers ran no tests or app themselves.

Final docs check: `scripts/check_docs.py` on the 11 changed Markdown files passed
with zero errors. Entry-relative inventory/whitespace and scoped `git diff --check`
passed for all 27 task files (13 Python, 3 QML, 11 Markdown). All 530 entry snapshot
copies and 511 unaffected entry files are byte-identical. Eight new task files and
19 modified entry files are accounted for; no removed or unexpected files. Branch/
HEAD stay unchanged, index empty. `task.diff`, `changed-files.json`,
`final-hashes.json` and `preservation.json` retain this evidence outside Git.
Final independent read-only review reports no unresolved confirmed findings in the
27-file tree. It independently checked actual code, task-only diff, contracts,
logs/native assertions, Git identity/empty index and all 530 entry copies. Its raw
outcome is retained in `independent-review.md` alongside the inventory. Only this
outcome and refreshed docs/inventory follow that review; human acceptance remains
open. A final type annotation prompted only its affected Ruff check (passed).

## Manual acceptance and remaining boundary

1. In a video/mixed project, choose each method, exact interval and candidate rate;
   Save, plan and run, then reopen. Compare the frozen published settings.
2. Toggle sharpness/dHash independently, including empty versus explicit zero
   threshold; verify validation, disabled incompatible controls and photo-only mode.
3. Exercise Save failure, retry back to the saved value, Save/Discard/Cancel and
   cancellation. Previous results and run/UUID decisions must remain available.
4. Recheck Trim source time, Image Review and source scopes after a new preparation;
   inspect both themes at narrow size and keyboard/focus/tooltips on the user's display.

Acceptance of M12b4/M12c1/Image Review/scopes and this slice stays open. Generated
fixtures do not establish real-user codec breadth, screen-reader or high/per-monitor
DPI behavior. Existing large manifest/hash I/O can remain O(N); no scale claim.
Normal Windows command execution fails logon1385; approved escalated commands ran
checks without toolchain/model installation. No Git publication or cleanup occurred.

Remaining M12c work is separately contracted masks/tracking, without an imposed
internal order; roadmap M12d currentness/lineage follows. Do not start either here.
