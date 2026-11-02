# Project state

Checked 2026-10-29 against Git and the combined dirty tree. Recheck each session;
a handoff is evidence, not authorization for another milestone. Delivered bounded correction:
[Trim-aware materialization](plans/completed/2026-10-29-trim-materialization.md).
The bounded correction preserves the original candidate grid and exact PTS while
excluding outside-Trim scratch images. Verification/review evidence is recorded
in that plan. The earlier
[Prepare budget correction](plans/completed/2026-10-29-m12c-prepare-budget-feedback.md)
records the initial user-reported 4K/Trim issue and historical short evidence. The
[direct settings plan](plans/completed/2026-10-29-m12c-direct-prepare-settings.md)
retains the prior capability inventory/contracts/evidence. Earlier scopes, Image
Review and M12c1 evidence stays in their plans.

## Checkout and preservation

- Branch `codex/m12b3-ux-review`; HEAD
  `4d83147acb01907ce02b1311977608f23d6eab17`; index remains empty.
- Current Trim correction entry: 540 nonignored files/hashes plus Git identity,
  status/diffs are retained in ignored `sample_data/trim-aware-20261029/`.
  Task-only diff and final preservation report are recorded there. Previous evidence
  roots and the combined dirty tree remain preserved.
- Earlier feedback correction entry: 538 nonignored files/hashes plus Git identity/status/diffs
  retained in ignored `sample_data/m12c-budget-20261029/entry/` and `entry-hashes.json`.
  Task-only `task.diff`, `changed-files.json`, `final-hashes.json` and `preservation.json`
  record changes against that entry, including new files, identity/index/snapshot and
  unaffected-file checks. Previous `m12c-settings-20261029`, `m12c-scopes-20261029`
  and `m12c-review-20261029` evidence is preserved.
- Existing runtime/COLMAP/benchmark and prior GUI/review/scopes work are preserved.
  No commit, push, merge, reset, clean, discard, stash, staging, dependency installation
  or model download. This scenario stops here; no next slice is started.

## Verification authorization

Full pytest/full verify, broad long-running suites and heavy benchmarks require a
**separate direct user request**. Continue/check/implement does not authorize them.
Use short targeted tests and scoped lint/QML/docs checks; never simulate a full run
via batches, delegation or background execution. Full verification was **not run**.
Rules: [AGENTS](../AGENTS.md#verification-authorization-all-agents-and-future-sessions),
[workflow](AGENT_WORKFLOW.md#integration-and-evidence),
[DEVELOPMENT](DEVELOPMENT.md#full-verification).

The pre-M12b4 full result (1989 passed, 74 skipped) covers only its old snapshot.
The later M12b4 full run was interrupted at the user's request with no full result.
Original evidence under `sample_data/continuation-20261029/` remains; no repeat was
authorized. Earlier short evidence stays in the
[M12c1](plans/completed/2026-10-29-m12c1-prepare-data.md),
[Image Review](plans/completed/2026-10-29-m12c-image-review.md) and
[scopes/provenance](plans/completed/2026-10-29-m12c-source-scopes-provenance.md) plans.

## Acceptance boundaries

Projects/Create and the latest Materials/Trim **visual** refinement were accepted
by the user. Functional Materials/M12b3 scenarios remain unconfirmed in the
[Materials plan](plans/active/2026-10-28-materials-workspace.md).
[M12b4 folder relink](plans/active/2026-10-29-m12b4-folder-relink.md), M12c1, Image
Review, source scopes/provenance and direct settings manual acceptance remain open.
Continued development does not establish that those checks were performed. Agent
tests, captures and reviews do not substitute for user acceptance. All M12c is not done.

## Delivered Trim materialization correction

Restricted videos now run a bounded timestamp-only prepass, exact rational admission
and an image pass over the unchanged original candidate grid. Outside-Trim images
are never encoded to scratch. Both passes can decode the full clip; no seek/concat,
new method or numerical semantics. PTS/time_base, UUIDs, hashes and both selection
results match the previous correct sample-then-filter behavior on generated CFR/VFR
JPEG/PNG. Semantic recipe/adapter versions and compatible caches remain unchanged.

Plan/run use saved/frozen Trim and the same conservative interval-aware estimator.
The synthetic metadata 4K case bounds 230 candidates / 14.23 GiB versus 436 / 26.97 GiB
unrestricted; default 20 GiB limit remains. Peak includes concurrent image allocation,
metadata/diagnostics and 8 MiB admission script. Expected encoded size stays unknown.
Unsaved Trim also revokes ready/in-flight Prepare tokens; Discard cannot revive them.

Short evidence: budget owner 11 passed in 3.47s; materializer combined 53 passed, 1 existing
opt-in skip in 0.95s, new 16 also pass under warnings-as-errors; main frozen snapshot 5 and
history/manual review/cancellation 4 passed. Real generated comparisons 4 cases,
additional direct interval matrix 1 case and real per-pass cancellation 2 cases pass;
final VFR/PNG recheck passes after progress fixes. Measured CFR JPEG scratch 4 / 4567 B
becomes 2 / 2268 B, with identical published content. Scoped lint and docs checked.
Fresh read-only reviewer confirmed two P2 defects, both fixed/re-reviewed: unbounded
restricted progress scratch and failing optional phase callbacks. No unresolved
confirmed code finding remains. Three agents requested Sol/high, no nested work;
actual serving metadata unavailable. Exact commands/evidence are in the linked plan.

Restricted progress uses completed-pass milestones, no within-pass percentage.
Metadata overflow can refuse a long clip even with a short Trim. Tiny generated
fixtures do not establish real-user/codec breadth. No user project/video was changed
or processed; full pytest/full verify/broad benchmarks were not run. Manual Prepare
Data acceptance and all M12c remain open. This task stops after this handoff.

## Earlier corrective Prepare plan feedback

The following is the delivered feedback-only correction's dated evidence. Its
full-clip materialization/budget description is superseded by the current
[Trim correction](plans/completed/2026-10-29-trim-materialization.md); preserve its
verification and manual-acceptance history.

The user's real 4K/Trim screenshots exposed false Saved plan ready, undefined count
and missing full-clip explanation on budget refusal. The full-source bound itself
is intentional: 3840x2160, 108.575 seconds, candidate 4fps means 436 candidates and
26.97GiB versus the default 20GiB. Current extraction precedes exact Trim filtering. This is
a conservative storage bound, not expected JPEG size or a free-disk-space reading.

Typed ValueError metadata now supports readable application blockers; arithmetic,
default limits, early refusal, core error strings and run/cache contracts are intact.
The GUI uses blocked status, honest unavailable/zero counts and a pinned Show reason
action. Informational notes retain the full-clip explanation on failure. Advice
offers changing Included sources; video sampling/interval suggestions require usable
video. A reviewer-confirmed photo-only advice defect is fixed and covered.

The user's project/source/Trim/settings were not changed or processed. Explicit
Sharpest interval 1 second/candidate 2fps gives a 13.55GiB bound in the metadata regression;
the user still needs to Save/recheck and try actual preparation. No invisible limit
increase or automatic FPS change. Human acceptance remains open.

Main targeted checks: initial core/service/planning 3 passed; expanded 4K/photo-only/
Trim-empty cases 3 passed (2.02s). Selected budget-before-decode/Trim/retry checks passed;
one old stale-error expectation failed and reproduced on entry code (5.79s). Only its
test expectation changed to preserve existing token guards. Final two native themes
plus that affected token node 3 passed (23.60s). Ruff 6 Python and qmllint 1 QML clean.
Native05 has 4 real exposed-window captures (1440x900/1024x640, DPR1), synthetic plan,
no 4K decode and no QML warnings. Final docs/preservation/review evidence is retained
in the linked corrective plan and current evidence root.

Two read-only agents (explorer and fresh reviewer), requested Sol/high; main owned
all edits/tests/Qt resources. No nested work or parallel editing; serving metadata
unavailable. Independent reviewer confirmed the photo fix and current captures,
with no unresolved confirmed finding in the final 12-file/doc/evidence review.
The raw outcome is retained in `m12c-budget-20261029/independent-review.md`.
All five changed Markdown files pass scoped links/anchors. Full verification/benchmarks not run.
Final preservation: all 538 entry copies and 528 unaffected entry files match;
12 task files, no unexpected changes/removals, unchanged branch/HEAD and empty index.

## Delivered direct Prepare settings

The user's decision replaces the Prepare Fast/Medium/High/Max intention with direct
access to working methods. Immediately visible: exclusive Fixed FPS / Sharpest
Interval selector, exact target interval in seconds and read-only reciprocal FPS,
separate candidate sampling, JPEG/PNG and applicable encoding parameter. Photos have
no active time fields. Sharpest video candidates must be at least twice target FPS;
Fixed needs at least target FPS and performs no quality stage.

An optional disclosure has independent minimum-sharpness and similar-video-dHash
checkboxes plus their parameters. Off sharpness is None; explicit zero is distinct.
No threshold is invented. Existing defaults stay visible: no threshold, Sharpest
video dHash on at distance4/lookback8, analysis max side1024. Proxy size is an ordinary
required Sharpest analysis parameter, not saved resolution. The existing assessor
measures edge variance and dHash together even if suppression is off. dHash policy
is per video, not photo/cross-source or geometric redundancy. Sampling/sharpness
does not guarantee reconstruction suitability.

Version1 `frame_selection.prepare_data` extends the existing intent envelope for
candidate/quality settings; typed selector settings stay in their existing slot.
Legacy opaque values and unrelated extras survive conversion. Unknown method/schema/
extension refuses Prepare editing/execution without blocking unrelated saves.
Inactive settings canonically resolve before frozen route metadata and keys; old
artifacts and the compatible legacy request entrypoint retain exact semantics.

Raw invalid edits participate in global Save/Discard/Cancel/close guards. Save uses
the existing revision-checked service; errors retain edits and never report success.
Launch pins the validated saved revision/request. Running fields cannot edit it;
form edits alone never process data. Plan/history success and failure responses use
revocable tokens. Historical settings disclose the selected run's frozen request,
not the current form. Header/validation/key actions remain pinned in the compact
inspector while its settings/history body scrolls.

Source participation, exact Trim/original video time, immutable automatic/effective
runs, exact-set/UUID manual decisions and scopes/provenance remain intact. No new
algorithm, mask/tracking, reconstruction or experimental dependency is connected.
The [technical backlog](TECHNOLOGY_STRATEGY.md#prepare-data-technical-backlog--2026-10-29)
records only sourced unready possibilities and their runtime/evaluation/adoption gates.

Contracts: [GUI](GUI_DESIGN.md#direct-prepare-settings-m12c),
[persistence](PROJECT_FORMAT.md#direct-prepare-settings-m12c),
[pipeline](PIPELINE.md#direct-prepare-settings).

## Earlier direct-settings verification and independent review

- Backend agent: initial settings 27 passed (3.57s); six existing desktop-service
  cases passed (6.22s). Expanded settings run had 28 pass/1 fixture failure (6.31s);
  corrected affected node passed (3.07s), final legacy wrapper node passed (0.72s).
  All 30 new settings cases pass across these runs, without a combined final rerun.
- Main: GUI/raw-form/save failure/frozen request/stale plan selection 8 passed
  (71.12s). Sources-during-Save regression passed; after updating stale test helpers/
  message expectations, affected old M12c1 themes and threshold case 3 passed (12.46s).
  Final footer selection (validation, photos, scopes and batch/preview) 4 passed
  (31.14s). Trim/cancel/stale-gallery/import/dependency selection 9 passed (25.75s).
  Runs overlap; no skips reported. Earlier failures and exact selections are in the plan.
- Main: scoped Ruff on 13 Python files passed; qmllint on 3 QML files passed with
  zero warnings. All 11 changed Markdown files pass links/anchors. All 27 task files
  pass whitespace/preservation; 511 unaffected entry files and all 530 entry copies
  are byte-identical, with no removed/unexpected files. Evidence stays in the prior
  `m12c-settings-20261029` directory and direct-settings plan. A later type annotation
  passed affected Ruff.
- Main native `native-03`: 12 real exposed-window captures, 1440x900 and 1024x640,
  Dark/Light, DPR1.0. Real services publish Sharpest/PNG and Fixed/JPEG from three
  generated sources. Pinned route settings, original PTS after Trim, preserved image
  dimensions, photo controls, frozen history, review heads, source participation/
  bytes and old artifact hashes pass. No QML warnings/exceptions. This verifies real
  runs with selected settings, not raw child-process argv capture.
- Fresh independent Sol/high review confirmed two defects: failed-save staged-draft
  readoption after returning to baseline, and Sources navigation during Save.
  Main fixed both; affected regression cases passed. Independent Terra/medium UX
  review found scrolling hid key actions; final pinned layout resolves it in both
  themes and compact windows, with no new concrete visual issue in the follow-up.
  Final 27-file code/contract/evidence review has no unresolved confirmed findings;
  its raw outcome is retained in `independent-review.md`. Reviewers performed
  read-only inspection, no tests/app sessions. This does not establish acceptance.

Five real agents: utility Luna/high, two implementation Sol/high, fresh reviewer
Sol/high and UX reviewer Terra/medium. At most three active/two editing, no nesting;
main owned contracts/integration/Qt/native/shared resources. Requested configurations
are known; serving metadata and task token/cost measurements are unavailable. Normal
Windows command runner fails logon1385; approved escalated commands ran the checks
without installation. No full run or benchmark was authorized/performed.

## Manual checklist and next boundary

1. In video/mixed input, select each method, exact interval, candidate sampling and
   format; Save, plan, run and reopen. Compare each run's published settings.
2. Toggle sharpness/dHash separately; check empty versus zero threshold, density
   errors, incompatible controls and photo-only behavior in Dark/Light.
3. Exercise failed Save/retry back to baseline, Save/Discard/Cancel, cancellation
   and rapid project switches. Prior results and exact UUID decisions must survive.
4. Recheck Trim time, Image Review and scopes after new preparation; check the
   compact inspector, keyboard/focus/tooltips on the user's display.

Remaining M12c: separately contracted masks/tracking; no mandatory internal order
is imposed. Then roadmap M12d currentness/lineage and later reconstruction
presentation. Do not start them automatically.

Generated media do not establish real-user/codec breadth, screen readers or high/
per-monitor DPI. Page reads stay bounded, but existing manifests/integrity hashes
can still require O(N) metadata/hash I/O; no large-history performance claim.
Evicted prepared pixels remain unavailable; historical source checks are not fresh
availability checks. The prior scopes plan retains those evidence limits.
