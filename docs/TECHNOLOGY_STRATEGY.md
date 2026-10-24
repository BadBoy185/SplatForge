# Technology Strategy and Evaluation Notes

Status: research and decision-support document only.

Last research refresh: 2026-10-22.

This document does **not** change the normative milestone contracts in `ROADMAP.md`,
does not certify any catalog entry as implemented, and does not make a named research
method a product default. It records how SplatForge should evaluate technology choices
from M7 onward without destabilizing the implemented M0-M6.5 foundations.

`ARCHITECTURE.md` and `ROADMAP.md` always take precedence over this file. This document
cannot add acceptance criteria, move functionality between milestones, require an
additional backend, or authorize implementation of a research candidate. Any such
change requires a separate explicit architecture/roadmap review and an independently
bounded implementation task. No implementation work should be added solely because a
method or idea appears in this document.

The central rule is simple: SplatForge should not chase one supposedly universal
"best" algorithm, and it should not accumulate a large method zoo. For each important
stage, keep a small set of materially different, well-tested routes and choose defaults
from measured end-to-end evidence on representative SplatForge data.

## 1. Decision principles

M12's implemented desktop decision is PySide6 6.12.0 / Qt Widgets as an optional
dependency, with standard Qt System/Light/Dark behavior and a lightweight bounded
QPainter point-center viewport. This client consumes existing services; it adds no
QtQuick/QML, browser UI, web server, third-party theme, Torch renderer, Open3D/VTK,
installer or updater. Future renderer/packaging evaluation requires separate scope.
This decision changes no processing methods/defaults or benchmark recommendations.
See [M12](M12.md) for the implemented boundary and verification.

### 1.1 Preserve a strong baseline

A newer learned method does not remove the need for a robust classical route. Keep a
well-understood baseline whenever it materially improves diagnosability, portability or
failure recovery. For local features this means retaining SIFT when it provides genuine
compatibility/diagnostic value even if a learned route wins the normal quality profile.
For mapping this means retaining Incremental Mapper as an explicit alternative even if
Global Mapper is preferred for well-connected datasets.

### 1.2 Candidate is not default

A method becomes a supported/default route only after all applicable checks below are
completed in the milestone that actually proposes adopting it:

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

Future profile families may eventually resemble `compatibility`, `balanced`, `robust`,
`aerial_rotation`, or `maximum_quality`, but these names are illustrative rather than
reserved product presets. Prefer a small profile family over exposing every model
variant directly to ordinary users. Do not add two routes whose measured behavior is
effectively identical for SplatForge.

### 1.4 Never hide algorithm substitution

Automatic profiles may recommend a fallback or another route, but an executing attempt
must use the method resolved into the frozen plan. If a route fails, diagnostics may
recommend another plan; execution must not silently switch algorithms inside the same
attempt.

### 1.5 Refresh research at implementation time

Named models in this document are a 2026-10-22 watchlist, not permanent commitments.
Before implementing a future technology-sensitive milestone, re-check the current state
of the art and current upstream releases. If a newer method clearly supersedes a listed
candidate, benchmark the newer method instead of implementing an obsolete placeholder
merely because it appears here.

## 2. Benchmark pack before choosing defaults

Build the benchmark pack incrementally from real project data plus small controlled
fixtures. Candidate coverage should include, where licensing and privacy permit:

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
phone and drone imagery into different reconstruction components is a useful regression
candidate after its source data can be retained legally and privately.

Do not optimize only for one showcase scene. Keep a small controlled suite that includes
negative and adversarial cases.

## 3. End-to-end research metrics

The paper metric for a stage is useful but insufficient. When comparing candidates,
measure the stage-specific metric and its downstream effect. These metrics guide research
and do not expand a milestone's acceptance criteria unless `ROADMAP.md` is amended.

### Frame quality / selection

Useful comparison evidence includes:

- selected/candidate ratio and temporal coverage;
- blur/sharpness rejection behavior on labelled fixtures;
- duplicate/redundancy rate;
- feature matchability and verified-pair yield from selected views;
- resulting graph connectivity and registration coverage;
- runtime and additional decode/storage cost.

### Local features and matching

Useful comparison evidence includes:

- keypoints/features per megapixel and their spatial distribution;
- attempted pairs, matched pairs and geometrically verified pairs;
- inlier count and inlier ratio distributions;
- relative-pose success on controlled data where reference is available;
- cross-source/cross-clip useful edges;
- resulting mapper registration/components;
- extraction/matching time, peak VRAM/RAM and model weight size.

### Retrieval

Recall@K remains useful for labelled retrieval data, but important product-oriented
comparison evidence includes:

- recall of pairs that later pass geometric verification;
- useful cross-clip edges at a fixed neighbor/pair budget;
- connected components, isolated views and source-group connectivity;
- false candidates on known non-overlap data;
- index build/query time, memory, index size and descriptor size;
- downstream registration coverage at the same total pair budget.

### Mapping

Useful comparison evidence includes:

- registered-view ratio overall and per source group;
- component count and component-size distribution;
- runtime and peak memory;
- track-length and observation statistics;
- reprojection-error distributions;
- triangulation-angle/degeneracy indicators where supported;
- camera/intrinsics plausibility;
- repeatability across difficult initialization cases.

### Gaussian training

Do not compare trainer candidates using PSNR alone. Useful research evidence includes
held-out-view metrics and resource costs together, for example PSNR/SSIM/LPIPS, train
time, peak VRAM, Gaussian count, scene size and render performance. Add geometry/depth/
normal metrics only when trustworthy reference or priors exist; unavailable evidence
stays unknown rather than becoming zero.

## 4. M4 and future frame-selection evolution

The implemented M4 `pillow_edge_dhash` + `sharpest_interval` route is intentionally a
cheap, deterministic baseline. Keep it unless a separately reviewed change demonstrates
a concrete defect. It remains useful for diagnostics and for avoiding expensive learned
dependencies early in the pipeline.

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

### Geometry-informed refinement: research gate only

After M7 provides real features/matches/verified geometry, it is worth running a bounded
experiment to test whether a second selection pass materially improves end-to-end
results. Candidate evidence could include verified overlap, inlier spatial coverage,
parallax/relative-rotation proxies, view-graph degree, bridge importance, cross-source
edges and homography dominance.

This experiment does **not** move adaptive selection out of M13b and does not make it an
M8 prerequisite. If the evidence is unusually strong, propose a separate roadmap change
that defines the new artifact, invalidation and acceptance boundaries before implementing
it. Until such a change is approved, advanced adaptive selection remains where the
current roadmap places it.

If a later roadmap change does introduce a geometry-informed selector, it should publish
a new immutable selection artifact referencing the original selected views and relevant
verification evidence rather than mutating M4 output. Hidden feedback loops inside one
attempt remain out of scope.

## 5. M7a/M7b: local features, matching and geometric verification

The current architecture choice remains sound: separate feature extraction, matching
and geometric verification, keep their compatibility explicit, and preserve SIFT as a
robust baseline/fallback where the bounded M7 implementation requires it.

### Current recommended research comparison set

Before finalizing M7 implementation choices, re-check the candidates that are practical
on the designated test machine. The existing `ROADMAP.md` scope remains authoritative:
it currently calls for ALIKED + compatible LightGlue plus SIFT + compatible brute-force
matching. Additional candidates below are research inputs, not mandatory M7 deliverables.

A useful comparison set currently includes:

1. `SIFT + compatible brute-force matching` as the planned compatibility baseline.
2. `ALIKED + LightGlue` as the planned learned route.
3. `SIFT + LightGlue` only if a verified backend makes it useful and the M7 scope is
   explicitly amended or the comparison can be done without expanding product scope.
4. Current COLMAP LoMa variants as research candidates where supported and licensable.

COLMAP 4.2 introduced LoMa extraction/matching via ONNX with `LOMA_B` and `LOMA_B128`
descriptors. Current COLMAP documentation describes compatible matcher variants
including `LOMA_B`, rotation-augmented `LOMA_R`, and progressively heavier `LOMA_L` /
`LOMA_G` for the 256-dimensional descriptor, while `LOMA_B128` has its own lighter
matcher. Treat these as benchmark/watchlist candidates rather than product profiles until
measured and separately adopted.

`LOMA_R` deserves a dedicated drone/aerial experiment containing roll or large image
rotation. Do not infer superiority from the method name; compare verified geometry and
downstream mapping under equal pair budgets. If LoMa clearly warrants replacing or
adding to the planned M7 routes, make that change explicitly in the M7 implementation
review rather than silently expanding the task.

### Compatibility must stay structural

Record and validate feature family, descriptor representation/dimension/normalization,
keypoint convention, matcher weights/model identity and relevant preprocessing. Do not
allow incompatible extractor/matcher combinations and do not share one writable native
database between incompatible feature identities.

### Detector-free / dense matchers

Do not expand M7 solely to include detector-free matchers. If a detector-free or direct
correspondence method later solves a benchmark gap that sparse routes cannot, add a
concrete typed route that represents what the backend actually produces. Do not fabricate
a FeatureSet just to fit the sparse pipeline. Unless a separate scope review says
otherwise, keep this class of methods for the M13e alternative-method research pass.

### Verification

Use the verified COLMAP robust two-view geometry route required by the selected M7
implementation before adding another verification library. Evaluate specialized
verification/pose libraries only when a concrete dataset or camera model shows a gap.
Matching success without robust geometric verification must never count as an accepted
pair.

## 6. M7c: cross-clip retrieval and hybrid pairing

Keep the planned high-level policy: temporal/sequential edges within a clip plus bounded
retrieval across clips, followed by deduplication and geometric verification.

Do not bind retrieval to the local ALIKED/SIFT/LoMa descriptor family unless an explicit
compatible aggregation is implemented. Retrieval has its own representation/model/index
identity.

### Candidate families to re-check

The 2026 watchlist includes several materially different visual-place-recognition
families, for example:

- MegaLoc as a broadly targeted image-retrieval/VPR candidate;
- DINOv2-SALAD as a strong learned aggregation candidate;
- BoQ as a different learned global aggregation approach;
- AnyLoc / related DINO-based domain-general retrieval approaches for unusual domains.

These names are not a required implementation list. At M7c, refresh the field and choose
a small comparison set that includes a deployable candidate, a strong current retrieval
candidate and, when useful, a domain-general candidate. Benchmark current released
weights and exact preprocessing rather than paper-only numbers. Implement only the one
verified retrieval route required by the current M7c roadmap unless that roadmap is
explicitly amended.

### Pair-budget objective

The optimization target is not "highest Recall@1" in isolation. Prefer the method that
produces useful geometrically verified cross-clip edges and a strong resulting
registration graph for an acceptable pair/index/resource budget.

For very weak graphs, a future explicit rescue pass may be researched that expands
retrieval only around under-connected views/source groups and publishes a new PairSet.
It is not part of M7c unless separately scoped. Any such pass must be inspectable rather
than hidden retry behavior. GPS/spatial evidence remains a separate M13a source of pair
proposals.

## 7. M8: mapping and calibration

Retain the planned multi-mapper strategy rather than declaring one universal mapper.
The roadmap splits implemented M8a Global/reader contracts and M8b1 explicit Incremental
Ceres / capability-gated Caspar BA, plus implemented M8b2 Hierarchical, separate Global
GP/BA GPU capability routes and sequential comparisons. Technical M8 is complete;
representative recommendation benchmarking remains pending.
Incremental M8b1 fixes native multi-model false to preserve disjoint component semantics;
it retains explicit unregistered views in the unchanged ReconstructionSet v1.

Current COLMAP guidance makes it reasonable to research the following routing logic:

- Global Mapper for well-connected practical datasets when its assumptions hold;
- Incremental Mapper as an explicit robust alternative;
- Hierarchical Mapper for scale cases where evidence justifies it;
- never silently retry one mapper with another inside the same attempt.

These points guide method selection; they do not add new acceptance criteria to M8.

### M8a explicit calibration policy

M8a implements the tested COLMAP >=4.2.1 Global route and ReconstructionSet/Reader;
M8b1 adds Incremental/Caspar BA using verified cameras directly, without calibration.
M8b2 implements Hierarchical, explicit Global GP/BA GPU routes and comparison infrastructure. The explicit M8a
scope authorizes optional view_graph calibration only on
a private mapping DB, with validated finite numerical state and deterministic result identity.
The default remains preserve_priors. Device/EXIF/scene classification never enables it.
Representative uncertain-intrinsics benchmarks must justify any future default change.
Calibration estimates are distinct from original priors and final optimized intrinsics;
none is automatically called ground truth. Learned calibration remains out of scope.
See [M8a contracts](M8A.md) and [M8b1](M8B1.md). Caspar is implemented but not compiled
in the locally tested runtime; real Caspar validation remains false. GPU inventory is
insufficient. The local Ceres build also lacks CUDA/cuDSS, so Global GPU remains
unavailable and real validation false. Hierarchical overlapping internal clusters publish
only through final native merging and disjoint membership validation. Tiny transport
fixtures do not establish a mapper quality winner. See [M8b2](M8B2.md). M7c production
VPR benchmarking proceeds independently.

## 8. M9: view-graph and reconstruction diagnostics

M9 is implemented as a validation/decision layer that observes immutable reconstruction.
Its normative acceptance remains the one in `ROADMAP.md`. Separate exact historical
universe, detailed geometry identity, measurements and baseline/custom policy evidence
support explicit manual or conservative dominance selection. No weighted quality score,
largest-component rule or mapper feedback is added. Heuristic thresholds primarily warn;
representative calibration remains empirical work. See [M9](M9.md).

Where the already-produced M7/M8 evidence makes them cheap and defensible, future M9
research may consider additional diagnostic signals such as:

- connected components before/after mapping;
- degree distribution and isolated/weakly connected views;
- cross-source/cross-clip verified edges;
- inlier-count/inlier-ratio distributions;
- likely bridge/articulation views;
- suspicious homography-dominated or low-parallax regions.

These are candidate diagnostics, not mandatory M9 fields. Add them only when the
concrete implementation can expose them without fabricating evidence or materially
expanding M9 scope.

Diagnostics may recommend actions such as "expand cross-clip retrieval", "inspect
calibration", "try Incremental Mapper", or "capture/add wider baseline". Recommendations
do not automatically rewrite settings or launch a hidden fallback run.

## 9. M10: trainer-ready dataset preparation

Technical M10 now implements the [explicit-selection flat COLMAP dataset route](M10.md):
historical immutable pixels, independent components, bounded undistortion/resizing,
independent numerical/file validation, cache/lifecycle and manual safe eviction. It does
not select a trainer; M11 is an independent downstream consumer. Production multi-video E2E
acceptance remains pending M7c production VPR selection; reference-pairing pilot success
does not satisfy that independent gate or choose a universal mapper.

Keep the first M10 conservative: validated images, camera/pose consistency,
undistortion/resizing and reproducible export as defined by the current roadmap.

Design concrete dataset extensions so later optional evidence can be added without
rewriting the basic image/camera route, including masks, held-out validation views,
depth priors, normal priors, confidence maps or exposure metadata. Do not reserve or
implement these merely because they are listed here; add them when the first concrete
consumer requires them.

Avoid automatic generative enhancement of source images in the ordinary photogrammetry
path. Denoising/sharpening/HDR or generative restoration can change correspondence
appearance and geometry assumptions. Any future enhancement route must be explicit,
benchmarkable and isolated from originals.

## 10. M11: Gaussian training

M11 selects **gsplat / Apache-2.0** as the managed production candidate. The positively
validated release is 1.5.3, tag commit `937e29912570c372bed6747a5c9bf85fed877bae`;
mutable main/latest is never a runtime identity. The owned external worker isolates
Torch/CUDA from Core/application and freezes installed numerical code/build, worker,
Python, Torch/CUDA/driver and GPU identity. Local RTX 5080 support is demonstrated by
kernel/backward/optimizer tests, not inferred from installation. See [M11](M11.md)
and the pinned [upstream/license evidence](M11_EVIDENCE.md).

`gsplat.default` uses DefaultStrategy; typed AbsGrad and antialiasing are independently
probed options. `gsplat.mcmc` uses MCMCStrategy with explicit cap_max, regularizers,
noise learning rate and refinement intervals. Both initialize from M10 sparse points,
keep pose optimization/world normalization false, preserve unknown arbitrary scale
and produce the same validated GaussianScene PLY contract. Checkpoints are separate
opaque resumable state. Different M10 components are never combined.

LichtFeld Studio / GPLv3-or-later remains an **external workflow**, interoperating via
conventional M10 datasets and Gaussian PLY, without copied/linked GPL implementation.
The original Graphdeco implementation is **reference only** because its license
restricts commercial use. A paper's license does not license derived implementations.

Candidate benchmarking freezes dataset, resolution/data factor, steps, SH degree,
seed and held-out membership across Default, AbsGrad and capped MCMC. It reports
quality, failures, time, allocated CUDA peak and output size with no combined score
or automatic winner. One-scene Russian-dacha evidence cannot establish universal
Fast/Balanced/Quality/Max presets; broader recommendation remains pending.

Research/watch: AbsGrad thresholds, Taming/Visible Adam, Mip-Splatting ideas,
Scaffold-GS, appearance/PPISP, 2DGS, 3DGUT, compression and hierarchical Gaussian
scenes. Sparse gradients, visible Adam, pose optimization, appearance embeddings,
PPISP, bilateral grids, compression and multi-GPU are not baseline production options.
The v1.5.3 runtime does not require later main-branch appearance work. 2DGS is a
separate representation, and distorted-camera 3DGUT is unnecessary for M10's flat
perspective baseline. Restrictive derived research implementations must not become
managed product dependencies; future permissive implementations need separate evidence.

Depth/normal regularization or other geometry priors belong in later quality research
only after the prior source, confidence semantics and invalidation rules are explicit.
They must not become mandatory inputs to the basic trainer.

## 11. M13: advanced methods

### M13a retrieval/spatial optimization

Combine GPS/spatial proposals with retrieval only after uncertainty and units are
explicit. GPS is evidence for candidate pairing, not proof of overlap, calibration or
metric scale.

### M13b masking and segmentation

Automatic masking should be evaluated as a temporal/geometry-aware tool, not simply
"segment every object". Current promptable video-segmentation families, including the
contemporary Segment Anything family, are worth re-checking when M13b starts; do not pin
M13b to a specific model/version now. Semantic identity alone does not tell whether an
object is harmful to SfM. A parked vehicle may be static scene content; a moving vehicle
is dynamic. Keep manual correction and separate SfM/training-mask invalidation.

Advanced adaptive selection remains in M13b unless a separately approved roadmap change
moves a proven geometry-informed refinement earlier.

### M13d large scenes

Research hierarchical pairing/retrieval, graph partitioning, selective caching and
trainer-side large-scene strategies rather than simply raising hard limits. Benchmark
memory, disk, pair count, interruption recovery and merge quality explicitly before
selecting an approach.

### M13e alternative/direct geometry routes

Re-check feed-forward 3D geometry/SfM systems at implementation time. Current research
families worth watching include VGGT-like visual geometry transformers and models such
as MapAnything that can infer cameras/dense geometry from flexible geometric inputs.
These are promising second-route or hybrid candidates, not replacements for the M8
classical production route without evidence.

If one is later implemented, use a direct typed route such as
Views/Priors -> ReconstructionSet when that matches the backend. Do not fabricate sparse
features, PairSets or two-view geometry that the method never actually computes. A
hybrid route may use neural depth or camera priors to initialize/support classical
optimization, but its dependencies and uncertainty must be explicit.

## 12. M14: 360/fisheye/equirectangular

Keep calibrated perspective projection as the first compatibility route because the
current roadmap intentionally preserves the existing flat-camera SfM/training pipeline.
Later compare native wide-angle/spherical camera support only when a concrete backend
and benchmark show a real benefit.

Do not infer that a model supporting a wide camera projection for rendering also solves
all upstream SfM/calibration problems for that projection.

## 13. Technology registry evidence

Before a new method is considered production-supported, record enough evidence to make
its identity and operational status inspectable. Useful evidence may include:

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

This is not a request for a generic plugin framework or for speculative schema fields.
Extend the existing catalog/capability/provenance contracts only when a concrete bounded
implementation needs the information.

## 14. Adoption workflow

For each future technology-sensitive milestone:

1. Read the current `ARCHITECTURE.md` and `ROADMAP.md` first.
2. Refresh upstream state of the art and releases.
3. Freeze a small research candidate list and document why candidates are materially
   distinct.
4. Verify licenses, weights and Windows/runtime feasibility before expensive integration.
5. Build the thinnest benchmark adapter or external experiment needed for comparison.
6. Run stage metrics **and** downstream metrics on the benchmark pack.
7. Decide whether the existing roadmap scope is still correct.
8. If the winning choice requires new scope, change the roadmap explicitly before code.
9. Implement only the bounded selected route(s) behind existing SplatForge boundaries.
10. Preserve a robust baseline/fallback when it provides genuine diagnostic value.
11. Record benchmark evidence and exact model/runtime identity.
12. Revisit defaults when new evidence appears; do not rewrite old artifact provenance.

## 15. Current 2026-10-22 research priorities

These are research priorities only, not roadmap contract changes:

- During M7 planning, re-check current COLMAP LoMa variants in addition to the planned
  SIFT and ALIKED/LightGlue routes; `LOMA_R` deserves a dedicated drone/rotation
  experiment. Adopt LoMa only through an explicit M7 scope decision.
- During M7c planning, select the one required retrieval implementation from an end-to-
  end cross-clip benchmark rather than Recall@K alone. MegaLoc, SALAD, BoQ and AnyLoc-
  style approaches are reasonable current comparison candidates, subject to fresh
  license/weight/runtime verification.
- After M7, a geometry-informed second-pass frame-selector experiment is worthwhile, but
  adaptive selection remains M13b unless a separate roadmap change is justified.
- M8 should retain the roadmap's multi-mapper design: Global preferred, Incremental and
  Hierarchical explicit alternatives. Research calibration preflight separately rather
  than silently adding a new mandatory stage.
- M9 can become more explainable by consuming existing graph evidence where practical,
  but candidate extra metrics do not expand current M9 acceptance automatically.
- M11 implements the selected gsplat managed adapter and external LichtFeld handoff.
  Additional trainer families require independent licensing/contract/quality evidence;
  broader recommendation remains pending after the bounded strategy comparison.
- M13e remains the correct roadmap location to evaluate direct/neural reconstruction
  families such as VGGT-like systems and MapAnything-style models, using honest direct
  contracts rather than forcing them through sparse-feature artifacts.

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
- VPR comparison wrapper (research aid, not a product dependency): https://github.com/gmberton/VPR-methods-evaluation
- gsplat: https://docs.gsplat.studio/
- gsplat densification strategies: https://docs.gsplat.studio/main/apis/strategy.html
- VGGT: https://vgg-t.github.io/
- MapAnything: https://map-anything.github.io/
- Segment Anything research: https://ai.meta.com/sam3/

Keep this file concise enough to remain a decision aid. Detailed benchmark results,
licenses and machine-specific measurements should live in dedicated evidence files when
the corresponding milestone begins rather than turning this note into a permanent dump
of transient SOTA claims.
