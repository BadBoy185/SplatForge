# Pipeline contracts

Status: target contracts, introduced incrementally by the [roadmap](../ROADMAP.md).
[ARCHITECTURE.md](../ARCHITECTURE.md) defines ownership; [PROJECT_FORMAT.md](PROJECT_FORMAT.md)
defines durable state. Stage names below are semantic contracts, not existing enum
members or promises that every stage already has an implementation.

## Stage inputs and outputs

| Stage | Inputs | Published result and minimum checks |
| --- | --- | --- |
| MediaIngest | Read-only source locators and import intent | Source inventory: IDs, content digests, media metadata, source/camera groups, unsupported or missing input diagnostics |
| ViewPreparation | Inventory and decoding/preprocessing settings | CandidateViewSet: stable view IDs, images, dimensions, source mapping, timestamps/time base, orientation/crop/resize transforms, camera references |
| QualityAssessment | Candidate views and scoring settings | QualityReport: per-view scores, metric versions, units and unavailable-score reasons; never deletes images |
| FrameSelection | Candidate views, optional quality report and selection policy | SelectedViewSet plus acceptance/rejection reasons, deterministic tie-breaking and selection order |
| Masking | Selected views, supplied masks or segmentation inputs | MaskSet with view IDs, dimensions, coordinate alignment and explicit pixel semantics; no mask is an explicit absent input |
| FeatureExtraction | Selected pixels, optional future SfM masks, method/model settings | LocalFeatureSet: descriptor signature, coordinate convention and payload format; M7a implements the unmasked route |
| RetrievalRepresentation | Selected pixels/metadata and explicitly prepared offline global descriptors | RetrievalRepresentationSet v1: corpus/pixel/model/preprocess/runtime identity and immutable flat index; production inference selection pending |
| PairSelection | Selected view IDs and the chronology, retrieval or spatial inputs actually used | PairSet: canonical unordered pairs, no self/duplicate pairs, coverage statistics, selection reasons |
| FeatureMatching | LocalFeatureSet and PairSet | MatchSet v1: exact requested pairs including zeros, valid feature indices, matcher/settings/model identity and raw numerical digest |
| GeometricVerification | MatchSet, keypoints and camera assumptions | VerifiedGeometrySet v1: inliers, pair models/relative constraints, camera identity and typed rejection states |
| Mapping (initial sparse route) | Verified geometry, views, cameras and optional declared priors | ReconstructionSet: all components, camera/pose/point metadata, native payloads, ID mappings and coordinate frames |
| ReconstructionValidation | ReconstructionSet, immutable ValidationUniverse and normalized optional detailed geometry | Separate ValidationGeometryInput, ReconstructionMetrics and ReconstructionValidationReport v1; exact/sampled/unavailable evidence, explicit policy and scoped issues; no model mutation |
| ReconstructionSelection (application decision) | ReconstructionSet, ValidationReport and explicit manual choices or configured policy | ReconstructionSelection: referenced set, selected component IDs, selection mode, policy/version/settings and evidence; no reconstruction mutation |
| DatasetPreparation | Published ReconstructionSelection v1, exact reconstruction/historical pixels and current validation gate | M10 PreparedDatasetComponent v1 per component, then PreparedDatasetSet v1 receipt: undistorted images, flat cameras, preserved poses/XYZ/tracks, unknown scale and explicit metadata |
| Training | One PreparedDatasetComponent v1, frozen TrainingSettings v1, positively validated exact backend and optional compatible checkpoint | TrainingCheckpoint v1 opaque resumable state; GaussianScene v1 independently validated Gaussian PLY, metrics and provenance; GaussianSceneSet v1 separate-component receipt |
| Export | Explicit dataset or training result, format/settings | ExportManifest: output files, consumer/format versions, checksums and any lossy conversion |

M11 implements the Training row through TrainingService -> TrainingBackend -> external
SplatForge gsplat worker. `gsplat.default` and `gsplat.mcmc` consume exactly one M10
component, its sparse XYZ/RGB and immutable explicit settings. No pose optimization,
world normalization, random baseline initialization or component merging occurs.
`data_factor` changes in-memory loading and intrinsics, never M10 pixels. Scale stays
`unknown_arbitrary`. External LichtFeld handoff validates the same directory without
copying it; it is a manual workflow, independent of the managed backend.

Training recipe inputs are dataset numerical digest, resolved settings/split and exact
positively probed worker/backend identity. Timeouts/log/workspace limits and diagnostics
do not invalidate numerical recipes. Changed strategy, cap, resolution, SH, steps,
seed or runtime do; earlier stages do not rerun. Resume additionally requires the exact
checkpoint schema/compatibility identity, originating recipe and completed step.
`max_steps` cannot change on resume in v1. Native state is not a public scene.

Checkpoint segments use persisted attempts, structured protocol v1, bounded process-tree
cancellation and `training.steps_v1` progress/ETA. Publication/cache/recovery independently
verify complete manifests, events, native files and final PLY values/attributes/counts.
GaussianScene semantics derive from actual canonical numerical Gaussian content;
SceneSet only references separate components in canonical order. See [M11](M11.md)
for field schemas, resources, held-out metrics and acceptance evidence.

The table describes the initial route. Explicit composite SfM or detector-free routes
may use different typed inputs and omit unavailable intermediate artifacts, as defined
in ARCHITECTURE.md. Validate only the operations needed by the requested target;
an unavailable trainer must not block a dataset-only plan. A fused route's settings,
recipe key, output bundle and restart boundary cover the complete native operation.

MediaIngest publishes versioned project input inventories through the project-save
protocol; subsequent stages publish derived artifacts through the attempt-publication
protocol. Both protocols are defined in PROJECT_FORMAT.md.

M2 implements MediaIngest for JPEG/PNG/MP4/MOV as read-only external locators. It fully
hashes bytes, records normalized FFprobe metadata and distinct source/camera groups, and
publishes a new immutable inventory revision only after a writer-locked CAS recheck.
Balanced/local and Strict verification evidence is durable state, not an inventory
rewrite.

M3 implements an explicit two-node route. `view_preparation.ffmpeg_fixed_pool` consumes
selected immutable inventory records and publishes `views.candidate_set` contract 1:
one explicitly oriented materialized view per photo and a bounded presentation-time
sample from each video. Video records carry the actual selected FFmpeg `showinfo` PTS
and filter-link time base; image sequence numbers are not timestamps. View IDs derive
from source/revision/stream/frame identity, while semantic identity additionally covers
source content, transforms, dimensions and streamed image SHA-256 values.
The filter path uses `-copyts -noautorotate`: integer PTS and rational time bases
refer to the source presentation timeline, including a non-zero origin, not a rebased
processing clock. FFprobe display-matrix rotation is counter-clockwise; +90 applies
`rotate_90_ccw`, -90/270 applies `rotate_90_cw`. Legacy clockwise `rotate` tags are
normalized to this convention. Exact decimal right angles are accepted; arbitrary
angles are refused without rounding. JPEG and PNG EXIF orientations 1..8 include mirrors.

Candidate validation verifies format/dimensions, container integrity and full pixel
decode, one image at a time, before streamed digest comparison. The adapter supports
at most 64,000,000 pixels, 256 MiB encoded bytes and 256 MiB of decoded image storage
per candidate; the encoded bound also limits container-chunk allocation. Validation does
not copy or re-encode images. Header-only/truncated images fail workspace publication,
cache reuse and orphan adoption even if their recorded digests match. Adapter version 2
invalidates recipes from the former rotation/timestamp semantics; contract 1 and valid
historical artifacts remain readable. Each new plan re-observes FFmpeg identity/version
before cache lookup, then pins it and refuses executable changes during materialization.
`frame_selection.fixed_fps` consumes candidate metadata without running FFmpeg and
publishes `views.selected_set` contract 1. It selects each photo once and applies an
independent exact-rational target grid to each clip, records target/actual time and
error, never duplicates a candidate, and copies no pixels.

M4 adds the explicit three-node `views.prepare_sharpest_interval` route without changing
the M3 route. `quality_assessment.pillow_edge_dhash` reads one published candidate image
at a time, verifies decoded dimensions, converts to 8-bit grayscale, optionally bounds
the maximum side with fixed Lanczos resampling, and publishes metadata-only
`views.quality_report` contract 1. `sharpness.edge_variance_8bit_v1` is the exact rational
variance of an implementation-defined 8-bit edge response after removing the filter
border; higher values mean more high-frequency content for this method, not a universal
physical blur scale. `duplicate.dhash64_v1` is a fixed-width 64-bit horizontal difference
hash measured from the same grayscale pixels. Unmeasurable views retain structured
unavailable reasons; missing, changed or corrupt candidate payloads remain integrity
failures rather than quality scores.

Measurement is separate from policy. QualityReport contains neither target FPS nor
sharpness/duplicate thresholds or selection decisions. `frame_selection.sharpest_interval`
uses source-local timelines anchored at each clip's first actual presentation time and
half-open intervals. It ranks by exact sharpness, earlier presentation time and stable
view ID, then tries ranked alternatives when a preferred candidate duplicates one of the
bounded recent accepted views from the same clip. Photos have no invented chronology and
are not duplicate-suppressed. The selected payload remains metadata-only and records one
typed decision per candidate plus empty/all-rejected interval diagnostics. Video routes
require configured candidate FPS of at least twice target FPS; photo-only routes do not.

Viewing is a consumer of artifacts, not an implicit processing stage. If generating
previews changes data, implement a separately fingerprinted conversion. A dataset
export is available without training; migrate the prototype `training.none` meaning
to an explicit dataset-only target without discarding saved user intent.

## View and camera rules

M12's optional desktop GUI is another client of these unchanged stage contracts.
Its explicit reconstruction action composes existing view/pair/feature/matching/
verification/mapping/validation services and their normal independent run IDs.
M9 selection remains a separate explicit decision; ambiguity publishes nothing.
M10/M11 consume explicit selection/dataset/checkpoint runs. Plan, progress, cancel,
recovery, cache and cleanup decisions stay in their existing application services.
Preview sampling is read-only display data and never a numerical pipeline artifact.
No whole-pipeline quality preset or production VPR claim is introduced. See [M12](M12.md).

Photos and decoded video frames enter the same view contract. Preserve original
filenames as metadata; generate filesystem-safe names from stable IDs. A frame's
identity includes its source, stream and actual presentation timestamp/frame identity,
not an assumed constant frame rate. Record rational time bases and orientation.
Mixed clips have separate timelines; a list of filenames is not a shared timeline.

M3 candidate recipe keys include selected source semantics, candidate FPS, encoding,
orientation policy and frozen FFmpeg binary identity. They exclude target FPS, source
locator spelling and project bookkeeping. Selection keys use the candidate semantic
digest and target FPS. Contract 1 retains target FPS even for photo-only metadata so
one recipe key cannot identify artifacts with different recorded resolved settings.
Consequently a target-FPS-only change reuses candidate pixels, while a candidate-FPS,
encoding, orientation, source-content or FFmpeg-identity change rebuilds them.

Decoding settings define available candidates. Fixed-FPS selection chooses from that
pool; sharpest-per-interval requires sufficient candidate density. A selector cannot
recover a frame never decoded: reject an undersampled request or require an explicit
candidate-pool change. Threshold-only changes reuse existing scores and pixels.
Adaptive selection may request a new explicit decoding plan; it cannot silently
expand an upstream artifact while downstream work is running.

Persist image dimensions and transforms so masks, keypoints and intrinsics refer to
the same pixels. Distortion models remain explicit. Undistortion for a trainer belongs
to DatasetPreparation and must update cameras and image references together.

Candidate storage must be budgeted before decoding: frame count, pixels, scratch and
retained output bytes. M3 starts with bounded materialized candidates, not every full
resolution frame by default. The contract may also carry exact source-frame locators
and analysis proxies for a later streaming/scoring route. Mark pixel availability
explicitly; before feature extraction publish materialized selected views using a
declared adapter operation with its decoding settings and source verification. Do not
introduce a generic lazy filesystem or promise reuse of pixels that were never retained.

Future virtual perspective views additionally describe parent capture, projection,
virtual intrinsics and relative orientation/rig information. Do not infer metric
baseline from multiple projections of one 360 capture.

## Reconstruction interchange

Each ReconstructionSet needs an adapter reader exposing component identity, view-to-
camera/pose mapping, image dimensions/transforms, projection model and parameters,
pose transform direction, axis/handedness, numeric ordering and coordinate-frame ID.
State scale units as known or unknown; include any applied similarity/alignment transform.
Sparse points/tracks are optional capabilities, not a universal prerequisite for SfM.
A dataset target states which records it requires and fails clearly when unavailable.

M8a component IDs are SplatForge UUIDv5 values derived from canonical registered-view
membership and remain stable across reruns with that membership. They do not identify
numerical geometry. A component digest covers the consumed cameras/poses/geometry and view
mapping; do not key datasets only by labels such as component 0 or image count.
M8a computes canonical camera/pose/count semantics, independent of native IDs/folder
numbering. Detailed point/track streaming is explicitly not_published. See [M8a](M8A.md).
Camera/GPS/LiDAR metadata must carry frame/units, timing and uncertainty where relevant;
convert explicitly or reject unsupported combinations. Add concrete schemas only when
implementing a consumer, not a universal sensor framework in M1a1.

## Method execution contract

Implement narrow typed stage interfaces rather than one untyped `execute(dict)` API.
A common execution context supplies run/attempt IDs, an owned workspace, cancellation,
structured events and resource limits. Input handles refer only to validated artifacts;
methods return candidate output manifests and diagnostics. The application validates
and publishes them through storage. Adapters do not mark their own attempts successful.

M6.5 supplies `StageProgressObservation` v1 and `PipelineProgressSnapshot` v1 for
backend-neutral work units, explicit stable work plans/revisions, phases and monotonic
elapsed evidence. Application computes throughput, ETA planning ranges/confidence and
duration-weighted pipeline progress; backend ETA is not authoritative. These diagnostics
and machine-local history never enter numerical recipes or artifact eligibility.
Unknown/phase-only totals do not imply whole-stage percentages. Cached/skipped stages
have zero remaining execution duration and never produce successful runtime samples.
The [development contract](DEVELOPMENT.md#progress-and-eta-foundation) freezes estimator,
history/privacy and throttling rules. SQLite status remains authoritative after crashes.

M7a extraction reports selected VIEWS/megapixels and observed feature counts; M7b matching
and verification use separate exact PAIRS work models. M8a exposes preparation, calibration,
native execution and validation phases. A later mapping milestone may parse
initialization, registration, triangulation, bundle-adjustment and finalization phases,
but nonlinear work must retain absent/phase-scoped percent and unavailable or wide
low/medium-confidence ETA. M11 uses completed/total steps, including checkpoint offsets.
M7a/M7b/M8a/M8b1/M8b2 and M11 use this boundary.

M1b1 implements one concrete deterministic route for contract testing:
`fake.sequence` consumes literal `start` plus resolved `count` and publishes
`fake.numbers`; `fake.scale` consumes that typed output plus resolved `factor` and
publishes `fake.scaled_numbers`. The first recipe key depends only on start/count and
declared method/adapter contracts. The second depends on factor and the consumed
numbers' semantic identity. Project label, path, revision and unrelated settings are
excluded. This route is ordinary Python composition, not a general plan language.

Each method declaration supplies:

- Stable method ID, method version, settings schema version and explicit defaults.
- Stage role, implementation/adapter identity and available checkpoint behavior.
- Consumed artifact formats/fields, optional inputs and compatibility requirements.
  Implement versioned dependency-key functions for concrete methods; do not add a
  reflection-based field-projection language or generic schema/graph compiler.
- Model/index digests, supported camera/descriptor variants and runtime requirements.
- Output contract, integrity validator, progress units and failure categories.

Keep stage settings independent. A preset is a versioned bundle of stage settings,
resolved into the project and run snapshot. "Balanced" alone is not a reproducible
recipe. Selecting an unavailable method produces a diagnostic; it never initiates
an unrequested download or a silent method change.

Compatibility validation must cover role, descriptor dtype/dimension/normalization,
keypoint convention, matcher weights, retrieval index/model, native format version,
camera model, trainer input format and device requirements. Equal descriptor dimensions
alone do not establish compatibility. Report all actionable plan errors before work.

## Local-feature extraction (M7a)

`features.extract` route 1 consumes exact candidate/selected contract-1 handles from
an explicitly requested successful Fixed-FPS or Sharpest views run. Validate selected
membership, then copy only its orientation-normalized published image bytes into an
owned attempt workspace with UUID filenames. Never read original source directories
or extract rejected candidates. Maximum image size is an explicit numerical setting;
there is no extra crop, rotation or re-encoding. Native COLMAP uses the existing M2
process boundary, executable verification, scoped environment, bounded diagnostics,
timeout, durable cancellation and process-tree teardown.

Settings v1 supplies SIFT, ALIKED_N16ROT/optional ALIKED_N32 and separate LOMA_B/LOMA_B128
routes: maximum features/image size, explicit CPU/GPU policy, learned minimum score and
LoMa resize policy. Reject unsupported backend options without substitution. BF16 is
deferred; LoMa uses explicit FP32. LoMa requires COLMAP >=4.2.1; compatible older
SIFT/ALIKED builds remain eligible. Tokens, version strings and model file presence
alone cannot establish learned support. Disposable inference must validate the exact
variant/device/model bytes and native descriptor schema. Successful inference can
positively establish ONNX runtime support when explicit build flags are absent.
No Python ML runtime or PyTorch is required in base SplatForge.

`features.local_feature_set` contract 1 publishes `features.json` (frozen
`LocalFeatureSet`), `backend_mapping.json` (private format/version/schema and exact
UUID-to-native-image-ID/name mapping) and self-contained `features.db`. The existing
manifest hashes all three. Public metadata includes selected artifact ID/digest,
method/version, typed numerical settings, model source/name/size/SHA-256, backend
numerical identity, descriptor signature, selected/feature totals and canonical per-view
summaries keyed by view UUID. Camera rows and backend IDs are private transport only;
M7b must assemble current camera assumptions in an independent database.

SIFT descriptors are 128 uint8 values; ALIKED are 128 float32 values; LOMA_B are
256 float32 values; LOMA_B128 are 128 float32 values. These four families remain
incompatible despite shared dimensions. Storage is row-major, float32 little-endian.
Keypoints use pixel-corner origin with first pixel center `(0.5, 0.5)`, in published
image dimensions even when the declared extraction size limit scales the input.
Native `descriptors.cols` counts bytes, not float dimensions. Typed native schemas must
match the selected extractor enum; legacy untyped databases are supported only for
fresh verified SIFT. Validate exact expected images, keypoint/descriptor presence,
counts/shapes/types, finite data, pixel bounds and empty match/geometry tables. Only the
owned attempt database is WAL-checkpointed and sealed after confirmed process teardown.
Published reads are immutable and create no sidecars.

Semantic identity streams every ordered keypoint/descriptor byte into per-view digests
in UUID order and includes numerical settings/signature/model/backend/input identity.
It excludes native IDs, insertion order, SQLite layout, timestamps and workspace paths.
Recipe v1 includes selected semantic identity, method/version/settings, model identity
and conservative backend identity (executable/version, schema and observed colocated
Windows DLL hashes). PairSet/matcher settings and private performance history are
excluded. Cache reuse revalidates manifest bytes, typed metadata and native content;
corrupt publications are refused and a new attempt can publish another immutable result.

Structural limits are MAX_VIEWS=100,000, 100,000 features/view, two learned models,
64 MiB public metadata, 32 MiB mapping metadata and 1 TiB database. Default execution
limits are 10,000 selected views, 100,000 source megapixels, 64 GiB workspace and 3600s.
Before launch estimate configured descriptor/keypoint storage, SQLite/index/journal
overhead, copied pixels and pinned model copies; enforce limits and current free disk.
This storage gate does not guarantee RAM/VRAM allocation. OOM fails without automatic
retry. Failed/cancelled/unresolved attempts never publish. Existing orphan validation
supports publication recovery; resume means stage restart, not checkpoint resume.

`features.selected_views_v1` uses exact selected VIEWS total with views/megapixels
workload. Verified COLMAP 4.2.1 logs provide bounded tolerant per-image evidence only
for expected UUIDs, extractor and bounded feature counts. Other formats leave observed
completion at zero until successful validation. Known total enables existing historical
ETA; elapsed time never advances completion. Performance signatures include method/
version/work model, settings key, runtime/executable/model digests and existing hardware
profile. Only a committed complete successful run teaches one private history sample.
Cached/failed/cancelled/interrupted/unresolved runs and Doctor do not teach history.
Event/history failures degrade diagnostics without affecting identity or publication.

Provision models explicitly. Replace backend URL defaults with copied, SHA-256-pinned
local files before numerical execution; explicit FP32 prevents fallback downloads.
Enforce backend-pinned expected hashes. Record source/name/hash provenance for later
installer-license review; permissive source licensing alone does not grant commercial
weight redistribution rights. SIFT is the baseline/fallback, ALIKED a learned route;
current SfM defaults remain unchanged. LoMa-R/L/G are M7b matchers. M7a adds
no matching, geometry or retrieval and leaves PairSet semantics unchanged.

References: [COLMAP database format](https://colmap.github.io/database.html),
[extractor types](https://colmap.github.io/features.html) and
[4.2.1 release](https://github.com/colmap/colmap/releases/tag/4.2.1).

## Pair selection and native execution

M7b consumes M6 PairSet through the verified explicit-pair `matches_importer` interface;
its backend never generates Sequential, Exhaustive, retrieval or spatial pairs.
`MatchSet` and `VerifiedGeometrySet` v1 are separate immutable artifacts/cache/restart
boundaries. Raw matching disables native verification and fixes its otherwise destructive
minimum-raw-count transport threshold to 1. Verification-only settings and camera priors
cannot invalidate raw matching. Every requested pair remains in public summaries,
including zero raw matches and rejected/insufficient geometry. Streaming per-pair
numerical hashing canonicalizes UUID direction and feature-index order independently
of SQLite/native-ID layout. Complete contracts are in [M7B.md](M7B.md).

Simple profiles resolve `auto` before execution: try route-specific GPU inference,
then positively supported CPU inference for the same technology candidate, then the
next candidate. Advanced `auto` resolves device only for its explicit methods. Explicit
CPU/GPU requests fail if unavailable. Every device assessment and final concrete device
is typed provenance; runtime failure cannot trigger device or technology fallback.
Local model arguments must be absolute paths to observed, SHA-pinned bytes. Native
URL/default download resolution is never used. Missing/reference-mismatching models
fail planning, with paths, expected SHA where known and manual rerun instructions.

M6 implements `pair_selection.sequential` and `pair_selection.exhaustive` version 1.
Both consume a published CandidateViewSet and either Fixed-FPS or Sharpest SelectedViewSet
from an explicitly requested successful views run. They read metadata and validate
published byte integrity without decoding candidate pixels, rereading originals, running
FFmpeg/COLMAP or requiring local features, retrieval embeddings or a GPU.

Sequential uses independent video timelines identified by
`(source_id, source_revision, selected_visual_stream_index)`. A source group may contain
several clips and is never a chronology. Sort by exact presentation time, occurrence
index, then unsigned 128-bit UUID integer. Equal timestamps retain distinct observations.
For each observation visit the next `forward_neighbors` observations (default 5, range
1..1000), optionally excluding deltas above exact non-negative `max_time_gap` seconds.
Complexity is sorting plus O(N * forward_neighbors). Photos have no chronology and stay
isolated unless explicitly connected. A graph with zero edges is refused with guidance
to use Exhaustive or explicit pairs. The default window is a development choice.

Exhaustive pairing estimates `N * (N - 1) / 2` pairs before materialization and enforces
a configured budget before constructing any edges. It treats all selected photos/videos
uniformly without a dense matrix, truncation or sampling. Both methods merge explicit
unordered selected-view pairs, including cross-source/group edges. Reversed duplicates
canonicalize; self-pairs, unknown IDs and malformed inputs fail. Explicit pairs count
towards the same total budget. `max_pairs` defaults to 100,000 for development; a cached
result must also fit the requested budget.

`pairs.pair_set` contract 1 publishes only `pair_set.json` and `manifest.json`. Its v1
immutable PairingViewUniverse contains only selected view IDs, media/source/revision/
stream/group/camera identities, occurrence indices and exact PTS/time bases (absent for
photos). It validates each selected observation against CandidateViewSet. Projection
identity excludes image bytes/digests, paths, source locators, quality scores, rejection
records, thresholds and project/run/publication bookkeeping. Selection policy changes
with identical selected membership and chronology preserve this pairing input identity.

Endpoints use `left_view_id.int < right_view_id.int` (unsigned UUID integer order).
Pair identity v1 is UUIDv5 in namespace `35a55597-1ab8-5bd4-9a56-82075e175da3` of
`1:<left-uuid>:<right-uuid>` using lowercase hyphenated UUIDs. It excludes method/reasons.
Pairs sort by endpoints. Typed reason records sort by unique kind: sequential timeline,
neighbor offset and exact time delta; exhaustive enumeration; explicit supplied pair.
Deduplication preserves all applicable reasons. M7c adds actual retrieval rank/score
evidence through its explicit offline representation route; no placeholder scores.

PairSet semantic identity v1 hashes the canonical universe digest and ordered pair IDs
with the semantic/contract versions. Settings, reasons, coverage, warnings, artifact UUIDs
and timestamps do not affect downstream graph compatibility. The full payload retains
exact CandidateViewSet and SelectedViewSet IDs/digests, selected method, universe digest,
resolved settings and reasons. The manifest binds both exact upstream handles.

Separate Sequential/Exhaustive recipe helpers include fingerprint version 1, PairSet
contract 1, method/settings versions, resolved settings, universe digest and canonical
explicit pairs. They exclude `max_pairs` (an eligibility gate) and irrelevant upstream
policy. A hit retains its original producer lineage; the new immutable run route freezes
its own exact upstream handles. Equal graphs from different recipes can have equal
semantic digests while their recipe keys differ.

Structural bounds are 100,000 selected views, 1,000,000 sparse pairs, four reasons per
pair, 100,000 entries per coverage collection, three warning codes and 768 MiB of compact
UTF-8 PairSet metadata. This accommodates roughly 20k views with tens of neighbors;
it is a bounded JSON contract, not a production memory/performance guarantee. The
application default is substantially lower. Validation recomputes IDs, canonical order,
universe/graph digests, reason chronology and all coverage counts.

Coverage records selected/paired/isolated observations, components and descending
component sizes, within-source/cross-source/cross-group pair totals and per-source/group
selected/paired/internal/cross counts. Cross counts are incident counts in each group;
each cross edge contributes once to each endpoint group. Deterministic diagnostics flag
isolated photos, disconnected candidate graphs and video timelines without a direct
cross-timeline edge. These are candidate-graph observations, not reconstruction results.

M7c adds practical cross-clip retrieval/hybrid pairing and is required for
the complete multi-video CLI: Sequential within clips plus bounded retrieved neighbors
across clips. Manual pairs and exhaustive matching remain optional diagnostic tools.
Warn when a requested whole-scene graph has isolated clips or photos;
never promise that candidate connectivity guarantees reconstruction connectivity.

M7c's neutral offline representation/hybrid implementation is documented in
[M7C.md](M7C.md); production VPR inference/selection and representative quality remain
pending as recorded in the [candidate ledger](M7C_BENCHMARK.md). M7b has no retrieval
model dependency. The exact CPU reference route is bounded and independent of local
features; no PyTorch/FAISS is added to base dependencies.

M7c must benchmark modern retrieval/hybrid options rather than treating Vocabulary Tree
as a final solution. No final neural model is selected in M6. Evaluate real drone/phone
video, mixed clips, unordered photos, indoor/outdoor, repeated texture, weak overlap and
large viewpoint changes. Compare useful geometrically verified pairs, graph coverage,
registration coverage, runtime, VRAM/RAM, descriptor/index size and pair count as well as
Recall@K. Weight/model licensing and commercial redistribution feasibility are selection
criteria alongside quality. M6 adds no ML dependency or model weights.

The neutral retrieval implementation has an explicit representation contract: embedding/aggregation method and
version, weights digest, image preprocessing, descriptor dimensions/normalization,
indexed view IDs and corpus digest, distance metric, index format/version/settings,
query limits and deterministic tie handling. The corpus identity covers actual view
pixels/transforms and source-group membership, not just its filenames/count. Cache its representation/index artifacts
separately where supported. ALIKED local descriptors alone do not establish retrieval
compatibility; any local-feature aggregation needs its own validated representation.

Bound cross-clip neighbors and total candidate pairs, merge/deduplicate with Sequential
pairs, and retain provenance and per-group coverage. Measure retrieval time/memory as
well as matching pair count; a small PairSet does not prove cheap index/query work.
Test known overlapping clip regions and verified matches rather than only output size.
Also test non-overlapping clips, near-duplicate bursts and group/temporal diversity so
one easy overlap does not hide disconnected coverage. Embeddings/indexes are immutable;
adding a clip produces a new corpus/index identity. Initial retrieval must not depend
on the reconstruction it is meant to enable. Pose-assisted refinement is a subsequent
explicit pass consuming a previous result, never a cycle in the same plan.
GPS/spatial pairing consumes coordinates with frame, units and uncertainty in M13a;
missing GPS is not zero. Advanced retrieval optimization also remains in M13a.

A native COLMAP command may combine pair selection, matching and verification. The
adapter must preserve the declared PairSet, either through a verified pair-import
route or a tested equivalent. If it cannot, mark that combination unsupported or
expose the native operation as an explicitly coupled execution unit. Coupling must
be visible in the plan, settings and cache behavior; UI/core boundaries stay separate.
Do not promise independent verification reuse for a fused backend operation.

## Reconstruction component selection

After Mapping and ReconstructionValidation, the application publishes an immutable
ReconstructionSelection decision artifact. This is a small typed decision/policy
function, not a new scheduler or plugin framework. Use the existing artifact manifest
and attempt/publication machinery. DatasetPreparation requires it.
The original ReconstructionSet and ValidationReport remain unchanged.

Record the referenced reconstruction artifact, stable component IDs, manual versus
policy selection, policy ID/version/resolved settings when applicable, chosen IDs,
excluded-component reasons and report/metric evidence used. Manual choices are saved
explicitly. A configured policy may select the only component or apply stated quality
criteria, but must record its decision; no implicit largest-component default exists.
Missing, empty or obsolete selections block preparation with a diagnostic. A new
ReconstructionSet requires selection revalidation, never unchecked component-ID reuse.

Fingerprint the selection decision from the set identity, explicit choices or policy
settings and metric values actually consumed. Dataset keys use the selected components'
content digests, view/camera data and material preparation settings, not a run-specific
artifact UUID or component label alone. Keep exact set/artifact IDs and full decision
provenance in lineage; conservative payload-based invalidation remains valid. A policy/report change re-evaluates selection. If chosen data and preparation
settings are unchanged, reuse the existing dataset after its gate passes. If a report
is only an eligibility gate, it does not enter the numerical dataset key. Manual
selection does not override a failed quality gate; overrides are separately recorded.
Reports distinguish per-component quality from whole-project coverage. A configured
gate states its scope: rejecting another component need not fail a valid selected one,
but a whole-scene coverage requirement still applies. Bind overrides to the exact
report, selected content and gate policy; a new reconstruction cannot inherit one.

Selecting several disconnected components creates separate datasets with explicit
component-to-output mapping. Do not concatenate unrelated coordinate frames. A future
aligned union needs an explicit alignment artifact and its own validation. Validation
continues to report all components, including excluded ones, to preserve coverage context.

## Stage fingerprints and cache eligibility

Operation-scoped validation memoization, provenance write strategy and optional process
diagnostics do not enter numerical fingerprints. Validation strength, memo contents,
hash-pass counts, diagnostics paths/output/duration/truncation do not change recipe
keys or semantic digests. Source assurance and publication eligibility remain separate
gates; a later application operation revalidates immutable upstream byte integrity.

A stage recipe key is a cryptographic digest of a versioned canonical representation:

```text
fingerprint schema version + stage contract version
+ method ID/version + settings schema version + resolved stage settings
+ adapter/backend identity + output-affecting runtime/device policy
+ model/index/weight digests + seed/determinism policy
+ consumed input semantic identities/digests + explicit absent optional inputs
```

Canonicalize object keys, ordered versus unordered collections, numbers, enums and
relative logical paths. Reject non-finite numeric settings. Include resolved defaults;
do not depend on dictionary insertion order, Python object hashes or a preset label.
Exclude display labels, project location, run/attempt IDs, bookkeeping timestamps
and log paths. Capture timestamps, video time bases, stream/frame identities and
ordering are semantic inputs wherever selection, pairing or synchronization uses them.
Record the full environment for diagnosis, but hash only declared output-affecting
parts; for a new backend use a conservative identity until narrower reuse is tested.
Resolve automatic choices before keying the attempt: actual backend/environment,
model, device policy, defaults and seeds. Include implementation revision and tested
native/library identity, not just a display version. Never change such choices inside
an attempt. Unknown settings fail validation rather than disappearing from the key.

Input identity consists of consumed content digests, contract/format identity and
declared metadata projections, not an absolute path or mere modification time. Retain
upstream recipe keys in lineage; include them in a consumer key where they affect
input interpretation. A semantic projection excludes incidental publication timestamps
and fields the consumer does not use. Separate pixel, camera and chronology metadata
dependencies where the contracts require independent reuse. Within a declared
dependency, start with whole-artifact caching; finer per-view/per-pair reuse is an
optimization requiring tests. If the contract consumes complete producer provenance,
a recipe change may conservatively rerun consumers even when payload bytes match.

Distinguish data dependencies from eligibility gates. A validation report that only
authorizes execution is checked and recorded for the run but is not hashed into a
consumer's numerical recipe. If a method actually consumes report values to alter its
output, those values are a data dependency and must be fingerprinted.

A recipe key may have several executions with different numerical results. Published
artifacts have separate immutable IDs and content digests. A run records consumed artifact IDs through its attempt records. Frozen plans refer to
future outputs by node/output reference; attempts bind those to real artifact IDs
before execution without rewriting the run snapshot. Never overwrite an older result just because its recipe
key matches. Reuse requires a successful publication, compatible contracts and
verified required files/checksums; interrupted workspaces are not cache hits. Validators
are versioned too: revalidate when the integrity contract changes even if numerical
settings do not. Record which check ran; cached success is not perpetual certification.

Source digest identity and current verification assurance are separate. Cache keys
continue to use content identities; the run records whether a digest was freshly
verified or accepted under Balanced/local metadata evidence. Apply the requested
verification policy before reuse and report uncertainty/change diagnostics; policy
changes alone do not alter numerical keys when the same content is established.
See [verification policies](PROJECT_FORMAT.md#source-verification-policies).

## Invalidation examples

These rules assume separate stages; a declared coupled execution unit invalidates
as a unit. Re-evaluate affected descendants only, and preserve unchanged branches.

| Change | Recompute or re-evaluate | Reuse |
| --- | --- | --- |
| Trainer iterations, loss, densification or seed | Training and consuming scene exports | Views, features, pairs, SfM, validation, prepared dataset |
| Dataset undistortion, resize or target layout | DatasetPreparation, training and dataset/scene exports | SfM and reconstruction validation |
| Reconstruction validation thresholds | Report, metric-dependent component selection and downstream gates | Reconstruction and datasets/training whose selected data remain identical and pass the gate |
| Selected reconstruction components or selection policy | ReconstructionSelection and affected datasets/training/exports | Mapping and validation; dataset reuse when selected data/settings remain identical |
| Mapper method/settings | Mapping and consumers | Features, PairSet, matches and verified geometry |
| Geometric verification thresholds | Verification, mapping and consumers | Raw matches and earlier artifacts, if separable |
| Matcher weights/settings | Matching and consumers | Features and PairSet |
| Sequential overlap/window | PairSet, matching and consumers | Features and selected views |
| Retrieval representation/model or corpus | Retrieval artifacts, dependent PairSets, matching and consumers | Local features when independently computed |
| Retrieval neighbor budget or query policy | PairSet, matching and consumers | Compatible retrieval representations/index and local features |
| Feature extractor/model/settings | Features, matching and consumers; retrieval only if it consumes these features | Views and feature-independent PairSets |
| SfM mask | Features and consumers; mask-aware retrieval if declared | Decoded views and unrelated pair selection |
| Training-only mask | DatasetPreparation/training according to declared use | SfM |
| Selection threshold using existing scores | Selection; PairSelection only if its selected-view projection changes | Candidate pixels, quality scores and PairSets with identical pairing universes |
| Sharpest target FPS with an explicitly unchanged candidate FPS | Sharpest selection and consumers | Candidate pixels and QualityReport |
| Duplicate threshold/lookback or minimum sharpness | Sharpest selection and consumers | Candidate pixels and QualityReport |
| Quality maximum side or quality method/backend version | QualityReport, sharpest selection and consumers | Candidate pixels |
| Candidate FPS for a quality-aware route | CandidateViewSet, QualityReport, selection and consumers | Unrelated independently materialized sources |
| Candidate sampling, crop, orientation or source content | Affected prepared views and descendants | Unrelated source branches when independently materialized |
| Source relocation with identical verified content | Locator validation only | All compatible artifacts |
| Stronger source verification policy, unchanged content | Verification/assurance gate; rebuild only provenance that cannot meet it | Compatible artifacts with sufficient source assurance |
| Camera calibration/prior or GPS update | Actual metadata consumers, downstream native-database assembly and descendants | Truly pixel-only features and unrelated pairing; rebuild current native camera records |
| Capture timestamps, time base or source/revision/stream timeline identity | Selection/pairing/synchronization consumers | Unaffected pixels and descriptors |
| UI preferences, project label or log verbosity | No numerical stage | All numerical artifacts |

A validation report is both evidence and a gate. Changing its policy re-evaluates
permission to continue and any metric-dependent component selection; if the selected
data are unchanged and the prepared dataset passes its gate, existing training need
not be rerun. A failed gate blocks new downstream execution unless an explicit override
is recorded. It never erases historical results.

Reproducibility records explain cache misses and numerical limits. Nondeterministic
backends must declare that limitation; a cache hit reuses a specific prior result,
not a promise that repeating the computation will produce identical bytes.


## M8a implemented mapping contract

The classical route consumes exact M7b accepted geometry plus actual camera/share/dimension
and indexed x/y keypoint state, not the whole verifier ancestry. MappingInput v1 freezes
that minimal numerical projection; MappingRoute retains exact upstream handles separately.
COLMAP Global is implemented, requiring tested >=4.2.1 (currently positively tested
4.2.1). Multiple models is forced true with explicit minimum size. Private DB copying,
optional explicit view-graph calibration and Global execution preserve all valid models.
ReconstructionSet v1 is neutral; the M7-specific receipt is separate so future direct
geometry need not fabricate M7 artifacts. Reader contracts own M9/M10 interchange.
Coordinate convention is right-handed camera_from_world, x right/y down/z forward,
wxyz quaternion and pixel centers at (.5,.5); scale is unknown_arbitrary. No component
is selected. Full identities, optional-record states, settings, cache and failure contracts
are in [M8A.md](M8A.md). M9 and M10 consume it downstream as described below.
The M7c production benchmark is independent.

M8b1 adds explicit Incremental Ceres CPU / capability-gated Caspar BA, consuming the same
MappingInput. `multiple_models=false` and `extract_colors=false` are fixed; exactly one
valid model becomes one component and every unregistered input view stays explicit.
Native overlapping hypotheses cannot be represented as disjoint components, so any
multiple-model output fails. Incremental uses verified cameras directly, without Global's
optional calibration, and reuses the same private DB/publication/Reader boundary.
Caspar requires compiled support, a concrete validated CUDA device, PINHOLE/SIMPLE_RADIAL
input and compatible refinement settings; no mapper/BA fallback occurs. No portable
ReconstructionSet semantics change. See [M8b1](M8B1.md).

M8b2 Hierarchical starts from the same M7 projection, uses overlapping internal clusters,
Incremental cluster reconstruction and one native Hierarchical merge process. Internal
clusters are never public components. Preserve all valid disjoint final models; fail final
overlap without selection, deduplication or custom merge. Explicit Global acceleration
keeps mapping.colmap_global and separates GP GPU from Ceres BA GPU, with concrete
device/runtime identity, bounded positive evidence and CPU-fallback refusal. Old Global
v1 snapshots/recipes remain unchanged. Comparison runs normal M8 routes sequentially
from the same M7 artifact; report metadata never enters numerical mapping identities.
No automatic mapper fallback, quality score or universal recommendation is introduced.
See [M8b2](M8B2.md). Technical M8 is complete; representative recommendation is pending.

## M9 measurement and policy boundary

The exact selected-view universe comes from validated immutable reconstruction/M7 lineage,
including source, source group, camera group and media type. It must match every M8 input
view UUID, including unregistered views. All registration fractions retain this denominator.
M9 adds its own canonical detailed geometry identity without changing ReconstructionSet v1.
Coordinates, tracks and actual 2D observations affect measurements; native IDs/layout do not.

Geometry canonicalization and numerical measurement use normal independent stages/cache.
ReconstructionMetrics v1 contains factual whole/component/source/source-group coverage,
fragmentation, camera plausibility and optional sparse evidence. Detailed values are exact,
sampled with method/count/population, or unavailable with a bounded reason. Unknown is never
zero/pass. Native summary text is not the canonical numerical representation.
MeasurementSettings freezes bounded sampling; refusal-only resources and history do not
change numerical settings. Baseline/custom policy evaluates these immutable measurements
into ReconstructionValidationReport v1 with structured scoped issues and deterministic IDs.
Threshold changes reuse measurements; policy/selection/M10 never re-key M8.
See [M9 methods, thresholds, availability and CLI](M9.md).

M9b implements ReconstructionSelection v1 with manual one/multiple components or explicit
selection.dominance_v1. Automatic comparisons require no-worse registration/every source
group/validation severity and strict improvement against each alternative. Tradeoffs,
ties or missing required comparison evidence return ambiguity without a selected artifact.
Applicable project-wide/component/source-group failures require exact issue IDs and reason,
bound to reconstruction, detailed geometry, report and canonical selected content. A global
failure survives deselection. Warnings remain visible. Selection recipes include decision
evidence; numerical downstream semantics exclude policy/reasons/artifact UUIDs and include
selected camera/pose/detailed sparse content. Same component ID with changed content is stale.
M10 emits separate datasets for multiple selected unaligned components.

## M10 dataset preparation

`dataset.colmap_undistorted_v1` consumes the explicit selection and exact historical
materialized pixels, never original source media. Plan and execution call M9's current
selection/override checks. Each selected component gets its own immutable conventional
COLMAP dataset (`images/`, `sparse/0/`, `dataset.json`); the final DatasetSet references
component artifacts. M10 makes no automatic largest choice or coordinate merge and
does not execute training; [M11](M11.md) consumes each component separately.

The component recipe uses exact M8/M9 selected numerical content, consumed pixel hashes,
settings and pinned undistorter runtime. Report/reason/pairing provenance and non-binding
resources do not invalidate numerical preparation. Separate components cache independently.
Native undistortion/resizing transforms cameras/pixels/observations together; only flat
PINHOLE/SIMPLE_PINHOLE outputs pass the independent consumer. Poses and XYZ/public track
membership remain equivalent to M8; scale stays unknown_arbitrary. Publication, recovery,
cache and cancellation retain the existing lifecycle. See [M10](M10.md) for frozen defaults,
numerical tolerances, resources, progress, cleanup and real integration instructions.

Technical preparation accepts any valid explicit selection. Production automatic
multi-video E2E acceptance still requires the unresolved M7c production VPR route;
reference Exhaustive success is not that acceptance.
