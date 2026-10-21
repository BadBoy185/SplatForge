# Roadmap

Every milestone ends in an executable command, inspectable artifact or automated
acceptance check. M0, M1a1, M1a2, M1b1 and M1b2 are implemented. Later deliverables
and CLI command names remain planned unless explicitly marked available. Use the
[task prompts](docs/CODEX_PROMPTS.md) one bounded task at a time.

Cache/state foundations precede processing. Minimal PairSelection precedes matching
because matching needs a verifiable PairSet. Practical cross-clip retrieval/hybrid
pairing arrives in M7c before the complete multi-video CLI; GPS/spatial pairing and
advanced retrieval optimization remain later. GUI follows CLI and the first training
integration. Do not implement all future method placeholders.

The bounded post-M5/pre-M6 foundation repair hardens lock-file object/alias safety,
native-only Windows process execution, candidate decode integrity, atomic historical
DDL upgrades, photo/video orientation, source PTS origin, per-plan FFmpeg observation
and exceptional teardown quarantine. It changes FFmpeg adapter recipe identity to 2,
without changing project/state/artifact JSON versions. M6 PairSet is implemented below.
The bounded post-M6/pre-M7 scalability/operability pass is complete: ordered exact
fixed-FPS selection and early slot/interval bounds, operation-scoped typed artifact
validation, one complete candidate provenance write and bounded durable FFmpeg attempt
diagnostics. Numerical identities and project/state/artifact versions stay unchanged.
M7 remains planned.

## M0 — existing foundation and architecture review

Available: configuration models, catalog, preset and `version`, `methods`,
`show-default-config`. Baseline: three passing tests; 18 pre-existing Ruff violations.
Documentation defines the target; it does not certify the catalog as executable.

## Optional research — legacy 3DGS

At any milestone, inspect the supplied legacy project read-only and record evidence,
unknowns and candidate lessons in [LEGACY_3DGS_RESEARCH.md](docs/LEGACY_3DGS_RESEARCH.md).
The verifiable result is a source-referenced research note, not code or official presets.
If the project is unavailable, record that status and continue early milestones.
Preset translation/benchmarking stays in M11a; research is never an early dependency.

## M1 — safe persistence and execution foundation

**M1a1: implemented, basic project persistence.** Application/storage boundaries,
separate project/config/state versions, SQLite metadata and create/open/save/show
are available. Creation writes only the project document and metadata database.
Saves use validated temporary-file replacement. Current settings and opaque unknown
method/settings envelopes (including extra envelope fields) round-trip without
reapplying presets. Prototype conversion is explicit, not a historical migration.
Independent role validation is fixed and covered by regression tests.
The document starts at revision 0; M1a1 saves preserve it without stale-save semantics.

Acceptance covered: CLI create/show and API save/reopen in Unicode/space paths;
settings round-trips, role-validation failure, empty-destination ownership, non-empty
refusal and unsupported-version refusal without rewrites. Originals remain untouched.
This is a controlled single-process development slice, not a durability release.
Target validation, processing and future directory creation remain deferred.

**M1a2: implemented, persistence safety.** Saves advance revisions and reject stale
documents under one OS-held local Windows writer lock. Validated, flushed temporary
siblings use same-volume replacement as the project-document commit point. Current and
unsupported project/config/state versions dispatch without speculative migrations.
Fault and Windows integration tests cover writer exclusion, replacement failures,
sharing conflicts and the internal migration-backup preparation boundary.

No older production format, migration transform, restore engine or multi-store journal
was invented. M1a2 completes persistence safety before M1b and processing.

**M1b: state and minimal runner**, delivered as two reviewable tasks:

- **M1b1: implemented, execution and cache happy path.** New projects use state schema
  v2; state v1 remains open/save compatible and has an explicit backed-up v1-to-v2
  upgrade. A concrete two-node fake route records frozen node/output references,
  actual attempt inputs, immutable manifests, explicit dependency keys and diagnostic
  events. Run/show, cache integrity checks, multiple publications per recipe key and
  downstream-only invalidation are covered without external tools, a scheduler or a
  workflow language.
- **M1b2: implemented, interruption and recovery.** State schema v3 adds durable
  cancellation acceptance, retry linkage, failure categories and teardown state while
  v1/v2 remain read-compatible and explicitly upgrade with a backup. A second CLI can
  request cancellation without becoming a writer. Fake-stage race/fault tests cover
  manifest/move/commit boundaries, pending cancellation, interrupted owners, exact
  orphan adoption, rejected publications, upstream reuse and the three-attempt bound.
  Unresolved teardown blocks retry. M2 still owns real external-process containment;
  these in-process fakes do not establish Windows process-tree safety.

Both tasks use the M1a2 writer boundary and no external tools. M1b is complete before
processing. Repair documented baseline lint separately or within an explicitly scoped
foundation cleanup task, not incidentally.

## M2 — media ingest and process boundary

Status: implemented. M2 provides immutable source inventories, streamed identity,
FFprobe metadata, Balanced/local and Strict verification, relinking, the bounded process
boundary and tested Windows Job Object/read-lease behavior. Frame extraction remains M3.

Implement source inventory, streaming content identity, read-only registration and
relinking for ordinary MP4/MOV/JPEG/PNG inputs. Add FFprobe metadata via the first
process adapter, with bounded logs, timeout, Windows process-tree cancellation and
structured results. Separate source groups from camera/calibration groups; preserve
EXIF orientation, video time bases and missing metadata explicitly. Fully hash initial
ingest; implement recorded Balanced/local re-verification and opt-in Strict rehashing.

Acceptance: `media add/list` registers photos and two clips without copying originals;
duplicate names do not collide; changed/missing/moved sources are diagnosed; cancelled
probe/hash leaves no completed ingest. Tests include fake processes and an opt-in real
FFprobe check on generated tiny media. Verify Balanced avoids unchanged-source full
reads and suspicious evidence triggers rehash. Strict hashes complete content and
maintains byte continuity through consumption using a tested lease or an explicitly
budgeted snapshot; unsupported guarantees fail clearly. Record policy/assurance and
source-change diagnostics. Test worker-owner death and descendants retaining handles.
The process adapter and inventory can be separate reviewable tasks within M2.

## M3 — candidate views and fixed-FPS extraction

Status: implemented. `views prepare` publishes a bounded materialized
`CandidateViewSet` through the contained FFmpeg adapter and a metadata-only
`SelectedViewSet` through deterministic per-source fixed-FPS selection. It preserves
actual selected-frame PTS/time bases, explicit photo/video orientation, source/camera
groups, immutable multi-file manifests, source-verification provenance, durable
cancellation and stage-boundary cache reuse. State remains schema v4.

Implement FFmpeg ViewPreparation plus simple fixed-FPS selection from an explicit
candidate pool. Photos enter the same view contract through orientation/preprocessing.
Record actual timestamps, source/view mapping, camera transforms and deterministic
names. Bound candidate count and peak disk demand before decoding; do not materialize
all frames by default. Start with a bounded materialized pool; exact frame locators or
analysis proxies are later measured optimizations. Use M1b publication, progress,
cancellation and stage-boundary restart now.

Acceptance: an extraction command emits validated image/manifests from a tiny VFR and
rotated video fixture; cancellation/resume does not reuse partial output; rerunning
unchanged settings reuses artifacts; originals remain byte-identical. Full-memory
video loading and shell command construction are forbidden.

## M4 — frame quality and selection

**Implemented.** `quality_assessment.pillow_edge_dhash` publishes a metadata-only,
candidate-pixel-bound QualityReport with exact edge-response variance and dHash64.
`frame_selection.sharpest_interval` applies explicit sharpness/duplicate policy per
source-local half-open interval, records deterministic typed decisions for every
candidate and refuses video candidate pools below twice the target FPS. The historical
fixed-FPS route remains independent of quality scoring.

Acceptance: a generated sequence with known blur/duplicates yields expected choices;
threshold changes reuse pixels and measurements; changing a scoring method recomputes
scores and consumers. Fixed-FPS remains usable without quality scoring. Adaptive
motion-aware selection stays deferred until a bounded quality benchmark exists.

## M5 — COLMAP and GPU capability integration

**Implemented.** `splatforge doctor` resolves COLMAP by explicit/environment/bundled/
safe-PATH precedence, records strong executable/version identity, parses bounded
operation and feature/matcher help fail-closed, checks concrete learned-model evidence,
and reports generic NVIDIA inventory separately from COLMAP GPU health. `--deep` uses
owned disposable workspaces for versioned native SQLite schema validation plus CPU/GPU
SIFT smoke probes through the M2 process boundary. Evidence has process-local freshness
limits and cached reports recheck concrete executable identity.
Windows official-style layouts use an inert `COLMAP.bat` locator or native exe path,
with bounded child-scoped DLL/Qt paths; the wrapper is never executed. Deterministic
layout fixtures are covered; real package coverage remains opt-in, not implied.

Acceptance: fixture probes cover missing executable, unsupported ONNX/model route,
missing Global Mapper, unhealthy CUDA/DLL loading and CPU-only capability. An opt-in
installed-backend smoke test records evidence. No feature extraction or downloads are
required merely to list methods or open a project. Risky probes use disposable workers;
probe availability/resource evidence has a freshness limit, while resolved execution
identity is pinned and checked again before launch.

## M6 — minimal pair selection (implemented)

Implemented `pairs build --views-run` with PairSet v1, a versioned selected-view
projection, source/revision/stream-local Sequential, budgeted Exhaustive and explicit
edges for videos/photos. Graph identity is independent of recipe/provenance; coverage
reports components, isolation and source/group edges. Uses existing attempts, cache,
durable cancellation and publication recovery, with no COLMAP/CUDA or image decoding.

Acceptance is covered by deterministic core, projection/key, coverage, CLI, cache,
corruption, cancellation/recovery and upstream M3/M4 regression tests. PairSet production
is independent of local features. Retrieval remains M7c; spatial pairing remains M13a.
The dedicated pre-M7 scalability/operability pass is complete. Its regression and
diagnostic contracts are documented in [DEVELOPMENT.md](docs/DEVELOPMENT.md#structured-events-and-diagnostics).

## M7 — features, matching and geometric verification

Deliver feature extraction as M7a and matching/verification as M7b, followed by M7c.
Implement ALIKED and compatible LightGlue using a verified backend route, plus SIFT
and compatible brute-force matching. Separate stages and settings for features,
matches and geometric verification; expose any unavoidable native coupling. Validate
actual descriptor/weight/format compatibility and preserve the requested PairSet.
Keep databases isolated and published upstream payloads immutable. Assemble current
camera/calibration metadata in private downstream databases; do not reopen published
payloads writable or use writable hardlinks. A fused native operation has one execution
key/restart boundary and only promises intermediates it actually exposes. Reject a
route that cannot honor requested external pairs rather than claiming PairSet support.

Acceptance: a tiny real integration fixture produces features, matches and verified
geometry; incompatible routes fail before work; changing pair settings reuses features;
changing extractor cannot reuse an incompatible database. Test fallback explicitly.
If a local learned route is unavailable, report the missing capability and validate it
on a designated test machine before claiming the milestone's integration complete.

## M7c — practical cross-clip retrieval and hybrid pairing

Benchmark modern retrieval/hybrid candidates on representative drone/phone video,
mixed clips, unordered photos and difficult indoor/outdoor overlap/texture/viewpoint
cases. Compare verified useful pairs, graph/registration coverage, runtime, VRAM/RAM,
index size and pair count alongside Recall@K and commercial redistribution/licensing.
Vocabulary Tree is a catalog option, not a selected final backend. M6 selects no model.

Implement one verified retrieval representation/index route, independent of the local
ALIKED/SIFT descriptor choice unless an explicit compatible aggregation is implemented.
Record embedding/model weights, preprocessing, normalization/dimension, indexed corpus,
distance metric, index version/settings and query budgets. Combine Sequential within
clips with bounded retrieval across clips, deduplicate pairs and explain coverage.

Acceptance: known overlapping regions in several drone/phone clips yield useful
cross-clip candidates and geometrically verified matches through M7b without manual
pairs or all-pairs descriptor matching. Enforce neighbor/total-pair budgets and measure
index/query time and memory. Test model/corpus/index invalidation and local-feature
reuse when retrieval alone changes, plus no-overlap clips, repetitive texture and
near-duplicate bursts. Publish corpus-bound immutable indexes; retrieval cannot depend
on the reconstruction it enables. Missing representation/model/index capabilities
produce actionable errors, not silent Exhaustive fallback. M10 depends on this route;
GPS/spatial pairing and advanced index/scale optimization remain in M13a.

## M8 — mapping

Implement Global Mapper as the preferred supported route and Incremental/Hierarchical
Mapper as explicit capability-gated alternatives. Capture every reconstruction
component, camera convention and native ID mapping. Add the minimal streaming
ReconstructionReader so validation/preparation never parse COLMAP directly. Test a
synthetic reader independent of COLMAP; optional unavailable tracks/points remain
explicitly unknown. Do not silently choose a component.

Acceptance: a tiny dataset yields a readable reconstruction on each supported route;
mapper changes reuse earlier compatible artifacts; invalid/no-component results are
not successes; cancellation and retries preserve original matching artifacts.

## M9 — reconstruction validation and component selection

**M9a:** implement a structured report for registration coverage overall/per source group,
components, unregistered views, point/track statistics, reprojection distributions,
triangulation/degeneracy checks where supported and camera plausibility. Use explicit
threshold profiles; missing metrics are unknown, not zero or pass.

Acceptance: controlled reconstruction fixtures trigger pass/warn/fail with reasons;
policy changes do not rerun mapping. Distinguish component-scoped and project-wide
rules. CLI displays actionable issues; continuation past applicable failing gates
requires an explicit override bound to the reconstruction, report and selected data.

**M9b:** publish ReconstructionSelection as a small application decision artifact
referencing the unchanged ReconstructionSet and validation evidence. Record chosen
component IDs, manual/policy mode, policy settings/version and reasons. Fingerprint
selection for downstream datasets; never silently select the largest component.

Acceptance: manual and metric-informed choices are inspectable and reproducible;
missing/obsolete choices block preparation; selection changes invalidate only affected
datasets/training/exports. Several unaligned components remain separate datasets.
Validation still reports all components. Evaluate selected-component gates plus
project-wide rules; deselection cannot waive a global failure. Test changed geometry
under identical component IDs, stale overrides and same-content dataset reuse.

## M10 — complete flat-camera CLI and training dataset

Implement DatasetPreparation, required undistortion/resizing, camera/pose consistency
checks and dataset export. Compose project/ingest/plan/run/status/cancel/retry/diagnose
use cases. Provide a dry-run plan with capability, resource, coverage and cache reasons.
Require M7c hybrid pairing for the practical multi-video route and M9b explicit
component selection before preparation. Manual/budgeted Exhaustive remain optional
small-fixture tools. Report measured scale limits and incomplete cross-clip coverage.

Acceptance: documented commands take a short video, unordered photo set, multiple
clips and a mixed ordinary-camera fixture to validated trainer-ready datasets. The
multi-video case must use cross-clip retrieval without manual pair lists or all-pairs
descriptor matching. Verify recorded component selection and separate component outputs.
Test restart, late-setting changes, source relocation, corrupt cache, disk-full handling,
paths with spaces/Unicode and a disconnected scene. Validate exported cameras against
images with a consumer or independent reader. Include a previewable manual cleanup
command for unpinned completed payloads, preserving lineage/manifests and marking
cache entries evicted; never delete originals or active/pinned outputs. Check peak disk
budgets including private database copies and exports. A successful exit alone is
insufficient.

## M11 — legacy evaluation and Gaussian training integration

**M11a:** use available legacy research to translate recovered recipes/assumptions
into candidate presets, then benchmark on controlled scenes before official adoption.
Research may already have happened; inspect additional evidence read-only if needed.
If unavailable, record the gap and evaluate independently sourced recipes without
blocking product work. Do not require legacy code as a runtime dependency.

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

- **M13a:** GPS/spatial pairing with uncertainty and advanced retrieval/index/hybrid
  optimization beyond M7c. Measure coverage/resource improvements at bounded budgets;
  keep representation/index compatibility explicit.
- **M13b:** manual masks and automatic segmentation; validate alignment and separate
  SfM/training mask invalidation. Add adaptive selection only with quality evidence.
- **M13c:** local batch/queue and bounded retry policies. Verify per-project writer
  exclusion, resource limits, cancellation and resumable job history.
- **M13d:** large-scene strategies, selective per-view caching and advanced retention/
  automatic cleanup beyond M10's manual cleanup.
  Benchmark memory/disk/pair budgets and interrupt recovery without silent data loss.
- **M13e:** a second SfM/trainer backend or LiDAR-assisted alignment when justified.
  Validate existing contracts, units/transforms and comparison metrics before expanding
  interfaces. Add a concrete typed route for detector-free or direct SfM engines if
  required, without fabricating sparse-feature intermediates. No plugin SDK solely
  to satisfy a placeholder.

## M14 — 360/fisheye/equirectangular input layer

Implement calibrated perspective projection, parent/rig provenance, mask transforms
and supported mixed drone + 360 workflows. Declare mapper requirements for virtual
views; diagnose unsuitable geometry rather than treating projections as baseline.

Acceptance: projection/calibration fixtures and a mixed-source scene pass through
existing flat-camera SfM/training interfaces. The complete flat-camera regression
suite remains valid. Native spherical SfM, advanced sensor fusion and distributed
processing remain separate future decisions.
