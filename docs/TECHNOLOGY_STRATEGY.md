# Technology Strategy and Evaluation Notes

Status: research and decision-support document only.

Last research refresh: 2026-10-22.

This document does **not** change the normative milestone contracts in `ROADMAP.md`,
does not certify any catalog entry as implemented, and does not make a named research
method a product default. It records how SplatForge should evaluate technology choices
from M7 onward without destabilizing the implemented M0-M6.5 foundations.

The central rule is simple: SplatForge should not chase one supposedly universal
"best" algorithm, and it should not accumulate a large method zoo. For each important
stage, keep a small set of materially different, well-tested routes and choose defaults
from measured end-to-end evidence on representative SplatForge data.

## 1. Decision principles

### 1.1 Preserve a strong baseline

A newer learned method does not remove the need for a robust classical route. Keep a
well-understood baseline whenever it materially improves diagnosability, portability or
failure recovery. For local features this means retaining SIFT even when a learned route
wins the normal quality profile. For mapping this means retaining Incremental Mapper even
if Global Mapper is preferred for well-connected datasets.

### 1.2 Candidate is not default

A method becomes a supported/default route only after all of the following are checked:

- real executable/model capability on the target Windows environment;
- exact input/output and descriptor/model compatibility;
- deterministic or bounded operational behavior appropriate to the stage;
- runtime, peak VRAM/RAM and disk/index cost;
- failure modes and actionable diagnostics;
- license and redistribution constraints for both code and weights;
- end-to-end benefit on SplatForge benchmark scenes, not only the method paper metric;
- cache/provenance identity sufficient to reproduce the choice later.

A method that is excellent in a paper but cannot be redistributed, cannot be invoked
reliably on Windows, or does not improve downstream reconstruction is not automatically
better for the product.

### 1.3 Keep alternatives only when they serve distinct jobs

Prefer a small profile family such as `compatibility`, `balanced`, `robust`,
`aerial_rotation`, and `maximum_quality` over exposing every model variant directly to
ordinary users. Advanced settings may expose the resolved concrete method where useful.
Do not add two routes whose measured behavior is effectively identical for SplatForge.

### 1.4 Never hide algorithm substitution

Automatic profiles may recommend a fallback or another route, but an executing attempt
must use the method resolved into the frozen plan. If a route fails, diagnostics may
recommend another plan; execution must not silently switch algorithms inside the same
attempt.

### 1.5 Refresh research at implementation time

Named models in this document are a 2026-10-22 watchlist, not permanent commitments.
Before implementing a future milestone, re-check the current state of the art and the
current upstream releases. If a newer method clearly supersedes a listed candidate,
benchmark the newer method instead of implementing an obsolete placeholder merely
because it appears here.

## 2. Benchmark pack before choosing defaults

Build the benchmark pack incrementally from real project data plus small controlled
fixtures. The pack should contain, where licensing and privacy permit:

- drone orbit / oblique flight with meaningful image rotation;
- drone nadir plus oblique views of the same area;
- ordinary phone walk outdoors;
- phone indoor sequence with low texture and repeated structure;
- mixed phone + drone coverage of one scene;
- several overlapping clips with weak temporal adjacency between clips;
- several intentionally non-overlapping clips as a false-positive control;
- repeated windows, fences, brick, foliage and similar ambiguous texture;
- low-light, motion-blurred and compression-heavy video;
- a medium-scale collection large enough to expose pair/index/runtime scaling;
- later, 360/fisheye + ordinary-camera material for M14.

Real troublesome datasets are especially valuable. A scene that currently separates
phone and drone imagery into different reconstruction components should remain as a
regression case after its source data can be retained legally and privately.

Do not optimize only for one showcase scene. Keep a small controlled suite that includes
negative and adversarial cases.

## 3. End-to-end metrics

The paper metric for a stage is useful but insufficient. Measure the stage-specific
metric and its downstream effect.

### Frame quality / selection

Track at least:

- selected/candidate ratio and temporal coverage;
- blur/sharpness rejection behavior on labelled fixtures;
- duplicate/redundancy rate;
- feature matchability and verified-pair yield from selected views;
- resulting graph connectivity and registration coverage;
- runtime and additional decode/storage cost.

### Local features and matching

Track at least:

- keypoints/features per megapixel and their spatial distribution;
- attempted pairs, matched pairs and geometrically verified pairs;
- inlier count and inlier ratio distributions;
- relative-pose success on controlled data where reference is available;
- cross-source/cross-clip useful edges;
- resulting mapper registration/components;
- extraction/matching time, peak VRAM/RAM and model weight size.

### Retrieval

Recall@K remains useful for labelled retrieval data, but the primary product metrics are:

- recall of pairs that later pass geometric verification;
- useful cross-clip edges at a fixed neighbor/pair budget;
- connected components, isolated views and source-group connectivity;
- false candidates on known non-overlap data;
- index build/query time, memory, index size and descriptor size;
- downstream registration coverage at the same total pair budget.

### Mapping

Track at least:

- registered-view ratio overall and per source group;
- component count and component-size distribution;
- runtime and peak memory;
- track-length and observation statistics;
- reprojection-error distributions;
- triangulation-angle/degeneracy indicators where supported;
- camera/intrinsics plausibility;
- repeatability across difficult initialization cases.

### Gaussian training

Do not select a trainer preset using PSNR alone. Track held-out-view metrics and resource
costs together, for example PSNR/SSIM/LPIPS, train time, peak VRAM, Gaussian count, scene
size and render performance. Add geometry/depth/normal metrics only when trustworthy
reference or priors exist; unavailable evidence stays unknown rather than becoming zero.

## 4. M4 and future frame-selection evolution

The implemented M4 `pillow_edge_dhash` + `sharpest_interval` route is intentionally a
cheap, deterministic baseline. Keep it. It is valuable for diagnostics and for avoiding
expensive learned dependencies early in the pipeline.

Do not equate perceptual image quality with SfM usefulness. A visually sharp frame may
still be redundant because it comes from almost the same pose as its neighbors, while a
slightly less sharp frame may be a critical bridge between viewpoints or source groups.

Future quality research may evaluate independent signals such as:

- directional motion blur in addition to generic edge sharpness;
- highlight/shadow clipping and exposure quality;
- local contrast / usable texture;
- compression/noise indicators;
- stronger perceptual-near-duplicate similarity;
- local-feature count and spatial coverage;
- optional learned image-quality estimates as advisory evidence only.

### Geometry-informed refinement: research gate, not an M8 prerequisite

After M7 provides real features/matches/verified geometry, evaluate whether a second,
bounded selection pass materially improves end-to-end results. Candidate evidence could
include verified overlap, inlier spatial coverage, parallax/relative rotation proxies,
view-graph degree, bridge importance, cross-source edges and homography dominance.

If the benchmark shows a clear gain, introduce a new immutable refined-selection
artifact in a separately scoped milestone/task. It must reference the original selected
views and verification evidence rather than mutating M4 output. Re-running downstream
work from the refined selection is acceptable; hidden feedback loops inside one attempt
are not.

If evidence is weak or the added complexity does not improve registration/3DGS quality,
do not promote this into the main pre-M8 path. Advanced adaptive selection can remain in
M13. This avoids turning a promising idea into a mandatory dependency without evidence.

## 5. M7a/M7b: local features, matching and geometric verification

The current architecture choice remains sound: separate feature extraction, matching
and geometric verification, keep their compatibility explicit, and preserve SIFT as a
robust baseline.

### Current mandatory evaluation set

At M7 implementation/review time, compare at least the routes below that are actually
available on the designated test machine:

1. `SIFT + compatible brute-force matching` as the compatibility/diagnostic baseline.
2. `SIFT + LightGlue` if the verified backend supports it.
3. `ALIKED + LightGlue` as the existing preferred learned candidate.
4. The current COLMAP LoMa family where supported and redistributable.

COLMAP 4.2 introduced LoMa extraction/matching via ONNX with `LOMA_B` and `LOMA_B128`
descriptors. Current COLMAP documentation describes compatible dedicated matcher
variants including `LOMA_B`, rotation-augmented `LOMA_R`, and progressively heavier
`LOMA_L` / `LOMA_G` for the 256-dimensional descriptor, while `LOMA_B128` has its own
lighter matcher. Treat these as benchmark candidates rather than hard-coded product
profiles until measured.

In particular, explicitly test `LOMA_R` on drone/aerial material containing roll or
large image rotation. Do not infer superiority from the method name; compare verified
geometry and downstream mapping under equal pair budgets.

### Compatibility must stay structural

Record and validate feature family, descriptor representation/dimension/normalization,
keypoint convention, matcher weights/model identity and relevant preprocessing. Do not
allow incompatible extractor/matcher combinations and do not share one writable native
database between incompatible feature identities.

### Detector-free / dense matchers

Do not expand M7 solely to include every detector-free matcher. If a detector-free or
direct correspondence method clearly solves a benchmark gap that sparse routes cannot,
add a concrete typed route that represents what the backend actually produces. Do not
fabricate a FeatureSet just to fit the sparse pipeline. Otherwise keep this class of
methods for the M13e alternative-method research pass.

### Verification

Use the supported COLMAP robust two-view geometry route first because it already fits
the native database/mapping path and has the strongest operational integration. Evaluate
specialized verification/pose libraries only when a concrete dataset or camera model
shows a gap. Matching success without robust geometric verification must never count as
an accepted pair.

## 6. M7c: cross-clip retrieval and hybrid pairing

Keep the planned high-level policy: temporal/sequential edges within a clip plus bounded
retrieval across clips, followed by deduplication and geometric verification.

Do not bind retrieval to the local ALIKED/SIFT/LoMa descriptor family unless an explicit
compatible aggregation is implemented. Retrieval has its own representation/model/index
identity.

### Candidate families to re-check

The 2026 watchlist includes several materially different visual-place-recognition
families, for example:

- MegaLoc as a broadly targeted image-retrieval/VPR model with a simple global
  descriptor interface;
- DINOv2-SALAD as a strong optimal-transport aggregation baseline;
- BoQ as a different learned global aggregation approach;
- AnyLoc / related DINO-based domain-general retrieval approaches for unusual domains.

These names are not a required implementation list. At M7c, refresh the field and choose
a small comparison set that includes a deployable candidate, a strong current retrieval
candidate and a domain-general candidate. Benchmark current released weights and exact
preprocessing rather than paper-only numbers.

### Pair-budget objective

The optimization target is not "highest Recall@1" in isolation. Prefer the method that
produces the most useful geometrically verified cross-clip edges and strongest resulting
registration graph for an acceptable pair/index/resource budget.

For very weak graphs, a future explicit rescue pass may expand retrieval only around
under-connected views/source groups and publish a new PairSet. Such a pass must be an
inspectable plan/artifact, not hidden retry behavior. GPS/spatial evidence remains a
separate M13a source of pair proposals.

## 7. M8: mapping and calibration

Retain the planned multi-mapper strategy rather than declaring one universal mapper.

Current COLMAP guidance describes Incremental Mapper as the most robust and well-tested
route, Global Mapper as potentially faster on larger collections with good matching
graphs but more sensitive to outliers and focal-length priors, and Hierarchical Mapper
as a large-scale alternative with its own trade-offs. Therefore:

- keep Global Mapper as the preferred candidate for well-connected practical datasets;
- keep Incremental Mapper as an explicit robust alternative;
- keep Hierarchical Mapper capability-gated for large-scene cases where evidence
  justifies it;
- never silently retry one mapper with another inside the same attempt.

### Calibration preflight

Global mapping should not assume that EXIF/device metadata means trustworthy intrinsics.
Where intrinsics are uncertain, evaluate the current COLMAP view-graph calibration route
before global mapping. The upstream tool mutates its database in place, so SplatForge
must continue to use a private downstream database copy and preserve published upstream
artifacts unchanged.

Future learned calibration may be evaluated as a prior/initializer, but a neural focal
estimate must not silently become ground truth. Multi-view optimization and plausibility
checks remain authoritative for the supported classical route.

## 8. M9: view-graph and reconstruction diagnostics

M9 should remain a validation/decision layer, not an algorithm that mutates the
reconstruction.

In addition to the already planned registration, component, reprojection, track and
camera-plausibility metrics, consume verified-geometry graph evidence where available:

- connected components before/after mapping;
- degree distribution and isolated/weakly connected views;
- cross-source/cross-clip verified edges;
- inlier-count/inlier-ratio distributions;
- likely bridge/articulation views when cheaply measurable;
- suspicious homography-dominated or low-parallax regions where the backend exposes
  enough evidence to make the interpretation defensible.

Diagnostics should lead to explicit recommendations such as "expand cross-clip
retrieval", "inspect calibration", "try Incremental Mapper", or "capture/add wider
baseline". Recommendations do not automatically rewrite settings or launch a hidden
fallback run.

## 9. M10: trainer-ready dataset preparation

Keep the first M10 conservative: validated images, camera/pose consistency,
undistortion/resizing and reproducible export.

Design the dataset contract so later optional evidence can be added without rewriting
the basic image/camera route, including masks, held-out validation views, depth priors,
normal priors, confidence maps or exposure metadata. Do not implement these merely to
reserve fields; add them only when the first concrete consumer needs them.

Avoid automatic generative enhancement of source images in the ordinary photogrammetry
path. Denoising/sharpening/HDR or generative restoration can change correspondence
appearance and geometry assumptions. Any future enhancement route must be explicit,
benchmarkable and isolated from originals.

## 10. M11: Gaussian training

A gsplat-based trainer remains a strong current candidate because the project provides
an efficient CUDA rasterization/training ecosystem and exposes multiple useful
strategies, including the original-style default densification, AbsGrad-related options,
anti-aliasing, sparse/distributed capabilities and 3DGS-MCMC-style densification.

This does not mean "gsplat forever" or "one gsplat preset". At M11 implementation time:

- re-check current trainers and external LichtFeld requirements;
- verify checkpoint/export compatibility actually needed by SplatForge;
- benchmark at least a preview/balanced-quality trade-off rather than one magic preset;
- measure held-out quality together with runtime, VRAM and Gaussian/scene size;
- keep SfM artifacts reusable when trainer parameters change.

Depth/normal regularization or other geometry priors belong in later quality profiles
only after the prior source, confidence semantics and invalidation rules are explicit.
They must not become mandatory inputs to the basic trainer.

## 11. M13: advanced methods

### M13a retrieval/spatial optimization

Combine GPS/spatial proposals with retrieval only after uncertainty and units are
explicit. GPS is evidence for candidate pairing, not proof of overlap, calibration or
metric scale.

### M13b masking and segmentation

Automatic masking should be evaluated as a temporal/geometry-aware tool, not simply
"segment every object". Current promptable video segmentation families such as SAM 3
can detect/segment/track objects, but semantic identity alone does not tell whether an
object is harmful to SfM. A parked vehicle may be static scene content; a moving vehicle
is dynamic. Keep manual correction and separate SfM/training-mask invalidation.

Advanced adaptive selection may also live here if the earlier geometry-informed
selection research gate did not justify promotion before M8.

### M13d large scenes

Prefer hierarchical pairing/retrieval, graph partitioning, selective caching and
trainer-side large-scene strategies over simply raising hard limits. Benchmark memory,
disk, pair count, interruption recovery and merge quality explicitly.

### M13e alternative/direct geometry routes

Re-check feed-forward 3D geometry/SfM systems at implementation time. Current research
families worth watching include VGGT-like visual geometry transformers and models such
as MapAnything that can infer cameras/dense geometry from flexible geometric inputs.
These are promising second-route or hybrid candidates, not replacements for the M8
classical production route without evidence.

If implemented, use a direct typed route such as Views/Priors -> ReconstructionSet when
that matches the backend. Do not fabricate sparse features, PairSets or two-view
geometry that the method never actually computes. A hybrid route may use neural depth or
camera priors to initialize/support classical optimization, but its dependencies and
uncertainty must be explicit.

## 12. M14: 360/fisheye/equirectangular

Keep calibrated perspective projection as the first compatibility route because it
allows the existing flat-camera SfM/training pipeline to remain valid. Later compare
native wide-angle/spherical camera support only when a concrete backend and benchmark
show a real benefit.

Do not infer that a model supporting a wide camera projection for rendering also solves
all upstream SfM/calibration problems for that projection.

## 13. Technology registry evidence

Before a new method is considered production-supported, record enough evidence to make
its identity and operational status inspectable. Useful fields include:

- semantic method ID/version and role;
- backend/runtime ID and exact version;
- executable/library identity;
- model/weight identity and digest;
- preprocessing and descriptor/index format identity;
- supported devices/precision modes;
- measured Windows capability evidence;
- code license and weight license/redistribution notes;
- benchmark-pack version and measured summary;
- known limits/failure modes;
- maturity state such as research candidate, optional, supported, or preferred.

This is not a request for a generic plugin framework. Extend the existing catalog and
capability/provenance contracts only when a concrete implementation needs the fields.

## 14. Adoption workflow

For each future technology-sensitive milestone:

1. Refresh upstream state of the art and releases.
2. Freeze a small candidate list and document why each candidate is materially distinct.
3. Verify licenses, weights and Windows/runtime feasibility before expensive integration.
4. Build the thinnest benchmark adapter or external experiment needed for comparison.
5. Run stage metrics **and** downstream metrics on the benchmark pack.
6. Select the smallest supported set that covers the real trade-offs.
7. Implement only the selected route(s) behind existing SplatForge boundaries.
8. Preserve a robust baseline/fallback when it provides genuine diagnostic value.
9. Record benchmark evidence and exact model/runtime identity.
10. Revisit defaults when new evidence appears; do not rewrite old artifact provenance.

## 15. Current 2026-10-22 recommendations

These are research priorities, not roadmap contract changes:

- M7 should definitely evaluate current COLMAP LoMa variants in addition to the already
  planned SIFT and ALIKED/LightGlue routes; `LOMA_R` deserves a dedicated drone/rotation
  benchmark.
- M7c should select retrieval from an end-to-end cross-clip benchmark rather than from
  Recall@K alone; MegaLoc, SALAD, BoQ and AnyLoc-style approaches are reasonable current
  comparison candidates, subject to fresh license/weight/runtime verification.
- A geometry-informed second-pass frame selector is worth benchmarking after M7, but it
  should become pre-M8 product scope only if it clearly improves registration/quality
  enough to justify the added complexity.
- M8 should remain multi-mapper: Global preferred where the view graph/intrinsics support
  it, Incremental retained as the robust alternative, Hierarchical evaluated for scale.
- M9 should become the main source of explainable graph/reconstruction diagnostics and
  recovery recommendations, without hidden automatic reruns.
- M11 should benchmark a gsplat-based managed route and more than one training profile,
  while preserving external LichtFeld handoff and keeping trainer choice replaceable.
- M13e is the correct place to evaluate direct/neural reconstruction families such as
  VGGT-like systems and MapAnything-style models, using honest direct contracts rather
  than forcing them through sparse-feature artifacts.

## 16. Primary references for the current refresh

Prefer upstream documentation/repositories and re-check them when the relevant milestone
starts:

- COLMAP feature guidance: https://colmap.github.io/faq.html#choosing-between-sift-aliked-and-loma-features
- COLMAP feature/matcher compatibility and LoMa variants: https://colmap.github.io/features.html
- COLMAP mapper guidance: https://colmap.github.io/faq.html#choosing-between-incremental-global-and-hierarchical-sfm
- COLMAP changelog (4.2.0 / 4.2.1): https://colmap.github.io/changelog.html
- MegaLoc: https://github.com/gmberton/MegaLoc
- DINOv2-SALAD VPR: https://github.com/serizba/salad
- BoQ VPR: https://github.com/amaralibey/Bag-of-Queries
- AnyLoc: https://github.com/AnyLoc/AnyLoc
- VPR comparison wrapper (useful for research, not a product dependency): https://github.com/gmberton/VPR-methods-evaluation
- gsplat: https://docs.gsplat.studio/
- gsplat densification strategies: https://docs.gsplat.studio/main/apis/strategy.html
- VGGT: https://vgg-t.github.io/
- MapAnything: https://map-anything.github.io/
- SAM 3: https://ai.meta.com/research/sam3

Keep this file concise enough to remain a decision aid. Detailed benchmark results,
licenses and machine-specific measurements should live in dedicated evidence files when
the corresponding milestone begins rather than turning this note into a permanent dump
of transient SOTA claims.
