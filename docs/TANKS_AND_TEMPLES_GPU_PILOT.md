# Ignatius: learned features and GPU solver follow-up

2026-10-26. The second diagnostic end-to-end pilot is complete, with limited visual
quality and no held-out metric improvement. Both additional GPU mapper routes pass
M8/M9; they were not trained. The [machine-readable result](tanks-and-temples-ignatius-gpu-pilot.json)
pins commands, settings, identities, split, metrics and evidence references. The
[first pilot](TANKS_AND_TEMPLES_PILOT.md) owns data provenance and the baseline.
This is not an official T&T geometry benchmark.

## Scope and fixed settings

The second end-to-end candidate is matrix **IGN-037**: ALIKED_N16ROT GPU +
ALIKED_LIGHTGLUE GPU, Exhaustive 34,453 pairs, separate geometric verification,
Incremental Ceres CPU, M9, explicit component selection, M10 and gsplat.default.
All 263 original photographs are reused unchanged. Camera sharing and approximate
initial SIMPLE_RADIAL intrinsics are identical to the baseline.

ALIKED uses max_features=2048, max_image_size=2048, min_score=0.2. SIFT used 8192;
this compares recorded configurations, not equal feature counts. Training remains
7,000 steps, seed 42, factor 2 and the exact baseline 230/33 source-name/view-ID
split. Eval frames participate in SfM but must not optimize Gaussians.

Separate mapper-only comparisons reuse the baseline's SIFT/BF verified geometry:
Incremental Caspar GPU0 and Global positioning + Ceres BA GPU0. They do not count
as completed end-to-end matrix cells without downstream training and evaluation.
Incremental Ceres is currently a CPU route; Global Ceres has separate GPU switches.
Selecting the name Ceres alone does not establish GPU execution.

## Storage and identities

External evidence directory (`$e`):
`C:\SplatForgeData\benchmarks\tanks-and-temples\Ignatius\gpu-methods-20261026`.
The production project (`$p`) remains the original
`C:\SplatForgeData\benchmarks\tanks-and-temples\Ignatius\pilot-20261026\project`.
Published baseline artifacts are retained; new runs have their own attempts/artifacts.
Each command has `.command.json`, `.result.json`, stdout JSON and stderr log in `$e`.
Fresh post-computation SHA-256 checks confirm all 263 originals and the source
archive are unchanged. Old/new executable and reused cuDNN identities remain
unchanged, and the observed process PATH matches its original hash.

The learned-feature pipeline deliberately retains the original COLMAP 4.2.1
runtime, executable SHA-256
`9418a14c93d4a5eec5eb33ebf48a917403b5faa7ab5d2232f23e50c206d9e427`.
For representative Ignatius runs, only the explicit GPU mapper comparisons select
the new runtime below; the separate GPU integration matrix also uses that bundle. Training
uses the existing Python 3.12.10 / Torch 2.7.1+cu128 / gsplat 1.5.3 environment,
RTX 5080 (compute 12.0, 16 GiB), driver 610.62. Exact worker/package/device identities
are saved in the JSON; installation or inventory alone was not accepted as execution.

The authorized third-party [lyehe/build_gpu_colmap release](https://github.com/lyehe/build_gpu_colmap/releases/tag/v4.2.1)
provided `COLMAP-4.2.1-windows-2022-CUDA-cuDSS-Caspar.zip`, 1,964,594,756 bytes,
SHA-256 `a36bc01763b3ecf50a43ebf541a3727e209998479a1821fd7900b33b75e2b4aa`.
It matches GitHub asset metadata and the publisher's SHA256SUMS.txt. Every extracted
member passed CRC/path checks; all 790 base files also match the separate full bundle.
This is a third-party build, not a COLMAP project release binary.

Publisher build_info: COLMAP 4.2.1, commit
`bd1fcf654d2dd8fefa1466999c190a246f83f4b9`, CUDA 12.8.1, cuDSS 0.7.1.4,
Caspar enabled, build date 2026-10-13. Executable SHA-256:
`d775560554491b3f5aef4f2752048d5ca9df0b2be31b91d948a67657e55b9550`.

The bare archive lacks cuDNN. The complete, separate runtime is
`C:\SplatForgeData\runtimes\colmap-4.2.1-cuda-cudss-caspar-cudnn9.27-20261026\unpacked\bin\colmap.exe`.
It adds the ten existing verified cuDNN 9.27.0.42 CUDA12 DLLs and license; individual
SHA-256 values and source paths are in `complete-runtime-identity.json`, the bundle
manifest and `complete-runtime-base-inventory.json`. No weights/toolchains were
installed. Existing runtimes and system PATH are not replaced.

## Measured stages

Times are full CLI process wall time, including preparation and publication; native
solver time is separately available. They are observations on a shared workstation,
not an isolated hardware performance comparison. Reused views and PairSet have no
fresh native work in this experiment.

| Stage | Actual wall time | Result / run |
| --- | ---: | --- |
| ALIKED_N16ROT GPU | 44.141 s | 537,682 features; `7eda323b-2ed8-42b4-ba83-cbce8314a232` |
| ALIKED_LIGHTGLUE GPU | 1,465.063 s | 6,250,618 raw matches; `b3117a07-0271-41a2-bc00-680e67d6963b` |
| Separate verification | 579.578 s | 26,308 accepted pairs / 5,156,155 inliers; `61ad10e9-5b19-4024-a05c-19666dc2a320` |
| First Incremental attempt | 172.922 s, failed | disappearing journal; `fa8179f9-75ad-40e1-a352-6fb0371f81eb` |
| Incremental after fix | 441.828 s | native 233.843 s; `dd80f99b-54db-40d6-a544-9a11cc42f096` |
| M9 validation | 123.250 s | PASS, no issues; `65e61d31-a0f1-4581-84b4-ae34c7d54d26` |
| M9 report read/revalidation | 36.781 s | separate from validation compute |
| Explicit selection | 38.125 s | sole component, no override; `15caf2c5-c717-4a6f-8939-00843c14cd4f` |
| M10 plan | 51.344 s | runnable; not dataset preparation time |
| M10 preparation | 226.969 s | `1fc26218-5060-45cd-9430-37b28ab61dfe`; native undistortion 22.406 s |
| Training plan | 89.422 s | runnable; separate from training work |
| Training, eval, checkpoint and PLY export | 435.343 s | 7000 steps; active training 227.125 s; no cache hit |
| PLY repeat validation | 89.875 s | stock `training show` passes |
| Independent PLY loading and rendering | 7.781 s | plyfile parameters/render checks pass |

All completed processing rows above are cache_hit=false. Reconstruction has one
component, 263/263 registered (100%), 52,762 sparse points and 477,991 supported
reprojection observations. M9 mean error 1.179510 px, RMS 1.419608 px, sampled p95
2.820101 px (10,000 observations out of 477,991). Baseline mean/RMS were
0.914202/1.106648 px. Neither registration nor this error alone proves visual quality.

The native LightGlue GPU PID was observed in NVIDIA's compute-process inventory.
WDDM reported its process memory as unavailable; that is not a measured VRAM peak.
The matching progress adapter did not expose committed pair progress within the
batch; read-only inspection confirmed continued database work. No progress-based
algorithm changes or retries were made.

The independent pre-training reader passed full image hashes/decoding, camera/pose
and reciprocal sparse-track checks. All 263 M10 images are 1978x1113, one PINHOLE
camera (fx=fy=1160.524922, cx=989, cy=556.5), arbitrary reconstruction scale.
At factor 2, the estimated raw RGB cache payload is 379,419,960 bytes if all 230
training views fit; this excludes container overhead and is not measured process RAM. The exact
33 held-out source names and IDs match the baseline settings byte-for-value.
All sparse RGB values are zero because this route explicitly disables color
extraction; this is preserved and disclosed, not treated as measured black scene
color. The existing float32 SH initialization permits color learning.

Baseline M10 images were 1973x1110. Each reconstruction induces its own small
intrinsic/undistortion differences, so eventual PSNR/SSIM compare whole configured
routes, not an isolated extractor intervention on identical target pixels.

## Training result

Checkpoint run `7042875b-134c-45da-ac13-a3ed078d22d5`; scene run
`426413f9-a9ef-49b6-8903-79db56813879`. The published scene is
`C:\SplatForgeData\benchmarks\tanks-and-temples\Ignatius\pilot-20261026\project\artifacts\gaussian_scene\fcd1803d-2c38-40d4-9be1-d7cde65eb89d\scene.ply`.

| Measurement | ALIKED/LG pilot | Original SIFT/BF baseline |
| --- | ---: | ---: |
| Eval views / training steps | 33 / 7000 | 33 / 7000 |
| Worker macro PSNR | 17.023498 dB | 17.500848 dB |
| Worker macro SSIM | 0.609812 | 0.651055 |
| Gaussians | 1,768,795 | 2,076,201 |
| PLY bytes | 438,662,692 | 514,899,380 |
| Active training seconds | 227.125 | 149.797 |
| Full training CLI seconds | 435.343 | 539.063 |
| PyTorch peak allocated CUDA bytes | 2,804,570,624 | 3,289,412,096 |

Allocated CUDA peak covers initialization through the training-loop boundary,
excluding subsequent evaluation/export. It is not total device VRAM or reserved
memory. LPIPS is unavailable; no weights are downloaded. Last sampled training
loss 0.143195 is not an evaluation score. The newer frontend does not improve
these held-out metrics; the small M10 target-pixel differences and shared machine
load limit strictly isolated quality/performance attribution.

## PLY and visual review

The stock PLY validator passes. Independent plyfile 1.1.3 loading agrees with
checkpoint parameters, accounting for normalized quaternions. The independent
loader/camera assembly uses the same gsplat 1.5.3 rasterizer, not a separate render
engine. On the first held-out view, checkpoint-vs-PLY renders differ by mean
5.1459e-8 and max 0.00067949. All 33 independent eval renders give macro PSNR
17.031797 dB after clamping; the worker's 17.023498 dB uses its original unclamped
metric. This small metric difference is not export corruption.

Manually reviewed all six names 000001, 000049, 000105, 000153, 000209 and 000257,
using both reference/render/difference sheets and raw-original/render sheets;
000001 and 000257 pairs were also inspected at full resolution. Files are in
`$e\visuals`: `comparisons-1.png`, `comparisons-2.png`,
`original-comparisons-1.png`, `original-comparisons-2.png` and per-view pairs.
Raw originals are display-resized; quantitative targets are the prepared M10 images.

The statue silhouette, gross camera pose and pedestal position agree across views.
Foreground colors are broadly plausible. Foliage, lawn, facade windows and bench
detail are blurred or smeared. Black/green elongated floating splats and incomplete
background coverage are visible at the upper edge in 000001; green streaks cross
sky in 000049. Water/paving and pedestal details look melted, with distorted small
plaques and reflections. There is no large missing foreground body or whole-scene
pose reversal, but background defects remain substantial.

Verdict: a completed reproducible diagnostic run, not a quality improvement or
accepted full-scene reconstruction. M9, the independent M10 reader and checkpoint/
PLY agreement do not demonstrate an export or gross pose-convention bug. Feature
budget, different geometry and limited fitting are plausible contributors, not
independently isolated causes. Preserve this result; no tuning sweep or speculative
numerical repair was made.

## Failures and bounded repairs

1. The workspace resource monitor enumerated `mapping.db-journal`, then SQLite
   removed it before stat. FileNotFoundError incorrectly aborted a valid mapper.
   Ignore only a disappearing optional file during that scan. Required mapping.db
   and final payload checks remain strict. Regression tests cover all three mapper
   families and refusal when the required database disappears. The failed run and
   workspace remain preserved; the retry restarts the stage from the same published
   geometry, not a solver checkpoint. Numerical settings are unchanged.
2. The first 18-case GPU integration run used the bare new archive: 2 passed,
   16 failed. Twelve learned cases lacked cuDNN; three Global cases hit the test
   fixture's 100 MB view workspace budget before mapping; a Caspar repeat encountered
   the same journal race. Logs/JUnit remain `native-gpu-integrations.*`.
3. The 60-view GPU fixture now explicitly budgets at least 4 MiB/view. This changes
   test resources only, not production defaults or numerical settings. The complete
   runtime reuses existing cuDNN. A fresh 18-case run is recorded separately as v2.

## Reproduction

Use the existing environment and immutable baseline project. Settings JSON and the
exact resolved command arrays live in `$e`; a fresh project must use its own upstream
run IDs. Repeating a command on unchanged published inputs should cache-hit and is
not a fresh timing observation. Keep each evidence destination new.

```powershell
$cli = 'C:\Dev\SplatForge\.venv\Scripts\splatforge.exe'
$b = 'C:\SplatForgeData\benchmarks\tanks-and-temples\Ignatius\pilot-20261026'
$e = 'C:\SplatForgeData\benchmarks\tanks-and-temples\Ignatius\gpu-methods-20261026'
$p = "$b\project"
$old = 'C:\Dev\SplatForge\sample_data\runtimes\colmap-4.2.1-cuda12.8-cudnn9.27.0.42\bin\colmap.exe'
$gpu = 'C:\SplatForgeData\runtimes\colmap-4.2.1-cuda-cudss-caspar-cudnn9.27-20261026\unpacked\bin\colmap.exe'
$models = 'C:\Users\Administrator\.cache\colmap'
& $cli features extract $p --views-run 7c36998d-5eb9-4c8b-b77a-076614725277 --method ALIKED_N16ROT --gpu --max-features 2048 --max-image-size 2048 --min-score 0.2 --max-views 263 --max-workspace-gib 32 --timeout 3600 --colmap $old --colmap-model-dir $models --json
& $cli matches run $p --features-run 7eda323b-2ed8-42b4-ba83-cbce8314a232 --pairs-run 35ba9623-7e3e-44a2-a5f4-78c4c4c533c7 --settings "$e\matching-settings.json" --resource-limits "$b\matching-limits.json" --colmap $old --colmap-model-dir $models --json
& $cli verification run $p --matches-run b3117a07-0271-41a2-bc00-680e67d6963b --camera-priors "$b\camera-priors.json" --settings "$b\verification-settings.json" --resource-limits "$b\matching-limits.json" --colmap $old --json
& $cli mapping run $p --verification-run 61ad10e9-5b19-4024-a05c-19666dc2a320 --method incremental --settings "$b\mapping-settings.json" --calibration preserve-priors --max-views 263 --max-pairs 35000 --max-workspace-gib 32 --max-output-gib 8 --timeout 7200 --colmap $old --json
& $cli reconstruction validate $p --mapping-run dd80f99b-54db-40d6-a544-9a11cc42f096 --json
& $cli reconstruction select $p --validation-run 65e61d31-a0f1-4581-84b4-ae34c7d54d26 --component 80f4d3c0-d0a4-5503-8b2c-c92728a3043d --mode manual --reason 'Sole component, all 263 frames, M9 PASS without override' --json
& $cli dataset prepare $p --selection-run 15caf2c5-c717-4a6f-8939-00843c14cd4f --colmap $old --json
& $cli mapping compare $p --verification-run 8f310d36-6c06-446f-b83c-23412ea9174b --routes "$e\gpu-mapping-plan.json" --colmap $gpu --json
$trainer = 'C:\Dev\SplatForge\sample_data\m11-review\runtime.json'
& $cli training plan $p --dataset-run 1fc26218-5060-45cd-9430-37b28ab61dfe --runtime $trainer --settings "$e\training-settings.json"
& $cli training run $p --dataset-run 1fc26218-5060-45cd-9430-37b28ab61dfe --runtime $trainer --settings "$e\training-settings.json"
```

GPU integrations use a scoped child environment; exact commands are saved in
`native-gpu-integrations-v2.command.json`. All 13 compatible GPU extractor/matcher
cases, three separate Global GPU modes and Incremental Ceres/Caspar are requested.
The v2 run passed **18/18**, zero failures/errors/skips, in 2,447.919 pytest seconds
(runner 2,448.360 s). Warnings concern record_property with xunit2; properties remain
present in the saved XML. All 13 matching routes resolved explicitly to gpu:0.
Native tiny transport tests do not establish Ignatius reconstruction quality.

| Real transport case | Views registered | Native mapper seconds | API seconds |
| --- | ---: | ---: | ---: |
| Global GP GPU / BA CPU | 60/60 | 12.218 | 44.578 |
| Global GP CPU / BA GPU | 60/60 | 12.141 | 45.891 |
| Global GP GPU / BA GPU | 60/60 | 11.187 | 45.531 |

Each Global case contains positive phase-scoped Ceres GPU solver evidence and
fallback_evidence_absent=true. Its later repeat cache-hits; the native/API times
above refer to the first uncached execution, not the cache validation call.
Incremental Ceres and Caspar also pass publication, cache, settings recomputation,
immutable upstream bytes and real cancellation with confirmed teardown/no artifact.

## Representative GPU mapping

Both routes consume the exact baseline SIFT/BF verified geometry, run
`8f310d36-6c06-446f-b83c-23412ea9174b`. The complete comparison command, per-route
API times and requested/resolved settings are retained separately from native time.

| Route | M8 coverage / points | Native seconds | Comparison API seconds | M9 |
| --- | --- | ---: | ---: | --- |
| Incremental Caspar GPU0 | 263/263, one component, 123,627 points | 137.969 | 380.265 | PASS, no issues |
| Global Ceres GP+BA GPU0 | 263/263, one component, 123,851 points | 185.500 | 401.297 | PASS, no issues |

Caspar run: `31c43b0d-1274-4130-aef5-0d14d4dbe4b6`. Publication requires positive
Caspar solver execution and no unsupported-camera/observation-skip/CPU fallback
evidence. The selected device is the same RTX 5080/GPU0 validated in preflight.
The old CPU Ceres baseline native duration was 326.656 s; runtime builds and
concurrent workstation load differ, so this is an observation, not an isolated
solver speedup claim.

Caspar M9 run `475565ce-dabf-49be-8e3e-11e44e4770ca`: mean reprojection
0.937200 px, RMS 1.138082 px, sampled p95 2.167039 px (10,000 out of 847,055
observations). Validation CLI 214.735 s; separate report read/revalidation 21.891 s.
This is close to, but not numerically identical with, the CPU Ceres baseline.

Global M9 run `94e5ca60-802f-474e-8b0c-0b82bff4048a`: mean reprojection
0.925994 px, RMS 1.201048 px, sampled p95 2.473586 px (10,000 out of 857,065
observations). Validation CLI 197.735 s; separate report read/revalidation 22.000 s.
Both GPU mapper components pass without overrides. Neither was trained in this
follow-up; these are M8/M9 acceptance results, not new completed end-to-end cells.

Global run: `ef60b992-6f85-4572-b5ff-728a69791160`. Both gp_gpu_validated and
ba_gpu_validated are true; fallback_evidence_absent=true. Final complete logs are
retained in `global-native-final-logs`, with per-file SHA-256 and a successful
replay of the stock GPU execution validator across all requested phases/refinement.
The complete comparison CLI command took 854.828 s, including initial common-input
verification outside the two API timings. Both routes are cache_hit=false.

One RAM observation during native Caspar reports resident working set 617,406,464
bytes and the OS peak-so-far 665,645,056 bytes at 17:14:01.786 UTC. It includes
shared pages and is not the final full-run peak, private memory or GPU VRAM.
The exact observation is `caspar-memory-observation.json`; GPU process VRAM under
WDDM remains unavailable.

Global's native log warns that fewer than half the cameras have prior focal lengths.
The shared f=1344 seed is intentionally an estimate with prior_focal_length=false,
not a calibration. This comparison keeps preserve_priors frozen; no view-graph
calibration is silently inserted. If Global geometry is worse, a separately frozen
view-graph-calibration experiment is a candidate, not an automatic retry.
The log also reports unavailable color images. This is the documented
[M8 geometry-only transport](M8A.md#supported-backend-and-explicit-settings): the mapper's image directory is owned
and empty; geometry consumes verified keypoints/constraints. No measured sparse
colors or source-pixel access are claimed. This is distinct from skipped geometric
observations, which Caspar explicitly refuses. The warnings remain in evidence.

## Verification

Codex ran the affected mapping/race suites and all four final race regressions;
changed Python files pass Ruff. Full default `python -m pytest -rs`:
**1629 passed, 72 skipped, 51 warnings in 3794.94 s** (runner 3796.016 s).
Integration opt-ins were absent. Skips require configured native tools, FFmpeg/
FFprobe, training runtime, cross-source or retrieval fixtures; the separately
configured GPU run above passes all 18 requested cases without skips.

`python -m ruff check .` retains only the existing E501 at
`src/splatforge/core/registry.py:52` (101 > 100 characters); that unrelated line was
not changed. Documentation links and diff whitespace are checked separately after
final report edits. The default suite's captured 297 Python-file hashes match the
final source tree; documentation edits do not invalidate that result.
Full logs/JUnit/commands are `$e\pytest-gpu-fix.*`, `ruff-gpu-fix.*` and
`native-gpu-integrations-v2.*`. No commit or push is made.

## Limits and next experiment

The thirteen tiny GPU passes do not clear the first pilot's invalid GPU SIFT
keypoints on Ignatius. That full-scene GPU SIFT case was not rerun with the new
build; baseline SIFT remains explicitly CPU. Learned routes were tested in FP32;
no BF16 support or all-scene quality guarantee is claimed.

The next bounded full benchmark should select the already PASS Caspar component,
prepare its M10 dataset and train the same 7k/seed42/factor2/split recipe. This tests
the rendered consequence of the GPU mapper without repeating M7. Keep its PLY and
metrics separate from this ALIKED/Ceres run. A subsequent Truck run can then use a
visually checked route with fresh camera/runtime/resource diagnostics. No Truck
data or new full LoMa-G scene run was started in this follow-up.
