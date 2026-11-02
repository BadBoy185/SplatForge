# Tanks & Temples: Ignatius pilot

Local, non-commercial research run on 2026-10-26. This is an image-to-Gaussian
pipeline pilot, with held-out image evaluation; no official T&T geometry score or
universal preset recommendation is claimed.

The proposed [benchmark matrix](TANKS_AND_TEMPLES_BENCHMARK_MATRIX.md) counts
method combinations separately from this pilot's measured execution evidence.

## Data and ownership

Only the [official Ignatius image set](https://storage.googleapis.com/t2-downloads/image_sets/Ignatius.zip)
was downloaded, following the [official download page](https://tanksandtemples.org/download/).
No videos, other scenes, laser scans, pretrained models or reference reconstructions
were downloaded. Existing toolchains and the existing isolated trainer environment
were reused.

| Record | Value |
| --- | --- |
| Images | 263 JPEGs, `000001.jpg` through `000263.jpg`, all 1920 x 1080 |
| Archive bytes | 456,110,810 |
| Archive SHA-256 | `80314fcd49f290ec97a9f262171ae573a1fc562e03727b71a8dc9466d8a3e5ea` |
| Actual archive / current official object MD5 | `3f581feda897a35918ebf85dfd2ac2e6` (match) |
| Official object generation | `1503871420776379` |
| Legacy checksum manifest MD5 | `1f86a3977fbfd260d89321c65a33ade6` (does not match current object) |
| Validation | Exact response size, ZIP CRC, full JPEG decoding and per-image SHA-256 |

The [legacy checksum manifest](https://storage.googleapis.com/t2-downloads/image_sets/image_sets_md5.chk)
differs from the [current official object metadata](https://storage.googleapis.com/storage/v1/b/t2-downloads/o/image_sets%2FIgnatius.zip).
Both responses are retained. The downloaded bytes match the current object's
`md5Hash`, not the legacy manifest. Reproduction must also match the SHA-256 above;
the object generation can be pinned in the download URL.

All archives, original images, projects, command logs, native databases, checkpoints
and rendered comparisons live outside Git:

```text
C:\SplatForgeData\benchmarks\tanks-and-temples\Ignatius\
  sources\Ignatius.zip
  sources\images\Ignatius\
  pilot-20261026\
    project\
    download.json
    publisher-metadata.json
    checksum-verification.json
    *.command.json / *.result.json / *.stdout.json / *.stderr.log
```

Originals are read-only inputs. M3 publishes independently materialized JPEGs;
their encoding and hashes are distinct from the original downloaded JPEG bytes.
No source image was renamed, recompressed or moved in place.

## Route and failures retained

The explicit baseline is all 263 photo views, Exhaustive pairing (34,453 pairs),
SIFT, compatible brute-force matching, standalone geometric verification,
Incremental Ceres, M9 validation/manual selection, M10, and one managed
`gsplat.default` training run. Photographs have no invented video timeline.

One shared `SIMPLE_RADIAL` camera starts at `f=1344`, `cx=960`, `cy=540`, `k=0`.
The focal seed is the authors' approximate `0.7 * width`, with
`prior_focal_length=false`. Ceres can refine focal length and distortion; this is
not exact calibration. Source and camera grouping are explicitly recorded.

The initial 4 GiB M3 disk estimate was insufficient; it was raised to 20 GiB with
identical numerical settings. Matching's conservative all-pairs raw-correspondence
bound is 282,238,976, above the default 100 million refusal budget. A saved
300-million budget permits the same 34,453 pairs and unchanged BF settings within
a 32 GiB workspace budget. Resource budgets are not numerical quality settings.

Two GPU SIFT attempts are retained:

1. `f369c004-5baf-4608-9290-17c9c46a3815`: native output had 8,196..12,712
   features/view despite `max_features=8192`; the old hard-limit validator refused it.
2. `9b6fedb2-0897-44f1-a193-e2e60d42e372`: after the hard-budget fix, full native
   validation found three out-of-image keypoints (`x=1940.94..1958.09`, width 1920).
   Validation remained strict and nothing was published.

A new, explicitly recorded CPU SIFT plan succeeds with 2,154,496 published features
(8192/view). GPU BF remains explicitly requested. This is an operator-recorded device
decision, not an automatic product fallback. Existing failed workspaces remain intact.

## SIFT correction

COLMAP retains whole scale levels and multiple orientations, so its native SIFT
count option is soft. SIFT adapter version 2 validates every native row first,
then transactionally retains a paired native keypoint/descriptor prefix up to the
existing hard budget in the unpublished DB. Invalid discarded tails still fail;
published artifacts are never mutated. Live progress counts retained rows.

Only the SIFT backend numerical identity changes. View/PairSet caches remain reusable;
learned extractors still refuse over-budget output. Regression tests cover paired
row alignment, publication/cache reuse, rejection of a malformed discarded tail,
unchanged learned overflow refusal and bounded progress. See the
[feature contract](PIPELINE.md#local-feature-extraction-m7a).

## Reconstruction evidence

M8 run `47bd06e3-1a06-40c0-a2c8-683ff5fea0e9` publishes component
`80f4d3c0-d0a4-5503-8b2c-c92728a3043d`. M9 report run
`1d189a22-2f63-41d1-be0f-101e8f24dbb4` is **PASS**, with no issues or overrides.
The component is explicitly selected because it is the sole produced component,
registers every input and passes the measured gate; no largest/first-model policy
is used.

| Measurement | Result | Evidence |
| --- | ---: | --- |
| Registered / selected frames | 263 / 263 | Exact |
| Components / shared cameras | 1 / 1 | Exact |
| Sparse points / observations | 123,891 / 844,227 | Exact |
| Reprojection mean / RMS | 0.914202 / 1.106648 px | Exact, original camera pixels |
| Reprojection p95 | 2.163754 px | SHA-256 bottom-k, 10,000 / 844,227 observations |
| Track mean / median | 6.8143 / 5 | Exact |
| Two-view track fraction | 2.5748% | Exact |
| Triangulation median | 7.628 degrees | Bounded rays plus 10,000 / 123,891 point quantile sample |
| Relative focal change from initial estimate | 13.7052% | Exact |
| Camera sharing mismatches | 0 | Exact |

All photos participate in SfM. The held-out image protocol excludes every eighth
original image, starting at zero-based index 0, from Gaussian optimization only.
This evaluates novel-view interpolation with known SfM cameras, not reconstruction
of wholly unseen cameras. Split membership is mapped from original names and source
SHA-256 to immutable view UUIDs, never from arbitrary UUID ordering.

Timings are CLI wall time unless identified as native or active training-loop time.
Full default pytest ran concurrently with early reconstruction/M10 stages; training
started after the final suite completed. These are operational timings, not an
isolated hardware speed comparison. Failed attempts and preflight refusals
remain separate from successful stages and cache reuse.

## M10 correction and training protocol

The first M10 component attempt `8345d769-5ac2-4894-8d43-fc5c7d51d9e6`
spent 799.078 seconds in preparation/input validation before native undistortion.
Every fine-grained sparse-validation checkpoint recursively walked the entire
image workspace to check disk budgets. It was canceled through `run cancel`;
teardown was confirmed and its workspace/attempt retained. No dataset was published.

The focused correction bounds filesystem budget polling to 250 ms while retaining
cancellation/time checks at every checkpoint and forced boundary checks. It changes
no numerical setting or fingerprint and removes no geometry/pixel validation.
The new component run `b4873e10-eb1c-480c-b8c3-2e31338c1dcc` completes and publishes
dataset artifact `645d80f8-6cd4-4a66-9a3f-6252dc72b018`; set run
`332d96ea-c5f7-466c-b55b-428a8c8d3163`. Total CLI wall time is 694.125 seconds,
including output validation/publication; this is not a directly comparable native
speedup against the incomplete canceled attempt.

Independent `read_dataset` validation checks image hashes/decoding, intrinsics,
camera convention, poses, finite sparse XYZ/RGB and reciprocal observation tracks.
All 263 views, one `PINHOLE` camera and 123,891 sparse points survive. Undistortion
expands native dimensions to 1973 x 1110, with `fx=fy=1159.8020306`,
`cx=986.5`, `cy=555`. Scale remains unknown/arbitrary.

Every sparse RGB is `(0,0,0)` because the frozen Incremental settings explicitly
set `extract_colors=false`. These are placeholder colors, not measured scene RGB.
They are preserved through M10 and initialization; the existing float32 SH-gradient
route learns color from training images. No recoloring or hidden preprocessing is used.

Training is one `gsplat.default` run: 7000 steps, seed 42, SH degree 3,
`data_factor=2`, classic rasterization, AbsGrad false, pose optimization false,
SfM initialization, no world normalization. Evaluation and checkpoint cadence are
7000. All other resolved strategy/optimizer settings are saved in the recipe.
Image resolution is therefore 986 x 555. Factor 2 was frozen before starting:
the 230 training RGB uint8 images total 377,588,700 bytes, within the worker's
512 MiB CPU image cache, and the installed GPU has 16 GiB device memory.
No automatic resolution, strategy or device retry is permitted.

`split.json` retains all 263 original-name/source-SHA/view-UUID mappings.
Names `000001.jpg, 000009.jpg, ..., 000257.jpg` are the 33 eval views; the
other 230 are optimization views. Membership is asserted disjoint before launch;
the worker samples optimization indices only from the train set. Eval cameras and
sparse initialization still originate from the all-frame SfM reconstruction.

## Runtime and interpretation

Fresh `doctor --deep` and the dedicated training capability worker positively
exercise the installed native/runtime/GPU combination, including rasterization,
backward and optimizer. This is not inferred from package versions or old reports.

| Identity | Value |
| --- | --- |
| Repository base | `9a4c8acf06407d6f0a922c83f7884b9dbb6f6c0b` plus this scoped diff |
| Application/trainer Python | 3.12.10 |
| COLMAP | 4.2.1, commit `bd1fcf6`, CUDA build |
| COLMAP executable SHA-256 | `9418a14c93d4a5eec5eb33ebf48a917403b5faa7ab5d2232f23e50c206d9e427` |
| Torch / CUDA | 2.7.1+cu128 / 12.8 |
| gsplat | 1.5.3, commit `937e29912570c372bed6747a5c9bf85fed877bae` |
| Worker SHA-256 | `182cae2c48acfb8883864f09501a51d34f06b077b00cd43c1964663cb0b586b5` |
| GPU / driver | NVIDIA RTX 5080, ordinal 0, compute 12.0 / 610.62 |
| Device capacity | 17,094,475,776 bytes; capacity, not measured peak |

`training-capability.stdout.json` records the exact GPU UUID, package digest and
kernel evidence. `code-identity-final.json` records hashes of the changed code/tests.
Seeded execution is reproducible in configuration and provenance; bitwise GPU
determinism has not been established.

PSNR and SSIM are macro averages over the 33 eval images at factor 2, against
undistorted M10 images resized with BOX. SSIM uses the existing valid-window worker
implementation. LPIPS is **unavailable**: no implementation/local weights are
configured. CUDA peak means PyTorch `max_memory_allocated` from worker reset through
the training-loop boundary, including initialization but excluding later eval/export;
it is not process VRAM, reserved memory
or total system memory. No measured CPU peak is available for the reconstruction
stages; disk refusal budgets must not be presented as RAM measurements.

Successful stage timings (fresh work, no cache hit):

| Stage | CLI wall seconds |
| --- | ---: |
| Ingest/full source hashing | 19.640 |
| Candidate/selected views | 71.406 |
| Exhaustive pairs | 3.735 |
| CPU SIFT | 774.547 |
| GPU brute-force matching | 104.266 |
| Geometric verification | 394.406 |
| Incremental mapping | 621.094 (native process: 326.656) |
| M9 validation | 537.047 |
| Manual selection | 33.437 |
| M10 preparation, corrected attempt | 694.125 |
| Training, evaluation, checkpoint and export | 539.063 |

The matcher reports 3,507,835 raw correspondences across 34,453 requested pairs;
verification accepts 12,489 pairs / 3,027,546 inliers. GPU extraction failures
cost 28.781 and 29.531 seconds; canceled M10 cost 799.078 seconds. These attempts
are excluded from the successful-stage timing rows. Upstream views/pairs are
consumed by immutable handle on retries; they are not silently recomputed or
reported as new successful work. Plans/inspection commands have their own ledger
entries and are not native-stage execution times.

Stored process/attempt logs further separate the expensive checks:

| Command | Measured internal work | Remaining command wall time |
| --- | --- | ---: |
| Geometric verification, 394.406 s | COLMAP verifier process: 318.235 s | 76.171 s |
| M9, 537.047 s | Geometry attempt: 261.755 s; measurement attempt: 240.693 s; policy/report attempt: 0.174 s | 34.425 s |
| M10, 694.125 s | COLMAP image_undistorter process: 32.281 s | 661.844 s |

Attempt durations include their own validation/publication; they are not isolated
algorithm CPU times. M10's remainder includes input copies, sparse transport,
hashing, repeated sparse/image validation and publication, not just undistortion.
That remainder has not been individually profiled. M9 rebuilds disk-backed
canonical observation/point indexes for its geometry and measurement passes.
These timings identify optimization candidates; they do not establish that every
integrity check can be removed or predict a speedup. Full details are in the recipe's
`timing_breakdown` and external `timing-breakdown-20261026.json`.

## Training result

Checkpoint run `2477d5f1-1368-480a-9583-7c02b688de7d` and scene/export run
`b33ae73c-22b9-4646-8c80-4eebb1937c94` both succeed without cache reuse.
Scene-set receipt run: `a23fea17-4602-490b-bcb8-4caf511f8a23`.

| Measurement | Result |
| --- | ---: |
| Completed optimization steps / seed | 7000 / 42 |
| Train / eval views | 230 / 33 |
| Eval PSNR | 17.500848 dB |
| Eval SSIM | 0.651055 |
| LPIPS | unavailable |
| Gaussians | 2,076,201 |
| PLY bytes | 514,899,380 (491.05 MiB) |
| Active training-loop time | 149.797 s |
| Whole training command wall time | 539.063 s |
| Training plan wall time, separate | 191.015 s |
| PyTorch allocated CUDA peak through training | 3,289,412,096 bytes (3.064 GiB) |

The remaining CLI wall time includes full input/provenance checks, capability
worker, data loading, held-out evaluation, checkpoint/export and publication
validation. It must not be added to the active-loop time as if disjoint work.
Training loss `0.131065` is the last sampled optimization loss, not an eval metric.
These metrics alone do not establish a good visual reconstruction.

The final PLY is:

```text
C:\SplatForgeData\benchmarks\tanks-and-temples\Ignatius\pilot-20261026\project\artifacts\gaussian_scene\c3f83b30-72da-42c5-ad45-7f1c1b6b6e7e\scene.ply
```

## Visual review and localization

The stock `training show` validator passes on the exact published scene (204.734 s).
An independent `plyfile 1.1.3` loader reads all 2,076,201 vertices and reconstructs
Gaussian parameters/SH ordering. Means, log scales, opacity logits and SH values
equal checkpoint tensors exactly; exported quaternions equal normalized checkpoint
quaternions. This loader uses independent camera assembly but the **same gsplat
1.5.3 rasterizer**, not an independent rendering engine. The read/render audit
takes 7.312 seconds. Native-checkpoint versus PLY rendering of the first view has
mean absolute difference `6.30e-8`, maximum `0.002575`.

Independent eval PSNR is 17.509445 dB, 0.008597 dB above the worker. The independent
consumer clamps display RGB to [0,1]; the worker scores its floating raster output
without this display clamp. These values are not claimed bitwise equivalent.

I inspected both six-view contact sheets, full-size pairs `000001` and `000257`,
and the six adjacent train-view diagnostic pairs. Eval names are evenly distributed
over the 33 withheld views: `000001`, `000049`, `000105`, `000153`, `000209`, `000257`.
Each has the reference, PLY render, 4x absolute-difference image and full pair.
Separate pairs show the unchanged original JPEG (resized only for display) against
the render; raw JPEG distortion differs from the undistorted evaluation camera.

All visual files are under the external evidence directory:

```text
visuals/original-comparisons-1.png        # original JPEG / PLY, first three
visuals/original-comparisons-2.png        # original JPEG / PLY, last three
visuals/comparisons-1.png                 # M10 reference / PLY / abs diff x4
visuals/comparisons-2.png
visuals/000001-original-comparison.png    # analogous files for all six names
visuals/000001-comparison.png
train-diagnostic-visuals/comparisons-1.png
train-diagnostic-visuals/comparisons-2.png
```

Observed quality:

- Statue silhouette, seated pose and green bronze base are recognizable and aligned
  across front, side and close views. There is no gross camera flip, mirrored scene
  or coherent double statue in these inspected views.
- Fine statue texture is softened. Lawn, foliage, flowers and building detail are
  substantially blurred; fountain/water highlights and paving seams are smeared.
- The top of `000001` has elongated foreground splats and conspicuous green/yellow
  floating color fragments at upper right. These recur in adjacent train view
  `000002`; they are not introduced by final PLY export.
- There is incomplete/unstable fine coverage in foliage and background edges,
  and the moving person in the first reference is not faithfully represented.
  No large missing part of the statue is evident, but six camera views do not
  establish complete free-view geometry.
- Overall bronze/grass colors are plausible; fountain/base highlights are too
  smooth and locally too bright, with color smears in foliage. This is not a
  globally black scene or an RGB-channel-order failure.

Read-only diagnosis renders neighboring optimization frames `000002`, `000050`,
`000106`, `000154`, `000210`, `000258` from the same PLY. Their six-view mean
clamped PSNR is 18.133939 dB; similar blur/floaters are visible. This small selected
sample is not a full train-set metric. It shows that degradation also exists in
optimization views, rather than being confined to withheld interpolation.

Localization: M9 passes with full coverage and low reprojection error; M10 preserves
validated geometry and pixels; PLY and checkpoint parameters/renderings agree.
There is no demonstrated export corruption or gross pose-convention bug to repair.
The remaining evidence points to limited scene fitting at 7k steps, especially
background/dynamic/detail/brightness behavior. Separating insufficient optimization,
view-dependent appearance and dynamic foliage/water requires a controlled experiment;
these are hypotheses, not established individual causes. No extra training or
parameter search was performed to improve the reported baseline.

**Verdict:** the complete technical route is reproduced and checked; full-scene
visual quality acceptance is **not passed**. This is a useful diagnostic baseline,
not a good-quality final reconstruction or an official T&T geometric benchmark.

The next experiment should keep this exact M10 artifact, factor 2, seed and split,
and run one fresh 30k-step recipe to test the optimization-horizon hypothesis,
measuring the same eval views, floaters, memory and Gaussian growth. The 7k run
must remain immutable; do not change its horizon and claim checkpoint resume.
Truck can then test scale/generalization with the same baseline, after checking
its actual all-pairs budget, camera grouping, component coverage and visual gate.
Moving directly to Truck is possible as a scale diagnostic, but this run does not
justify calling the current quality preset accepted. No Truck data was downloaded.

## Reproduction and checks

The compact [machine-readable recipe](tanks-and-temples-ignatius-pilot.json) contains
the exact argument arrays, command start times, run/artifact IDs, cache flags,
per-stage wall times, complete resolved matching/verification/mapping/training
settings, backend identity, explicit eval UUIDs and measured final scene metrics.
The external `*.command.json`, `*.result.json`, `*.stdout.json` and `*.stderr.log`
retain full original evidence, including refused/failed/canceled attempts.

Representative exact commands for the retained project (PowerShell):

```powershell
Set-Location C:\Dev\SplatForge
$sf = 'C:\Dev\SplatForge\.venv\Scripts\splatforge.exe'
$e = 'C:\SplatForgeData\benchmarks\tanks-and-temples\Ignatius\pilot-20261026'
$p = "$e\project"
$colmap = 'C:\Dev\SplatForge\sample_data\runtimes\colmap-4.2.1-cuda12.8-cudnn9.27.0.42\bin\colmap.exe'
$runtime = 'C:\Dev\SplatForge\sample_data\m11-review\runtime.json'
& $sf pairs build $p --views-run 7c36998d-5eb9-4c8b-b77a-076614725277 --method exhaustive --max-pairs 35000
& $sf features extract $p --views-run 7c36998d-5eb9-4c8b-b77a-076614725277 --method SIFT --cpu --max-features 8192 --max-image-size 2048 --max-views 263 --max-workspace-gib 32 --timeout 3600 --colmap $colmap --json
& $sf matches run $p --features-run e79206e2-0868-4246-b2e9-480003b87eb5 --pairs-run 35ba9623-7e3e-44a2-a5f4-78c4c4c533c7 --settings "$e\matching-settings.json" --resource-limits "$e\matching-limits.json" --colmap $colmap --json
& $sf verification run $p --matches-run 98a6c8d4-073f-4654-a702-fb2a414cdf03 --camera-priors "$e\camera-priors.json" --settings "$e\verification-settings.json" --resource-limits "$e\matching-limits.json" --colmap $colmap --json
& $sf mapping run $p --verification-run 8f310d36-6c06-446f-b83c-23412ea9174b --method incremental --settings "$e\mapping-settings.json" --calibration preserve-priors --max-views 263 --max-pairs 35000 --max-workspace-gib 32 --max-output-gib 8 --timeout 7200 --colmap $colmap --json
& $sf dataset prepare $p --selection-run 0fee5df5-a771-4b7d-818e-01a179c27f58 --colmap $colmap --json
& $sf training plan $p --dataset-run 332d96ea-c5f7-466c-b55b-428a8c8d3163 --runtime $runtime --settings "$e\training-settings.json"
& $sf training run $p --dataset-run 332d96ea-c5f7-466c-b55b-428a8c8d3163 --runtime $runtime --settings "$e\training-settings.json"
```

These commands can reuse validated immutable cache entries on the retained project;
a cache hit is not another measured training/reconstruction run. For fresh execution,
create an empty new project destination, use the recipe's `project-create`,
`media-add` and `views-budget20` argument arrays, and bind each consuming command
to the newly returned producing run IDs. Regenerate per-view priors/split by the
recorded original-name/source-SHA mapping, not new UUID sort order. Do not replay
`project create` onto this populated project. The CLI's `--target-fps 1 --selection
fixed-fps` photo-import flags do not create timestamps: all 263 photos are retained.

Data acquisition/inventory, camera-prior/split generation and independent PLY
consumption helpers are retained as external evidence (`prepare_data.py`,
`reconstruct_cpu.py`, `prepare_training.py`, `consume_ply.py`, `original_pairs.py`).
They compose existing CLI/application services or inspect outputs; no parallel
SfM/training implementation is added. Acquisition helpers refuse existing output
paths. Compare the archive SHA-256 before ingest; do not replace originals.

Final code verification:

```powershell
& .\.venv\Scripts\python.exe -m pytest -rs --junitxml="$e\pytest-final.xml"
& .\.venv\Scripts\ruff.exe check .
git diff --check
```

Full default pytest: **1608 passed, 72 skipped, 51 warnings**, 3847.17 seconds.
The 72 skips are explicitly opt-in native/FFmpeg/CUDA/cross-source integrations
without their test environment variables; this pilot separately exercises the real
selected COLMAP and CUDA route. Focused SIFT publication/progress/cache tests and
M10 execution/resource-guard tests also pass. Changed Python files pass Ruff.
Full `ruff check .` retains the existing **E501 in `src/splatforge/core/registry.py:52`**
(101 > 100 characters); that unrelated line is unchanged. `git diff --check` passes.
No commit or push is made.
