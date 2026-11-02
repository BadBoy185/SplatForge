# Ignatius: Caspar GPU reconstruction to 30k Gaussian training

2026-10-26 UTC start (2026-10-27 local completion pending). One fresh downstream
fit was authorized after the [Ceres 30k reference](TANKS_AND_TEMPLES_30K.md).
This experiment changes the consumed reconstruction to the previously measured
Caspar GPU result. It does not rerun feature extraction, matching, verification,
mapping or M9 measurements, and does not change product defaults.

## Frozen route and provenance

- Same 263 official Ignatius photographs and original source identities from the
  [first pilot](TANKS_AND_TEMPLES_PILOT.md); Exhaustive 34,453 pairs, SIFT CPU and
  compatible brute-force GPU, separate geometric verification.
- Reused Caspar GPU0 mapping run `31c43b0d-1274-4130-aef5-0d14d4dbe4b6`:
  263/263 registered views, one component, 123,627 points. Its positive native GPU
  solver evidence and runtime hashes are owned by the [GPU report](TANKS_AND_TEMPLES_GPU_PILOT.md#representative-gpu-mapping).
- Reused M9 PASS run `475565ce-dabf-49be-8e3e-11e44e4770ca`, no issues/override.
  Mean reprojection 0.937200 px, RMS 1.138082 px, sampled p95 2.167039 px.
- Explicit manual selection of component `80f4d3c0-d0a4-5503-8b2c-c92728a3043d`,
  bound to that exact Caspar report/geometry. A shared component UUID reflects
  membership, not equality of geometry between mappers.
- Fresh M10 with the original COLMAP undistorter executable/settings, followed by
  full reader/image/camera/pose/XYZ/RGB audit and original-name-to-view-ID split check.
- One fresh gsplat.default fit: exactly the Ceres 30k settings, seed 42, factor 2,
  SH3, final-only checkpoint/evaluation, same explicit 230 train / 33 eval IDs.
  Eval photos participate in SfM, not Gaussian optimization. No automatic fallback.

Different mapper geometry can change prepared camera intrinsics, pixels and target
dimensions. Matching eval names alone does not establish identical scoring pixels;
this report records those differences rather than claiming a pure trainer comparison.
This is not an official Tanks & Temples geometric benchmark. LPIPS is unavailable.

## External evidence and reproduction

Project: `C:\SplatForgeData\benchmarks\tanks-and-temples\Ignatius\pilot-20261026\project`.
Evidence: `C:\SplatForgeData\benchmarks\tanks-and-temples\Ignatius\caspar-30000-20261026`.
Exact commands, resolved settings, run IDs, logs and checks remain there. Existing
CLI/services and external pilot helpers are reused; no alternate pipeline is added.

Fresh measured wall times so far: explicit selection 22.562 s, dataset plan
50.016 s, dataset command 370.093 s. The M10 component's persisted run duration is
217.089 s; it is inside the command time, not an additional amount to sum.
Upstream GPU mapping/M9 times are historical reused evidence, not new work/cache hits.

## Clean collection for visual inspection

`C:\SplatForgeData\benchmarks\ReadyToReview\README.md` indexes completed variants.
`Ignatius\01-SIFT-Ceres-7000`, `02-ALIKED-LightGlue-Ceres-7000` and
`03-SIFT-Ceres-30000` are already copied and verified. Caspar is added only after
training, PLY validation, independent loading and direct visual inspection finish.

Every variant contains exactly three files:

- `scene.ply`: independent byte-for-byte copy, SHA-256 checked against published output.
- `comparison.png`: six evenly distributed original-JPEG/render pairs in one image.
- `README.md`: recipe, metrics, time/memory meanings, quality limits and original provenance.

One collection-root README is the index. There are no logs, checkpoints, scripts,
archives, duplicate intermediate renders or temporary files in the collection.
Staging/receipts remain in external technical evidence; existing destinations are
verified or refused, never overwritten. Original project artifacts stay immutable.
Raw JPEG previews retain distortion; numerical scores use undistorted M10 targets.
Future completed variants follow the same compact layout; failed/incomplete runs
stay in technical evidence. A completed result with limitations is labelled explicitly.

## Result and verification

Pending training, final PLY checks, independent raw-score/render agreement and six
inspected views. No quality or speed improvement is assumed from the GPU mapper.
Product sources match the prior full-suite tree; three documentation-harness files
were changed by separate repository work. Fresh harness tests pass (38 tests), while
full Ruff reports only the previously recorded E501 in registry.py:52. This task
does not change Python product code; final documentation/link/diff checks are pending.
