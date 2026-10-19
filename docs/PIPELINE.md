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
| FeatureExtraction | Selected pixels, optional SfM masks, method/model settings | FeatureSet: view/keypoint correspondence, descriptor signature, coordinate convention and payload format |
| PairSelection | Selected view IDs and the chronology, retrieval or spatial inputs actually used | PairSet: canonical unordered pairs, no self/duplicate pairs, coverage statistics, selection reasons |
| FeatureMatching | FeatureSet and PairSet | MatchSet: valid feature indices, counts/confidence, descriptor and matcher identities |
| GeometricVerification | MatchSet, keypoints and camera assumptions | VerifiedGeometry: inliers, pair models/relative constraints, rejection reasons and convention metadata |
| Mapping | Verified geometry, views, cameras and optional declared priors | ReconstructionSet: all components, camera/pose/point metadata, native payloads, ID mappings and coordinate frames |
| ReconstructionValidation | ReconstructionSet and relevant views/observations | ValidationReport: metrics, warnings, missing measurements, policy result and component coverage; no model mutation |
| DatasetPreparation | Selected reconstruction components, views, validation gate and target input format | TrainingDataset: images, cameras/poses, sparse points where required, masks if used, units/transforms and conversion manifest |
| Training | TrainingDataset, trainer settings and optional compatible checkpoint | TrainingResult: scene payload, metrics, logs and checkpoints with recipe provenance |
| Export | Explicit dataset or training result, format/settings | ExportManifest: output files, consumer/format versions, checksums and any lossy conversion |

MediaIngest publishes versioned project input inventories through the project-save
protocol; subsequent stages publish derived artifacts through the attempt-publication
protocol. Both protocols are defined in PROJECT_FORMAT.md.

Viewing is a consumer of artifacts, not an implicit processing stage. If generating
previews changes data, implement a separately fingerprinted conversion. A dataset
export is available without training; migrate the prototype `training.none` meaning
to an explicit dataset-only target without discarding saved user intent.

## View and camera rules

Photos and decoded video frames enter the same view contract. Preserve original
filenames as metadata; generate filesystem-safe names from stable IDs. A frame's
identity includes its source, stream and actual presentation timestamp/frame identity,
not an assumed constant frame rate. Record rational time bases and orientation.
Mixed clips have separate timelines; a list of filenames is not a shared timeline.

Decoding settings define available candidates. Fixed-FPS selection chooses from that
pool; sharpest-per-interval requires sufficient candidate density. A selector cannot
recover a frame never decoded: reject an undersampled request or require an explicit
candidate-pool change. Threshold-only changes reuse existing scores and pixels.
Adaptive selection may request a new explicit decoding plan; it cannot silently
expand an upstream artifact while downstream work is running.

Persist image dimensions and transforms so masks, keypoints and intrinsics refer to
the same pixels. Distortion models remain explicit. Undistortion for a trainer belongs
to DatasetPreparation and must update cameras and image references together.

Future virtual perspective views additionally describe parent capture, projection,
virtual intrinsics and relative orientation/rig information. Do not infer metric
baseline from multiple projections of one 360 capture.

## Method execution contract

Implement narrow typed stage interfaces rather than one untyped `execute(dict)` API.
A common execution context supplies run/attempt IDs, an owned workspace, cancellation,
structured events and resource limits. Input handles refer only to validated artifacts;
methods return candidate output manifests and diagnostics. The application validates
and publishes them through storage. Adapters do not mark their own attempts successful.

Each method declaration supplies:

- Stable method ID, method version, settings schema version and explicit defaults.
- Stage role, implementation/adapter identity and available checkpoint behavior.
- Consumed artifact formats/fields, optional inputs and compatibility requirements.
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

## Pair selection and native execution

Sequential pairing operates within a source group by timestamp or explicit order.
Exhaustive pairing estimates `N * (N - 1) / 2` pairs before materialization and enforces
a configured budget. For multiple clips, explicitly include cross-clip pairs through
bounded exhaustive/manual policies initially and retrieval/hybrid strategies later.
Warn or block when a requested whole-scene plan has no cross-group candidate edges;
never promise that candidate connectivity guarantees reconstruction connectivity.

Retrieval may depend on local features or separate image embeddings. Spatial pairing
consumes coordinates with a known frame, units and uncertainty. Missing GPS must not
be interpreted as zero. Hybrid policies merge/deduplicate PairSets with provenance.

A native COLMAP command may combine pair selection, matching and verification. The
adapter must preserve the declared PairSet, either through a verified pair-import
route or a tested equivalent. If it cannot, mark that combination unsupported or
expose the native operation as an explicitly coupled execution unit. Coupling must
be visible in the plan, settings and cache behavior; UI/core boundaries stay separate.
Do not promise independent verification reuse for a fused backend operation.

## Stage fingerprints and cache eligibility

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
Exclude display labels, project location, run/attempt IDs, timestamps and log paths.
Record the full environment for diagnosis, but hash only declared output-affecting
parts; for a new backend use a conservative identity until narrower reuse is tested.

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
artifacts have separate immutable IDs and content digests. A run pins the actual
artifact IDs it consumed. Never overwrite an older result just because its recipe
key matches. Reuse requires a successful publication, compatible contracts and
verified required files/checksums; interrupted workspaces are not cache hits.

## Invalidation examples

These rules assume separate stages; a declared coupled execution unit invalidates
as a unit. Re-evaluate affected descendants only, and preserve unchanged branches.

| Change | Recompute or re-evaluate | Reuse |
| --- | --- | --- |
| Trainer iterations, loss, densification or seed | Training and consuming scene exports | Views, features, pairs, SfM, validation, prepared dataset |
| Dataset undistortion, resize or target layout | DatasetPreparation, training and dataset/scene exports | SfM and reconstruction validation |
| Reconstruction validation thresholds | Report and downstream eligibility gates | Reconstruction and payloads whose inputs remain identical |
| Mapper method/settings | Mapping and consumers | Features, PairSet, matches and verified geometry |
| Geometric verification thresholds | Verification, mapping and consumers | Raw matches and earlier artifacts, if separable |
| Matcher weights/settings | Matching and consumers | Features and PairSet |
| Sequential overlap/window | PairSet, matching and consumers | Features and selected views |
| Feature extractor/model/settings | Features, matching and consumers; retrieval only if it consumes these features | Views and feature-independent PairSets |
| SfM mask | Features and consumers; mask-aware retrieval if declared | Decoded views and unrelated pair selection |
| Training-only mask | DatasetPreparation/training according to declared use | SfM |
| Selection threshold using existing scores | Selection and its dependent stages under the conservative stage cache | Candidate pixels and quality scores |
| Candidate sampling, crop, orientation or source content | Affected prepared views and descendants | Unrelated source branches when independently materialized |
| Source relocation with identical verified content | Locator validation only | All compatible artifacts |
| Camera calibration/prior or GPS update | Only stages consuming the changed metadata and their descendants | Pixel-only stages and unrelated pairing policies |
| UI preferences, project label or log verbosity | No numerical stage | All numerical artifacts |

A validation report is both evidence and a gate. Changing its policy re-evaluates
permission to continue; if it passes on the same reconstruction and prepared dataset,
existing training need not be rerun. A failed gate blocks new downstream execution
unless an explicit override is recorded. It never erases historical results.

Reproducibility records explain cache misses and numerical limits. Nondeterministic
backends must declare that limitation; a cache hit reuses a specific prior result,
not a promise that repeating the computation will produce identical bytes.
