# M12c corrective slice — Prepare plan budget feedback

Status: delivered bounded correction, 2026-10-29; human acceptance open.
Main owns this bounded correction after the user's real
4K/Trim screenshots. It does not close manual acceptance or start another M12c feature.

## Entry and confirmed cause

Branch `codex/m12b3-ux-review`, HEAD `4d83147acb01907ce02b1311977608f23d6eab17`,
empty index. All 538 nonignored entry files, hashes and Git status/diffs are retained
in ignored `sample_data/m12c-budget-20261029/entry/`. Preserve the combined dirty
tree, especially runtime/COLMAP/benchmark and previous GUI work. No Git publication,
reset/cleanup/discard/stash/staging or dependency/model install is authorized.

The 3840x2160, 108.575-second video at candidate4fps needs a conservative bound of
436 candidates / 28,959,440,896 bytes (26.97GiB), exceeding the default20GiB limit.
The existing extractor materializes the full source before exact Trim restriction;
using only the 56.196-second Trim union for scratch would be incorrect. JPEG quality
does not reduce this deliberately encoding-independent bound. Defaults stay intact.
See [pipeline](../../PIPELINE.md#used-video-intervals).

Confirmed presentation defects: a blocked plan says Saved plan ready, a null count
becomes undefined in QML, the full-duration explanation disappears on budget failure,
and the low-level byte/UUID message suggests a budget setting absent from this GUI.

## Scope and ownership agreed before edits

| Owner | Responsibility / exclusive files |
| --- | --- |
| Main | core/views.py typed ValueError metadata only, application/desktop_prepare.py diagnostics, prepare_vm.py, PreparePage.qml, targeted tests, small native harness, docs/state/plan and all Qt/native/cache resources |
| Read-only Sol/high explorer | Trace full-duration budget versus actual Trim execution; no edits or runs; complete |
| Fresh read-only Sol/high reviewer | Final requirements/entry-relative diff and evidence; no edits, tests or app |

No concurrent editing or nested delegation. At most three active subagents.

Contract: preserve existing ValueError strings and all budget math/defaults/early
refusal in core; attach typed metric/estimate/limit for application presentation.
PreparePlan adds optional explicit blockers while preserving warnings compatibility.
No parser of raw exception text in QML. Unknown counts remain unavailable, zero stays
zero. Blocked plans cannot launch or report ready. A pinned indication links to the
full reason in the scrolling inspector. Readable GiB distinguish a bound from actual
disk consumption/free space. Form edits/save/replan remain explicit and unchanged.

The user can test Sharpest at target1fps/candidate2fps within the unchanged default
budget; both density values must be changed explicitly. No automatic parameter,
source, Trim or project changes, run, original extraction or resource-limit bypass.
New budget controls, changing extraction order and optimizing Trim decoding are out.

## Ready when and verification

- Metadata-only 4K/Trim planning regression proves full-source refusal, explanation,
  unchanged saved intent/limits and no materialization/run creation.
- GUI checks blocked status/counts/reason visibility, no false ready/launch, retry
  after explicit compatible settings, and retained stale-request protection.
- Short affected core/service/GUI tests; scoped Ruff/QML/docs; bounded native
  Dark/Light screenshots including compact blocked state. Synthetic fixtures are
  labeled and do not establish real-video execution acceptance.
- Fresh independent review; fix confirmed issues, repeat only affected checks;
  preserve entry identity/index/files and update PROJECT_STATE.

Full pytest/full verify, broad long suites and heavy benchmarks are forbidden without
a separate direct user request; no batches/background/delegated workaround. All
manual acceptance remains open.

## Delivered and independently checked

Core keeps all arithmetic/default limits and existing ValueError strings. The new
subclass supplies typed metric/estimate/limit for application diagnostics; no parsing
of a low-level message or budget bypass is introduced. PreparePlan retains warnings
for compatibility and adds blockers. Current GUI separates informational notes from
the cause, uses blocked status and shows the full reason through a pinned button.
Missing QVariant counts never render undefined; explicit zero stays zero. Storage
units correctly use GiB/MiB.

Recovery hints offer changing Included sources. Actual usable-video context gates
candidate-FPS and method-density advice, so photo-only or Trim-empty-video projects
never recommend disabled controls. That issue was confirmed by the fresh reviewer,
fixed by main, and covered by two 324-photo metadata cases. No source participation,
Trim, saved settings or resource policy changes implicitly.

### Short evidence (main-owned runs)

All commands use `.venv/Scripts/python.exe` from the checkout, isolated
`--basetemp sample_data/m12c-budget-20261029/<run>` and an owned cache directory.
No selected pytest skips; repeated cases overlap and are not a unique-suite total.

| Selection / retained log | Result |
| --- | --- |
| `tests/test_prepare_budget.py` (initial4K case), `tests/test_views_core.py::test_candidate_budget_accepts_bounded_input_and_refuses_all_unbounded_cases`, `tests/test_desktop_prepare.py::test_plan_uses_saved_participation_and_video_intervals_without_source_io`; `backend-01.log` | 3 passed; double-quiet output has no elapsed summary. Metadata-only 4K/Trim refusal, typed errors and existing plan context. |
| Expanded `tests/test_prepare_budget.py`; `backend-04.log` | 3 passed,2.02s after photo-advice correction. Includes 4K explicit lower-density replan plus photo-only and Trim-empty-video cases, no decode/run creation. |
| `tests/test_qml_prepare.py::test_blocked_plan_shows_unknown_count_reason_and_explicit_retry` in native Windows; `native-01.log` | Both themes passed; superseded captures retain earlier shorter synthetic wording. |
| `tests/test_views_execution.py::test_budget_refuses_before_backend_decode`, `tests/test_video_usage_execution.py::test_restricted_publication_vfr_bounds_cache_and_reset`, `tests/test_qml_prepare.py::test_prepare_plan_errors_are_local_and_retryable`, `tests/test_qml_prepare.py::test_project_generation_revokes_prepare_plan_history_and_local_error`; `regression-02.log` | 4 passed,1 failed,14.95s. The failure was an inherited test expecting an unbound error to bypass an already existing request-token guard. |
| Same one failing node on preserved entry code/tests with entry/src PYTHONPATH; `baseline-03.log` | Same failure reproduced,5.79s. No checkout restoration, production guard weakening or Git mutation. |
| New two-theme GUI node plus the corrected stale-token node; `native-05.log` | 3 passed,23.60s. Obsolete/unbound errors remain rejected; current-token errors are accepted. |
| Scoped Ruff on six changed Python files / qmllint on PreparePage.qml | Passed; zero final QML warnings. Initial format/import and QML point/Flickable diagnostics were corrected before native checks. |

Native05 retains four exposed-window PNGs and `native-budget.json` for each theme,
1440x900 and 1024x640, Windows platform/DPR1. Full current reason is readable and
reachable from the inspector bottom, with header/actions visible. Main and the
independent reviewer inspected the real captures. These are explicitly synthetic
plan fixtures; they verify UI behavior, not real 4K decoding or successful execution
of the user's video. Original 4K metadata numbers are separately checked through the
real preparation planner using synthetic inventory metadata.

The read-only Sol/high explorer confirmed full-source extraction/Trim and found the
missing-on-error explanatory note. A fresh read-only Sol/high reviewer inspected the
actual task-only diff/core consumers and captures; its confirmed photo-only hint
finding is fixed and no unresolved production finding remains. Reviewer ran no
tests/app. Final docs/state/inventory confirmation is retained in the evidence root.
Two real subagents, no nesting or parallel edits; requested configurations are known,
actual serving metadata and task token/cost measurements unavailable.

Final independent review reports no unresolved confirmed findings after checking all
12 task files, five documents, logs and four native05 captures. Its documentation
wording correction (budget-before-decode) is applied. `independent-review.md` retains
the raw outcome. Scoped `scripts/check_docs.py` passes all five Markdown files with
zero errors. Entry-relative whitespace/preservation and scoped `git diff --check`
pass: all 538 entry copies and 528 unaffected entry files match, two new/ten modified
files are accounted for, no removed/unexpected files, unchanged branch/HEAD and empty
index. Final hashes/diff are refreshed after recording only this review outcome.

Full verification/benchmarks were not run under the user's rule. A temporary
auto-review usage-limit failure prevented two check commands from launching; after
the user's Continue the same commands ran successfully, without bypassing approval.
Normal sandbox command launch still has Windows logon1385; approved escalation was
used. No toolchain installation or user-project execution occurred.

## Manual recheck and boundary

1. Save/restart the application and reopen the user's project. Check its existing
   Trim/source participation before changing settings.
2. At target2/candidate4, Check plan must show blocked, readable26.97/20.00GiB and
   full-clip explanation; no undefined or ready claim. Show reason works after scrolling.
3. Explicitly set Sharpest interval1second/candidate2fps, Save and Check plan. The
   full-clip storage bound is13.55GiB, within default budget; then test real preparation.
4. Compare Fixed with a compatible candidate/target pair, cancellation/reopen and
   unchanged original source/Trim/review decisions. Check keyboard and both themes.

The real user-video preparation in step3 remains unverified; no acceptance is closed
on the user's behalf. No new budget controls, trimming extraction optimization,
masks/tracking, reconstruction or next roadmap slice starts here.
