# M8a reconstruction foundation and COLMAP Global Mapper

M8a implements the classical `VerifiedGeometrySet -> private DB -> optional explicit
view-graph calibration -> Global Mapper -> all components -> ReconstructionSet`
route. M9/M10 consume `ReconstructionReader`, never COLMAP files directly. This is
structural validation and immutable transport, not M9 reconstruction-quality validation
or M9b component selection. [M8b1](M8B1.md) now adds explicit single-model Incremental
Ceres and capability-gated Caspar BA through these unchanged portable contracts.
[M8b2](M8B2.md) adds Hierarchical, explicit Global GPU gates and comparison infrastructure. Caspar is not a mapper.
M7c's representative production VPR benchmark is pending independently. [M9](M9.md) now
implements downstream validation/selection; M10 has not started. No training, GUI,
dense/MVS/mesh or direct-geometry route is implemented.

## Supported backend and explicit settings

The production floor is COLMAP >=4.2.1. The currently positively tested version is
4.2.1, commit `bd1fcf6`, executable SHA-256
`9418a14c93d4a5eec5eb33ebf48a917403b5faa7ab5d2232f23e50c206d9e427`.
4.2.0 is refused because 4.2.1 fixes the Global Mapper BA/triangulation-outlier camera
regression. Later versions are refused until positive integration validation adds
them to the supported version policy; a higher version string is insufficient.
No standalone GLOMAP, new native runner or Python native/ML dependency is added.

Installed executable help was inspected before implementation. The supported command
is `global_mapper --database_path ... --image_path ... --output_path ...`.
The output directory must exist. COLMAP writes numeric model directories plus
`project.ini`; every model is read and preserved. Native model order is provenance.
The input image directory is an owned empty attempt directory: M8a reconstructs
geometry from database keypoints/constraints, does not consume source pixels or
claim measured sparse colors. COLMAP may log missing color-image warnings. Native
point colors are not published portable semantics. Originals are never reopened.

`GlobalMapperSettings` v1 intentionally exposes/fixes this numerical subset:

| Setting | Resolved default |
| --- | --- |
| `min_num_matches` | 15 |
| `num_threads` / `random_seed` | 1 / 0 |
| `multiple_models` | true, cannot be disabled in this route |
| `min_model_size` | 3 registered frames; current inputs have one frame per view |
| `ba_num_iterations` | 3 |
| `gp_max_num_iterations` | 100 |
| `ba_ceres_max_num_iterations` | 200 |
| `ba_refine_focal_length` / `ba_refine_principal_point` / `ba_refine_extra_params` | true / false / true |
| `gp_use_gpu` / `ba_ceres_use_gpu` / `ba_backend` | false / false / CERES |

Global and default random seed are supplied explicitly. Other native numerical
settings (including relative-pose decomposition, rotation averaging, track and
triangulation controls) depend on exact frozen executable/DLL bytes. They are not
claimed to be cross-version portable defaults. No raw backend flags are accepted.
Disconnected valid components meeting the explicit minimum are retained independently.
An output component below that minimum is refused rather than quietly discarded by
SplatForge. Zero models, malformed models and overlapping Global memberships fail.
There is no model-0/largest/first selection and no alternate-mapper or settings fallback.

Doctor keeps command presence, supported version, required typed options, optional
calibrator support, exact native identity, schema/runtime evidence and real integration
validation separate. Help/schema evidence does not certify reconstruction quality or
an integration run: `colmap.mapper.global.integration` remains explicitly unknown in
Doctor. Actual successful stage diagnostics and opt-in integration provide execution
evidence. M8a implemented Global; M8b1 separately adds Incremental. M8b2 separately implements Hierarchical with final-membership validation.

## Numerical input and recipe

`MappingInput` v1 is a canonical projection of the exact published M7b database:

- Canonical selected SplatForge view UUIDs and their bijective native image/name mapping.
  Native ID/name spelling is adapter transport; the public digest uses UUIDs.
- Perspective camera model, dimensions, parameters, focal-prior status and actual
  camera-sharing partition. Current M7b independent single-sensor rig/one-view-frame
  transport is validated. Nontrivial rigs/pose priors require a future explicit route.
- Keypoint row count and float32 x/y coordinates in feature-index order, streamed
  from bounded SQLite blobs and encoded canonically. Scale/orientation/affine columns
  that mapping does not consume are excluded.
- Only M7b accepted verified edges; canonical endpoint UUIDs, inlier feature-index
  correspondences, configuration, F/E/H, optional relative pose and per-pair estimated
  cameras. Native reversed endpoints invert numerical geometry before hashing.

Rejected edges are removed from the private input. Descriptor bytes, rejected/raw
matches, MatchSet ancestry, verification thresholds themselves, feature/matcher
recipes, profile labels, timestamps, paths, SQLite page layout and incidental native
IDs are not numerical mapping dependencies. Full upstream integrity still validates
all published bytes before use. `VerifiedGeometrySet.semantic_digest` alone is not
the mapping key: it also includes producer settings/ancestry that mapping does not read.

`MappingRoute` in RunSnapshot schema 1 freezes the exact verification handle/run,
MappingInput, Global settings, calibration policy/settings, backend identity, refusal
limits, reservation and expected ReconstructionSet contract. No state/project migration
or generic DAG engine is introduced. Recipe identity hashes mapping-input digest,
method/settings versions, exact mapper settings, explicit calibration and backend
executable/runtime identity. Resource gates, progress/history, duration, paths and
artifact IDs are excluded.

| Change | Reuse | Recompute |
| --- | --- | --- |
| Mapper settings / seed | All M7 artifacts | M8 |
| Calibration policy/settings | All M7 artifacts | M8 |
| Non-binding resource limits / ETA history | Same numerical M8 cache and M7 | Nothing numerical |
| Verified numerical geometry / consumed x/y / camera state | Unchanged upstream branches | M8 and future consumers |
| M9 policy | M8 and unchanged M9 measurements | Report/selection only |

A verification-threshold change reruns verification. Mapping invalidates when its
consumed numerical projection changes; provenance-only changes with identical mapper
input do not defeat cache reuse. A cache hit retains its original producer lineage;
the new run freezes its own exact input handle.

## Calibration and isolation

`preserve_priors` is the conservative default and never invokes a calibrator.
`view_graph` must be explicitly requested and positively supported. There is no
phone/drone/EXIF/scene classifier. Calibration is an estimator, not ground truth.

The verified database is copied by pinned-byte streaming into a fresh attempt;
same-file copies, writable hardlinks and redirects are refused. Raw matches and
descriptors are removed from that independent copy. Its complete numerical projection
must match the frozen input before launch. `view_graph_calibrator` modifies only that
copy, then finite camera/geometry state, keypoints and universe are revalidated.
Calibration failure fails the attempt, without preserve-priors fallback. A sealed
post-calibration/pre-mapper snapshot is published as `mapping.db`; Global runs against
the separate private work database. No M7 database is ever supplied writable.

Calibration settings v1 explicitly resolve native help defaults: cross-validate priors
true; calibrated-pair ratio .5; relative-pose re-estimation true; focal ratio .1..10;
calibration error 2; relative-pose error 1; minimum inliers 30; ratio .25; seed 0.
The receipt preserves policy, method/version/settings, backend identity, camera-state
digests before/after, full numerical MappingInput after and a deterministic result
digest. `input_cameras.json` preserves original priors separately from calibrated
`mapping.db` and final optimized sparse intrinsics. There is no learned calibration.

Disk refusal gates cover view/verified-pair/keypoint/inlier counts, source DB size,
private copy/journal reservation, sparse output bound, total workspace and timeout.
Reservation uses known record-volume estimates, including the disk-backed validation
index; host peak memory is not predicted. Native workspace and validation-index growth
are bounded. Validation checks scratch-volume free space and supports owner cancellation
checkpoints; these refusal/telemetry gates never enter numerical identities. Resource failure never silently changes settings.

## ReconstructionSet and reader v1

The immutable backend-neutral `mapping.reconstruction_set` metadata contains contract,
producing method/version, exact resolved settings/version, numerical input digest,
upstream lineage, calibration evidence, backend/recipe identity, canonical components,
registered/unregistered UUID membership, conventions, native format and semantic digest.
The classical M7-specific `ClassicalMappingReceipt` lives separately in `mapping.json`;
a future direct backend need not fabricate features, matches or verified geometry.
Large numerical arrays stay in adapter-owned native payloads.

A component has a versioned SplatForge UUIDv5 over sorted registered view UUID membership,
component numerical digest, membership/counts, camera count, measured native point count,
optional-record availability, relative payload locator and optional native model provenance.
The namespace is `ac772aa6-ef6e-5fc8-a1fe-fd51f2b39bd9`, with name
`component.membership.v1:<comma-separated canonical UUIDs>`. Camera UUIDs similarly use
`camera.membership.v1` over the views sharing those intrinsics within the component.
Geometry is excluded from these IDs. Same views + changed pose/intrinsics therefore
mean the same component ID and a different component digest; different membership
means a different component ID.

Component semantics stream canonical finalized intrinsics and camera-sharing UUIDs,
registered UUIDs and camera-from-world poses, convention and measured point count.
Floats use little-endian float64 with normalized signed zero; q/-q rotations share a
canonical quaternion hemisphere. Native camera/image/point IDs, folder numbering and
binary record layout are excluded. Detailed point positions/colors/tracks are preserved
native payloads, not portable numerical semantics in v1. Native manifest hashes protect
them byte-for-byte. Changing a supported camera/pose/count changes the digest.
The set digest hashes convention/scale, canonical component IDs/digests and
registered/unregistered membership, excluding mapper/backend/recipe provenance.

The convention is right-handed `camera_from_world`: `p_camera = R(wxyz) p_world + t`,
X right, Y down, Z forward. Quaternion order is w,x,y,z; camera center is `-R^T t`.
Pixels use top-left origin and first pixel center (.5,.5), with native perspective
model/parameter ordering and explicit distortion. `scale=unknown_arbitrary`; no meters,
GPS metric inference or implicit OpenGL/3DGS conversion. Future M10 owns conversion.

`ReconstructionReader` can enumerate components, calibrated cameras, registered UUID
views/poses and unregistered UUIDs. Points and tracks are **unavailable** through this
reader (`not_published`); access raises an explicit error, not an empty stream. Measured
native point count may be zero; unavailable count is null, never silently zero.
The adapter parses current rigs/cameras/frames/images/points3D sparse binary files,
accepting compatible legacy models without rigs/frames. IDs need not be contiguous.
Point/track reciprocal references are checked with a bounded-memory disk-backed index;
large numerical arrays are never loaded into JSON or the application layer.

Publication includes reconstruction.json, mapping.json, input_cameras.json,
backend_mapping.json, sealed mapping.db and every native sparse file. Publication,
cache and recovery recompute the complete native summaries and semantic digests;
lineage validation reprojects the exact published upstream DB. An orphan is adopted
only after frozen-route/recipe/lineage/payload validation. Partial models never become
cache entries. Cancellation/timeout use the existing bounded process runner and Windows
Job Object tree ownership; unresolved teardown blocks publication/restart. Restart is
stage restart from M7, not checkpoint resume. Generic retry remains fake-only.

## Progress, tests and real evidence

`mapping.global_phases_v1` reuses M6.5 session/history and normalized complete-job
work for historical durations, with phase mode, explicit `historical_job_duration`
opt-in and no live fraction. Ordinary phase totals do not authorize ETA. Observable phases
are preparing_database, calibration (only when requested), validating_mapping_input,
global_mapping and validating_output. No rotation/BA log parser or registered/total
percentage is claimed. Cold ETA is unavailable. Compatible history supplies a broad
low/medium-confidence planning range through the existing estimator, partitioned by
mapper/settings/calibration, native/DLL identity, CPU/hardware and views/pairs/features/
inlier workload. Failed/cancelled/cached attempts do not teach history. The aggregate
also keeps a missing fraction when any active phase has no fraction.

Synthetic tests cover sparse reader conventions, current/legacy files, noncontiguous
IDs, camera sharing, multiple components/unregistered views, semantic invariance,
changed geometry/membership, unavailable optional records, malformed state, numerical
input projection, all-component publication/minimum size, immutable upstream bytes,
calibration, resource refusal, cancellation, corruption/recovery, cache, CLI and M6.5.

Run focused tests and the opt-in installed-runtime integration:

```powershell
python -m pytest tests/test_reconstruction_core.py tests/test_reconstruction_reader.py tests/test_reconstruction_identity.py tests/test_mapping_database.py tests/test_mapping_execution.py tests/test_mapping_capabilities.py tests/test_mapping_progress.py tests/test_mapping_cli.py
$env:SPLATFORGE_TEST_COLMAP = "C:\Your provisioned runtime\bin\colmap.exe"
$env:SPLATFORGE_TEST_MAPPING_CALIBRATION = "1"
python -m pytest tests/test_mapping_integration.py -rs -s
```

The tiny real fixture extends M7's texture harness with multi-depth patches and
translational parallax. It validates transport, execution and contracts only; it is
not a representative reconstruction-quality or calibration benchmark. Detailed local
logs/projects stay outside Git. Real metrics are recorded by the integration test.

Verified upstream implementation references: [Global entrypoint/output behavior](https://github.com/colmap/colmap/blob/bd1fcf6/src/colmap/exe/sfm.cc),
[multi-component pipeline](https://github.com/colmap/colmap/blob/bd1fcf6/src/colmap/controllers/global_pipeline.cc),
[numerical database inputs](https://github.com/colmap/colmap/blob/bd1fcf6/src/colmap/scene/database_cache.cc),
[sparse binary layout](https://github.com/colmap/colmap/blob/bd1fcf6/src/colmap/scene/reconstruction_io_binary.cc).
Installed command help and successful integration remain the execution evidence.


### Recorded local integration (2026-10-22)

The configured existing isolated COLMAP 4.2.1 runtime passed both opt-in cases and
real cancellation. Each case ran its own M7 fixture/project (UUID/input identities
therefore differ; this is not a policy comparison or reproducibility benchmark).

| Policy | Views / verified pairs | Components / registered per component | Unregistered | Native points | Global process / mapping API |
| --- | --- | --- | --- | --- | --- |
| preserve_priors | 3 / 3 | 1 / [3] | 0 | [552] | 0.250 s / 15.188 s |
| view_graph | 3 / 3 | 1 / [3] | 0 | [552] | 0.218 s / 19.297 s |

The calibrator process took 0.140 s and reported `No cameras to optimize` for these
explicit reliable priors. This certifies invocation/isolation/validation only, not
calibration benefit. Both repeated routes hit cache, all prior M7 payload bytes and
published reconstruction bytes remained identical, and a separately launched Global
process was cancelled with positive process/tree teardown evidence and no publication.
API times include preflight/runtime-file hashing, validation and publication; native
process times above include controlled launch/teardown. No quality conclusions follow.


### Final verification

Python 3.12 default full suite: **1173 passed, 54 skipped** (1277.87 s).
The 38 warnings are existing `record_property`/JUnit xunit2 reporting compatibility
warnings, not test failures. The final native smoke uses legacy JUnit reporting and
passes both cases without warnings. Final focused resource/lifecycle/reader regressions:
31 passed; Progress/ETA compatibility: 53 passed. All 37 changed Python files pass Ruff.
Full `ruff check .` retains only the unchanged baseline E501 in
`src/splatforge/core/registry.py:52`; unrelated code was not repaired.
`git diff --check` and all 150 checked local documentation/heading links pass.
