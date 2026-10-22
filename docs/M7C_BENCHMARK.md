# M7c candidate audit and evidence ledger

Audit date: 2026-10-22. Decision: **no initial production model selected**.
This working tree contains M7b's synthetic execution fixtures and its explicitly
provisioned native GPU runtime. No representative multi-clip/phone-drone VPR corpus
or prepared VPR inference exports/weights/runtime was found in those local fixtures.
No models, datasets or ML toolchains were downloaded or installed for this task.

All four candidates received source/deployment/licensing inspection. **None received
a real image-retrieval quality benchmark here.** Synthetic vector comparisons test
the harness, not the candidate neural representations. Leaderboard scores are not
used as evidence of useful SfM pairs or as a production selection rule.

## Separate licensing evidence

| Candidate | Code | Model weights | Backbone | Training data and redistribution | Product disposition |
| --- | --- | --- | --- | --- | --- |
| MegaLoc | Official repository [MIT license](https://github.com/gmberton/MegaLoc/blob/main/LICENSE) | Official [model card](https://huggingface.co/gberton/MegaLoc) independently declares MIT; this is weight-specific evidence, not inferred from code | Current [implementation](https://github.com/gmberton/MegaLoc/blob/main/megaloc_model.py) identifies a DINOv2 backbone; DINOv2's own code/model terms are below | Authors' [FAQ](https://github.com/gmberton/MegaLoc) says training datasets cannot be redistributed. Do not ship them. Retain exact code/weight license notices; audit transitive/adapted implementation provenance before bundling | Strong benchmark candidate; not selected without local measured yield, Windows deployment and notice audit |
| AnyLoc VLAD | Official [BSD-3-Clause](https://github.com/AnyLoc/AnyLoc/blob/main/LICENSE): retain notice/disclaimer in source/binaries and no implied endorsement | No single AnyLoc learned checkpoint establishes the complete representation. Pin DINOv2 weights and a separate VLAD vocabulary; reviewed [release documentation](https://github.com/AnyLoc/AnyLoc) does not separately settle all vocabulary redistribution terms | Chosen DINOv2 checkpoint: Apache-2.0 model declaration; do not generalize to other possible backbones | Vocabulary training corpus/release must be identified; public benchmark datasets retain their own terms. Operator-owned vocabulary still needs provenance | External benchmark only until exact vocabulary and dependency audit |
| BoQ | Official [MIT license](https://github.com/amaralibey/Bag-of-Queries/blob/main/LICENSE) | Official [release loader](https://github.com/amaralibey/Bag-of-Queries/blob/main/hubconf.py) supplies `.pth` checkpoints, but a separate explicit weight license grant was not confirmed in reviewed material | DINOv2 variant can use its Apache-2.0 terms; ResNet/torchvision alternative requires its own exact artifact audit | [Training documentation](https://github.com/amaralibey/Bag-of-Queries) identifies GSV-Cities. Dataset availability is not a grant to redistribute imagery or proof of release-weight terms | External benchmark only; unresolved weight rights block default bundling |
| SALAD | Official [GPL-3.0](https://github.com/serizba/salad/blob/main/LICENSE) | [README](https://github.com/serizba/salad) offers pretrained checkpoints; a separate weight grant was not confirmed | DINOv2 base terms do not relicense the finetuned complete SALAD model | README identifies GSV-Cities training; dataset rights remain separate. Bundling GPL code would require an explicitly accepted compatible distribution plan | External scientific candidate only; no SALAD code or weights copied into the product |

Meta's [DINOv2 model card](https://github.com/facebookresearch/dinov2/blob/main/MODEL_CARD.md)
explicitly declares Apache-2.0 for the model family and names LVD-142M training data.
The separate [code license](https://github.com/facebookresearch/dinov2/blob/main/LICENSE)
is Apache-2.0. Preserve license/NOTICE and modification notices as applicable; a
backbone license does not automatically cover an aggregator, fine-tuned checkpoint,
vocabulary or training images. This ledger records published grants and uncertainty;
it does not certify an as-yet-unassembled commercial redistributable.

Links point to the inspected upstream publications on the audit date. Before a
production bundle, archive/pin exact upstream revisions, downloaded artifact SHA-256,
license/NOTICE texts and third-party provenance. Future upstream changes do not
retroactively establish rights for an unexamined older checkpoint.

## Deployment shortlist

| Candidate representation | Published descriptor dimension | Raw FP32 bytes/view | Windows deployment work remaining |
| --- | --- | --- | --- |
| MegaLoc default | 8448 | 33792 | Explicit PyTorch/torchvision and local safetensors or separately validated ONNX route; pin preprocessing/runtime/model and test actual GPU inference |
| AnyLoc DINOv2 VLAD | Depends on backbone/cluster count; 32768 is an example configuration, not a measured winner | 131072 for 32768D | Isolate backbone inference and VLAD implementation; pin centers and dependencies, avoid implicit hub/model downloads |
| BoQ DINOv2 | 12288; ResNet50 alternative 16384 | 49152; 65536 | Isolate PyTorch stack and local checkpoint loading; inspect Windows/optional attention compatibility and weight rights |
| SALAD default | 8448 (8192+256) | 33792 | GPL distribution decision plus isolated PyTorch/xformers environment; public setup is not Windows certification |

Dimensions above are declarations from the linked official model/code documentation,
not observed SplatForge descriptors. Bytes are arithmetic `dimension * 4`; the current
flat index stores `N * dimension * 4` descriptor bytes plus bounded JSON metadata.
This does not estimate framework RAM/VRAM, inference latency or production throughput.

MegaLoc's [hub loader](https://github.com/gmberton/MegaLoc/blob/main/hubconf.py) and
BoQ's loader perform online downloads in their public convenience paths. Those paths
are not called by SplatForge. Offline export is the current boundary. Any eventual
inference adapter must prove no hidden downloads and run heavy imports/inference in
an owned disposable worker, not Core/Application or the CLI process.

[EfficientVPR's official repository](https://github.com/WiniTang/EfficientVPR)
was inspected as a watch candidate. Its reviewed README exposes a description and
architecture image; a complete runnable implementation, released weights and usable
license/deployment package were not established. It is not a product dependency.

## Benchmark matrix and missing measurements

The [strict opt-in fixture interface](M7C.md#opt-in-comparison-fixtures) covers:

1. Two overlapping same-device clips.
2. Phone/drone overlap.
3. Multiple partially overlapping clips.
4. Unordered photos.
5. No-overlap clips.
6. Repetitive texture.
7. Near-duplicate bursts.
8. Large viewpoint/orientation change.

All eight real categories remain unavailable in this task's measured evidence.
UAVPairs was not downloaded or used. No large public dataset becomes a CI dependency.
For each available capture, export each candidate on the exact same selected pixels,
then run identical K sweeps through one fixed real LoMa-B M7a/M7b route. Record useful
verified pairs, inliers, source/clip connectivity and coverage per pair budget. The
harness rejects changed matcher/runtime/model identities across candidates.

| Quantity | Real candidate evidence in this task |
| --- | --- |
| Retrieved/raw/verified candidate pairs and useful-pair yield | Unknown for all four models |
| Phone/drone or multi-clip verified connectivity/coverage | Unknown for all four models |
| Inference time, observed peak RAM and VRAM | Unknown; export import timing cannot substitute |
| Representative index/query/match/verification time | Unknown; synthetic timing is not a production estimate |
| Flat index payload size | Exact for each imported export; no real candidate export available |
| Production model choice | Blocked by missing representative measurements and remaining artifact-specific distribution audit |

The real native transport check passed on the already provisioned COLMAP 4.2.1
CUDA/cuDNN bundle, with LOMA_B extraction and LOMA_B matching on `gpu:0`, followed
by separate geometric verification. Two constant-vector cross-source candidates
plus one unchanged Sequential edge across three tiny synthetic views produced:

| Transport metric | Observed result |
| --- | --- |
| Retrieved / raw-matched / geometrically verified cross-source pairs | 2 / 2 / 2 |
| Raw correspondences / verified inliers on those retrieval edges | 4096 / 4096 |
| Verified view components before / after retrieval | 2 / 1 |
| Verified source components before / after | 2 / 1 |
| Final hybrid pairs / paired views | 3 / 3 |
| Synthetic flat index | 2D FP32, 3 views, 24 bytes |
| Complete native opt-in test wall time | 80.57 seconds, including probes/setup/cache checks |
| RAM / VRAM peaks / VPR model inference time | Not measured |

Published upstream bytes remained unchanged and representation/PairSet cache reuse
passed. Local diagnostic evidence is in ignored `sample_data/m7c-review/`.
This is not a MegaLoc inference test, phone/drone capture, candidate ranking or
multi-video quality claim. It proves that retrieved ordinary PairSets work with M7b.

## Remaining gate before production M7c and M8

Provide representative authorized captures and explicitly provision candidate code,
weights, preprocessing and isolated local inference runtimes. Measure cold inference
and trustworthy resource peaks externally, retain complete identity/evidence, run
the eight fixture categories through M7b, compare useful verified edges/connectivity
against budgets, resolve exact redistribution obligations and select one initial
production backend. Only then add its owned offline inference adapter and one Simple
hybrid policy. Keep other research frameworks outside the product. Mapping, pose-led
refinement, GPS, training and GUI remain outside this work.

## Validation of this slice

- Baseline before M7c: 1071 passed, 50 skipped.
- Full default pytest after initial M7c implementation: 1094 passed, 52 skipped.
- Final focused M7c/M6/M7b/progress regressions, including subsequent corpus,
  descriptor validation and declared-device metadata checks: 183 passed.
- Separate real LoMa-B GPU retrieval-PairSet transport opt-in: 1 passed.
- Ruff on all M7c-changed Python files passes. Full `ruff check .` reports one
  pre-existing E501 at `src/splatforge/core/registry.py:52`; that file is unchanged
  from HEAD and was left outside task scope.
- Documentation check: 14 Markdown files, 152 local links, no errors.
  `git diff --check` passes. Normal CLI/schema imports load no torch, FAISS or
  ONNX Runtime modules. No base dependency was added.

The skipped integrations include absent representative retrieval fixtures. These
checks establish implementation contracts; the production quality gate above stays
open. The original local user diff was preserved; no commit, push, reset, checkout
or stash was performed.
