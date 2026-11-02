# Tanks & Temples benchmark matrix

This is a candidate method-comparison matrix. Execution evidence exists only for
the linked completed rows: the original [Ignatius pilot](TANKS_AND_TEMPLES_PILOT.md)
and [ALIKED/LightGlue follow-up](TANKS_AND_TEMPLES_GPU_PILOT.md). Counting the original
matrix itself launched no work; the follow-up was separately authorized afterward.
The [JSON matrix](tanks-and-temples-benchmark-matrix.json) enumerates all 156 cells
and identifies the 18-cell initial screening subset.

## Counting scope

Use Ignatius's same 263 original photos, Exhaustive pairing, standalone geometric
verification, explicit M9 selection, M10, 7000 training steps, seed 42, factor 2 and
the original name-bound 230/33 split. Select one explicit numerical preset and
extractor/matcher device plan per route before execution. Vary method families;
do not multiply arbitrary thresholds, feature caps, camera models, calibration,
threads, seeds, resolution, horizons or data scenes into this initial count.
The JSON mapper settings are templates; unexecuted cells are not frozen run recipes.

### Feature extraction and matching: 13 compatible combinations

| Extractor | Compatible matchers | Count |
| --- | --- | ---: |
| SIFT | SIFT brute-force; SIFT LightGlue | 2 |
| ALIKED_N16ROT | ALIKED brute-force; ALIKED LightGlue | 2 |
| ALIKED_N32 | ALIKED brute-force; ALIKED LightGlue | 2 |
| LoMa B | LoMa brute-force; LoMa B, R, L, G | 5 |
| LoMa B128 | LoMa brute-force; LoMa B128 | 2 |

These are five extraction variants, not five mutually compatible descriptor sets.
The count was checked with `resolve_extraction_settings`, `descriptor_signature`,
`COMPATIBLE_MATCHERS`, `resolve_matching_settings` and `validate_matcher_compatibility`.
See [matching contracts](M7B.md#advanced-compatibility-and-settings).

### Mapper families: 3

1. Incremental with CPU Ceres.
2. Global with CPU positioning and CPU Ceres BA.
3. Hierarchical with CPU Ceres.

This comparison fixes the baseline calibration policy rather than introducing an
additional calibration sweep. See [Incremental](M8B1.md) and [Hierarchical/Global GPU](M8B2.md).

### Training configurations: 4

1. `gsplat.default`, classic rasterization.
2. Default + AbsGrad, explicit `grow_grad2d=0.0008`.
3. Default + antialiased rasterization, AbsGrad false.
4. `gsplat.mcmc`, explicit `cap_max=1000000`.

These are four configurations of two stable trainer methods, not four independent
engines. All share the same steps, seed, factor, SH degree and explicit eval membership.
The original pilot's positive trainer probe includes the separate default, AbsGrad,
AA and MCMC features. Combined AbsGrad+AA and MCMC+AA are excluded because their
combined capability evidence is absent. See [training contracts](M11.md#strategies-and-resolved-settings).

**Base matrix: 13 x 3 x 4 = 156 cells. Two completed diagnostic runs, 154 unexecuted cells.**

IGN-001 is the SIFT/BF baseline; IGN-037 is ALIKED_N16ROT/LightGlue with the same
Incremental Ceres/default trainer. The follow-up has lower held-out metrics and
limited visual quality; completion does not mean quality acceptance. Its two
additional GPU mapper runs pass M8/M9 only and do not count as completed E2E cells.

Separate follow-up `IGN-001-H30000` is a completed [30k horizon experiment](TANKS_AND_TEMPLES_30K.md)
on IGN-001's exact M10/split. It improves PSNR/SSIM with higher time, memory and PLY
size. It is outside this fixed-7k matrix, so the count remains two of 156 cells.

This is a compatibility-level candidate count. Every new launch still needs fresh
exact runtime/model/device checks, resource planning and a saved resolved recipe.
A cell can legitimately fail or be unavailable. Do not reinterpret historical tiny
integration passes as successful Ignatius runs. SIFT GPU already failed native
keypoint validation on Ignatius; the completed baseline used CPU SIFT / GPU BF.

## First screening matrix: 18 cells

Vary one part relative to the completed SIFT BF / Incremental Ceres / Default route:

| Group | Cells including the shared baseline | Additional cells |
| --- | ---: | ---: |
| All compatible extractors/matchers, fixed mapper/trainer | 13 | 12 |
| All three mapper families, fixed SIFT BF and trainer | 3 | 2 |
| All four training configurations, exact baseline M10 dataset | 4 | 3 |
| Unique union | **18** | **17** |

This initial screen does not test all interactions between methods. It identifies
candidates for a smaller crossed follow-up; no automatic winner is declared.
IGN-001 and IGN-037 are complete; 16 of the initial 18 cells remain unexecuted.

Reuse immutable upstream artifacts: trainer changes reuse M10/SfM; mapper changes
reuse verified geometry; matcher changes reuse that exact extractor output; the
PairSet stays reusable for all routes. Failed validation or changed numerical
identity invalidates only actual consumers. Do not estimate cost as 156 complete
repetitions of the original run or count cache hits as fresh native work.

Keep the original eval names fixed. If another reconstruction cannot register all
eval views, report missing coverage and mark metric comparability explicitly rather
than silently scoring a smaller/easier eval set. Record actual prepared/eval
dimensions and camera changes; training-only comparisons reuse exactly one M10
artifact and are the cleanest comparison of training methods.

## Optional execution-backend expansion

There are seven distinct mapper execution modes when including:

- Incremental Ceres CPU and Incremental Caspar GPU: 2.
- Hierarchical Ceres CPU: 1.
- Global positioning/BA CPU/CPU, GPU/CPU, CPU/GPU and GPU/GPU: 4.

With the same 13 frontends and four trainers, this is **13 x 7 x 4 = 364 cells**.
Global v2 CPU/CPU is not counted again just because its serialization differs from
v1. This expansion still fixes extractor/matcher device plans and calibration; it
does not enumerate all hardware, configuration or quality-budget permutations.
Caspar and the two Global GPU subsystems each require their own positive native
capability evidence. GPU inventory or a successful gsplat probe is insufficient.
The [GPU follow-up](TANKS_AND_TEMPLES_GPU_PILOT.md) now records all three Global GPU
transport modes and Caspar on an isolated runtime, plus Caspar/Global GPU Ignatius
M8/M9 passes. It also executes all thirteen compatible GPU matching routes on tiny
fixtures; this does not imply all 364 end-to-end variants have been benchmarked.

Retrieval/hybrid are separate pairing experiments needing an explicit compatible
retrieval representation; production VPR selection remains pending. Sequential is
not inferred from photo filenames. Catalog-only vocabulary-tree/spatial methods
are excluded. Fast/Medium/High/MaxHigh profiles resolve to existing method routes
and numerical presets, so they are not extra algorithm families in this count.

Additional steps, seeds, feature budgets, resolutions, calibration policies and
scenes would create explicitly scoped follow-up matrices. The number 156 is not
the total number of every possible numerical configuration.
