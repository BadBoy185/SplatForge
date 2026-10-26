# SplatForge

SplatForge is a Windows-first, local-first application in early development for
turning photos and videos into high-quality 3D Gaussian Splatting scenes. The product
aims for the breadth and convenience of desktop tools such as 360 Gaussian / 360
Gaussian Pro, while keeping processing methods replaceable. This is a product goal,
not a claim of current feature parity.

Phase 1 targets drone and phone video, DSLR/mirrorless photographs, multiple clips
and mixed ordinary-camera sources. "Flat camera" means a perspective camera, with
ordinary lens distortion supported through an explicit camera model; it does not
mean every input must already be distortion-free. 360, fisheye and equirectangular
inputs come later through preprocessing into perspective views.

## Current status

The optional desktop application is launched with `splatforge-gui` after installing
`python -m pip install -e ".[dev,gui]"` in the development environment. It uses
PySide6 6.12.0 / Qt Quick / QML and the same application services, project settings,
runs and artifacts as CLI. Home, Sources, Reconstruct, Dataset, Train, Results and
Diagnostics provide Guided/Advanced operation without a separate processing pipeline.
See [desktop usage, threading and limitations](docs/M12.md). Base CLI installation
does not require Qt. Installer/updater packaging remains deferred.

The repository contains configuration models, a method catalog, safe local project
persistence, the M1b2 fake-stage execution/recovery slice, M2 media ingest, the M3
candidate-view/fixed-FPS route, M4 quality-aware selection, M6 deterministic PairSet
construction, the M6.5 progress/ETA foundation and M7a local-feature extraction. The CLI
can create/show projects, upgrade historical state v1/v2/v3 to v4, register/list/verify/
relink ordinary JPEG/PNG/MP4/MOV sources, and execute or inspect the deterministic fake
route. `views prepare` materializes bounded JPEG/PNG candidate pixels from registered
photos and independent video timelines, then publishes either a metadata-only fixed-FPS
selection or a Pillow-backed QualityReport followed by sharpest-per-interval selection.
Saved intent lives in `project.json`; immutable input inventories live under
`sources/`; state v4 stores execution history and durable source-verification evidence.

Project saves and fake runs share one OS-held Windows writer lock. Fake outputs are
validated before immutable publication and cache reuse rechecks manifests and payload
digests. A second CLI can create the bounded `cancel.request` without taking that lock;
the owner durably accepts it before stopping, publishing or succeeding. Manual bounded
retry remains specific to in-process fake stages; publication recovery validates
interrupted M3/M4/M6/M7a runs. An interrupted M3 route
restarts as a new command and reuses only completed stage artifacts. M2 streams source
hashes, normalizes FFprobe metadata and runs external processes with bounded output,
timeouts, cancellation and Windows Job Object containment. M3 uses that boundary for
FFmpeg, preserves selected input presentation timestamps, applies orientation explicitly,
and validates every published image without modifying originals. M4 measures exact
8-bit edge-response variance and dHash64 from candidate pixels, keeps thresholds out of
the reusable report, records a typed decision for every candidate and compares video
duplicates only against a bounded same-clip accepted history. M5 adds project-free,
read-only COLMAP/GPU diagnostics with exact binary identity, bounded command/help
discovery, model evidence, native-database compatibility and optional CPU/GPU SIFT
smoke probes. M6 builds immutable metadata-only candidate view graphs independently of
COLMAP/GPU or local features. M7a extracts SIFT, ALIKED_N16ROT, optional ALIKED_N32,
LOMA_B and LOMA_B128 through a positively verified native COLMAP process.
M7b adds explicit PairSet matching and separate geometric verification. LoMa,
ALIKED/LightGlue and SIFT/brute-force are supported technology families; local
availability and real integration validation are reported separately. M7c offline retrieval,
M8a Global mapping and M8b1 single-model Incremental Ceres / capability-gated Caspar BA
and M8b2 Hierarchical / capability-gated Global GPU / mapper comparison are implemented.
M9a reconstruction measurements/policy validation and M9b explicit component selection are
implemented. M10 adds flat-camera dataset planning/preparation, independent validation,
per-component cache and manual safe cleanup. M11 implements external LichtFeld dataset
handoff and isolated managed gsplat Default/MCMC training, compatible checkpoints,
validated Gaussian PLY scenes and candidate comparison. Production VPR inference,
practical automatic multi-video E2E acceptance, representative mapper recommendation,
broader training preset recommendation remain pending. M12 adds the optional Qt Quick / QML
desktop client described in [M12](docs/M12.md). See [M10](docs/M10.md)
and [M11 contracts and evidence](docs/M11.md).
Catalog entries describe intended methods, not installed or implemented capabilities.

Fixed-FPS selection uses an exact ordered sweep with bounded target expansion.
Artifact integrity checks share results only within one command. M3 attempts retain
bounded local FFmpeg invocation diagnostics; `run show` lists their path, retained
invocation count and truncation status without printing backend logs.

M6.5 adds application-owned stage/pipeline progress, throughput, elapsed time and
versioned ETA planning ranges/confidence. `run progress <project> <run-id> [--json]`
reads current committed lifecycle plus bounded progress evidence without a writer lock.
FFmpeg emits structured live progress; quality, selectors and pairs share the same
contract. Cached/skipped stages have zero remaining execution time. Without history,
ETA starts unavailable and refines from live throughput; unknown totals stay explicit.
Private successful runtime history lives outside projects in
`%LOCALAPPDATA%/SplatForge/performance.sqlite`. `performance show [--json]` inspects its
anonymous signature aggregates; `performance reset` clears samples without changing
project artifacts or cache. History failure only reduces prediction evidence.

These commands work in the foundation:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\splatforge.exe version
.\.venv\Scripts\splatforge.exe methods
.\.venv\Scripts\splatforge.exe doctor
.\.venv\Scripts\splatforge.exe doctor --deep --json --colmap "C:\COLMAP\colmap.exe" --colmap-model-dir "C:\COLMAP\models"
.\.venv\Scripts\splatforge.exe show-default-config
.\.venv\Scripts\splatforge.exe project create "C:\SplatForge Projects\First scene" --label "First scene"
.\.venv\Scripts\splatforge.exe project show "C:\SplatForge Projects\First scene"
.\.venv\Scripts\splatforge.exe project upgrade-state "C:\SplatForge Projects\First scene"
.\.venv\Scripts\splatforge.exe media add "C:\SplatForge Projects\First scene" "D:\Media\photo.jpg" "D:\Media\clip.mp4" --ffprobe "C:\ffmpeg\bin\ffprobe.exe"
.\.venv\Scripts\splatforge.exe media list "C:\SplatForge Projects\First scene"
.\.venv\Scripts\splatforge.exe media verify "C:\SplatForge Projects\First scene" --policy balanced
.\.venv\Scripts\splatforge.exe media verify "C:\SplatForge Projects\First scene" --policy strict
.\.venv\Scripts\splatforge.exe media relink "C:\SplatForge Projects\First scene" <source-id> "E:\Moved\photo.jpg"
.\.venv\Scripts\splatforge.exe views prepare "C:\SplatForge Projects\First scene" --target-fps 2 --candidate-fps 4 --ffmpeg "C:\ffmpeg\bin\ffmpeg.exe" --image-format jpeg --jpeg-qscale 2 --max-candidates 10000 --max-disk-gib 20
.\.venv\Scripts\splatforge.exe views prepare "C:\SplatForge Projects\First scene" --selection sharpest-interval --target-fps 2 --candidate-fps 4 --quality-max-side 1024 --duplicate-hamming-threshold 4 --duplicate-lookback 8 --ffmpeg "C:\ffmpeg\bin\ffmpeg.exe"
.\.venv\Scripts\splatforge.exe run fake "C:\SplatForge Projects\First scene" --start 0 --count 3 --factor 2
.\.venv\Scripts\splatforge.exe run show "C:\SplatForge Projects\First scene" <run-id>
.\.venv\Scripts\splatforge.exe run cancel "C:\SplatForge Projects\First scene" <run-id>
.\.venv\Scripts\splatforge.exe run recover "C:\SplatForge Projects\First scene" <run-id>
.\.venv\Scripts\splatforge.exe run retry "C:\SplatForge Projects\First scene" <run-id>
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
```

`splatforge pairs build` requires the exact successful `views prepare` run ID, supports
both selection variants, and never chooses a latest artifact. For example:

```powershell
splatforge pairs build "C:\SplatForge Projects\First scene" --views-run <views-run-id> --method sequential --forward-neighbors 5 --max-time-gap 3/2 --max-pairs 100000
splatforge pairs build "C:\SplatForge Projects\First scene" --views-run <views-run-id> --method exhaustive --max-pairs 100000
splatforge pairs build "C:\SplatForge Projects\First scene" --views-run <views-run-id> --pair <view-id>:<other-view-id>
```

Sequential connects timestamp neighbors independently within each video clip/stream;
a shared source group does not join clip timelines. Unordered photos stay isolated
unless explicit pairs connect them. Exhaustive connects all selected observations,
refusing `N(N-1)/2` above the budget before materializing pairs. Explicit edges merge
with generated edges, preserve both reasons, and count towards the same budget.
Exhaustive rejects Sequential-only options. Gaps accept exact decimal/integer/fraction
seconds. The 100,000-pair default is conservative for development; the structural
PairSet v1 limit is 1,000,000 sparse pairs and 768 MiB metadata.

The JSON result reports artifact handle, cache hit, pair/isolated/component counts,
cross-source/group coverage and warnings without dumping all pairs. Disconnected clips
and isolated photos are diagnostics; candidate connectivity does not prove successful
SfM. M6 validates published hashes without decoding images or accessing originals.
Its one-node attempts support durable cancellation and safe publication recovery via
`run recover`; interrupted work regenerates in a new `pairs build` run. Generic
`run retry` remains fake-only. M7c now has an explicit offline descriptor import and
bounded retrieval/hybrid route; production VPR inference/model selection remains
pending representative benchmarks. See [M7c usage/contracts](docs/M7C.md) and
[candidate evidence](docs/M7C_BENCHMARK.md). Spatial
pairing remains later; no embeddings, matching, COLMAP processing or GPU work occurs.

Creation requires a missing or empty directory. It creates `project.json`,
`project.lock` and state schema v4 in `state.sqlite`; source and execution directories
are created only by their operations. Existing state v1/v2/v3 projects remain
open/show/save compatible. The M1b fake route remains usable on v3, while M2 mutation and
verification and M3/M4 execution require explicit upgrade to v4. `SPLATFORGE_FFPROBE`
may provide the FFprobe path instead of `--ffprobe`; `SPLATFORGE_FFMPEG` similarly
provides the FFmpeg path instead of `--ffmpeg`. M3's explicit command uses
`frame_selection.fixed_fps` run settings and does not reinterpret or rewrite a
project's saved `frame_selection.sharpest_interval` intent. The default
`--selection fixed-fps` route performs no quality scoring. For
`--selection sharpest-interval`, omitted candidate FPS resolves to exactly twice the
target FPS; video requests below that density are refused. Changing target FPS,
minimum sharpness or duplicate policy reuses candidate pixels and QualityReport, while
changing `--quality-max-side` recomputes measurements and their selection consumer.

`splatforge doctor` does not require or mutate a project. COLMAP selection is, in order:
`--colmap`, `SPLATFORGE_COLMAP`, an explicitly composed bundled candidate and safe
absolute `PATH` entries. Model roots use `--colmap-model-dir`,
`SPLATFORGE_COLMAP_MODEL_DIR`, a composed bundled root, or the read-only local default
`%LOCALAPPDATA%/SplatForge/models/colmap`. Lightweight mode
reads bounded binary/build and CLI evidence only. `--deep` additionally creates and
removes owned temporary databases and images for native-schema, CPU SIFT and GPU SIFT
functional checks. M7a extends deep discovery with disposable learned inference when
the required local models are configured. Missing COLMAP, NVIDIA tools, CUDA, ONNX support or model files are
valid diagnostic results, not project failures. Doctor never downloads COLMAP, models,
ONNX Runtime, CUDA or drivers.

On Windows SplatForge always executes and hash-identifies native `colmap.exe`.
You may supply an official `COLMAP.bat` path as an installation locator: SplatForge
never reads or executes its commands, but resolves `bin/colmap.exe` or `colmap.exe`
at that installation root. For recognized layouts (also when selecting the native exe
directly), existing root/bin/lib runtime directories are prepended to the child's PATH;
known Qt plugin locations are supplied only when `platforms/qwindows.dll` exists.
The inherited PATH follows those controlled entries. No system PATH modification is
required. Custom native installs remain probeable without guessed sibling paths.
Doctor records the bounded runtime layout separately from executable identity, never
the user's complete PATH or environment. Other batch/script entry points are refused.

Unknown help layouts remain `unknown`. Learned methods require successful disposable
inference and validated native descriptor output, in addition to exact local model and
executable identities. ONNX build flags or option tokens alone cannot make them runnable.
Matching routes require disposable raw-correspondence inference and the explicit-pair
interface; help tokens alone do not establish runnable matching.

### Local-feature extraction (M7a)

```powershell
.\.venv\Scripts\splatforge.exe features extract "C:\Scenes\Example" --views-run <uuid> --method SIFT --cpu --json
.\.venv\Scripts\splatforge.exe features extract "C:\Scenes\Example" --views-run <uuid> --method ALIKED_N16ROT --colmap-model-dir "C:\Models\COLMAP" --json
.\.venv\Scripts\splatforge.exe features extract "C:\Scenes\Example" --views-run <uuid> --method LOMA_B128 --colmap-model-dir "C:\Models\COLMAP" --json
```

Use the explicit UUID of a successful `views prepare` run. Only its selected,
orientation-normalized published pixels are copied into the attempt workspace;
originals and rejected candidates are never extracted. SIFT is the baseline/fallback;
ALIKED is a learned alternative. LoMa requires **COLMAP >=4.2.1**, exact local detector
and descriptor files, and verified ONNX/runtime inference. This floor does not apply
globally to compatible SIFT/ALIKED installations. LOMA_B uses 256 float32 dimensions;
LOMA_B128 and ALIKED use 128 float32 dimensions; SIFT uses 128 uint8 dimensions.
The families are incompatible even when dimensions match. Current SfM defaults are unchanged.

Settings include `--max-features`, `--max-image-size`, explicit `--gpu/--cpu`, learned
`--min-score` and LoMa `--fast-resize`. Unsupported backend options are refused.
M7a supports FP32 LoMa; BF16 is deferred. Resource gates include view/megapixel limits,
descriptor storage, copied models and private database/workspace overhead; use
`--max-views`, `--max-workspace-gib` and `--timeout` to configure bounded execution.
GPU OOM fails the attempt without automatic retry. `run show`, `run progress`,
`run cancel` and `run recover` use the existing execution foundation. Restart with
`features extract` after recovery; checkpoint resume is not claimed.

`features.local_feature_set` contract 1 publishes canonical metadata, an exact view-to-
native-image mapping and a sealed private feature database, all covered by manifest
hashes. Semantic identity streams numerical keypoint/descriptor bytes in view-ID order,
excluding SQLite layout, native IDs and provisional cameras. Pair/matcher settings and
private performance history do not enter feature recipes. Published inputs stay immutable.
The `features.selected_views_v1` work model uses exact VIEWS total plus megapixels;
verified COLMAP 4.2.1 logs provide observed per-image progress. Other formats retain
zero observed completed views until terminal validation and can use historical ETA.
Elapsed time never fabricates a progress count. Only committed successful runs teach history.

SplatForge never downloads weights, including through URL-backed COLMAP defaults.
Provision models separately and configure their directory. Provenance records source/name,
size and SHA-256; backend-pinned hashes are checked. This is reproducibility evidence,
not clearance to redistribute weights commercially. Base SplatForge has no PyTorch or
Python ML-runtime dependency. LoMa-R/L/G are M7b matchers, not M7a extractors.

### Matching, verification and profiles (M7b)

```powershell
splatforge sfm resolve --profile high --colmap "C:\COLMAP\bin\colmap.exe"
splatforge sfm resolve --extractor LOMA_B --matcher LOMA_R --colmap-model-dir "C:\Models\COLMAP"
splatforge matches run "C:\Scenes\Example" --features-run <uuid> --pairs-run <uuid> --matcher SIFT_BRUTEFORCE --cpu --json
splatforge verification run "C:\Scenes\Example" --matches-run <uuid> --min-inliers 15 --max-error 4 --json
```

Simple feature/matching profiles **Fast, Medium, High, Max High** express speed/quality
intent. The versioned resolver chooses an exact compatible route before execution and
returns JSON explaining unavailable higher candidates. Advanced users select compatible
SIFT, ALIKED/LightGlue and LoMa variants and typed numerical settings directly. These
are shared Application contracts used by the desktop GUI. All routes are
recorded and never change algorithm silently during an attempt. Existing explicit saved
ALIKED defaults are unchanged and are not reinterpreted as a Simple profile.

Simple profiles default to `--device auto`: each technology candidate checks its own
GPU inference, then supported CPU inference, before trying the next technology. JSON
records every device decision and freezes `cpu` or `gpu:0` before execution. Advanced
`--device auto` changes only device for the explicitly selected algorithms;
`--device cpu` or `--device gpu:0` fails if unavailable. No runtime device retry occurs.

`sfm resolve` only plans features/matching/verification, not mapping or training. It emits
a `ResolvedFeatureMatchingRoute` JSON document. `matches run --resolved-route <file>`
requires a feature artifact with exactly those extraction settings; it never re-extracts.
Use `verification run --resolved-route <file>` to retain the same profile provenance.
Low-level stage commands otherwise use explicit `--matcher` or versioned `--settings`
JSON, and verification accepts `--camera-priors` JSON. Unknown settings/flags and
incompatible signatures fail. See [M7b contracts, profiles and provisioning](docs/M7B.md).

Matching consumes exactly the external M6 PairSet using `matches_importer --match_type
pairs`, disables native geometric verification and publishes immutable `MatchSet` v1,
including requested zero-match pairs. Standalone `geometric_verifier` consumes a private
copy and current camera priors, publishing `VerifiedGeometrySet` v1. Verification-only
or camera-prior changes reuse raw matches. Both stages use existing durable attempts,
cancellation, recovery and separate PAIRS/ETA history, without writable upstream links.
Real CPU and GPU integration passes for all ten matcher types in all thirteen
compatible SIFT/ALIKED/LoMa combinations on COLMAP 4.2.1. GPU validation uses an
explicitly provisioned isolated CUDA 12.8/cuDNN 9.27.0.42 runtime; the original
installation remains unchanged. See [controlled Windows GPU runtime](docs/GPU_RUNTIME.md)
for setup, selection and validation commands. GPU availability remains machine-specific.
Official weights were explicitly staged and SHA-verified separately for M7b.2 validation.
These tiny fixtures prove execution/contracts, not quality superiority. Model roots are
explicit/manual; the default read-only lookup is `%LOCALAPPDATA%/SplatForge/models/colmap`.
Doctor reports exact missing paths and reference SHA evidence. Processing never downloads weights.

For programmatic editing:

```python
from pathlib import Path
from splatforge.bootstrap import build_project_service

projects = build_project_service()
root = Path("C:/SplatForge Projects/First scene")
document = projects.open(root)
document.label = "Renamed scene"
document = projects.save(root, document)
```

Python 3.12 is the tested baseline. Windows tests exercise Job Object cancellation,
timeout, owner-death descendant cleanup and local fixed-volume read leases that deny
write/delete while allowing readers. Default tests require no FFmpeg installation; set
`SPLATFORGE_TEST_FFPROBE` for the generated-PNG real FFprobe test and
`SPLATFORGE_TEST_FFMPEG` to an FFmpeg executable (or `1` for configured PATH lookup)
and `SPLATFORGE_TEST_FFPROBE` together for VFR source-origin, asymmetric display-matrix
rotation and PNG EXIF pixel integration tests. PNG inventories with historical unknown
orientation require `media add` followed by selection of the new `--source-id` for
view preparation. Candidate images must fully
decode within the documented resource bounds; old corrupt publications are ineligible.
New plans re-observe FFmpeg, then pin its concrete binary identity. Set
`SPLATFORGE_TEST_COLMAP` to an absolute executable, or `1` for
`SPLATFORGE_COLMAP`/safe-PATH resolution, to opt into real M5 identity, command and
native-database checks. `SPLATFORGE_TEST_COLMAP_DEEP=1` also enables disposable CPU/GPU
SIFT smoke checks; a missing functional GPU is reported rather than assumed. Default
tests still require no COLMAP, GPU, model files or network. The same COLMAP opt-in also
runs tiny real M7a SIFT publication/cache/immutability tests. Add
`SPLATFORGE_TEST_COLMAP_LEARNED=1` with `SPLATFORGE_COLMAP_MODEL_DIR` to test each learned
route only when functional capability is verified; missing prerequisites skip with a reason.
`SPLATFORGE_TEST_COLMAP_FEATURE_GPU=1` selects GPU for these extraction tests.

Future SplatForge releases should prefer the current stable upstream toolchain only
after compatibility testing and should pin each shipped backend by exact identity/hash.
New upstream binaries are not trusted automatically. A newer tested runtime may be
shipped side-by-side; it must not reinterpret the concrete provenance of older work.

### Reconstruction foundation and explicit mapping (M8a / M8b1)

```powershell
splatforge mapping run "C:\Scenes\Example" --verification-run <uuid> --method global --calibration preserve-priors --colmap "C:\COLMAP\bin\colmap.exe" --json
splatforge mapping run "C:\Scenes\Example" --verification-run <uuid> --calibration view-graph --min-model-size 3 --num-threads 1 --json
splatforge mapping run "C:\Scenes\Example" --verification-run <uuid> --method incremental --ba-backend ceres --json
splatforge mapping run "C:\Scenes\Example" --verification-run <uuid> --method incremental --ba-backend caspar --gpu-index 0 --json
splatforge mapping show "C:\Scenes\Example" <mapping-run-id> --json
```

The tested production floor is COLMAP >=4.2.1 (currently positively validated 4.2.1;
4.2.0 and untested later versions are refused). Global publishes every valid disconnected
component in immutable ReconstructionSet v1, with stable SplatForge component UUIDs and
separate geometry digests. It never selects model 0/largest/first or retries another mapper.
The backend-neutral reader exposes cameras, registered views/poses and unregistered UUIDs;
point/track streaming is unavailable (`not_published`), while native files/counts are preserved.
Coordinates are right-handed camera-from-world, X right/Y down/Z forward, wxyz quaternion;
SfM scale is unknown/arbitrary. M10 preserves it in the undistorted dataset.

Calibration defaults to preserve-priors. Explicit view-graph calibration modifies only an
independent private DB, preserves original priors and records its estimator result separately
from final optimized intrinsics. It is never selected automatically from device/EXIF type.
M7 artifacts remain byte-identical. Existing progress/cancel/recover/cache machinery is reused;
nonlinear mapping has phase-only progress without an invented percentage. Incremental Ceres
is an explicit alternative with native multi-model disabled: overlapping native hypotheses
cannot be disjoint ReconstructionSet components. It publishes one component plus all
unregistered views, disables sparse color extraction and uses verified cameras directly.
Caspar is capability-gated Incremental BA, not a mapper, with PINHOLE/SIMPLE_RADIAL-only
cameras and no Ceres fallback. The route is implemented; the existing local runtime lacks
compiled Caspar, so real Caspar validation remains false. There is no automatic build/install.
M8b2 adds Hierarchical internal clustering/native merging, separate explicit Global GP/BA GPU
gates and sequential mapper comparison. Final Hierarchical overlaps and requested GPU CPU
fallback are refused. Technical M8 is complete; representative recommendation remains pending.
M7c's production VPR benchmark remains pending independently. M9 validation is described
below; M10 dataset preparation is documented next.
See [M8a](docs/M8A.md), [M8b1](docs/M8B1.md) and [M8b2 contracts/evidence](docs/M8B2.md).

### Reconstruction validation and explicit selection (M9)

```powershell
splatforge reconstruction validate "C:\Scenes\Example" --mapping-run <uuid> --json
splatforge reconstruction validation-show "C:\Scenes\Example" <validation-run-id> --json
splatforge reconstruction validate "C:\Scenes\Example" --mapping-run <uuid> --policy custom.json
splatforge reconstruction select "C:\Scenes\Example" --validation-run <uuid> --mode recommended
splatforge reconstruction select "C:\Scenes\Example" --validation-run <uuid> --component <a> --component <b>
splatforge reconstruction selection-show "C:\Scenes\Example" <selection-run-id> --json
```

M9 freezes the exact historical selected-view source/camera grouping, canonically hashes
the detailed sparse geometry separately from M8, then publishes measurements and a separate
policy report. Coverage denominators always use M7 selected views. Human inspection shows
source-group imbalance, camera diagnostics, tracks, reprojection/triangulation availability
and structured PASS/WARN/FAIL evidence. Threshold changes reuse measurements; unknown
metrics stay explicit. The conservative baseline warns on unbenchmarked heuristics and
supports explicit custom hard thresholds. It never mutates/reruns M8 or merges components.
See [M9 contracts and policy thresholds](docs/M9.md).

Manual selection retains one or several separate components. Automatic
`selection.dominance_v1` compares registration, every source group's coverage and validation
severity transparently. Coverage tradeoffs/equal evidence are AMBIGUOUS and require manual
selection; largest/first is never a tie-break. Applicable FAIL gates require exact
`--override-issue` IDs and a non-empty `--override-reason`, bound to reconstruction,
report and selected content. Changed geometry under the same component UUID invalidates
old choices/overrides. Reason/policy changes with identical selected content preserve
downstream numerical semantics. M10 consumes this selection and prepares separate datasets.

### Trainer-ready flat-camera datasets (M10)

```powershell
splatforge dataset plan "C:\Scenes\Example" --selection-run <selection-run-id> --colmap "C:\Runtime\bin\colmap.exe" --json
splatforge dataset prepare "C:\Scenes\Example" --selection-run <selection-run-id> --json
splatforge dataset prepare "C:\Scenes\Example" --selection-run <selection-run-id> --max-image-size 2400 --json
splatforge dataset show "C:\Scenes\Example" <dataset-run-id> --json
splatforge run active "C:\Scenes\Example" --json
splatforge project cleanup "C:\Scenes\Example" --dry-run --json
splatforge project cleanup "C:\Scenes\Example" --apply --preview <dry-run-preview-digest>
splatforge project pin "C:\Scenes\Example" <artifact-uuid>
```

Continue the explicit M9 selection above; a mapping run alone is insufficient. The plan
checks current selection/override, exact historical pixels, undistorter capability,
registered membership, disk estimates, cache and warnings. `prepare` uses COLMAP 4.2.1
`image_undistorter` with independent input copies and publishes validated images,
flat PINHOLE/SIMPLE_PINHOLE cameras, unchanged poses and sparse points/tracks under
`images/`, `sparse/0/` and `dataset.json`. Each selected component remains independent.
The DatasetSet receipt references these ready component directories without copying
their images. No second export is needed and no training is invoked.

Original source files may be unavailable after M3: M10 reads the exact immutable
CandidateViewSet selected by historical M9 lineage. Corrupt/missing historical pixels
fail without reopening originals. Default resolution is native undistorted resolution;
an explicit max side changes cameras and pixels together through COLMAP and invalidates
M10 only. Scale remains unknown/arbitrary. `run show/progress/cancel/recover` inspect
or control component/receipt runs; restart with `dataset prepare` reuses completed
components. Cleanup requires an exact preview, protects current/pinned/active lineage
and originals, and durably marks removed generated payloads evicted.

DatasetPreparation can consume valid explicit selections from reference pairing now.
**Production automatic multi-video E2E acceptance still requires M7c production VPR
selection**; an Exhaustive pilot does not satisfy that gate. M11 consumes these same
published datasets independently of that production retrieval gate.
See [M10 defaults, layout, validation, resources and cleanup](docs/M10.md).

## Intended workflow

Create project -> register sources -> decode/preprocess candidate views -> assess
quality and select views -> optional masks -> extract features and select pairs ->
match and geometrically verify -> reconstruct -> validate -> select reconstruction
components -> prepare training dataset -> optional training -> export/view.

Feature extraction and pair selection have independent inputs; this summary is not
a mandatory linear execution order. A project can stop at a validated training
dataset for use in an external trainer.

- Feature technology ladder: LoMa, ALIKED + compatible LightGlue, and SIFT + brute-force;
  all remain supported. Simple profiles resolve a recorded route before execution;
  Advanced selection does not fall back. COLMAP Global Mapper is the implemented M8a preferred
  mapper; M8b1 adds explicit Incremental Ceres / capability-gated Caspar BA and M8b2
  implements Hierarchical / explicit Global acceleration. Representative recommendation
  benchmarking remains pending; no automatic fallback or universal winner is added.
- Ordered video starts with within-clip Sequential pairs. Practical multi-video
  support combines these with cross-clip retrieval from M7c, before the complete CLI.
  Retrieval has explicit representation/index requirements independent of ALIKED.
- Preserve originals; show progress, failures and reconstruction quality; resume
  valid work. Training changes must not rerun decoding or SfM.

The CLI can stop at a validated dataset or continue through an explicitly configured
external gsplat runtime to checkpoints and independently validated Gaussian scenes.
Run `splatforge training handoff`, `training plan`, `training run`, `training show`
or `training compare`; see [M11 commands and runtime setup](docs/M11.md).
The optional desktop GUI uses the same application services. No universal quality preset is adopted.
Later work includes masks/segmentation, GPS, LiDAR, alternative SfM/training methods,
large-scene automation, batch jobs and 360 workflows. Previously successful 3DGS work
may be researched read-only earlier without blocking implementation; official preset
translation/benchmarking stays with training integration.

## Documentation

Use the [documentation map](docs/index.md) to find authoritative owners, active plans,
research and historical milestone notes. Contributors start with [AGENTS.md](AGENTS.md)
and read only the sections relevant to the task. The
[development workflow](docs/DEVELOPMENT.md#verification-workflow) defines affected/full
checks; [durable plans](docs/DEVELOPMENT.md#durable-plans) replace growing prompt lists.

Keep source media, generated projects, model weights and training output outside the
repository. M6 PairSet is implemented. The separate pre-M7 scalability/operability
pass, M7a feature extraction and M7b matching/verification are implemented;
M7c's offline retrieval/hybrid foundations are implemented, while production retrieval
inference and model selection remain pending. Real learned-route integration requires a configured
compatible model/runtime and is not established by fixture tests alone.
