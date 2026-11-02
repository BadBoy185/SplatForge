# Ignatius learned-feature and GPU solver pilot

Status: completed diagnostic experiment, 2026-10-26; quality improvement not achieved.
User authorized local benchmark execution and an
isolated third-party CUDA/cuDSS/Caspar runtime; no model or toolchain installation.

## Goal and scope

Complete ALIKED_N16ROT/LightGlue -> Incremental Ceres -> M9 -> explicit selection
-> M10 -> gsplat.default, 7,000 steps, seed 42, factor 2, using the baseline's
exact held-out IDs. Separately prove advanced GPU matching and Ceres/Caspar mapper
execution. Preserve all failed attempts and benchmark evidence outside Git.
No product-default changes or broad parameter search.

## Contracts and affected areas

- [AGENTS](../../../AGENTS.md): architecture, state/cache, process and user-data invariants.
- [PIPELINE](../../PIPELINE.md): feature/matching/verification/mapping/validation/dataset/training contracts.
- [PROJECT_FORMAT](../../PROJECT_FORMAT.md): immutable runs, attempts and published artifacts.
- [M7B](../../M7B.md), [M8B1](../../M8B1.md), [M8B2](../../M8B2.md): GPU transport/execution evidence.
- [M9](../../M9.md), [M10](../../M10.md), [M11](../../M11.md): downstream gates.
- [DEVELOPMENT](../../DEVELOPMENT.md#verification-workflow): verification and provisioning boundaries.
- colmap_mapping resource polling; mapping race regressions; GPU fixture budget.

## Acceptance and verification

- Record actual run IDs, uncached/cache time, registration, components, M9 errors,
  exact split, PSNR/SSIM, PLY count/size and available memory measurements.
- Validate PLY, independently load/render it and inspect six held-out comparisons.
- GPU execution requires numerical evidence, with no silent CPU fallback.
- Run affected race/mapping tests, explicit native GPU integrations, full default
  pytest, Ruff and documentation links. Report failures and skips accurately.
- Update the benchmark ledger only for completed end-to-end cells.

## Decisions and evidence so far

- External evidence: `C:\SplatForgeData\benchmarks\tanks-and-temples\Ignatius\gpu-methods-20261026`.
- ALIKED/LightGlue uses its recorded 2,048-feature preset; baseline SIFT used 8,192.
  This compares configured routes, not equal feature budgets.
- First mapper attempt failed on a disappearing SQLite journal. Ignore only an
  optional file disappearing during workspace polling; required database and final
  artifact validation remain strict. Failed attempt preserved; restart from M7.
- The downloaded runtime lacks cuDNN. A separate full bundle reuses the already
  installed, hash-verified cuDNN and license; original runtimes/PATH are unchanged.
- The 60-view GPU test fixture needed a larger test-only view workspace budget.

## Final status

ALIKED/LightGlue completes M9/M10, 7k training, PLY validation and independent loading/
rendering; six views visually reviewed. The foreground is recognizable but background
defects remain and held-out metrics are lower than baseline. No quality acceptance
or universal default recommendation is claimed. Caspar and Global GPU separately
pass Ignatius M8/M9 with full coverage and positive GPU execution evidence; neither
was trained in this task. Tiny GPU matrix: 18/18 passes without skips.

Codex ran affected regressions, full default pytest (1629 passed, 72 skipped), Ruff
(only the existing registry.py E501) and documentation checks. Python file hashes
match the captured full-suite tree. Existing housekeeping/user edits were preserved.
The [final report](../../TANKS_AND_TEMPLES_GPU_PILOT.md) owns exact commands, times,
metrics, failed evidence and limitations. Next: train the already validated Caspar
component under the same settings before a larger-scene GPU quality comparison.
