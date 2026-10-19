# Architecture

## Status and product boundary

This document describes the target architecture. The current code is a configuration
and CLI foundation, not an implementation of these contracts. The [review](docs/ARCHITECTURE_REVIEW.md)
records what must change; the [roadmap](ROADMAP.md) stages adoption.

SplatForge owns project intent, orchestration, provenance, diagnostics and a convenient
local workflow. It delegates media processing, SfM and Gaussian optimization to
replaceable methods. The long-term product spans import, quality control,
reconstruction, training and viewing; the first deliverable stops at a validated
training dataset. No cloud service or account is required for ordinary local runs.

Phase 1 supports perspective photos and videos from multiple devices and clips.
Camera calibration, distortion, image orientation and source chronology are explicit.
Photogrammetric scale is unknown unless established by a recorded measurement or
alignment; GPS presence alone does not establish accuracy or metric scale.

## Dependency direction

```text
CLI / future PySide6 GUI
          |
          v
Application services -----> Core domain and contracts
          ^                         ^
          | injected implementations|
Storage / process / media / SfM / trainer adapters

Composition root constructs services and adapters.
```

| Boundary | Owns | Must not own |
| --- | --- | --- |
| Core | Typed configurations, IDs, artifact metadata, compatibility rules, dependency/fingerprint rules | UI, filesystem I/O, database connections, subprocesses, heavy backend imports |
| Application | Create/open/plan/run/cancel/retry/diagnose use cases, orchestration, publication policy | Widget state or vendor command syntax |
| Adapters | Storage, discovery, process management, FFmpeg, COLMAP, learned libraries, trainers, format conversion | Product defaults or silent fallback decisions |
| CLI/GUI | Input presentation, user choices, event rendering | Processing, cache decisions, direct backend invocation |
| Composition root | Explicit dependency wiring and built-in method factories | Business rules or mutable global registry |

Introduce `application/` and `adapters/` when their first use cases arrive. Do not
create a package for every noun now. Core may use Pydantic and `Path` values without
performing I/O. Storage interfaces belong to the application; artifact and method
contracts belong to core. Concrete adapters depend inward, never the reverse.

## Domain vocabulary

- **Source**: an original file with stable content identity and a separately stored
  locator. **Source group**: a clip/session/import grouping; not a calibration group.
- **Camera group**: observations that may share intrinsics under a declared model
  and policy. Resolution, zoom, crop, stabilization and lens changes can require new
  groups. Do not infer shared intrinsics from filenames or one import batch.
- **View**: an image observation with source provenance, dimensions, orientation,
  timestamp where applicable and camera reference. Future projected 360 views also
  carry parent capture and projection transforms.
- **Stage**: a semantic operation with an input/output contract. **Method**: an
  algorithm choice. **Backend/adapter**: an implementation/runtime for that choice.
  One backend may implement several stages without merging their contracts.
- **Artifact**: a validated, immutable published result with a manifest. Large
  arrays, images and native models remain on disk, referenced by typed handles.
- **Run**: a frozen resolved plan/configuration. **Attempt**: one execution of one
  stage or explicit fused operation in that run. Retrying creates another attempt,
  not overwritten history.

## Processing boundaries

The application constructs a small explicit acyclic plan in Python, not a workflow
language or a single mutable "pipeline database". Semantic operation kind and plan
node ID are distinct: one operation may appear once per source or selected component. [PIPELINE.md](docs/PIPELINE.md) owns the detailed contracts.

```mermaid
flowchart TD
    sources[Source inventory] --> views[ViewPreparation / candidate views]
    views --> quality[QualityAssessment]
    views --> selection[FrameSelection / selected views]
    quality --> selection
    selection --> masks[Optional Masking]
    selection --> features[FeatureExtraction]
    masks --> features
    selection --> pairs[PairSelection]
    features --> matching[FeatureMatching]
    pairs --> matching
    matching --> verification[GeometricVerification]
    verification --> mapping[Mapping]
    mapping --> validation[ReconstructionValidation]
    mapping --> component_selection[ReconstructionSelection]
    validation --> component_selection
    component_selection --> dataset[DatasetPreparation]
    validation -.-> dataset
    dataset --> dataset_export[Dataset export]
    dataset --> training[Training]
    training --> scene_export[Scene export]
```

The dashed edge is an eligibility gate; it does not transform reconstruction data.
This diagram omits optional dependencies: retrieval may consume feature or embedding
artifacts; geometric verification consumes camera assumptions; training may consume
its own masks. Such dependencies must be declared, not inferred from stage order.

Decoding determines the candidate pool. Quality measurement produces scores;
selection chooses a subset and records rejection reasons. Pair selection proposes
image pairs; matching produces descriptor correspondences; geometric verification
produces verified constraints. Mapping builds cameras/poses/points. Validation
reports quality without mutating reconstruction. A small application decision publishes
ReconstructionSelection with component IDs, manual/policy provenance and the report
evidence used; it never silently chooses the largest component. Dataset preparation
consumes that selection and handles undistortion, resizing, coordinate conversion and
trainer input layout explicitly. Multiple unaligned components remain separate datasets.

The diagram is the initial sparse-feature route, not a mandatory interface for every
future algorithm. A detector-free matcher may consume views and emit correspondences;
an alternative SfM system may consume views/priors and emit ReconstructionSet directly.
Add a specific typed route only when implementing that backend. Do not fabricate
FeatureSet, PairSet or verified-geometry outputs it cannot supply. Consumers still use
the reconstruction/validation/dataset contracts; capabilities state which metrics and
constraints are available. Unavailable intermediate metrics remain unknown.

An explicitly selected native operation may cover several semantic stages. Its plan
entry lists covered operations, real inputs/outputs, consumed settings and one recipe
key over all of them. It publishes one validated output bundle and resumes as a unit.
If it controls pairing internally, the route cannot claim to honor an external PairSet;
reject that requested combination or select the native route explicitly. Never treat
this as a silent fallback. No optimizer or framework for arbitrary stage fusion.

## Replaceable methods and capability checks

Keep the built-in registry small and explicitly injected. A registration must connect
metadata and a versioned settings schema to an implementation factory. Catalog-only
entries remain labeled planned. No third-party plugin loader is needed initially.

Validation has three levels:

1. **Configuration**: check every role separately, known settings, parameter bounds,
   input/output contracts and descriptor/model/camera compatibility.
2. **Environment**: probe executable/library identity, supported operations, model
   files, devices and runtime health. Report available, unavailable or unknown, with
   evidence and a reason. Unknown is not runnable.
3. **Plan**: resolve methods, input artifacts, resources, dependencies and required
   conversions for this project. Reject incompatibility before expensive execution.

Validate the requested target and its required operations, not every saved method.
Published inputs can be consumed without their producing backend installed; current
readers/validators and operations actually scheduled still need working capabilities.
Cache reuse does not certify that the original producer could be executed now.

ALIKED + compatible LightGlue is the preferred learned route; COLMAP Global Mapper
is the preferred mapper. Selection depends on verified installed capabilities and
dataset suitability. SIFT with compatible brute-force matching and COLMAP
Incremental/Hierarchical Mapper remain explicit alternatives. An automatic profile
may propose a fallback; execution records the resolved choice and never substitutes
another algorithm inside an attempt.

The documented COLMAP learned route depends on build options, including ONNX support;
it is not guaranteed by the executable name or version alone. This motivates probing,
not a requirement that every learned method use COLMAP's ONNX implementation.
See [COLMAP's feature guidance](https://colmap.github.io/faq.html#choosing-between-sift-aliked-and-loma-features).

Descriptor compatibility includes family, representation, dimensions, normalization,
keypoint convention and matcher weight variant. Retrieval/Vocabulary Tree is not a
universal operation over every local descriptor family. Keep retrieval model/index
requirements explicit; ALIKED local descriptors are not automatically retrieval
embeddings. M7c delivers a practical representation/index and bounded hybrid pairing:
Sequential within clips plus retrieval across clips, before the complete multi-video
CLI. GPS/spatial pairing and advanced retrieval optimization remain later.

## Backend artifact ownership

COLMAP's database and sparse files are adapter-owned payloads behind manifest contracts.
Do not force all algorithms into a universal tensor store, or make every consumer
understand COLMAP internals. Define portable metadata plus versioned payload formats;
implement conversion only when a real consumer requires it. By M8, a reconstruction
adapter must expose a small streaming reader for view/camera/pose/component records,
with optional points/tracks and declared conventions. Validation and dataset preparation
must not parse COLMAP files themselves. Do not build a universal feature-array store.

Separate application `state.sqlite` from every COLMAP database. Isolate databases by
feature identity and compatible processing branch. Copy or rebuild a native database
into an attempt workspace before a later operation mutates it. Never let matching or
mapping alter a published upstream database. Record SplatForge-to-native image/camera
ID mappings. Validate schema, coordinates, descriptors and verified geometry at import.
COLMAP distinguishes raw matches from the two-view geometry used by reconstruction;
that distinction is part of the adapter contract.
See [COLMAP database format](https://colmap.github.io/database.html).

Never hardlink a writable native database or hand a published file to a tool that may
open it for writing. Close/checkpoint native writers before a consistent copy; include
required sidecars or use the backend's supported snapshot mechanism. A readonly file
attribute alone is not isolation. Current calibration/priors belong to downstream
assembly: update a private database copy from the current camera inputs even when
reusing pixel features. If extraction really consumes calibration/gravity metadata,
those fields belong in its key. Native feature-row IDs must remain mapped to view IDs.

## State, reproducibility and execution

[PROJECT_FORMAT.md](docs/PROJECT_FORMAT.md) owns storage and recovery. Fingerprints
follow actual input dependencies, so training changes cannot invalidate frames or SfM.
Invalidation makes artifacts ineligible for a new plan; it does not delete history.
Reuse requires compatible provenance and validated output integrity, not just a key.
Sources are fully hashed at ingest. Later runs default to recorded Balanced/local
verification using metadata/identity/change indicators, with full rehash on suspicion
or insufficient evidence; Strict rehashes complete content and maintains stable bytes
through consumption. The run/attempt records assurance
and limitations, and stronger verification gates cannot silently upgrade weak provenance.
See [source verification](docs/PROJECT_FORMAT.md#source-verification-policies).

Record resolved settings/defaults, source and model digests, adapter/backend identity,
seeds, device/runtime information, input/output lineage and exact invocation metadata.
Reproducibility means an inspectable, repeatable recipe with declared numerical
limitations; GPU/SfM/training results are not promised to be bit-for-bit deterministic.

Start with one writer and one active stage per project. The owner holds the project
lock; other clients can inspect committed status and request cancellation without
writing SQLite. Settings saves while a run is active return busy in the initial
implementation. Use a synchronous application runner off the GUI thread, with owned
worker processes for native/GPU work. This does not require a service, distributed
scheduler, event-sourcing platform or cross-project cache.
Stage-boundary restart is required from the first processing milestone. Backend
checkpoint resume is an additional capability, not a universal promise.

## Training, legacy work and future inputs

Dataset preparation is independently useful: external LichtFeld handoff must work
without pretending an external/manual run is managed training. Managed trainers
implement start/progress/cancel/results and, only where supported, checkpoint resume.
gsplat is a potential trainer implementation dependency; its name alone does not
specify a complete training recipe. Keep optimizer, densification, loss, schedule,
camera conventions and output formats explicit in the trainer contract.

The developer's earlier successful 3DGS project may be inspected read-only at any
milestone as optional, non-blocking research. Record versions, parameters, preprocessing,
camera/scale assumptions, hardware and evidence in
[LEGACY_3DGS_RESEARCH.md](docs/LEGACY_3DGS_RESEARCH.md). Its availability never blocks
early implementation. M11 translates available evidence into candidate presets and
benchmarks them before adoption as official versioned presets. If evidence is missing,
record the gap and proceed with independently validated defaults. Do not import that
project's internals as SplatForge core or label it obsolete.

Later 360 preprocessing emits perspective views with virtual intrinsics, projection,
parent capture, timestamps and optional rig relationships. Avoid treating simultaneous
views from one center as independent translational evidence. A mapper without needed
rig support must reject the plan or expose a documented limitation. The existing
flat-camera contracts remain usable. GPS, LiDAR, masks and alignment attach as explicit
metadata/artifacts with units, uncertainty and coordinate frames, never hidden inputs.
Preserve observation time, sensor/rig relationships, pose direction/axis conventions
and transform provenance when present. LiDAR is a geometry/prior input, not a fake
image source. Only a backend declaring support may consume such constraints; unknown
models/constraints must not be silently ignored. Projection is the first 360 route,
not a promise that every future spherical or sensor-fusion method fits preprocessing.

Deferred implementation choices and non-goals are listed in the [review](docs/ARCHITECTURE_REVIEW.md#intentionally-deferred).
