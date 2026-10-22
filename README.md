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
availability and real integration validation are reported separately. Retrieval,
mapping, training and GUI remain planned.
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
are shared Application contracts for the future GUI; no GUI exists yet. All routes are
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
  Advanced selection does not fall back. COLMAP Global Mapper remains a planned preferred
  mapper, with explicit Incremental/Hierarchical alternatives in M8.
- Ordered video starts with within-clip Sequential pairs. Practical multi-video
  support combines these with cross-clip retrieval from M7c, before the complete CLI.
  Retrieval has explicit representation/index requirements independent of ALIKED.
- Preserve originals; show progress, failures and reconstruction quality; resume
  valid work. Training changes must not rerun decoding or SfM.

The first usable release is a complete CLI pipeline producing a validated dataset.
Training integration follows, then a GUI using the same application services.
Later work includes masks/segmentation, GPS, LiDAR, alternative SfM/training methods,
large-scene automation, batch jobs and 360 workflows. Previously successful 3DGS work
may be researched read-only earlier without blocking implementation; official preset
translation/benchmarking stays with training integration.

## Documentation

| Document | Responsibility |
| --- | --- |
| [AGENTS.md](AGENTS.md) | Authoritative engineering rules and task completion checks |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Product boundaries, dependency direction and decisions |
| [Pipeline contracts](docs/PIPELINE.md) | Stage inputs/outputs, compatibility and invalidation |
| [Project format and state](docs/PROJECT_FORMAT.md) | Storage ownership, migrations, attempts and recovery |
| [Development guide](docs/DEVELOPMENT.md) | Testing, diagnostics and Windows/backend risks |
| [Architecture review](docs/ARCHITECTURE_REVIEW.md) | Evidence from the original foundation and deferred decisions |
| [Legacy research](docs/LEGACY_3DGS_RESEARCH.md) | Optional read-only evidence gathering before later preset evaluation |
| [ROADMAP.md](ROADMAP.md) | Incremental, verifiable milestones |
| [Codex prompts](docs/CODEX_PROMPTS.md) | Scoped implementation tasks aligned with the roadmap |

Keep source media, generated projects, model weights and training output outside the
repository. M6 PairSet is implemented. The separate pre-M7 scalability/operability
pass, M7a feature extraction and M7b matching/verification are implemented;
M7c's offline retrieval/hybrid foundations are implemented, while production retrieval
inference and model selection remain pending. Real learned-route integration requires a configured
compatible model/runtime and is not established by fixture tests alone.
