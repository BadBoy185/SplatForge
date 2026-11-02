# M12c — Source scopes and frame provenance

Status: implemented and independently reviewed; manual acceptance open.
Owner: main agent, 2026-10-29. M12c as a whole remains incomplete.

## Goal and boundary

Review one exact prepared run by source or existing source groups, with truthful
per-scope membership counts and frame provenance in preview. The delivered
[Image Review plan](../completed/2026-10-29-m12c-image-review.md) names source scopes/
provenance as remaining M12c work; no numbered substage or different mandatory order
is specified. This task selects that one scenario. Previous manual acceptance stays
open. No masks, reconstruction, presets or selection algorithm is introduced.

## Relevant contracts

[GUI](../../GUI_DESIGN.md#prepared-image-decisions-m12c-review),
[source grouping](../../GUI_DESIGN.md#m12b3-capture-metadata-and-groups),
[reference #7](../../design/references/07-prepared-frames.png),
[UX Image Review](../../UX_UI_SPEC.md),
[source identities](../../PROJECT_FORMAT.md#paths-and-source-identity),
[saved decisions](../../PROJECT_FORMAT.md#prepared-image-decisions-m12c-review),
[PTS/timelines](../../PIPELINE.md#view-and-camera-rules).

## Agreed semantics and acceptance

- Scopes are display-only: All sources, individual prepared source UUIDs, existing
  saved user groups, then unassigned sources' reliable captured device / Videos /
  Unknown device sections, reusing Sources' precedence. Current logical organization
  is presentation; historical source/camera groups and frozen run data stay immutable.
  Empty saved groups remain selectable. Equal names never merge source identities.
- Scope intersects Selected/Rejected/All before pagination. New scope resets offset,
  preview and page-local batch; both success/error responses are token guarded.
  Neighbors belong to the full current scope/filter order. Existing decisions and
  effective run remain unchanged by browsing; actions still capture explicit UUIDs.
- Existing page counts retain whole-run meaning; additional scope counts describe
  the scope before the status tab, and page totals describe its tab intersection.
  UI labels identify each universe. Batch always means current visible page.
- Provenance uses frozen run/candidate/automatic evidence: original source name/type,
  historical locator, absolute source PTS/time_base (not Trim-relative), automatic
  decision/reason, available recorded score, manual override, effective membership.
  Current matching inventory locator and last recorded verification are separate
  evidence; no original is reread/probed or assumed currently available for browsing.
  Missing metadata is explicit, never replaced with a made-up zero/quality reason.
- At most 100 review items/pixel references are returned. Scope metadata/filtering
  uses existing saved metadata contracts, with no full-resolution decode or rerun.
  Technical UUID/PTS details are collapsed; long paths remain fully readable.

## Entry, ownership and resources

Branch `codex/m12b3-ux-review`; HEAD `4d83147acb01907ce02b1311977608f23d6eab17`;
empty index. 524 nonignored entry files/hashes plus Git diffs/status are retained in
ignored `sample_data/m12c-scopes-20261029/entry/`. Preserve existing runtime/COLMAP/
benchmark and Image Review changes. No Git mutation/cleanup/tool installation.

| Owner | Exclusive responsibility/files |
| --- | --- |
| Main | Contracts/docs/state/plan, native harness and Qt/app runs, old test-fixture compatibility and integration outside assigned files |
| implementation backend · Sol/high | core/application/adapters frame_review.py, optional new pure application read projection, new test_frame_review_scopes.py |
| implementation GUI · Sol/high | frame_review_vm.py, prepare_vm.py, PreparedFrameReview.qml, PreparePage.qml, new provenance component, new test_qml_frame_scopes.py |
| utility · Luna/high | Read-only exact contract inventory, completed |
| fresh reviewer · Sol/high | Requirements and final task-only diff, read-only |
| UX reviewer · Terra/medium | Actual native screenshots/scenarios, read-only |

No shared file editors or nested delegation. Main owns Qt/native/shared fixtures and
caches; backend may run only assigned short non-Qt tests in independent roots. At
most two code-editing and three active subagents. Requested configuration is known;
serving model/effort metadata remains unconfirmed.

Public read API adds `scope='all'` to `frame_review.page`, scope options/counts and
bounded item provenance. Existing whole-run counts/apply/publication semantics stay
unchanged. New read fields have compatible defaults; unknown scopes refuse safely.
Implementation owners confirm exact new model fields before parallel edits.

## Verification and final status

Short targeted tests cover scope/status intersections, counts/pagination, immutable
browsing, UUID/name isolation, batch/preview resets, original video time after Trim,
current-vs-historical locators, missing metadata and stale replies. Scoped Ruff/QML/
docs checks and short real native Dark/Light smoke include multiple sources, long
paths, empty scope and compact window. Full pytest/full verify, broad long suites
and heavy benchmarks are forbidden, including via agents/background/batches.

### Delivered implementation

The application read service composes scope options/counts, effective membership
and bounded item provenance from the exact saved run, current organization/inventory
and historical verification evidence. No storage schema, method, write/publication
path, cache fingerprint or dependent-result invalidation changes. Filtering is
ephemeral presentation, so it invalidates only GUI reads/preview/page selection.
Existing automatic/effective publications and saved overrides remain authoritative.
Unknown scopes fail explicitly instead of broadening to All sources.

The GUI presents separate whole-set, current-scope and tab/page counts. Scope/tab
changes revoke prior success/error responses and clear preview and page-local batch.
Controller/executor errors now carry the same optional request token, including
service-factory failures outside the read callback. Per-frame and batch actions retain
their existing captured UUID targets and persisted readback. Two old test doubles
accept the compatible optional scope argument; no old write behavior was replaced.

Single mode places effective/manual and automatic/reason summaries first, followed by
recorded source time/score/dimensions/device/current group and separate historical/
current locators/checks. Unknown evidence stays explicit. Technical IDs are disclosed
on request. The inspector wraps/selects long paths and scrolls beside the media or
below it in compact windows. The existing Basic ScrollView scrollbar retains its
native geometry and resets when the viewed UUID changes.

### Short verification evidence

All commands used the repository `.venv` on the combined dirty entry plus this task.
Qt/native/shared resources were exclusively run by main. Evidence is ignored local
`sample_data/m12c-scopes-20261029/`; repeated cases below overlap.

| Owner / check | Result |
| --- | --- |
| Backend agent: new `tests/test_frame_review_scopes.py` | 12 passed, 21.41 s |
| Main: new `tests/test_qml_frame_scopes.py`, initial run | 6 passed, 2 failed, 39.00 s; real recursive layout warning found |
| Main: affected Dark/Light layout rerun | 2 passed, 12.49 s |
| Main: unknown-count/status follow-up | 3 passed, 19.26 s |
| Main: inspector priority follow-up | 2 passed, 11.97 s |
| Main: final scrollbar geometry follow-up | 2 passed, 11.80 s |
| Main: 7 selected existing Image Review / M12c1 regressions | 7 passed, 46.31 s |
| Main: 2 existing persisted-review cases + 5 import/boundary cases | 7 passed, 10.37 s |
| Main: Ruff over 13 changed Python files | Passed, 0.13 s |
| Main: qmllint over 3 changed QML files | Passed, zero warnings, 0.44 s |

No skips in these pytest selections. Backend fixtures initially exceeded an existing
source-ID length bound; that fixture was corrected before the recorded 12-case pass.
The GUI layout failure was corrected by removing the self-height preferred-height
binding; only the two affected theme cases were rerun. Native screenshots then exposed
an undefined unknown-quality label and low-priority decisions; both were corrected.
UX review caught the replacement scrollbar's lost geometry. Preserving Qt's existing
bar fixed it; the final affected tests and native mouse/geometry assertions pass.

Exact pytest selections (each command includes `--basetemp` and separate `cache_dir`
under the evidence root; no default/full collection):

```text
python -m pytest tests/test_frame_review_scopes.py
python -m pytest tests/test_qml_frame_scopes.py
python -m pytest tests/test_qml_frame_scopes.py::test_scope_qml_empty_and_single_provenance
python -m pytest tests/test_qml_frame_scopes.py::test_scope_qml_empty_and_single_provenance tests/test_qml_frame_scopes.py::test_scope_status_pagination_clear_and_captured_apply_readback
python -m pytest tests/test_qml_frame_review.py::test_batch_selection_is_independent_of_preview_and_reset_restores_automatic tests/test_qml_frame_review.py::test_preview_exclude_uses_pre_action_uuid_neighbor_across_page tests/test_qml_frame_review.py::test_save_failure_does_not_report_success_or_leave_stale_actions tests/test_qml_prepare.py::test_prepare_run_failure_keeps_published_history_and_replaces_running_message tests/test_qml_prepare.py::test_stale_gallery_failure_cannot_contaminate_new_context
python -m pytest tests/test_frame_review.py::test_review_all_candidates_keep_exclude_reset_and_reopen tests/test_gui_architecture.py::test_inward_imports_and_no_processing_libraries tests/test_gui_architecture.py::test_client_entry_imports_do_not_load_heavy_libraries tests/test_gui_architecture.py::test_dependency_boundaries
```

Coverage includes scope/status intersections before paging, current-scope neighbors,
same-name source isolation, empty/device/fallback groups, page-local batch vs preview,
stale service/factory success/error and project/run switches, original PTS after Trim,
unknown metadata versus recorded zero, missing/relinked locators and persistence.
Read-only service/native assertions retain saved decisions, effective run, original
bytes and immutable artifacts. The old fixed-FPS reason assertion now expects truthful
"Automatic reason not recorded" for unsampled candidates without recorded reasons.

Native command (main):

```text
python scripts/capture_frame_scopes.py --output sample_data/m12c-scopes-20261029/native-03
```

Final smoke: 12 actual exposed-window captures, Dark/Light at 1440x900 and 1024x640,
DPR 1.0; passed in 8.96 s. Real services/installed FFmpeg used only three owned generated
sources: two equal filenames, a 179-character Unicode locator, and video with nonzero
PTS origin plus Trim. It exercised source/group combo keyboard selection, manual
exclusion readback, real Missing/Relink, original video time, empty scope, cleared batch/
preview, mouse scrollbar track click and viewed-UUID scroll reset. Manifest records
all preservation assertions true and no QML warnings/exceptions. Earlier `native-01`
and `native-02` captures are retained as pre-correction evidence.

### Independent review, limits and manual acceptance

A fresh Sol/high reviewer read the frozen 26-file task-only diff, requirements,
application/GUI consumers, corrections, recorded evidence and final documentation;
no confirmed production defect remains. Its documentation precision suggestion was
applied: the inspector discloses UUID/PTS details, not an artifact digest. The reviewer
independently confirmed unchanged branch/HEAD and empty index and ran no app/tests.
A separate Terra/medium UX reviewer inspected real screenshots/reference #7. Its
decision-priority and scrollbar concerns were fixed; native-03 follow-up found no
new concrete visual defect. Screenshot review is distinct from main's interaction
assertions and from human acceptance. No reviewer implemented code or ran a suite.

Final focused link/anchor check passed for all 10 changed Markdown files (0 errors).
Task-only diff/new-file whitespace checks pass. The preservation manifest passes:
524 entry files, 504 unaffected entry files byte-identical, 20 intentional modified
files and 6 new files; no removed entry files, unexpected changes or damaged entry
copies. Branch/HEAD/index remain unchanged. Git emitted only its LF-to-CRLF future
conversion notice for `tasks.py`, not a whitespace error. Final hashes/task diff and
snapshot evidence remain under the ignored evidence root.

One inherited integration uncertainty was noted without reproduction: the unchanged
Sources preview listener clears its participation auto-advance marker on any controller
error. A very late background error during Sources Save may interact with it. It was
not introduced or confirmed by this task, and no unrelated fix or acceptance claim is made.

Page returns at most 100 items and decodes only requested bounded pixels. Existing
manifest/inventory reads and published-artifact integrity hashing can still require
O(N) metadata/hash I/O; no indexed large-history performance claim is made. Generated
fixtures do not establish real-media/codec breadth, screen-reader behavior or high/
per-monitor DPI. Saved verification can predate Relink; browsing never checks current
original-file availability. Missing prepared pixels remain unavailable as before.

Manual acceptance (open, including M12b4/M12c1/Image Review):

1. With several sources/groups and equal filenames, combine scopes with every status
   tab and pages; check whole-set/scope/page counts and empty scope.
2. Select page checkboxes, open another frame, switch scope/tab/run/project rapidly;
   no hidden old batch or foreign preview may remain. Check failed load/save/retry.
3. Exclude / Keep Anyway / Reset and reopen; the exact UUID decisions/effective input
   must persist, while browsing scopes changes no source participation or result.
4. Inspect original source video time after Trim, Missing/Relink, long paths and absent
   metadata in both themes at normal scale; verify mouse/keyboard/focus/tooltips.

Next remaining M12c work is Prepare presets/advanced editing and separately
contracted masks/tracking; the roadmap specifies no further mandatory internal order.
Do not begin any of it automatically. Full pytest/full verify, broad long-running
suites and heavy benchmarks were **not run**, by the user's rule.
