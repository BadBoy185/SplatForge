# M7b matching and geometric verification

Implemented stages: `FeatureMatching` and additive
`StageKind.GEOMETRIC_VERIFICATION`. No retrieval, mapping, training or GUI is included.
The three production technology families are LoMa, ALIKED/LightGlue and SIFT/BF.
Implementation/support, local availability, functional capability evidence and real
integration validation are distinct. Missing weights are an environment gap.

## Simple profile policy v1

| Profile / display label | Ordered candidates (extractor + matcher) |
| --- | --- |
| `fast` / Fast | LOMA_B128 + LOMA_B128; ALIKED_N16ROT + ALIKED_LIGHTGLUE; SIFT + SIFT_BRUTEFORCE |
| `medium` / Medium | LOMA_B + LOMA_B; LOMA_B128 + LOMA_B128; ALIKED_N16ROT + ALIKED_LIGHTGLUE; SIFT + SIFT_BRUTEFORCE |
| `high` / High | LOMA_B + LOMA_L; LOMA_B + LOMA_B; ALIKED_N16ROT + ALIKED_LIGHTGLUE; SIFT + SIFT_BRUTEFORCE |
| `max_high` / Max High | LOMA_B + LOMA_G; LOMA_B + LOMA_L; LOMA_B + LOMA_B; ALIKED_N16ROT + ALIKED_LIGHTGLUE; SIFT + SIFT_BRUTEFORCE |

Every resolution records `requested_mode`, `requested_profile`, `profile_version=1`,
the complete extractor/matcher/verifier settings and ordered typed capability decisions
with reasons and evidence. Unknown capability never qualifies. No candidate means an
actionable planning failure. Advanced selection assesses exactly one compatible choice;
Application resolution also pins extractor/matcher/verifier backend identities and
extractor/matcher model roles, sizes and SHA-256. Stage execution rechecks those pins;
a changed backend/model requires explicit resolution again.
Runtime failure never triggers re-resolution. LoMa-R is a rotation-robust Advanced
option, not a rung on the generic quality ladder. Source type never chooses LoMa-R.

V1 uses existing M7a defaults and explicit verified COLMAP defaults, without claiming
benchmark-proven threshold differences between profiles. All learned extractors use
2048 maximum features, 2048 maximum image side, their M7a score defaults (ALIKED .2,
LoMa .0), FP32 and LoMa fast-resize disabled. SIFT uses 8192 maximum features and
2048 maximum side. Simple defaults to `auto`: each candidate tries `gpu:0`, then
positively supported `cpu`, before technology downgrade. No runtime device switch
occurs. Matching defaults: 32768 maximum matches, one thread,
seed 0; SIFT BF ratio .8/distance .7/cross-check on/native CPU index route;
learned BF cosine .85/ratio 1/cross-check on; LightGlue/LoMa minimum score .1.
All profiles use the verification defaults below. Their numerical difference is the
preferred model route; future tuning requires another profile version and evidence.
Max High is a quality-oriented intent, not a claim of universally best reconstruction.

`sfm resolve --profile max-high` returns JSON without executing a project.
`sfm resolve --extractor LOMA_B --matcher LOMA_R` is Advanced planning.
Use `--extractor-settings`, `--matcher-settings`, `--verification-settings` for bounded
typed versioned JSON. Unknown fields are refused. The future GUI can call the same
Application service. Settings files are bounded at 64 KiB; complete resolved routes
and camera-prior sets allow up to 64 MiB for their bounded metadata.
Profiles currently control only features/matching/verification.

`sfm resolve --profile high --device auto` records `requested_device_policy`,
`resolved_device` and the bounded ordered `device_decisions` (at most ten), alongside
one final assessment per technology candidate in `decisions`. Each rejected device
retains its capability reason/evidence. GPU inventory is insufficient: native CUDA
build evidence and that method's contained inference must succeed. Learned extraction
does not depend on unrelated SIFT GPU inference. Supported device modes are `auto`,
`cpu`, `gpu:0` (`gpu` is a CLI alias). GPU index zero is the only exposed native index.
Advanced `--device auto` resolves device for the same explicit extractor/matcher and
numerical settings. Explicit CPU/GPU checks only that device and fails if unavailable.
The resolved device applies to extraction/matching; standalone verification remains CPU.
Without a device override, existing Advanced typed `use_gpu` settings, including
independent extraction/matching choices, remain explicit and unchanged. Old snapshots
without device-policy provenance remain readable. Low-level stages remain explicit.
The resolved device is represented by existing numerical `use_gpu` settings; requested
`auto` and profile labels do not enter stage keys. CPU/GPU remain separate numerical
recipes and performance signatures. History never chooses methods or devices.
Native failure, OOM or a reported whole-inference CPU fallback fails a frozen GPU
attempt; it never launches CPU or another technology automatically. CPU operators
inside a CUDA ONNX session are not a claim that every operator executes on GPU.
Existing `SfMConfig` and saved explicit ALIKED selections are unchanged; no project,
config or state schema migration is introduced.

Low-level `matches run --features-run X --pairs-run Y --matcher ...` already fixes the
extractor to X. It cannot re-extract. Passing `--resolved-route <JSON file>` requires
that exact resolved extraction and matching settings match the selected feature
artifact. `verification run --matches-run X --resolved-route <JSON file>` similarly
freezes the profile's verification settings and checks its upstream route. Otherwise
stages accept explicit matcher selection or `--settings <typed JSON file>`.
Camera priors include explicit optional sharing groups; the verifier rebuilds current
cameras and trivial native rig/frame transport in its private copy. Extraction-time
camera grouping cannot silently affect verification. Shared groups require identical
parameters and dimensions. M7b performs no intrinsic refinement or project migration.

## Advanced compatibility and settings

| Extraction variant (stable ID policy) | Compatible matcher tokens |
| --- | --- |
| SIFT / `feature_extraction.sift` | SIFT_BRUTEFORCE, SIFT_LIGHTGLUE |
| ALIKED_N16ROT / existing `feature_extraction.aliked` | ALIKED_BRUTEFORCE, ALIKED_LIGHTGLUE |
| ALIKED_N32 / same ID with typed variant | ALIKED_BRUTEFORCE, ALIKED_LIGHTGLUE |
| LOMA_B / `feature_extraction.loma_b` | LOMA_BRUTEFORCE, LOMA_B, LOMA_R, LOMA_L, LOMA_G |
| LOMA_B128 / `feature_extraction.loma_b128` | LOMA_BRUTEFORCE, LOMA_B128 |

SIFT/ALIKED LightGlue retain the existing IDs `feature_matching.lightglue_sift` and
`feature_matching.lightglue_aliked`. Other IDs are `feature_matching.<lowercase token>`.
The verifier ID is `geometric_verification.colmap`. No LoMa method is experimental.
Compatibility uses M7a's validated family/dtype/dimension/storage/keypoint convention,
plus its upstream variant/model/settings identity. ALIKED 128D and LoMa-B128 128D are
incompatible. Invalid cross-family or wrong LoMa variant fails before native work.

Advanced exposes all versioned supported numerical settings, existing M7a extraction
controls, CPU/GPU policy, threads, correspondence cap, seeds and resource limits.
Both stage commands accept `--resource-limits <typed JSON file>` to provide the complete
bounded resource schema; it takes precedence over inline resource defaults/options.
SIFT BF exposes ratio/distance/cross-check/CPU brute-force implementation policy;
learned BF exposes cosine/ratio/cross-check; LightGlue/LoMa expose minimum score.
Models come from the existing explicit provisioning root, pinned by bytes and runtime
inference. Arbitrary backend flags/shell fragments, unsupported precision and unknown
settings cannot bypass validation. LoMa uses FP32; BF16 is unavailable in the typed
route and has not been tested. No BF16 performance is claimed.

## MatchSet v1 and private database validation

`matching.match_set` contract 1 publishes `match_set.json`, `features.json`,
`pair_set.json`, `backend_mapping.json`, `matches.db` and the normal manifest. Upstream
metadata snapshots permit independent payload validation; exact producer handles remain
in lineage. Public MatchSet contains upstream feature/pair artifact IDs and semantic
digests, method/version, versioned numerical settings, descriptor signature,
backend identity, model role/name/source/size/SHA, requested/processed/matched/zero totals,
raw count, bounded canonical pair summaries and a semantic digest.

The external M6 PairSet is authoritative regardless of its producer. An owned pair-list
file contains exactly its edges, using the verified UUID-to-native-name mapping.
Only `matches_importer --match_type pairs` is used. Explicit options disable guided,
rig and geometric verification and same-frame skipping. The native 4.2.1 controller
otherwise drops raw sets below its geometry minimum even with verification skipped;
SplatForge sets that transport-only minimum to 1. It is not the verification threshold.

Every pair must have a processed raw row, including a valid empty matrix. A missing
processed row, unexpected pair or any two-view geometry fails publication. Validate
schema, exact images/mapping, feature content/signature, pair-ID decoding, row count,
two columns, uint32 little-endian blob layout and indices within feature bounds.
Zero-row NULL/empty blobs are accepted according to the native schema. Duplicate raw
or inlier correspondences are refused by canonical policy v1. Process crashes and
initialization failures never become a successful zero-match result.
The shared feature validator also accepts native NULL/empty blobs only for zero
feature rows, with identical numerical identity. Nonempty NULL payloads remain invalid.

Numerical hashing streams pairs in canonical UUID endpoint order. Each pair's bounded
matrix is read in 64 KiB chunks, validated, sorted by feature-index correspondence
and hashed using `<II` encoding. Native endpoint direction is canonicalized. Overall
identity includes consumed upstream semantics, method/settings/model byte identity
and conservative backend numerical identity. It excludes SQLite layout, timestamps,
native IDs, absolute matcher model path spelling, matcher source URL spelling, profile labels, events
and performance history. One matrix is capped at 100000 matches; the whole raw payload
is never loaded merely to hash it. Structural pair/metadata bounds follow M6 (one
million pairs, 768 MiB metadata); M7a feature/mapping metadata retain their bounds.

## VerifiedGeometrySet v1 and cameras

`geometry.verified_geometry_set` contract 1 adds `verified_geometry.json` and
`cameras.json` to the independent downstream payload. It records upstream MatchSet
ID/digest, verifier/version, exact settings, camera-prior digest, input/eligible/
accepted/rejected pairs, raw/inlier totals and all bounded per-pair states:
`no_raw_matches`, `insufficient_raw_matches`, `geometrically_rejected`, `verified`.
Rejected totals include all non-verified states. Geometry configurations remain
visible; verification is not mapping suitability or a reconstruction-quality gate.

| Verification setting | Frozen v1 default |
| --- | --- |
| Minimum inliers / maximum pixel error | 15 / 4.0 |
| Confidence / maximum trials / minimum inlier ratio | .999 / 10000 / .0 |
| Multiple models / relative-pose computation | false / false |
| Detect watermark / multiple-ignore-watermark / watermark error | true / true / 4.0 |
| Filter stationary matches / stationary error | false / 4.0 |
| DEGENSAC / Sampson refinement | false / true |
| Random seed / threads / batch size | 0 / 1 / 1000 |

These are the intentionally supported installed COLMAP 4.2.1 CLI controls. Unsupported
native options are refused. No changing native CLI defaults are substituted for them.
Internal solver constants belong to the pinned executable/runtime identity.

`CameraPriorSet` v1 uses canonical view UUIDs, perspective model, dimensions, finite
parameters, explicit focal-prior status and optional `camera_group_id`. An omitted
group means an independent camera. The camera digest includes the actual sharing
partition and numerical parameters; group UUID spelling and assumption-policy labels
are provenance rather than numerical identity. Supported models are SIMPLE_PINHOLE,
PINHOLE, SIMPLE_RADIAL, RADIAL, OPENCV and FULL_OPENCV. Without supplied priors,
`uncalibrated_focal_1.2_v1` explicitly seeds SIMPLE_RADIAL at 1.2 times maximum image
dimension, center at half width/height, zero radial distortion and no focal prior.
This is a recorded assumption, not learned calibration. Current priors update only
the downstream private database and are hashed into verification, never matching.

Standalone `geometric_verifier` processes positive raw-match pairs, including sets
it immediately rejects as insufficient. Validate unchanged raw rows and features,
only upstream pairs, inlier subsets/bounds, configuration, finite F/E/H 3x3 float64
row-major blobs and optional wxyz quaternion/translation layout and unit quaternion.
Rejected native rows must not retain numerical payload. Numerical geometry digest
uses deterministic little-endian numeric encoding, configuration, canonical UUID
endpoints, inliers, model-presence markers and pose. Opposite native ordering inverts
models/pose before hashing; native image IDs never enter public numerical identity.
Optional native per-pair estimated camera blobs are length/layout/parameter validated
and included in numerical identity using canonical view UUIDs; native camera IDs are
excluded. Current camera/rig/frame references and sharing are validated before publication.

## Isolation, lifecycle and resource gates

Validate upstream manifests and private payloads, then make independent pinned-byte
copies; no writable hardlinks. Matching starts with empty raw/geometry state, and
verification starts with unchanged raw matches and empty geometry. Published databases
are never opened writable. Owned native databases are checkpointed/sealed only after
confirmed teardown. Each output is validated again before immutable publication,
cache reuse and orphan recovery. No shared mutable pipeline database is introduced.

Native execution reuses M2's argument arrays, explicit native executable, controlled
child DLL/Qt environment, bounded streams, Job Object tree ownership, timeout,
durable cancellation and diagnostic evidence. Unresolved teardown blocks further
execution. Restart means a new stage command; checkpoint resume is not claimed.
Generic `run retry` remains fake-only; `run recover` can validate/adopt exact M7b
orphan publications. Non-Windows native recovery refuses to infer teardown from a lock.

Default limits: 100000 pairs, 100 million total features, 100 million raw matches,
64 GiB workspace, 4 GiB conservative pair working-memory bound, 8 GiB model files,
3600 s timeout. Matching estimates descriptor/feature, pair product/thread, raw output,
private database/journal/publication copies, metadata and model-file storage before
launch. Verification bounds actual raw pairs/matches, copied database growth and known
working buffers: uint32 raw pairs, float64 view coordinates and two float64 2D point
arrays for the largest simultaneously processed pairs. Concurrency is bounded by
the selected thread count, batch size and positive raw-pair count. Solver/allocator
overhead remains unknown; the estimate does not claim a measured memory peak.
Runtime database growth is checked through the cancellation boundary,
with confirmed tree teardown before reporting a resource failure. Limits cannot
guarantee GPU allocation; OOM fails the attempt without changing its recipe.
The per-pair correspondence cap is a strict SplatForge publication bound. Native
SIFT CPU implementations do not always truncate output to `max_num_matches`; valid
numerical output above the frozen cap fails as a resource error, without truncation
or method substitution. A higher limit requires an explicit new plan/attempt.
Existing M7a SIFT feature limits are also strict publication bounds around a native
soft target: a local request for eight features produced 78 and was refused by M7a
validation. M7b preserves that policy and never silently trims published feature indices.

| Change | Reuse | Recompute |
| --- | --- | --- |
| Verification threshold | Features, PairSet, MatchSet | VerifiedGeometrySet |
| Camera prior | Features, PairSet, MatchSet | VerifiedGeometrySet |
| Matcher/model/settings | Features, PairSet | Matching and verification |
| PairSet graph | Features | Matching and verification |
| Extractor/model/settings | Feature-independent PairSet | Features and actual consumers |
| Profile label | Any numerically identical stage recipe | Only changed resolved stage inputs |

## Progress and diagnostics

`matching.explicit_pairs_v1` uses exact requested PAIRS. `verification.raw_match_pairs_v1`
uses the positive raw-match PAIRS the native verifier visits; zero-match public lineage
is still complete. Current supported evidence is real copy/match/verify/validate phase
plus elapsed time, with zero observed completed pairs until validated success.
No per-pair log parser is claimed. Existing M6.5 polling/throttling emits heartbeats;
historical ETA remains available for compatible signatures, otherwise cold ETA is unknown.

Signatures separate matching from verification and include settings, descriptor
signature, exact executable/runtime/model bytes, actual supported precision, hardware
classification and pair/view/feature/match workload. Unknown GPU classification is
not fabricated.
SIFT is classified as `native_sift`, without inferring arithmetic precision from its
uint8 descriptors. Verification is float64; supported learned inference is FP32.
Profile labels and private history cannot affect method choice, recipes, digests or
cache. Only committed successful complete work teaches history;
cache/failure/cancellation/interruption/Doctor never do. Process evidence supplies
bounded runtime and diagnostics for future benchmarks. Peak native memory remains
unknown; it is not inferred from a storage estimate.

## Model provisioning and real validation

Configure `--colmap-model-dir` or `SPLATFORGE_COLMAP_MODEL_DIR` with the exact files
reported by the selected native binary's help. SplatForge hashes local bytes, checks
backend-pinned SHA-256 where advertised, copies/pins models before execution and
requires disposable inference with valid raw output. Matching probes use bounded
synthetic descriptors of the selected signature, without extracting images again or
requiring producer model files. The standalone verifier probe uses known raw matches
and requires neither an extractor nor a matcher model. GPU matching proves its own
runtime health in an owned worker and checks the native CUDA build. Help tokens/ONNX flags alone
cannot make learned matching runnable. Model source and redistribution/license
evidence remain separate; no weights are downloaded by SplatForge.
Root precedence is explicit argument, environment, composed bundled root, then
`%LOCALAPPDATA%/SplatForge/models/colmap` (read-only lookup; never created/provisioned).
Within that one root SplatForge checks the exact filename, then an already-existing
`SHA256-filename` native-cache spelling only when a backend reference digest exists
and the plain file is absent. A wrong plain file cannot be hidden by another file.
Use an existing native cache only by explicitly selecting its root. No scanning,
moving, downloading or renaming of user weights occurs.
Doctor model evidence retains expected root/name/reference SHA, checked path and
observed size/SHA separately, including missing/wrong-file results. No observed SHA
is claimed for absent files. A missing reference digest is explicitly reported;
local SHA plus successful exact inference remains mandatory.
Application `learned_route_provisioning` returns all consumed route roles and exact
environment/pytest rerun instructions; integration skips render that typed evidence.
When the complete model set exists, native runtime failures fail the integration.
Learned command builders reject URIs and unresolved relative model arguments.
Numerical launch uses only owned copies that passed byte/size pin validation;
no learned role is left to a native URL/default. LoMa BF16 stays disabled explicitly.
Doctor JSON preserves the binary's expected `URL;filename;SHA256` pins in
`colmap.command_discovery.model_defaults`, including missing-file cases. Those
expected pins do not claim that local model bytes were found or inference succeeded.

M7b.2 operator setup explicitly provisioned missing official weights separately
from processing. Source URLs were read from the SHA-verified installed binary's
model defaults: COLMAP release `3.13.0` for ALIKED/LightGlue/brute-force and the
binary's exact `davnords/storage` LoMa release URLs. Each download was staged,
fully SHA-256 checked against that native pin, then copied/checked before placement
in the explicitly selected local root. Existing models were preserved. The setup
script and machine-specific evidence stay ignored; no model downloader is shipped
or called by Doctor, tests or a numerical attempt. Checkpoint licensing remains
separate from runtime validation.

The eight staged files below total 2357825369 bytes. For every row, the full
observed SHA-256 equalled the expected native reference SHA-256. These pins describe
the tested build, not a substitute for reading defaults from another selected binary.

| File | Expected = observed SHA-256 |
| --- | --- |
| `aliked-n32.onnx` | `a077728a02d2de1a775c66df6de8cfeb7c6b51ca57572c64c680131c988c8b3c` |
| `sift-lightglue.onnx` | `e0500228472b43f92b3d36881a09b3310d3b058b56187b246cc7b9ab6429096e` |
| `bruteforce-matcher.onnx` | `3c1282f96d83f5ffc861a873298d08bbe5219f59af59223f5ceab5c41a182a47` |
| `loma_descriptor_dedode_g.onnx` | `5a7b9eaf7425d4513c5d7feae86080bae7ed3aceae7fb1b9f059d0752e2ad564` |
| `loma_descriptor_dedode_b.onnx` | `82660a364299013618fe649092ebc4f617559f6a77e1ab5a3412be62a47ddc2d` |
| `loma_matcher_B128.onnx` | `e71ad490d13713374433a7ef99a7b4f4877d09338e40f347b7e64cc90150ee16` |
| `loma_matcher_L.onnx` | `918da5427f37c3d9e05264a58a4d05729f87d459c3d5d69add7ce72eeacea66d` |
| `loma_matcher_G.onnx` | `62134cde779ed1031982c13c2c1952ed14856d715e97072364821a91f6276cf9` |

GPU diagnosis inspected the selected COLMAP installation and child-scoped layout.
Its ONNX Runtime/provider DLLs report `1.30.0.20260909.8.f2c39fe`; no cuDNN DLL is
present in the controlled installation. The installation root and native `bin`
directory are already in the child's runtime search paths. ALIKED N16ROT/N32 and
LoMa B/B128 GPU extraction report a Conv failure loading `cudnn64_9.dll`;
SIFT LightGlue GPU matching reports the same missing library at ReduceMax.
This remains an external runtime prerequisite. No adapter path fix, copied DLL,
CUDA/cuDNN installation or global PATH mutation was appropriate. SIFT/brute-force
has independently passed its complete GPU route; learned CPU routes are independent
of that missing GPU dependency. Explicit GPU never silently becomes CPU.

Observed native build: COLMAP 4.2.1, commit `bd1fcf6`, executable SHA-256
`9418a14c93d4a5eec5eb33ebf48a917403b5faa7ab5d2232f23e50c206d9e427`.
LoMa execution requires >=4.2.1; other routes have independent option/schema gates.
Expected FP32 files for this
build (obtain separately; run Doctor again for another binary):

| Route/role | Files |
| --- | --- |
| ALIKED_N16ROT + LightGlue | `aliked-n16rot.onnx`, `aliked-lightglue.onnx` |
| Advanced ALIKED_N32 | `aliked-n32.onnx` plus its selected matcher |
| Advanced SIFT LightGlue | `sift-lightglue.onnx` |
| ALIKED/LoMa brute-force | `bruteforce-matcher.onnx` |
| LoMa-B128 extraction | `loma_detector.onnx`, `loma_descriptor_dedode_b.onnx` |
| LoMa-B extraction | `loma_detector.onnx`, `loma_descriptor_dedode_g.onnx` |
| LoMa B128/B/R/L/G matching | corresponding `loma_matcher_B128.onnx`, `loma_matcher_B.onnx`, `loma_matcher_R.onnx`, `loma_matcher_L.onnx`, `loma_matcher_G.onnx` |

```powershell
$env:SPLATFORGE_TEST_COLMAP = "C:\Program Files\COLMAP 4.2.1\bin\colmap.exe"
$env:SPLATFORGE_COLMAP_MODEL_DIR = "D:\Provisioned models\COLMAP"
$env:SPLATFORGE_TEST_COLMAP_LEARNED = "1"
$env:SPLATFORGE_TEST_COLMAP_HEAVY = "1"  # optional L/G
# Learned tests default to auto; use cpu or gpu:0 for an explicit device:
$env:SPLATFORGE_TEST_COLMAP_DEVICE = "auto"
python -m pytest tests/test_matching_integration.py -rs -s
```

Real SIFT CPU validation: 3 views, 3 requested pairs, 636 raw matches, 3 verified
pairs and 636 inliers; matching 4.89 s and verification 8.91 s including capability
preflight. Both repeat stages hit cache; upstream and raw MatchSet bytes stayed
unchanged. A separate real verification with explicit shared cameras also passed and
used a distinct verification key, then hit cache on repetition. These synthetic identical
textured views prove contracts, not difficult
scene quality.

M7b.1 real ALIKED_N16ROT + LightGlue validation passed with already-existing,
reference-hash-verified local weights: 3 views, 3 requested pairs, 339 raw matches,
3 verified pairs and 339 inliers. Feature/matching/verification runtime was
3.36/5.06/5.98 seconds in the final tiny-fixture run, excluding full-route resolution.
`auto` rejected GPU after native extraction inference failed (the local CUDA ONNX
provider could not load `cudnn64_9.dll`), then positively proved
CPU for the same technology. CPU FP32 was frozen and actually requested. Both repeat
stages hit cache; feature and MatchSet bytes stayed unchanged; separate PAIRS progress
contracts passed. These figures validate contracts, not reconstruction quality.
The two observed model SHA-256 values were
`39c423d0a6f03d39ec89d3d1d61853765c2fb6a8b8381376c703e5758778a547`
(ALIKED_N16ROT) and
`b9a5de7204648b18a8cf5dcac819f9d30de1a5961ef03756803c8b86c2dceb8d`
(ALIKED LightGlue). At the M7b.1 review, LoMa real validation was still pending
missing FP32 weights. M7b.2 results below supersede that availability status. L/G
remain heavy opt-ins; an existing BF16 file does not satisfy FP32 provisioning.

### M7b.2 real validation

All ten distinct matcher types passed CPU validation in all thirteen compatible
extractor/matcher combinations. Every row below used three views and exactly three
external requested pairs; all three pairs verified. On this synthetic fixture the
inlier total equalled the raw count in every row. All feature/matching/verification
cache checks and published feature/MatchSet byte-integrity checks passed. Raw
databases contained no precomputed geometry; model SHA and exact backend/device
identities were frozen and verified. No numerical attempt downloaded weights.

| Extractor | Matcher | Total features | Raw matches / inliers | Extraction / matching / verification (s) |
| --- | --- | ---: | ---: | --- |
| SIFT | SIFT_BRUTEFORCE | 1044 | 636 | 2.17 / 3.14 / 7.86 |
| SIFT | SIFT_LIGHTGLUE | 1044 | 729 | 2.17 / 4.12 / 7.48 |
| ALIKED_N16ROT | ALIKED_BRUTEFORCE | 342 | 210 | 3.27 / 3.02 / 7.34 |
| ALIKED_N16ROT | ALIKED_LIGHTGLUE | 342 | 339 | 3.39 / 4.44 / 7.25 |
| ALIKED_N32 | ALIKED_BRUTEFORCE | 183 | 114 | 3.77 / 2.95 / 7.27 |
| ALIKED_N32 | ALIKED_LIGHTGLUE | 183 | 183 | 3.75 / 3.50 / 7.31 |
| LOMA_B128 | LOMA_BRUTEFORCE | 6144 | 3939 | 15.84 / 7.44 / 8.20 |
| LOMA_B128 | LOMA_B128 | 6144 | 1626 | 16.06 / 14.45 / 7.78 |
| LOMA_B | LOMA_BRUTEFORCE | 6144 | 4353 | 129.80 / 7.39 / 8.20 |
| LOMA_B | LOMA_B | 6144 | 5670 | 129.62 / 15.12 / 8.14 |
| LOMA_B | LOMA_R | 6144 | 1083 | 127.45 / 14.61 / 8.06 |
| LOMA_B | LOMA_L | 6144 | 6135 | 126.84 / 26.20 / 7.88 |
| LOMA_B | LOMA_G | 6144 | 6090 | 125.70 / 64.77 / 8.28 |

Times measure stage API calls, including their own preflight, excluding initial
full-route resolution and subsequent cache checks. Some checks ran concurrently.
The table rounds times to hundredths of a second. These are execution diagnostics,
not comparative performance or quality benchmarks.
The identical textured views prove execution/contracts, not difficult overlap,
rotation robustness or reconstruction quality. Simple profile v1 is unchanged.

The complete SIFT/brute-force GPU route also passed: 939 total features, 171 raw
matches/inliers, three verified pairs, 2.45/3.20/3.98 seconds for the three stages,
and all three caches/upstream byte-integrity checks. At the M7b.2 review, learned
GPU routes were unavailable on the original installation because of the missing
cuDNN dependency described above. LoMa/ALIKED matcher-only GPU inference was not
certified when its required
GPU extractor failed; no CPU execution was labelled GPU. No BF16 was exposed or run.

Permanent real SIFT edge cases include one empty view: all three requested pairs
remain present, two contain zero matches, and the textured pair produces 212 raw
matches/212 inliers. A sparse L-shaped fixture produces 15 raw matches; an explicit
verification minimum of 16 yields one `insufficient_raw_matches` and two
`no_raw_matches` states, zero accepted pairs and zero inliers. Input bytes remain
unchanged. These are contract regression fixtures rather than quality benchmarks.

### M7b.3 isolated GPU runtime validation

Explicit operator setup provisioned official NVIDIA cuDNN 9.27.0.42 for CUDA 12
into a separate native COLMAP 4.2.1 runtime, alongside pinned DLLs from the existing
CUDA 12.8 installation. Archive size and SHA-256 matched the official NVIDIA
manifest before extraction. All original COLMAP files, existing CUDA files and
models stayed byte-identical; user/system PATH stayed unchanged. Setup details,
the exact archive checksum and rerun commands are in [GPU_RUNTIME.md](GPU_RUNTIME.md).
No downloader or installer was added to production code or numerical attempts.

All ten matcher types passed in all thirteen compatible GPU combinations below,
with explicit `gpu:0` and the existing FP32 learned settings. Every row used three
views and three exact external pairs, produced three verified pairs, and had the
same total inliers as raw matches. All three stage caches, raw-only database checks,
model/backend/device pins, separate PAIRS work models and published feature/MatchSet
byte-integrity checks passed. The selected native executable's bytes are unchanged;
the new DLL set has a distinct backend numerical identity and requires a new plan.

| Extractor | Matcher | Total features | Raw matches / inliers | Extraction / matching / verification (s) |
| --- | --- | ---: | ---: | --- |
| SIFT | SIFT_BRUTEFORCE | 939 | 171 | 7.41 / 10.06 / 13.84 |
| SIFT | SIFT_LIGHTGLUE | 939 | 669 | 7.38 / 10.77 / 13.92 |
| ALIKED_N16ROT | ALIKED_BRUTEFORCE | 342 | 186 | 8.28 / 10.23 / 13.89 |
| ALIKED_N16ROT | ALIKED_LIGHTGLUE | 342 | 339 | 8.33 / 10.81 / 14.95 |
| ALIKED_N32 | ALIKED_BRUTEFORCE | 183 | 96 | 8.14 / 13.34 / 14.03 |
| ALIKED_N32 | ALIKED_LIGHTGLUE | 183 | 183 | 8.41 / 15.16 / 14.52 |
| LOMA_B128 | LOMA_BRUTEFORCE | 6144 | 3069 | 8.77 / 10.41 / 14.12 |
| LOMA_B128 | LOMA_B128 | 6144 | 3735 | 8.84 / 10.95 / 14.27 |
| LOMA_B | LOMA_BRUTEFORCE | 6144 | 3150 | 13.70 / 14.58 / 14.53 |
| LOMA_B | LOMA_B | 6144 | 6144 | 13.99 / 15.28 / 14.52 |
| LOMA_B | LOMA_R | 6144 | 4152 | 13.86 / 15.42 / 14.53 |
| LOMA_B | LOMA_L | 6144 | 6144 | 13.78 / 15.91 / 14.42 |
| LOMA_B | LOMA_G | 6144 | 6144 | 13.50 / 18.98 / 14.47 |

Stage times include preflight and repeated runtime identity checks, excluding
initial full-route resolution and later cache checks. Other checks ran concurrently;
these are diagnostics rather than comparative GPU/CPU performance benchmarks.
CPU ALIKED_N16ROT/LightGlue also passed on the new bundle with 339 matches/inliers.
The default suite passed with 1071 tests and 50 opt-in skips; the explicit GPU matrix
passed all 13 cases without skips. BF16 was not exposed or tested.

GPU integration ran with a scoped PATH containing only the bundle and Windows
directories. Read-only observations confirmed the observed ONNX/CUDA/cuDNN modules
loaded from that bundle. Numerical execution still uses the existing contained
process boundary; no whole-inference CPU fallback was accepted. All machine-specific
paths, file inventories, models and detailed diagnostics remain in ignored local
storage. Simple profile v1, saved explicit project intent and production code did
not change. These fixtures prove execution contracts, not real-scene quality.

### Cross-source validation

The external cross-source test accepts `SPLATFORGE_TEST_CROSS_SOURCE_FIXTURE`:

```json
{
  "fixture_version": 1,
  "views": [
    {"path": "phone/frame.png", "source": "phone", "sha256": "<64 hex digits>"},
    {"path": "drone/frame.png", "source": "drone", "sha256": "<64 hex digits>"}
  ],
  "pairs": [[0, 1]]
}
```

Paths are relative to the manifest or absolute, with supplied content SHA-256.
Inputs are already oriented perspective views. The test snapshots/re-encodes them
into a new temporary photo project and supplies only the explicit index edges; it
never mutates the originals or runs retrieval. Bounds: 32 views, 100 pairs, 16 MiB
encoded/16 MP per input, 64 KiB manifest. No representative external fixture was
configured locally; cross-source quality comparison remains pending.

Before M7c quality benchmarking: supply representative phone/drone overlap with
fixed explicit edges and retain quality/runtime/model evidence. The CPU and GPU
execution matrices above are validated; another machine still needs its own
positively verified model/runtime combination. M7c then adds retrieval/hybrid PairSet generation;
M8 independently adds mapping. Neither milestone is completed by M7b.

Verified upstream references: [installed-build importer/verifier entrypoints](https://github.com/colmap/colmap/blob/bd1fcf6/src/colmap/exe/feature.cc),
[raw controller behavior](https://github.com/colmap/colmap/blob/bd1fcf6/src/colmap/controllers/feature_matching_utils.cc),
[native geometry storage](https://github.com/colmap/colmap/blob/bd1fcf6/src/colmap/scene/database_sqlite.cc).
Installed executable help and successful functional probes remain the execution gate.
