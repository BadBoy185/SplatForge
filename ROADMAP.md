# Roadmap

Every milestone ends in an executable command, inspectable artifact or automated
acceptance check. These are planned deliverables; only M0 exists today. CLI command
names below are proposed interfaces, not currently available commands. Use the
[task prompts](docs/CODEX_PROMPTS.md) one bounded task at a time.

Cache/state foundations precede processing. Minimal PairSelection precedes matching
because matching needs a verifiable PairSet. Retrieval, spatial and hybrid methods
follow after the first complete pipeline rather than blocking it. GUI follows CLI
and the first training integration. Do not implement all future method placeholders.

## M0 — existing foundation and architecture review

Available: configuration models, catalog, preset and `version`, `methods`,
`show-default-config`. Baseline: three passing tests; 18 pre-existing Ruff violations.
Documentation defines the target; it does not certify the catalog as executable.

## M1 — safe persistence and execution foundation

**M1a: next task, project persistence.** Implement application/storage boundaries,
create/open/save/inspect, a versioned project document, revisioned stage settings,
empty ownership directories and SQLite schema metadata. Preserve the prototype
config through an explicit importer/default-resolution path; do not interpret its
version as a project version. Fix independent role validation with a regression test
before persisting configurations. Preserve opaque unknown method settings; block
execution instead of dropping them. No processing adapters or generic scheduler.

Acceptance: `project create/show` and API save/reopen work in a Unicode/space path;
non-empty destination and stale save are refused; source files are untouched; unknown
newer formats are not rewritten; migration/atomic-save failure tests retain the last
valid project. Add a small legacy-format fixture when introducing a supported migration.

**M1b: state and minimal runner.** Add immutable run snapshots, attempts, artifact
manifests, dependency keys, publication/recovery, events and cancellation. Use a tiny
fake stage and a simple dependency plan, not a public workflow DSL.

Acceptance: fake stages demonstrate cache hit/miss, downstream-only invalidation,
failed/cancelled/interrupted attempts, retry as new attempt, writer exclusion and
crash recovery at every publication boundary. Editing a late fake stage reuses earlier
outputs. No external tools are needed. Repair documented baseline lint separately or
within an explicitly scoped foundation cleanup task, not incidentally.

## M2 — media ingest and process boundary

Implement source inventory, streaming content identity, read-only registration and
relinking for ordinary MP4/MOV/JPEG/PNG inputs. Add FFprobe metadata via the first
process adapter, with bounded logs, timeout, Windows process-tree cancellation and
structured results. Separate source groups from camera/calibration groups; preserve
EXIF orientation, video time bases and missing metadata explicitly.

Acceptance: `media add/list` registers photos and two clips without copying originals;
duplicate names do not collide; changed/missing/moved sources are diagnosed; cancelled
probe/hash leaves no completed ingest. Tests include fake processes and an opt-in real
FFprobe check on generated tiny media. Unsupported inputs fail clearly.

## M3 — candidate views and fixed-FPS extraction

Implement FFmpeg ViewPreparation plus simple fixed-FPS selection from an explicit
candidate pool. Photos enter the same view contract through orientation/preprocessing.
Record actual timestamps, source/view mapping, camera transforms and deterministic
names. Use M1b publication, progress, cancellation and stage-boundary restart now.

Acceptance: an extraction command emits validated image/manifests from a tiny VFR and
rotated video fixture; cancellation/resume does not reuse partial output; rerunning
unchanged settings reuses artifacts; originals remain byte-identical. Full-memory
video loading and shell command construction are forbidden.

## M4 — frame quality and selection

Separate blur/quality and duplicate measurements from selection thresholds. Add
sharpest-per-interval selection, reasoned rejection metadata and deterministic ties.
Reject insufficient candidate density or require an explicit extraction-plan change.

Acceptance: a generated sequence with known blur/duplicates yields expected choices;
threshold changes reuse pixels and measurements; changing a scoring method recomputes
scores and consumers. Fixed-FPS remains usable without quality scoring. Adaptive
motion-aware selection stays deferred until a bounded quality benchmark exists.

## M5 — COLMAP and GPU capability integration

Add explicit executable discovery, identity/version/operation probes, model-file
checks, native-format support and backend-specific GPU/runtime health. Expose a
`doctor` report with available/unavailable/unknown reasons. Catalog entries remain
separate from implemented and runnable methods. Extend the shared process boundary.

Acceptance: fixture probes cover missing executable, unsupported ONNX/model route,
missing Global Mapper, unhealthy CUDA/DLL loading and CPU-only capability. An opt-in
installed-backend smoke test records evidence. No feature extraction or downloads are
required merely to list methods or open a project.

## M6 — minimal pair selection

Implement typed PairSet, Sequential within clips and budgeted Exhaustive across
selected views. Allow an explicit cross-group pair list for controlled mixed-source
tests. Define future retrieval/spatial requirements without shipping fake methods.

Acceptance: stable pair output with no self/duplicate pairs, deterministic chronology,
quadratic-budget refusal and coverage diagnostics for two clips plus unordered photos.
PairSet production needs no COLMAP/CUDA and can run independently of local features.

## M7 — features, matching and geometric verification

Implement ALIKED and compatible LightGlue using a verified backend route, plus SIFT
and compatible brute-force matching. Separate stages and settings for features,
matches and geometric verification; expose any unavoidable native coupling. Validate
actual descriptor/weight/format compatibility and preserve the requested PairSet.
Keep databases isolated and published upstream payloads immutable.

Acceptance: a tiny real integration fixture produces features, matches and verified
geometry; incompatible routes fail before work; changing pair settings reuses features;
changing extractor cannot reuse an incompatible database. Test fallback explicitly.
If a local learned route is unavailable, report the missing capability and validate it
on a designated test machine before claiming the milestone's integration complete.

## M8 — mapping

Implement Global Mapper as the preferred supported route and Incremental/Hierarchical
Mapper as explicit capability-gated alternatives. Capture every reconstruction
component, camera convention and native ID mapping. Do not silently choose a component.

Acceptance: a tiny dataset yields a readable reconstruction on each supported route;
mapper changes reuse earlier compatible artifacts; invalid/no-component results are
not successes; cancellation and retries preserve original matching artifacts.

## M9 — reconstruction validation

Implement a structured report for registration coverage overall/per source group,
components, unregistered views, point/track statistics, reprojection distributions,
triangulation/degeneracy checks where supported and camera plausibility. Use explicit
threshold profiles; missing metrics are unknown, not zero or pass.

Acceptance: controlled reconstruction fixtures trigger pass/warn/fail with reasons;
policy changes do not rerun mapping. CLI displays actionable issues, and an explicit
recorded override is required to continue past a failing quality gate.

## M10 — complete flat-camera CLI and training dataset

Implement DatasetPreparation, required undistortion/resizing, camera/pose consistency
checks and dataset export. Compose project/ingest/plan/run/status/cancel/retry/diagnose
use cases. Provide a dry-run plan with capability, resource, coverage and cache reasons.
Initial multi-clip/mixed-source support uses bounded exhaustive or explicit cross-group
pairs; large collections may require later retrieval and must report that limit.

Acceptance: documented commands take a short video, unordered photo set, multiple
clips and a mixed ordinary-camera fixture to validated trainer-ready datasets. Test
restart, late-setting changes, source relocation, corrupt cache, disk-full handling,
paths with spaces/Unicode and a disconnected scene. Validate exported cameras against
images with a consumer or independent reader. A successful exit alone is insufficient.

## M11 — legacy evaluation and Gaussian training integration

**M11a:** inspect the earlier successful 3DGS project read-only when supplied. Recover
recipes and assumptions into documented, versioned candidate presets; compare on
small controlled scenes. Do not require that project's code as a runtime dependency.

**M11b:** deliver a tested external LichtFeld dataset handoff, then one managed trainer
adapter selected from verified requirements (gsplat-based or another suitable backend).
Keep manual handoff distinct from managed execution. Add checkpoint compatibility,
training progress/cancellation, metrics and scene export.

Acceptance: a dataset opens in the selected external workflow; a managed smoke run
produces a loadable scene; supported checkpoint resume is tested; changing trainer
parameters reuses SfM. Record quality/runtime/memory evidence for presets without
claiming universal superiority. Legacy evidence unavailability is reported explicitly.

## M12 — desktop GUI

Build PySide6 as a client of existing application services: project/source management,
guided profiles, advanced stage settings, plan preview, progress/cancel/retry,
diagnostics and reconstruction/scene inspection. Processing runs off the UI thread.

Acceptance: the same project can be created/run/reopened by CLI and GUI; persisted
settings and cache decisions agree; UI stays responsive during a fake long stage and
real smoke run; architecture checks reject backend imports/process calls in widgets.

## M13 — advanced methods and automation

Deliver independent submilestones, each with a fixture and measurable acceptance:

- **M13a:** retrieval/hybrid pair selection and GPS pairing with uncertainty. Demonstrate
  cross-clip coverage at a bounded pair budget and feature/index compatibility.
- **M13b:** manual masks and automatic segmentation; validate alignment and separate
  SfM/training mask invalidation. Add adaptive selection only with quality evidence.
- **M13c:** local batch/queue and bounded retry policies. Verify per-project writer
  exclusion, resource limits, cancellation and resumable job history.
- **M13d:** large-scene strategies, selective per-view caching and explicit cleanup.
  Benchmark memory/disk/pair budgets and interrupt recovery without silent data loss.
- **M13e:** a second SfM/trainer backend or LiDAR-assisted alignment when justified.
  Validate existing contracts, units/transforms and comparison metrics before expanding
  interfaces. No plugin SDK solely to satisfy a placeholder.

## M14 — 360/fisheye/equirectangular input layer

Implement calibrated perspective projection, parent/rig provenance, mask transforms
and supported mixed drone + 360 workflows. Declare mapper requirements for virtual
views; diagnose unsuitable geometry rather than treating projections as baseline.

Acceptance: projection/calibration fixtures and a mixed-source scene pass through
existing flat-camera SfM/training interfaces. The complete flat-camera regression
suite remains valid. Native spherical SfM, advanced sensor fusion and distributed
processing remain separate future decisions.
