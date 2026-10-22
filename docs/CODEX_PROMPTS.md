# Codex implementation tasks

Use one bounded task at a time. [ROADMAP.md](../ROADMAP.md) owns milestone acceptance;
read only the selected milestone, not the whole roadmap for every task. AGENTS.md is
always required. Each task lists its additional contract reading below; follow other
documents only when a concrete dependency requires them. Review the diff after each
task. Do not commit or push unless explicitly requested. Future command names are
proposed until implemented.

The post-M5/pre-M6 foundation repair is bounded to lock object/alias safety, native
Windows entrypoints, full candidate decode integrity, atomic state v1/v2/v3 upgrades,
orientation/source-PTS semantics, fresh FFmpeg plan identity and exceptional teardown
quarantine. Preserve these regressions in later milestones. Adapter version 2 changes
candidate recipes; state v4 and candidate contract 1 stay unchanged. M6/PairSet is
implemented. The dedicated post-M6/pre-M7 scalability/operability pass is complete:
preserve the brute-force selector oracle, early expansion bounds, operation-scoped
validation, linear producer provenance and bounded optional attempt diagnostics in
later milestones. Numerical keys and existing project/state/artifact versions are
unchanged. M7a extraction and M7b matching/verification are implemented. M7c's neutral
offline contracts/hybrid path are implemented; production inference/model selection
and representative quality acceptance remain pending.

M6.5 progress/ETA foundation is implemented. Later backends must integrate
with the [progress contract](DEVELOPMENT.md#progress-and-eta-foundation), preserving
diagnostic-only estimates, worker-local private history, deterministic clock tests,
bounded events and absent percentages for unknown/nonlinear work. Do not rebuild
estimation in CLI/GUI or include performance history in numerical identity.

## Common instructions for every task

Prepend this to the selected task:

```text
Read AGENTS.md, the selected task's additional reading and its roadmap acceptance
criteria. Inspect relevant implementation/tests and Git status; preserve user changes.
Implement only the selected task. Give a concise plan when it crosses boundaries.
Inject adapters through application services; keep core independent of UI/backends.
Preserve settings and originals. Do not present planned methods as runnable, silently
substitute fallbacks, or download models/install toolchains implicitly.
Add meaningful tests for changed behavior. Run relevant tests, full pytest and
ruff check . in the project environment; report existing failures and integration
skips honestly. Documentation-only work needs documentation checks, not code tests.
Update affected contracts, inspect the diff and report evidence, limits and next steps.
Do not commit or push automatically.
```

## M1a1 Basic project persistence

Implemented development slice; retained as its scope reference. Additional reading:
[PROJECT_FORMAT: ownership](PROJECT_FORMAT.md#storage-layout-and-ownership),
[authoritative records](PROJECT_FORMAT.md#authoritative-records),
[paths](PROJECT_FORMAT.md#paths-and-source-identity), the M1a1 boundary at the start of
[safe writes](PROJECT_FORMAT.md#safe-writes-and-migrations), and
[ARCHITECTURE: dependency direction](../ARCHITECTURE.md#dependency-direction).

```text
Implement M1a1 as the basic single-process persistence development slice.
- Add application/storage boundaries and a basic project document with distinct
  project/config/state versions, revision initialized to 0, directory ownership and
  SQLite metadata initialization.
  Persist current settings plus opaque envelopes, not schemas for all future stages;
  create owned subdirectories on demand.
- Implement create/open/save/show, with CLI delegation and no I/O in core models.
  Use validated temporary-file replacement for basic save; M1a2 proves failure safety.
- Preserve known settings and opaque unknown method/version envelopes, including
  unknown envelope fields as equivalent JSON values. Keep preset provenance separate
  from resolved settings; never reapply presets on open. Resolve
  prototype defaults explicitly; do not invent a historical project migration.
- Fix independent role validation; test training.none incorrectly used as the mapper.
- Test create/reopen/save/show, settings round-trips, Unicode/space paths, non-empty
  destination refusal, unsupported versions without rewrites and directory ownership.
Do not claim durability/concurrency readiness. Leave revision/stale-save checks,
writer locks, atomic replacement details, migration scaffolding and fault recovery
for M1a2. No processing, external tools, run tables, scheduler or unrelated cleanup.
```

## M1a2 Persistence safety

Implemented; retained as its scope reference. Additional reading:
[PROJECT_FORMAT: safe writes and migrations](PROJECT_FORMAT.md#safe-writes-and-migrations),
[ARCHITECTURE: dependency direction](../ARCHITECTURE.md#dependency-direction) and
[DEVELOPMENT: testing layers](DEVELOPMENT.md#testing-layers).

```text
Complete M1a2 before M1b or processing uses persisted projects. Add revision/stale-save
protection, one local writer lock, validated atomic replacement, migration dispatch
and consistent backup/recovery boundaries. Test concurrent/stale writers, Windows
sharing errors, interrupted replacement, disk-full and failed backups while retaining
the last valid project. Test current/unsupported-version dispatch with fault hooks.
There is no older production format: do not invent legacy versions or speculative
migration transforms or a generic multi-store migration journal. Add a real migration
fixture and any required journal only when a supported format changes.
No run/attempt/artifact execution infrastructure yet; that remains M1b.
```

## M1b1 Execution and cache happy path

Status: implemented with state schema v2, an explicit
v1-to-v2 upgrade and the deterministic two-node fake route described below.

Additional reading: [PROJECT_FORMAT: records](PROJECT_FORMAT.md#authoritative-records),
[publication](PROJECT_FORMAT.md#attempts-publication-and-recovery),
[PIPELINE: execution contract](PIPELINE.md#method-execution-contract) and
[cache rules](PIPELINE.md#stage-fingerprints-and-cache-eligibility).

```text
Implement a concrete two-node fake plan with one writer/active stage. Add frozen run
intent using node/output references, attempt records binding actual inputs, manifests,
explicit key functions, validated publication and minimal events. Prove cache hit/miss,
corrupt/missing-output refusal and downstream-only invalidation. Do not put future
artifact IDs into immutable snapshots before they exist. Prepare durable publication
ordering for M1b2; no plan compiler, workflow language or external tools.
```

## M1b2 Interruption and recovery

Status: implemented with state schema v3, durable fake-stage cancellation, validated
orphan recovery and explicit bounded retry against the immutable M1b1 run snapshot.

Additional reading: [PROJECT_FORMAT: cancellation](PROJECT_FORMAT.md#writer-ownership-and-cancellation),
[publication/recovery](PROJECT_FORMAT.md#attempts-publication-and-recovery) and
[DEVELOPMENT: testing layers](DEVELOPMENT.md#testing-layers).

```text
Extend M1b1 using fake stages: durable cancellation acceptance, retry as a new attempt,
stale-owner detection and recovery. Test cancellation requests from another CLI without
writer access, publication/cancellation races and crashes around manifest/rename/commit.
Never promote cancelled, unvalidated or unexpected output. Block retry while teardown
is unresolved. Complete this before processing. M2 separately proves real Windows
process containment; do not claim it from fake tests. No network service or scheduler.
```

## M2 Media ingest

Status: implemented with state schema v4, immutable JSONL inventory revisions, durable
verification evidence, FFprobe normalization, relinking and the Windows-contained
bounded process adapter. M2 does not decode frames; candidate views start in M3.

Additional reading: [PROJECT_FORMAT: paths](PROJECT_FORMAT.md#paths-and-source-identity),
[source verification](PROJECT_FORMAT.md#source-verification-policies),
[PIPELINE: view and camera rules](PIPELINE.md#view-and-camera-rules) and
[DEVELOPMENT: process contract](DEVELOPMENT.md#external-process-contract).

```text
Implement read-only photo/video registration, inventory revisions and relinking.
Fully hash initial ingest; implement recorded Balanced/local metadata/identity checks
and Strict full hashing with stable byte continuity through backend consumption.
Use tested read leases or explicitly approved/budgeted snapshots; unsupported guarantees
fail clearly. Test attempted edits/replacements during consumption and unchanged-source
read avoidance,
suspicious/unreliable evidence, changed content, cancellation and assurance provenance.
Separate source/camera groups; preserve time bases, orientation and missing metadata.
Add the process/FFprobe adapters with argument arrays, scoped working directory and
environment, bounded streams, timeout and Windows process-tree cancellation. Test
fakes/helpers, owner death/descendant cleanup and an opt-in generated-media fixture.
Do not copy originals implicitly or extract frames. A failed metadata/hash check must not silently become an unchanged result.
```

## M3 Candidate views and fixed-FPS selection

Status: implemented with the explicit `views prepare` two-node route, state schema v4,
bounded FFmpeg materialization, actual VFR presentation timestamps, explicit orientation,
multi-file artifact validation, source-verification eligibility, durable cancellation
and stage-boundary cache reuse. Quality/scoring selection remains M4.

Additional reading: [PIPELINE: views](PIPELINE.md#view-and-camera-rules),
[execution](PIPELINE.md#method-execution-contract),
[cache](PIPELINE.md#stage-fingerprints-and-cache-eligibility) and
[DEVELOPMENT: process contract](DEVELOPMENT.md#external-process-contract).

```text
Implement FFmpeg ViewPreparation behind an adapter and fixed-FPS selection from an
explicit candidate pool. Photos use the same view contract. Record actual frame
identity/timestamps, dimensions and transforms; do not assume constant frame rate.
Budget candidate count/peak disk before decode; start with bounded materialized views.
Use existing attempts/cache/cancellation/publication. Test VFR/orientation, unchanged
originals, cancellation/restart and reuse. No quality scoring, SfM or GUI.
```

## M4 Quality and frame selection

Implemented by the concrete `views.prepare_sharpest_interval` route. Pillow measures
exact edge-response variance and dHash64 from published candidate pixels; thresholds
remain versioned selection policy so policy-only changes reuse QualityReport. The
fixed-FPS route remains available without quality work. Adaptive/motion-aware sampling
is still deferred.

Additional reading: [PIPELINE: views](PIPELINE.md#view-and-camera-rules),
[stage inputs](PIPELINE.md#stage-inputs-and-outputs) and
[invalidation](PIPELINE.md#invalidation-examples).

```text
Separate blur/duplicate measurements from selection. Add sharpest-per-interval,
deterministic ties, rejection reasons and candidate-pool sufficiency checks. Threshold
changes reuse measurements/pixels; scoring changes invalidate consumers. Preserve
rejected images as metadata-backed artifacts. Defer adaptive motion selection.
```

## M5 COLMAP and GPU capabilities

Implemented by the project-free `doctor` application service and CLI. Lightweight
discovery records exact executable/build identity, bounded raw commands/options/tokens,
ONNX/model prerequisites and separate generic-GPU evidence. `--deep` adds disposable
native database and CPU/GPU SIFT functional probes. M7a extends this same machinery
with exact ALIKED/LoMa variant/device/model inference gates. M7b adds explicit-pair
matching and standalone verification inference gates. M8 methods remain planned;
capability evidence alone cannot make an unimplemented method runnable.
Windows official-style installations accept `COLMAP.bat` only as an inert locator;
all probes execute hash-verified native `colmap.exe` with the same controlled child
runtime paths. Record typed layout evidence separately; never execute the wrapper,
change system PATH or infer portable layout from a `bin` directory alone.

Additional reading: [ARCHITECTURE: capability checks](../ARCHITECTURE.md#replaceable-methods-and-capability-checks),
[PIPELINE: method execution contract](PIPELINE.md#method-execution-contract) and
[DEVELOPMENT.md](DEVELOPMENT.md).

```text
Implement discovery and doctor output, not feature execution. Probe binary/operation/
format/model/runtime identity and backend-specific GPU health with timeouts. Distinguish
available/unavailable/unknown with evidence and freshness limits. Use owned disposable
workers for risky probes. Test missing ONNX/models/Global Mapper,
CPU-only support and CUDA/DLL failures. No heavy imports in core/UI for method listing,
version-string-only compatibility claims or implicit component downloads.
```

## M6 Minimal pair selection (implemented)

Additional reading: [PIPELINE: pair selection](PIPELINE.md#pair-selection-and-native-execution)
and [PROJECT_FORMAT: recovery](PROJECT_FORMAT.md#attempts-publication-and-recovery).

Implemented independently of branch name: `pairs build --views-run` resolves an exact
successful M3/M4 views run, freezes its selected-view projection and publishes PairSet v1.
Sequential timelines use source/revision/stream identity, never source groups or photo
filenames. Budgeted Exhaustive and explicit selected-view edges share a bounded budget.
Tests cover deterministic IDs/reasons, graph semantic versus recipe identity, coverage,
cache/invalidation, upstream integrity, cancellation and orphan recovery. No project/state
schema bump, image decode, native execution, local features or GPU work.
Practical modern retrieval/hybrid benchmarking remains M7c; spatial pairing remains M13a.

## M7a Features

Status: implemented as `features extract` and `LocalFeatureSet` contract 1, with
deterministic contract/adapter/application tests and opt-in real SIFT. Real ALIKED/LoMa
integration requires configured compatible ONNX models/runtime; mocks do not certify it.
The route consumes an exact successful views run, uses existing immutable publication,
cache/recovery/cancellation and `features.selected_views_v1` Progress/ETA history.

Additional reading: [PIPELINE: stage inputs](PIPELINE.md#stage-inputs-and-outputs),
[view conventions](PIPELINE.md#view-and-camera-rules),
[execution](PIPELINE.md#method-execution-contract),
[cache](PIPELINE.md#stage-fingerprints-and-cache-eligibility),
[ARCHITECTURE: backend ownership](../ARCHITECTURE.md#backend-artifact-ownership) and
[DEVELOPMENT: testing layers](DEVELOPMENT.md#testing-layers).

```text
Implement verified SIFT, ALIKED_N16ROT, optional ALIKED_N32, LOMA_B and LOMA_B128
extraction routes and feature artifacts. Require COLMAP >=4.2.1 only for LoMa.
LoMa-R/L/G belong to M7b matching. Keep current SfM defaults. Validate
signatures, model digests and pixel/keypoint conventions. Isolate native databases
by feature identity and publish immutable results. Test incompatible routes and real
opt-in extraction. Missing learned support is a capability gap, not a completed
integration milestone based solely on mocks/SIFT. No matching or mapping.
Pin explicitly provisioned local models before numerical execution, record source/name
and SHA-256 for a later installer-license audit, and forbid implicit downloads.
No PyTorch or other Python ML runtime. Integrate VIEWS/megapixels and eligible successful
history through M6.5; never put ETA/history or pair/matcher settings in feature keys.
```

## M7b Matching and geometric verification

Status: implemented with `MatchSet`/`VerifiedGeometrySet` v1, exact external PairSet,
separate immutable database copies/cache boundaries, PAIRS progress/history, production
SIFT/ALIKED/LoMa families and versioned feature/matching profile v1 resolution.
Real tiny SIFT passes on installed COLMAP 4.2.1; learned real validation requires
provisioned local model/runtime evidence. See [M7B.md](M7B.md) for exact routes,
settings, fixture configuration and limitations. M7b.1 hardens route-specific device
resolution: Simple `auto` checks GPU then supported CPU inside each candidate;
Advanced `auto` changes device only. Concrete devices are frozen, performance history
never selects them, and local models cannot invoke native URI downloads. Real
ALIKED_N16ROT/LightGlue CPU passes. M7b.2 extends the opt-in real fixture to the
complete 13-combination Advanced matrix, including N32 and learned brute-force.
Official weights are explicitly provisioned separately using verified native
URL/name/SHA defaults; numerical attempts still cannot download. Runtime diagnosis
stays inside the controlled installation, with no software installation, borrowed
DLLs or global PATH changes. All thirteen compatible CPU combinations passed real
validation, covering all ten matcher types. SIFT/brute-force also passed GPU;
learned GPU routes remain blocked by missing cuDNN 9 in the controlled installation.
M7b.3 subsequently resolves this dependency through explicitly authorized isolated
runtime provisioning: native COLMAP 4.2.1, CUDA 12.8 and cuDNN 9.27.0.42. All thirteen
compatible routes pass real GPU validation, with cache and published-input integrity;
CPU ALIKED/LightGlue also passes on that bundle. The original installation, existing
models and system PATH are preserved. Numerical attempts and Doctor still perform
no installation/download. Simple profile v1 and production code are unchanged.
See [GPU runtime setup](GPU_RUNTIME.md) and M7B.md for metrics and limitations.
This prompt remains a scope reference.

Additional reading: [PIPELINE: stage inputs](PIPELINE.md#stage-inputs-and-outputs),
[pairing and native execution](PIPELINE.md#pair-selection-and-native-execution),
[cache](PIPELINE.md#stage-fingerprints-and-cache-eligibility),
[ARCHITECTURE: backend ownership](../ARCHITECTURE.md#backend-artifact-ownership) and
[DEVELOPMENT: testing layers](DEVELOPMENT.md#testing-layers).

```text
Implement first-class SIFT/BF/LightGlue, ALIKED/BF/LightGlue and LoMa-B128/B/R/L/G/BF
matching over the exact M6 PairSet, then standalone geometric verification. Preserve
zero-match/rejected pairs and separate MatchSet/VerifiedGeometrySet identities.
Resolve Simple Fast/Medium/High/Max High v1 before execution; Advanced is explicit
typed selection without fallback. Freeze exact numerical settings and capability
evidence; never switch algorithms inside an attempt or migrate saved ALIKED intent.
Use independent private database copies, canonical numerical digests, current camera
priors, existing attempts/cancellation/recovery and separate PAIRS/ETA signatures.
Test full compatibility, corruption, cache dependencies, immutable bytes and real
SIFT; provide complete learned opt-ins and actionable provisioning gaps. No retrieval,
mapping, training, GUI, downloads or new Python ML runtime.
```

## M7c Practical cross-clip retrieval and hybrid pairing

Status: partially implemented. Read [M7C.md](M7C.md) and the
[candidate audit/evidence ledger](M7C_BENCHMARK.md) before continuing. Preserve the
offline contracts/hybrid path and complete the real candidate comparison before
selecting or integrating one production inference backend. No current Simple profile
selects a retrieval model. Do not reinterpret synthetic transport evidence as quality.

Additional reading: [PIPELINE: pair selection](PIPELINE.md#pair-selection-and-native-execution),
[PIPELINE: cache rules](PIPELINE.md#stage-fingerprints-and-cache-eligibility) and
[DEVELOPMENT: testing layers](DEVELOPMENT.md#testing-layers).

```text
Evaluate modern retrieval/hybrid candidates using representative SplatForge datasets
and both useful verified/reconstructed coverage and commercial redistribution constraints.
Vocabulary Tree is not the final selected solution; no model is selected in M6.
Implement one practical retrieval representation/index plus Sequential-within-clip
and retrieval-across-clips hybrid pairing. Keep embedding/aggregation, weights,
preprocessing, normalization/dimension, corpus, metric and index/query settings explicit.
ALIKED local descriptors are not automatically a retrieval representation.
Bound neighbors/total pairs, deduplicate and record reasons/coverage. On known
multi-drone/phone clip overlap, demonstrate verified cross-clip matches through M7b
without manual lists or all-pairs descriptor matching; measure query/index time and
memory too. Test corpus/model/index invalidation, independent local-feature reuse,
no-overlap clips and duplicate bursts. Indexes are immutable and corpus-bound; initial
retrieval cannot depend on the reconstruction it enables.
Do not silently fall back to Exhaustive. GPS and advanced optimization stay in M13a.
```

## M8 Mapping

Additional reading: [PIPELINE: stage contracts](PIPELINE.md#stage-inputs-and-outputs),
[reconstruction interchange](PIPELINE.md#reconstruction-interchange),
[ARCHITECTURE: backend ownership](../ARCHITECTURE.md#backend-artifact-ownership) and
[DEVELOPMENT.md](DEVELOPMENT.md).

```text
Implement preferred supported Global Mapper and explicit Incremental/Hierarchical
alternatives. Publish every component, coordinate convention and native ID mapping.
Add a minimal streaming ReconstructionReader and independent synthetic reader tests;
downstream logic must not parse COLMAP. Never choose/discard components here. Test mapper-only invalidation, cancellation,
invalid output and real supported routes. Preserve upstream databases and keep quality
policy out of command execution. Component selection follows M9a validation in M9b.
```

## M9a Reconstruction validation

Additional reading: [PIPELINE: reconstruction interchange](PIPELINE.md#reconstruction-interchange),
[selection and gates](PIPELINE.md#reconstruction-component-selection) and [DEVELOPMENT: diagnostics](DEVELOPMENT.md#structured-events-and-diagnostics).

```text
Implement non-mutating validation of all components: per-source registration/coverage,
tracks, reprojection and camera/geometry metrics with units/unknowns. Add configurable
pass/warn/fail policies with component versus project-wide scope and overrides bound
to exact evidence/selected data. Test controlled fixtures and
threshold changes without remapping. Do not select components or rewrite models.
```

## M9b Reconstruction component selection

Additional reading: [PIPELINE: component selection](PIPELINE.md#reconstruction-component-selection)
and [PROJECT_FORMAT: authoritative records](PROJECT_FORMAT.md#authoritative-records).

```text
Publish ReconstructionSelection as a small application decision artifact. Record the
unchanged ReconstructionSet reference, selected component IDs, manual/policy mode,
policy version/settings, metric evidence and reasons. Never silently choose largest.
Test manual/policy choices, stale/absent IDs, decision fingerprinting and downstream-only
invalidation, including changed geometry under the same IDs. Multiple unaligned
components yield separate datasets; no implicit merge. Apply selected-component gates
and all project-wide rules; deselection must not waive global coverage failures.
Same selected data can reuse a dataset after its gate passes. Selection is not a gate
override, and Validation continues to report every component. No new workflow framework.
```

## M10 Complete flat-camera CLI

Additional reading: [PIPELINE.md](PIPELINE.md),
[ARCHITECTURE: application boundary](../ARCHITECTURE.md#dependency-direction) and
[DEVELOPMENT: testing layers](DEVELOPMENT.md#testing-layers).

```text
Implement dataset preparation/export with explicit component selection, undistortion/
resize and consistent cameras/poses/images. Compose plan/run/status/cancel/retry and
cache/resource/capability diagnostics. Require M7c for the multi-video route: demonstrate
multiple clips without manual pairs or all-pairs descriptor matching. Exercise single
video, photos and mixed sources too; record selected components and separate outputs.
Verify datasets with a consumer/independent reader and test interruption, relocation,
corrupt cache, disk-full and Windows paths. Add previewable manual cleanup of unpinned
completed payloads, preserving manifests/lineage and eviction records; protect originals,
active outputs, exports and checkpoints. Budget database copies/workspaces and exports.
No GUI or managed training yet.
```

## Optional early legacy research

Additional reading: [LEGACY_3DGS_RESEARCH.md](LEGACY_3DGS_RESEARCH.md) and
[ARCHITECTURE: legacy boundary](../ARCHITECTURE.md#training-legacy-work-and-future-inputs).

```text
If supplied, inspect the successful legacy project read-only and record traceable
versions, settings, preprocessing, camera/scale assumptions, hardware and result
evidence in docs/LEGACY_3DGS_RESEARCH.md. Separate observations, hypotheses and unknowns.
Do not run legacy scripts, install dependencies, implement adapters or adopt official
presets in this research task. If unavailable, record the gap; early milestones proceed.
Preset translation and benchmarking remain M11a.
```

## M11a Preset translation and benchmarking

Additional reading: [LEGACY_3DGS_RESEARCH.md](LEGACY_3DGS_RESEARCH.md),
[ARCHITECTURE: training boundary](../ARCHITECTURE.md#training-legacy-work-and-future-inputs)
and [DEVELOPMENT: testing layers](DEVELOPMENT.md#testing-layers).

```text
Use available legacy evidence to translate candidate recipes with provenance and
explicit overrides. Compare controlled scenes before adopting official versioned
presets. Fill evidence gaps read-only when possible; if legacy material is unavailable,
record this and validate independently sourced recipes without blocking product work.
Do not import legacy internals as core or label untested recipes equivalent/superior.
```

## M11b Training integration

Additional reading: [PIPELINE: stage inputs](PIPELINE.md#stage-inputs-and-outputs),
[execution](PIPELINE.md#method-execution-contract),
[cache](PIPELINE.md#stage-fingerprints-and-cache-eligibility),
[ARCHITECTURE: training boundary](../ARCHITECTURE.md#training-legacy-work-and-future-inputs),
[DEVELOPMENT: process contract](DEVELOPMENT.md#external-process-contract) and
[testing](DEVELOPMENT.md#testing-layers).

```text
Implement a tested external LichtFeld dataset handoff, then one selected managed
trainer. Keep manual handoff distinct from execution. Verify loadable scenes, progress/
cancellation, compatible checkpoint resume where supported, metrics and export.
Trainer changes must reuse SfM. A gsplat-based option needs an explicit training recipe.
```

## M12 GUI

Additional reading: [ARCHITECTURE: application/dependency contracts](../ARCHITECTURE.md#dependency-direction)
and [ARCHITECTURE: execution contracts](../ARCHITECTURE.md#state-reproducibility-and-execution).
Inspect the implemented application use-case/event interfaces for screen-specific details.

```text
Implement PySide6 as a client of existing application services: projects/sources,
profiles/settings, plan/progress, cancel/retry, diagnostics, component choice and
inspection. Keep processing off the UI thread. Test CLI/GUI interchange and prevent
backend/process calls from widgets. Do not duplicate pipeline/cache/persistence logic.
```

## M13 Advanced methods and automation

Choose exactly one submilestone and a bounded executable slice. Additional reading:

| Subtask | Relevant contracts |
| --- | --- |
| M13a GPS/spatial and advanced retrieval beyond M7c | [PIPELINE pairing/cache](PIPELINE.md#pair-selection-and-native-execution), [DEVELOPMENT testing](DEVELOPMENT.md#testing-layers) |
| M13b Masks/segmentation | [PIPELINE stage inputs and invalidation](PIPELINE.md), [DEVELOPMENT testing](DEVELOPMENT.md#testing-layers) |
| M13c Local queue/retry | [PROJECT_FORMAT attempts](PROJECT_FORMAT.md#attempts-publication-and-recovery), [ARCHITECTURE execution](../ARCHITECTURE.md#state-reproducibility-and-execution) |
| M13d Measured scale/cleanup | [PIPELINE cache](PIPELINE.md#stage-fingerprints-and-cache-eligibility), [PROJECT_FORMAT retention](PROJECT_FORMAT.md#retention-and-diagnosis), [DEVELOPMENT risks](DEVELOPMENT.md#windows-cuda-colmap-and-scale-risk-register) |
| M13e Concrete alternative backend/LiDAR | [ARCHITECTURE.md](../ARCHITECTURE.md), relevant [PIPELINE contracts](PIPELINE.md), [DEVELOPMENT integration](DEVELOPMENT.md#testing-layers) |

Preserve flat-camera contracts and add tests for new dependencies and resource/quality
limits. No generic plugin SDK, workflow language or distributed scheduler.

## M14 360 input preprocessing

Additional reading: [PIPELINE: view/camera contracts](PIPELINE.md#view-and-camera-rules),
[ARCHITECTURE: future inputs](../ARCHITECTURE.md#training-legacy-work-and-future-inputs)
and [DEVELOPMENT: testing layers](DEVELOPMENT.md#testing-layers).

```text
Implement preprocessing into existing perspective views with parent capture,
projection, virtual calibration, timestamps, masks and rig metadata. Validate mixed
drone + 360 geometry without inventing translational baseline from projections.
Demonstrate calibrated fixtures and a mixed scene through existing SfM/training.
Run flat-camera regressions; no rewrite or unverified native spherical mapper support.
```
