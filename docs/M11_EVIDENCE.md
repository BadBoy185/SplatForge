# M11a candidate evidence ledger

Research date: 2026-10-24. Status: candidates, no adopted quality presets.

## Legacy inspection

`legacy_evidence_unavailable`: read-only filename and bounded text searches of the
repository and ignored `sample_data` found no historical trainer recipes, LichtFeld
settings, Nerfstudio/Splatfacto runs, gsplat experiments or native checkpoints.
Existing Russian-dacha evidence describes SfM and M10, not Gaussian quality.
Legacy code and material are never runtime dependencies.

## Independently sourced candidates

The official latest release API reports gsplat **v1.5.3**, tagged commit
`937e29912570c372bed6747a5c9bf85fed877bae`. Mutable upstream branches are not backend
identities. Source references below are pinned to that release; installed bytes and
the worker/runtime must also be fingerprinted before execution.

| Candidate | Verified upstream recipe | Status |
| --- | --- | --- |
| Default | DefaultStrategy, SFM initialization, SH 3, L1/SSIM weight 0.2, 30,000 steps | candidate |
| Default + AbsGrad | DefaultStrategy absgrad=True in both strategy and rasterizer; explicit grow_grad2d=0.0008 | candidate |
| MCMC | MCMCStrategy, cap_max=1,000,000, noise_lr=500,000, opacity/scale regularization 0.01 | candidate |

All comparisons freeze the same dataset, data factor, target steps, SH degree,
seed and explicit held-out membership. Antialiasing is off in the first baseline.
Pose optimization is disabled; world normalization is disabled; initialization uses
M10 sparse points/colors. Smoke steps establish transport only. A 7,000-step
Russian-dacha comparison is a pilot, never a universal preset recommendation.

Upstream sources:

- [Release](https://github.com/nerfstudio-project/gsplat/releases/tag/v1.5.3)
- [Trainer recipe](https://github.com/nerfstudio-project/gsplat/blob/v1.5.3/examples/simple_trainer.py)
- [DefaultStrategy and AbsGrad semantics](https://github.com/nerfstudio-project/gsplat/blob/v1.5.3/gsplat/strategy/default.py)
- [MCMCStrategy](https://github.com/nerfstudio-project/gsplat/blob/v1.5.3/gsplat/strategy/mcmc.py)

## Licensing decisions

gsplat is the managed production candidate under Apache-2.0. Its permissive code
may inform a SplatForge-owned worker. The original Graphdeco implementation is
reference-only because its license limits commercial use. LichtFeld Studio is an
external GPLv3 workflow through conventional COLMAP datasets/PLY; no code is copied
or linked. A paper's availability does not license a derived implementation.

- [gsplat license](https://github.com/nerfstudio-project/gsplat/blob/v1.5.3/LICENSE)
- [Graphdeco license](https://github.com/graphdeco-inria/gaussian-splatting/blob/main/LICENSE.md)
- [LichtFeld license](https://github.com/MrNeRF/LichtFeld-Studio/blob/master/LICENSE)

## Evaluation policy

The comparison harness runs sequentially, retains failures and every resolved recipe,
and selects no winner. Report held-out PSNR/SSIM/LPIPS availability separately from
training loss, Gaussian count, elapsed time, peak allocated CUDA bytes and output size.
LPIPS remains unavailable in the v1 worker. A later measured route needs explicit local
model/weight identity; no implicit model download is permitted.
Source-aware explicit held-out IDs are preferred. If only UUID membership is available,
declare the hash-based deterministic baseline and its spatial/source limitations.

Runtime and completed 7k benchmark measurements are recorded in [M11](M11.md) and its
[numerical receipt](m11-russian-dacha-pilot.json). Visual fidelity is inadequate for
preset adoption; no 30k expansion or universal default was adopted.
