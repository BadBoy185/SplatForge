# M12b2 — Mixed Folder Import & Source Browser

Status: COMPLETE; manual UX acceptance PASSED (user, 2026-10-27).
Owner/date: Codex, 2026-10-27. Base: M12b1 `34039c5`.

## Goal and scope

Sources -> Add Folder / mixed drop -> bounded recursive scan -> classification ->
preview -> explicit confirmation -> existing MediaService inventory -> List/Grid.
Also remember the last successful project parent through existing QSettings.

No device/logical groups, relink, Prepare, frame extraction, quality, reconstruction,
viewer or export. M12b2 stays unstaged and uncommitted for user review.

## Contracts

- [UX specification](../../UX_UI_SPEC.md), sections 5, 7–10, 14 and 18.
- [GUI boundaries](../../GUI_DESIGN.md#presentation-architecture).
- [Shared project contracts](../../M12.md#architecture-and-shared-projects).
- [Project ownership](../../PROJECT_FORMAT.md#storage-layout-and-ownership).
- [Roadmap](../../../ROADMAP.md#m12--desktop-gui).
- [Verification](../../DEVELOPMENT.md#verification-workflow).

## Affected areas and acceptance

Application scan contract, injected filesystem adapter, controller cancellation and
generation guards, scan preview, Sources browser, bounded thumbnail provider,
existing Preferences/Create dialog and focused tests. Preserve unrelated edits.
Scan nested directories deterministically with bounded entries/directories/depth,
skip links/reparse points, expose limit/errors, cancel without inventory writes.
Preview photo/video/ignored counts and paths before ingest; backend identity and
atomic cancellation remain authoritative. Same source ordering/selection/preview in
List/Grid, lazy thumbnails and bounded delegates for 1000+ items. No new media store.

## Verification and decisions

Run the eight requested GUI/media/desktop test files plus M12b2-specific tests,
scoped Ruff, all-QML qmllint, changed-doc checks and diff checks. Capture native Qt
Dark/Light 1024x640 and 1440x900: empty, scanning, preview, List/Grid, 100+ sources,
videos, unsupported and cancellation. Full H commands prepared only; user owns H.
List/Grid preference will use existing machine-local QSettings allowlist.

## Implementation decisions

- Discovery is an ephemeral read-only preflight, not a pipeline stage or a second
  ingestion engine. Limits/ordering and the supported extension contract are owned
  by [M12](../../M12.md#navigation-and-settings). Actual validation stays in ingest.
- Duplicate locators within a scan are collapsed. Existing inventory paths are
  explained in preview; MediaService's persisted occurrence semantics are unchanged.
- Grid and List retain their Qt component contexts to avoid destroying delegates
  during incubation. Hidden Grid detaches its model, so it requests no new images.
  Both views read the same source model/UUID selection; preview uses M12b1's popup.
- Scan cancellation discards even a late successful result. A project switch clears
  scan counts/path review and closes its popup. Ingest checks cancellation after the
  final probe, before inventory commit. No optimistic source rows are introduced.
- Import reserves the mutation slot and drains owned metadata readers before its
  atomic inventory write, using the existing Save ownership pattern. Save/Open
  callbacks wait for worker-finished ownership release, not a timer after result.
- QSettings keys `last_project_parent` and `source_view_mode` extend the existing
  allowlist. Only a completed Create updates the parent; missing parents are ignored.
- No playback/runtime, poster extraction, frame artifacts or source groups are added.

## Changed-file map

| Files | Responsibility |
| --- | --- |
| `src/splatforge/application/media_scan.py` | Typed scan limits, progress, entries/result and scanner protocol |
| `src/splatforge/adapters/media_scanner.py` | Bounded local recursion, link/cycle avoidance, cancellation and partial results |
| `src/splatforge/application/media_contracts.py`, `media.py` | Shared extension classification and final-probe cancellation checkpoint |
| `src/splatforge/application/desktop.py`, `src/splatforge/bootstrap.py` | Facade/composition injection; legacy enumerator shares classification |
| `src/splatforge_gui/controller.py`, `qml_bridge.py` | Worker ownership, progress, contextual drop, scan preview and successful Create preference |
| `src/splatforge_gui/preferences.py`, `presentation.py` | Existing preference allowlist and scan progress label |
| `src/splatforge_gui/qml_media.py` | Source image roles and existing bounded thumbnail/provider integration |
| `src/splatforge_gui/qml/pages/SourcesPage.qml` | Empty/compact actions, persistent List/Grid contexts, lazy tiles and video hint |
| `src/splatforge_gui/qml/components/ImportPreviewDialog.qml`, `qml/Main.qml` | Counts/path review, confirmation, progress/cancel and Create prefill |
| `tests/test_media_scan.py`, `test_media_ingest_cancel.py`, `test_qml_folder_browser.py` | New scanner, cancellation, browser, drop and preference coverage |
| `tests/test_qml_sources.py`, `test_qml_workflows.py` | Adapted empty Sources/Create expectations and ingest failure diagnostics |
| `docs/GUI_DESIGN.md`, `docs/M12.md`, `ROADMAP.md`, `docs/index.md`, `docs/plans/active/README.md` | Bounded delivery contracts and plan routing |

## Evidence locations

Ignored local evidence: `sample_data/m12b2-final-targeted-tests-3.log`,
`sample_data/m12b2-final-context-tests.log`,
`sample_data/ui-review/m12b2-native/manifest.json` and adjacent native PNGs.
Native fixtures/probes are synthetic; playback/codecs and an OS-operated folder
picker/drop remain for user smoke. Native platform is Windows, DPR 1.0, with
Dark/Light at logical 1024x640 and 1440x900. The capture harness exercised 121
persisted sources (120 photos, one video), unsupported counts, scanning/cancel and
the reused photo popup. It reported no QML warnings.

## Evidence before the corrective pass (superseded for current acceptance)

Ready for the user's manual UX review. M12b2 is unstaged and uncommitted; index is
empty. M12b1 is separately committed as `34039c584baa27ac51b6cb680ef0b4699afd5b8b`.
No push, full H, M12b3 or Prepare work was performed.

Codex verification on M12b1 plus this slice and the preserved unrelated tree:

| Check | Actual result |
| --- | --- |
| Final 11-file targeted gate below | 207 passed, 0 failed/skipped, 393.73 s |
| Deterministic ownership checks plus affected import/Save workflows | 5 passed, 34.82 s |
| Folder/Create context gate before the last ownership repair | 42 passed, 175.73 s; superseded by final gate |
| Scoped Ruff, 16 changed Python files | Passed |
| All-QML qmllint | Passed, no output |
| Seven changed/closure Markdown files, local links | 0 errors |
| Native Windows Qt captures | 21, exact logical sizes above, DPR 1.0, no QML warnings |
| Final whitespace/scope/index checks | Passed; index empty |

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
.\.venv\Scripts\python.exe -m pytest -o addopts= -v -rs `
  tests/test_media.py tests/test_gui.py tests/test_qml.py `
  tests/test_qml_workflows.py tests/test_qml_interaction.py `
  tests/test_gui_architecture.py tests/test_qml_sources.py tests/test_desktop.py `
  tests/test_media_scan.py tests/test_qml_folder_browser.py tests/test_media_ingest_cancel.py
```

The final gate includes 27 new cases. Development gates exposed and then repaired
Grid context incubation, owned metadata reader/write conflicts and Save-to-Open
completion ordering. Earlier failed logs are retained; the final gate is clean.
The initial native run at DPR 1.25 was clamped by Windows to height 844 for the
large window; final captures use process-local scaling and assert exact sizes.
Prior captures remain under `sample_data/ui-review/m12b2-native/dpr-125/`.

34 initial files outside the M12b2 edit set match their SHA-256 snapshot (30
unrelated files plus four untouched M12b1 files). Existing benchmark hunks in
ROADMAP/map/active index were inspected and preserved. The unrelated registry.py
E501 at line 52 was not repaired; full Ruff/H were not run.

## Corrective pass: manual findings and root causes

The user reported a photo from another project on a video card, inaccessible or
unclear Details, a technical-first inspector, ambiguous availability, weak recents
and no meaningful ingest progress. This remains M12b2; no M12b3/Prepare work.

- `ThumbnailModel.replace` kept cached images and running requests. Late `_store`
  accepted any identity, and MediaProvider read raw caches without checking current
  reference membership. Gallery URLs had no model generation. The saved baseline
  reproduces serving project A's photo URL after replacing its model with an empty
  model, and accepting an unowned late reply. This proves a cross-project delivery
  hole; the exact Qt delegate timing of the user's observed card is not claimed.
  Fix: revoke URL namespaces/cache/queues on replacement, validate job generation
  and active references, clear preview tokens/selection on project adoption, including
  same-project reopen. Video cards now instantiate no photo Image component.
- Details depended solely on a toolbar button disabled until selection; video had
  neither the row Preview action nor a double-click inspection action. Persistent
  selection outlines and per-card/video-row Details now select and inspect explicitly.
  The inspector prioritizes filename/type/dimensions/duration/location/status and
  processing participation; IDs/hash/codec/check provenance remain collapsed below.
- Availability was derived from historical persisted verification strings, and ingest
  did not create a separate verification record. This made fresh imports look unchecked
  and reopened historical checks look current. A presentation-only session ledger now
  keys successful ingest/check evidence by project generation and source ID/revision/hash.
  Reopen is neutral; successful checks are Available, missing is Missing, other or
  incomplete checks are Needs attention. Historical evidence remains separate.
- Recent Projects was hidden inside an open workspace, stored paths only, and overview
  refresh re-remembered projects. Existing QSettings now records identity/name/path and
  successful Open/Create time. Refresh does not change ordering/time. Locate uses
  ProjectService's supported-storage/document validation, refuses another known identity,
  and requires confirmation for old identity-less entries. Remove is preference-only.
- Ingest exposed only mutation busy state. MediaService now emits real hash/probe/file
  completion/final-publication observations. Controller project/job tokens and monotonic
  guards reject obsolete observations. Existing M6.5 live throughput requires at least
  four stable positive intervals and sufficient completion before an ETA range; no
  history is trained and no timer fabricates progress. Finalizing has no ETA claim.
  The existing controller poll only refreshes observation age during ingest: after
  five seconds without evidence (M6.5 freshness policy), ETA becomes unavailable and
  completed work stays fixed. Stalled/variable live rates also withhold an estimate.
- Native review exposed background color animations retaining old theme/selection
  colors. Button/navigation backgrounds now bind directly to current tokens/state.
  Dark/Light List/Grid switching has focused regression coverage. Grid gives status
  its own full-width line and fits one complete card at the minimum browser height.

## Source participation decision and proposed follow-up contract

**DEFERRED — requires real backend contract.** `ProjectDocument` format v1 forbids
unknown fields and has no durable source participation intent. `ViewsService.prepare`
already accepts an explicit `source_ids` set for one run: `None` means all inventory,
unknown/empty sets fail, and resolved selected IDs feed route semantics. It does not
persist Included/Excluded for later runs or provide a project-level default selection.
Adding a QML filter would leave downstream behavior unchanged and is intentionally absent.

Proposed capability, requiring a separate approved backend extension:

1. Versioned project-owned `SourceParticipationIntent` with explicit excluded source
   UUIDs, default empty (all Included), separate from content identity and historical
   SourceOccurrence. ProjectService applies changes with existing atomic revision/CAS
   writes and a tested format/migration/default policy. Relink preserves participation
   for the same stable source ID; unknown IDs are rejected explicitly.
2. Application resolver returns effective included source IDs from current inventory
   and participation intent. Explicit run subsets must validate against that set;
   exclusions are never silently bypassed. Empty effective sets produce a clear error.
3. Prepare planning resolves this set before execution and snapshots it immutably.
   Its sorted membership and consumed source revisions/content identities participate
   in downstream semantic fingerprints; unrelated consumers/history remain unchanged.
   Current whole-inventory dependencies must be audited before claiming selective
   invalidation. No mutable flag or deletion is added to published inventories.
4. Only with these contracts: All/Included/Excluded, reversible Exclude/Restore, one
   List/Grid selection, persisted reopen behavior and original-file safety tests.

This is an explicit follow-up capability, not an activated M12c assignment or a
temporary UI implementation. Processing currently reads Included by default.

## Corrective verification (Codex)

- New focused tests cover project A photo -> B video -> A, URL revocation, colliding
  thumbnail IDs, queued/running late replies, preview tokens, List/Grid selection,
  photo/video human Details and retained collapsed provenance, ingest/reopen/check/
  missing/uncertain states, durable recents/ordering/Locate identity validation and
  legacy confirmation, preference-only removal, real ingest progress/cancellation.
- The 1500-source lazy/bounded regression remains in `test_qml_folder_browser.py`.
- Targeted final gate adds `test_media_import_progress.py`,
  `test_qml_sources_corrective.py`, `test_qml_recent_projects.py`, `test_eta.py` and
  `test_projects.py` to the previous 11-file command. Results recorded below when complete.
- Ignored evidence: `sample_data/m12b2-corrective-before/manifest.json` and
  `unstaged.patch`, `sample_data/m12b2-thumbnail-baseline-repro.py`,
  `sample_data/m12b2-corrective-final-targeted.log`, and
  `sample_data/ui-review/m12b2-corrective/` native captures.
- Native capture harness now runs inside the application's event loop so animated
  theme/control states settle correctly. An earlier harness timeout while persisting
  121 verification records was extended; there is no new backend verification policy.

The plan stays ACTIVE. Manual acceptance and then user-authorized full H/commit
remain pending. Nothing is staged, committed or pushed by this corrective pass.

### Final corrective evidence

| Check (Codex, Windows / Python 3.12.10 / Qt 6.12.0) | Result |
| --- | --- |
| 16-file targeted gate, including ETA and project lifecycle consumers | 287 passed, 412.03 s |
| Seven affected QML modules after final color/selection correction | 142 passed, 343.18 s |
| Final ingest ETA/GUI poll consumers | 16 passed, 65.67 s |
| Scoped Ruff, all 24 M12b2 Python files | Passed |
| All-QML qmllint | Passed, no warnings |
| Final native Windows Qt captures | 33; Dark/Light, exact logical 1024x640 and 1440x900, DPR 1.0, no QML warnings |

The first expanded run was 286 passed / 1 failed: an existing lifecycle test began
another edit at Open result/adoption before the separate worker-finished signal.
It now waits for ownership release; the clean repeat above supersedes that result.
Later bounded UI/ETA changes were rechecked against their affected consumers above.
There are 289 distinct selected cases including two added theme cases, not 445
independent tests; supplemental runs overlap the main gate.

The native fixture contains 120 synthetic photos and one synthetic video, using
normal MediaService inventory publication with deterministic probe fixtures. Captures
cover List/Grid, selected video, photo/video Details, fresh Available, neutral reopen,
Missing, real active ingest counts/cancel surface, Home recents and a missing recent.
For the final Missing captures the existing backend verifies three selected originals;
no fake availability or progress is injected. The final harness uses the normal Qt
application event loop; no theme token or animation duration is overridden. OS picker
interaction and a real MP4 remain user smoke checks; native captures are not playback
or codec validation. Final files/metadata: `sample_data/ui-review/m12b2-corrective/`.

All 30 initially unrelated benchmark/COLMAP/feature/docs files remain byte-identical
to the corrective-entry snapshot. ROADMAP/map/active-index files were not edited in
this pass, preserving their mixed hunks. Index is empty and HEAD remains `34039c5`.

Final supplemental commands (the 16-file gate is the earlier 11-file command plus
`test_media_import_progress.py`, `test_qml_sources_corrective.py`,
`test_qml_recent_projects.py`, `test_eta.py`, `test_projects.py`):

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
.\.venv\Scripts\python.exe -m pytest -o addopts= -v -rs `
  tests/test_qml.py tests/test_qml_workflows.py tests/test_qml_interaction.py `
  tests/test_qml_sources.py tests/test_qml_folder_browser.py `
  tests/test_qml_sources_corrective.py tests/test_qml_recent_projects.py
.\.venv\Scripts\python.exe -m pytest -o addopts= -v -rs `
  tests/test_media_import_progress.py tests/test_qml_sources_corrective.py `
  tests/test_gui.py::test_poll_skips_overlap_and_keeps_timer_responsive
```

Remaining: manual native picker/drop smoke and user UX acceptance; user-owned full H.
Classification is extension candidacy until ingest validates content. There is no
individual file exclusion or video playback. The scan's time/cancel checkpoints
cannot interrupt an individual blocked OS filesystem call. An oversized directory
has no arbitrary partial prefix; select a smaller folder or explicit files.

## M12b2 closure (2026-10-27)

Manual UX acceptance: **PASSED**, explicitly confirmed by the user: “Всё работает.”
The accepted corrective workflow covers Sources import/browser, List/Grid, photo/video
Details, availability, recent projects and import progress. The user did not provide
a per-scenario execution log; the detailed native evidence above is Codex evidence.
Full H was **not run** after the corrective pass, by either this task or the user.
This closure supersedes the pending-acceptance/commit notes above. M12b3 remains
capture metadata + device/user-visible logical groups; M12b2a is a separate slice.

Closure checks reuse the applicable corrective test results above (no code changes
since that evidence). Scoped Ruff, all-QML lint, local doc links and whitespace
checks are rerun for the staged closure; results follow below.

Closure verification (Codex): scoped Ruff on the 24 M12b2 Python files passed;
all-QML qmllint passed (absolute paths); six scoped Markdown files: 0 errors;
`git diff --check` passed. Existing corrective targeted evidence was reused.
Full H remains unrun; the known unrelated registry.py E501 was not changed.
