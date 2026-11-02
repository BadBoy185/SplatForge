# Ignatius: one 30,000-step training experiment

2026-10-26. One fresh optimization run was requested and completed. The original
[7k SIFT/BF pilot](TANKS_AND_TEMPLES_PILOT.md) supplies the exact immutable M10
dataset; its observed PSNR/SSIM exceeded the ALIKED follow-up. This selects the
stronger tested starting route, not a universal optimum.

## Frozen recipe

- DatasetSet run `332d96ea-c5f7-466c-b55b-428a8c8d3163`, component artifact
  `645d80f8-6cd4-4a66-9a3f-6252dc72b018`; no new SfM/M9/M10 computation.
- gsplat.default, 30,000 steps, seed 42, SH3, factor 2, classic rasterization.
- Same Python 3.12.10, gsplat 1.5.3 commit
  `937e29912570c372bed6747a5c9bf85fed877bae`, Torch 2.7.1+cu128,
  CUDA runtime 12.8 and driver 610.62 on RTX 5080 (compute capability 12.0).
- Same 230 training / 33 eval IDs, original numeric filename order every eighth
  view starting at zero. Eval frames were used in SfM, not Gaussian optimization.
- Same DefaultStrategy: refinement 500..15,000, every 100 steps, opacity reset
  every 3,000. Fixed poses/world coordinates, sparse initialization, no AbsGrad/AA.
- Final-only evaluation/checkpoint cadence 30,000, yielding one optimization
  process. Only max_steps and those two cadences differ from the original recipe.
- Fresh from sparse initialization. A 7k checkpoint cannot resume under a new
  max_steps/LR horizon in the current [M11 contract](M11.md#checkpoints-resume-and-numerical-identity).

Factor 2 uses the identical 986x555 target pixels/intrinsics as the 7k baseline.
Before execution NVIDIA reported 13,566 MiB free on the RTX 5080 (whole-device
snapshot, not a stage memory peak). Default limits remain 4 h/segment, 10 million
Gaussians, 16 GiB checkpoint and 8 GiB PLY. No automatic fallback or parameter sweep.

## Evidence and reproduction

External directory:
`C:\SplatForgeData\benchmarks\tanks-and-temples\Ignatius\training-30000-20261026`.
Project remains
`C:\SplatForgeData\benchmarks\tanks-and-temples\Ignatius\pilot-20261026\project`.
All commands, settings, run IDs, worker evidence, checkpoints, PLY and visual
comparisons are preserved externally. Original 7k artifacts remain immutable.
Data provenance/checksums are owned by the original pilot: this run reuses its
263 official Ignatius images. A fresh full SHA-256 audit again confirms that all
originals and the downloaded archive are unchanged (`source-integrity-after.json`).

```powershell
$cli = 'C:\Dev\SplatForge\.venv\Scripts\splatforge.exe'
$p = 'C:\SplatForgeData\benchmarks\tanks-and-temples\Ignatius\pilot-20261026\project'
$e = 'C:\SplatForgeData\benchmarks\tanks-and-temples\Ignatius\training-30000-20261026'
$runtime = 'C:\Dev\SplatForge\sample_data\m11-review\runtime.json'
& $cli training plan $p --dataset-run 332d96ea-c5f7-466c-b55b-428a8c8d3163 --runtime $runtime --settings "$e\training-settings.json"
& $cli training run $p --dataset-run 332d96ea-c5f7-466c-b55b-428a8c8d3163 --runtime $runtime --settings "$e\training-settings.json"
```

The existing external pilot wrappers/independent PLY consumer are reused. A repeat
of an unchanged completed recipe may cache-hit; it is not fresh training time.
No models, toolchains or packages were installed. Training plan/runtime and dataset
checks execute freshly; the copied pre-training audit is explicitly baseline evidence.

## Result and verification

Both checkpoint and Gaussian export completed with `cache_hit=false`. The dataset
digest and backend numerical identity match the 7k baseline exactly. Only the three
declared horizon/cadence fields changed. These are macro means over the same 33
eval views, with identical target pixels and fixed SfM poses:

| Measurement | Original 7k | One 30k run |
| --- | ---: | ---: |
| PSNR, dB | 17.500848 | 18.044663 |
| SSIM | 0.651055 | 0.701812 |
| Gaussians | 2,076,201 | 4,099,967 |
| PLY bytes | 514,899,380 | 1,016,793,348 |
| Optimization loop, seconds | 149.797 | 2,470.218 |
| CUDA allocated peak, bytes | 3,289,412,096 | 6,468,200,960 |

PSNR improves by 0.543815 dB and SSIM by 0.050758. This is a single seed and
training-horizon experiment, not a universal quality claim or an official T&T
geometry benchmark. Changing max_steps also changes the LR schedule; this is not
a continuation of the 7k checkpoint. LPIPS remains unavailable.

| Fresh operation | Wall seconds | Scope |
| --- | ---: | --- |
| Training plan | 101.969 | Runtime/dataset capability and integrity checks |
| Training command | 2,776.640 | One optimization process, eval, checkpoint, export and publication checks |
| Optimization loop (inside command) | 2,470.218 | 41 min 10 s; not an additional stage to sum |
| Repeated stock PLY validation | 125.407 | Full published GaussianScene inspection |
| First independent consumer | 10.265 | Failed scoring-definition comparison, retained |
| Corrected independent consumer | 10.281 | Same PLY; raw/raw score agreement and six renders |

No upstream stage was rerun: its artifacts were explicitly reused, not timed as
fresh SfM/M9/M10 work. Loop time excludes initialization, final evaluation and
serialization. CUDA memory is `torch.cuda.max_memory_allocated()` since reset
before initialization through the loop, sampled before final eval/export; it
excludes reserved memory and other processes. It is not whole-device VRAM peak.
The run uses seeded CUDA, without a claim of bitwise reproducibility.

Checkpoint run `87fc6834-9f74-4a90-b8f5-5bb1ad622d6b`, artifact
`6eccd7ec-a346-423d-abe4-1eb114b0286d` (state.pt: 2,935,598,543 bytes).
Gaussian export run `a2138e6a-4b22-4475-878b-e9fcfb8db719`, scene artifact
`03cf8aaa-d736-448a-89b9-a5cdd25ddd83`; SceneSet run
`1d8b60a9-7ba0-4fc9-9f28-721fb497f477`.

PLY: `pilot-20261026\project\artifacts\gaussian_scene\03cf8aaa-d736-448a-89b9-a5cdd25ddd83\scene.ply`
under the external Ignatius root above. Stock PLY validation passes. Independent
plyfile 1.1.3 loading verifies all exported parameters against the checkpoint
(quaternions normalized as specified by the PLY contract). Independent camera
assembly uses the same gsplat rasterizer, not a second rendering engine. First-view
checkpoint/PLY render difference: mean 8.88e-8, max 0.003086. Across all 33 views,
independent raw RGB PSNR is 18.044662 dB, within 8.42e-7 dB of the worker.

The original external consumer failed its 0.02 dB guard: it compared clamped RGB
PSNR with the worker's raw float RGB metric. At 30k this difference is 0.020111 dB.
The first command/result/error/helper and `visuals/` remain untouched as evidence.
`consume_ply.v2.py` records both definitions and compares raw with raw using the
original tolerance. Its clamped PSNR is 18.064774 dB. PNGs use clamped RGB for
display; the 7k/30k table uses the unchanged worker definition for both runs.
No product code, checkpoint, PLY or training settings changed to pass this check.

Codex inspected all six evenly spaced eval names (000001, 000049, 000105, 000153,
000209, 000257), the reference/render/difference sheets, raw-original sheets and
full first/last pairs. `visuals-7k-vs-30k/7k-vs-30k-{1,2}.png` puts identical M10
reference pixels, 7k and 30k side by side; equality of target pixels is asserted.
`visuals-v2/` contains full-size pairs and original-JPEG comparisons. Raw originals
retain distortion, so pixel metrics use the separate undistorted M10 reference.

Flowers, grass, distant facade and fine statue details improve. The large bright
green/yellow floating patch in the first 7k view is strongly reduced. The statue
stays aligned without gross doubling or collapse in the inspected views. Water
and pale paving are still smeared; foliage/windows and sky boundaries remain soft
or streaked. The first view still has a dark floating band at the top and speckles
around thin details; bright highlights look washed out. The distant person is not
faithfully reconstructed. This is the best observed Ignatius fit so far, with
clear remaining defects, not a pristine full-scene reconstruction.

The loop took 16.49 times the original 7k loop time, while final Gaussian count
is 1.97 times larger. These are observations from two runs, not a controlled
scaling law or a claim that step count alone explains cost. Detailed stage wall
times, backend/recipe identities, split and failed evidence are saved in the
[machine-readable report](tanks-and-temples-ignatius-30k.json).

No product Python changed. All 297 Python-file hashes match the previous full suite
(Codex: 1629 passed, 72 skipped); that result is reused. Documentation links and diff
scope passed at delivery: 35 Markdown files, zero link errors; `git diff --check`
passed with existing LF/CRLF warnings. Full Ruff's previously recorded unrelated E501
in registry.py:52 remains outside this experiment.

This horizon experiment is outside the fixed-7k 156-cell matrix; it does not
increment that matrix's completed-cell count.

Next useful experiment: one explicit MCMC Gaussian-cap or AbsGrad configuration
on this exact M10/split to measure quality per time/size; neither was launched.
Truck can be a separate scene-scaling pilot after a fresh resource/pair-budget
plan. Ignatius does not prove its coverage, memory use or final quality.
