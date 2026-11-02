# Trim-aware candidate materialization and resource bounds

Status: delivered bounded correction, 2026-10-29. Manual acceptance remains open.
Owner: main integration.

## Goal and boundaries

Materialize only globally sampled video candidates inside saved exact half-open
used intervals. Preserve original PTS/time_base, pixels, source-local selection,
quality/dHash policy, immutable publications, historical runs and manual decisions.
Align plan/run storage bounds with scratch plus retained output. No user video or
project processing, Git publication, model/toolchain installation or broad tests.
Prepare Data manual acceptance and all M12c remain open.

## Contracts

- [Engineering](../../../AGENTS.md), [workflow](../../AGENT_WORKFLOW.md).
- [Used intervals](../../PIPELINE.md#used-video-intervals),
  [view budgets](../../PIPELINE.md#view-and-camera-rules).
- [Saved intent](../../PROJECT_FORMAT.md#video-usage-intent), [Trim API](../../VIDEO_USAGE.md).
- [Affected verification](../../DEVELOPMENT.md#verification-workflow).

## Entry and ownership

The existing combined dirty tree is preserved in ignored
`sample_data/trim-aware-20261029/entry/` (540 files), hashes, Git identity/status,
unstaged diff and empty index diff. Existing COLMAP/benchmark work is outside scope.

| Owner | Exclusive responsibility |
| --- | --- |
| Main | Contracts, plan/state/docs, frozen-plan audit, integration and preservation |
| Implementation Sol/high | FFmpeg materializer/port, application/views.py, focused temporal/integration tests |
| Implementation Sol/high | core/views.py resource estimator, application/desktop_prepare.py, focused budget tests |
| Fresh reviewer Sol/high | Final entry-relative changes and evidence; read only |

No nesting; at most two code editors. Each agent owns its isolated generated test
files/cache/processes; main owns final checks. Requested configurations do not prove
serving metadata. Full pytest/full verify and broad benchmarks are not authorized.

## Confirmed cause and decision

Entry FFmpeg executes the minimum-interval candidate select and writes every sampled
image from the full clip. Application then checks exact Trim while moving images to
the candidate publication. Thus rejected images already occupy scratch.

Keep the original sampling filter unchanged. Restricted videos first run a bounded
metadata-only pass, test PTS with Fraction, then select the admitted original candidate
sequence indexes before encoding. No seek or concatenation. This costs a second decode
but avoids floating-point Trim membership and preserves original sampling state.
Both passes pin the same backend and retain contained cancellation/error handling.
Unrestricted extraction retains its existing path. Budget and execution consume the
same frozen saved intent; no default limit increase or semantic cache reset.

An unsaved Trim draft now also revokes ready/in-flight Prepare tokens. Discard does
not revive their old responses; a new Plan is required. Saved revisions and exact
requests remain checked again under the writer lease before run creation.

## Verification evidence

- Budget owner: 11 affected cases passed in 3.47s; scoped Ruff clean. Includes
  synthetic 4K metadata, both formats, exact intervals, unknown duration/origin,
  identity/limit refusal and saved-Trim stale-plan rejection.
- Main: five selected frozen-request/Trim-token/race cases passed; four selected
  historical review/manual decisions/cancellation/teardown cases passed. Commands
  are retained in `sample_data/trim-aware-20261029/main-checks.txt`. These runs had
  no skips. Import ordering was corrected; final main-owned scoped Ruff clean.
- Metadata-only 4K comparison: candidate4fps full bound436 /26.97GiB; saved three
  intervals bound230 /14.23GiB. Explicit candidate2fps bounds117. Defaults/limits
  and saved source/Trim data stay unchanged. These are upper bounds, not measured
  encoded sizes; no user4K video was decoded.
- Reviewer confirmed that append-only progress scratch could outgrow the Trim peak
  bound during a long decode. Restricted extraction now uses honest pass milestones
  and no disk progress stream. Unrestricted progress remains outside this correction.
- Materialization owner: final combined `tests/test_ffmpeg.py`,
  `tests/test_ffmpeg_progress.py`, `tests/test_ffmpeg_trim.py`: 53 passed, 1 existing
  integration-opt-in skip, 0.95s. Covers exact fractions/PTS beyond 2^53, preserved
  sampling order, empty/no-sample sets, metadata truncation/backend drift, PTS drift,
  shared timeout, cancellation at/between passes, no progress scratch and failing
  telemetry callbacks. Initial pre-fix subset results are superseded by this check.
- Real generated integration `tests/test_ffmpeg_trim_integration.py`: four
  CFR-zero-origin/VFR-origin5 by JPEG/PNG publication comparisons passed. Each
  compares old sample-all-then-filter behavior to new admission: PTS/time_base,
  exact candidate records/UUIDs/pixel hashes, recipe and semantic digests, Fixed
  selection and Sharpest selection/quality/decisions/unsatisfied intervals, cache
  reuse and original-byte preservation. Evidence is retained under ignored
  `sample_data/trim-materialization-20261029/integration01/`.
- Additional generated direct matrix passed: full/short/middle/end/disjoint/empty/
  no-sample. It compares original indexes, PTS/time_base, pixel hashes and actual
  scratch files; measurements under `integration02/`. Full JPEG: 4 images/4567B;
  short: 1/1146B; middle: 1/1151B; end: 1/1148B; disjoint: 2/2294B;
  empty and no-sample: 0/0B. This is a tiny integration example, not a benchmark.
- Real cancellation of each running FFmpeg pass passed 2/2 in 3.96s, evidence
  `cancellation04/`. Test-only `-re` and input decoder threads1 keep the tiny clip
  running until cancellation. Observed decoded showinfo, confirmed tree teardown,
  released source/partial-output handles and intact originals. An initial missing
  encoding fixture and over-strong showinfo assertion were corrected in tests;
  decoder buffering required the explicit test-only pacing/thread setting.

| Measured scratch before application publication | Old full-grid images / bytes | Trim images / bytes |
| --- | --- | --- |
| CFR JPEG | 4 / 4567 | 2 / 2268 |
| VFR origin5 JPEG | 4 / 4598 | 2 / 2299 |
| CFR PNG | 4 / 7995 | 2 / 3990 |
| VFR origin5 PNG | 4 / 7853 | 2 / 3854 |

Final VFR/PNG comparison rerun after the progress corrections passed in8.61s;
new16 Trim unit cases also pass under warnings-as-errors in0.79s. Final owned
scoped Ruff is clean. Repeated checks overlap; they are not a unique-suite total.

Integration opt-ins point only at existing `C:/Tools/ffmpeg/bin/ffmpeg.exe` and
`ffprobe.exe`; generated fixtures live in owned ignored test directories. No user
video or project is processed. Main initial docs checks pass; final checks and the
task-only diff/preservation report are retained in the current evidence root.
Materialization commands and corrections are recorded in
`sample_data/trim-materialization-20261029/verification.md`; budget commands and
entry-relative diff in `sample_data/trim-budget-20261029/`.

Final main closeout: scoped Ruff on 11 changed Python files and links/anchors on
all 8 changed Markdown files pass. Preservation verifies all 540 entry copies,
525 unaffected files, 19 scoped task files, no removed/unexpected files or added-line
whitespace errors, unchanged branch/HEAD and empty index. Exact final hashes,
task-only diff, preservation JSON and independent review summary are retained in
`sample_data/trim-aware-20261029/`. No pending owned process or follow-on work.

## Independent review and implementation limits

Fresh read-only Sol/high reviewer inspected the entry-relative implementation,
contracts and tests, and confirmed two P2 findings. Both are resolved: restricted
passes create no append-only progress scratch; optional phase-callback errors warn
once and cannot abort numerical processing, including under warnings-as-errors.
The reviewer re-read both fixes and the corresponding regressions; no unresolved
confirmed production/test defect remains. Reviewer ran no tests or app sessions.

Two implementation agents and one independent reviewer were requested at Sol/high;
actual serving model metadata and task token/cost measurements are unavailable.
No nested delegation or shared-file concurrent editing occurred.

This slice preserves semantic identity: original sampling, candidate PTS/time_base,
UUIDs and image SHA-256 feed unchanged recipes. Version/contract/cache identity is
not bumped; old compatible candidate/quality/selection publications can be reused.
Historical views_run and manual review decisions remain immutable. Unknown duration
still refuses; unknown origin is never guessed. Large full-grid metadata can exceed
the bounded capture and fail safely even with a short Trim.

Restricted clips can be fully decoded twice. Within-pass progress is unavailable;
start/completed-pass milestones and cancellation remain. Synthetic fixtures do not
establish codec breadth, user-video acceptance, or visual/manual Prepare acceptance.
No user video/project processing, full pytest/full verify or broad benchmark was run.

## Acceptance and final boundary

Automated acceptance covers small generated clips, temporal semantics, storage,
both selectors, lifecycle, compatibility and frozen settings as recorded above.
Prepare Data manual acceptance and all M12c remain open. This handoff ends the
authorized correction; no next feature or broad verification run is started.
