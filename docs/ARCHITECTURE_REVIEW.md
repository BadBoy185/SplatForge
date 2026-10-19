# Architecture review of the foundation

Reviewed 2026-10-19 before feature implementation. All 16 tracked files were inspected:
the five original documentation files, package/configuration/CLI modules, two test
files, `pyproject.toml` and `.gitignore`. The working tree was initially clean.
This is a historical review baseline, not a claim that these gaps remain after future
milestones. Resolution references below reflect the focused documentation revision:
M1a1/M1a2, early retrieval in M7c and optional early legacy research. No source, tests
or project configuration were changed in these documentation reviews.

## Decisions worth preserving

Local-first Windows focus, CLI before GUI, Pydantic models, stable method IDs,
dependency injection, separate pair selection, descriptor compatibility checks and
explicit fallback intent are sound. Keeping 360 preprocessing out of Phase 1 avoids
unnecessary scope. The foundation has no heavyweight runtime dependencies in core.
These strengths are retained, with concrete contracts replacing broad promises.

## Findings and resolution

| Finding and repository evidence | Consequence | Documentation decision / implementation milestone |
| --- | --- | --- |
| `FrameSelectionConfig` combines sampling rate, maximum count, blur rejection and duplicates; the original roadmap combines extraction and sharpest selection | Cannot change thresholds without ambiguous recomputation; no candidate-pool semantics | Separate ViewPreparation, QualityAssessment and FrameSelection; M3/M4 |
| `SfMConfig` stores four method IDs with no stage settings; masking, validation and export exist only as enum values | Method parameters and omitted stages cannot be persisted or fingerprinted reliably | Versioned per-stage settings and explicit disabled/absent inputs; M1/M7 onward |
| `MethodSpec` and `builtin_methods.py` describe names but no implementations, probes or runtime requirements | `methods` can be mistaken for installed functionality; ONNX availability is assumed by old prompts | Distinguish catalog/implemented/available/runnable; M1b/M5 |
| `MethodRegistry.validate_pipeline` constructs a dictionary keyed by selected method ID | Reusing an ID in two roles overwrites a role check | Validate slots independently, regression test before persistence; M1a1 |
| Compatibility checks cover only a descriptor-family string; an empty accepted set skips checking | No dtype/dimension/weight/index/camera/format guarantees | Typed signatures, strict known settings, capability/plan validation; M1/M5/M7 |
| No compatible brute-force matcher is registered despite fallback claims | A documented fallback is not an implemented or even complete catalog route | Explicit SIFT/brute-force integration and availability tests; M7 |
| Original linear pipeline omits geometric verification and dataset preparation | Raw correspondences, reconstruction constraints and trainer-ready cameras/images are conflated | Explicit verification and preparation contracts; M7/M10 |
| Sequential defaults and a generic Vocabulary Tree entry have no cross-clip policy or retrieval compatibility | Unordered photos/multiple clips can be disconnected; ALIKED-compatible retrieval is not established | PairSet coverage/budget rules; basic pairing before matching in M6, practical retrieval/hybrid in M7c before M10 |
| `PipelineConfig.schema_version` rejects all but 1; no project format or migration path exists; unknown fields can be discarded by current model defaults | Saving a prototype risks locking in incomplete structure or losing future settings | Version/settings preservation in M1a1; migration boundary and backup safety in M1a2 without invented legacy formats |
| Old persistence prompt prescribes JSON plus SQLite without assigning authority or recovery ordering | Conflicting settings/status, incomplete writes and ambiguous ownership | JSON intent, SQLite attempt/index state, frozen run snapshots, explicit publication protocol; M1 |
| Cache/resume originally follows mapping; no manifests, recipe keys or source identity exist | Early stages would need retrofitting; late changes could rerun the whole pipeline | Fake-stage cache/recovery foundation before media processing; M1b |
| No ownership rules for COLMAP databases or native schemas | Matching/mapping could mutate cached features or mix incompatible branches | Adapter-owned immutable publications and isolated writable workspaces; M7/M8 |
| Hard-coded 2 FPS / 1,800 frames / balanced preset, plus `training.none` | Unbenchmarked defaults and dataset handoff become permanent architecture | Treat as prototype profile; version/resolve presets; explicit dataset-only target; M1/M4/M10/M11 |
| No source/camera/coordinate model or distinction between a clip and shared intrinsics | Mixed devices, zoom, EXIF transforms and later virtual views become fragile | Common view contract, calibration groups and explicit transforms; M2/M3/M14 |
| No application service, process lifecycle or observability contract | Future GUI could own processing; cancellation and errors become backend-specific | Inward dependencies, shared execution context, structured events and owned process trees; M1b/M2 |
| Three tests cover one positive profile, one descriptor mismatch and registry counts | Catalog size is not proof of compatibility, persistence, cache safety or integration | Layered tests, fault injection, Windows checks and opt-in backend/quality fixtures |
| `pyproject.toml` has broad dependency ranges; `.gitignore` excludes only limited data locations | Installed behavior can drift; arbitrary project/model files may enter Git | Record runtime/model identities, explicit provisioning and diff/data review; ignore-rule changes deferred to implementation |
| No policy for the earlier successful 3DGS setup | Valuable recipes could be discarded or imported as tightly coupled code | Optional early read-only research; evidence-based translation/benchmarking and official presets in M11a |

The role-validation defect was reproduced without editing code: assigning
`config.sfm.mapper_id = config.training.trainer_id` allows `training.none` to pass as
the mapper, because the later trainer dictionary entry replaces the mapper's expected
stage. This must become a negative test, not a behavior preserved by migration.

## Verification baseline

- Repository virtual environment: Python 3.12.10; full pytest: **3 passed**.
- `ruff check .`: **18 existing violations**, comprising 17 E501 and one UP037 in
  `builtin_methods.py`, `registry.py` and `models.py`. No automatic fixes applied.
- No external-tool, GPU, reconstruction or training integration was executed. The
  current code has no such adapters; registry listings are not evidence of support.
- The system Python lacks pytest/Ruff; use the existing project virtual environment.

## Intentionally deferred

| Decision | When to decide and required evidence |
| --- | --- |
| Exact supported COLMAP build and ALIKED/LightGlue implementation route | M5/M7: Windows capability probes, descriptor/database round-trip and tiny real scene |
| CLI versus pycolmap/library use per operation | Adapter task: cancellation, installation, format compatibility and performance evidence; no global mandate |
| Universal feature/reconstruction storage or third-party plugin SDK | Only after a second concrete backend shows a missing contract; use native payloads plus manifests first |
| Optimal frame density, quality thresholds, matcher settings and training presets | Controlled datasets/hardware benchmarks, including recovered legacy recipes |
| Exact SQL schema, serializer types, fingerprint encoding and process-tree mechanism | Implementation tasks within the published semantics, tested with crash/Windows fixtures |
| Managed trainer and full training recipe | M11 using available legacy evidence plus packaging/capability evaluation; missing legacy material does not block product work; external handoff can ship first |
| Per-view cache granularity, database snapshot optimization, cross-project cache and parallel stages | M13 scale measurements; start with stage artifacts and one active stage |
| Practical retrieval representation/index | M7c before M10, with measured cross-clip matches and resource/pair budgets; ALIKED alone is not a retrieval representation |
| Adaptive retries, advanced retrieval optimization, batch scheduling and segmentation model | M13 independent acceptance tests; no invisible quality-changing fallbacks |
| 360 projection strategy, rig use, GPS/LiDAR fusion and native spherical SfM | M13/M14 calibration/geometry evidence; retain the common perspective-view contract |
| Installer, bundled CUDA/Python engines, auto-update, remote workers and distributed execution | After CLI/backend support is established; cloud/distributed services are outside initial scope |

No new backend, installation/version matrix, training quality superiority or legacy
project result is asserted without inspection and testing. Upstream integration
references and Windows risks are recorded in [DEVELOPMENT.md](DEVELOPMENT.md).

## Recommended next task

Implement **M1a1: basic project persistence**, including the narrow role-validation fix,
create/open/save/show, version separation, owned directories, SQLite metadata and
known/opaque settings preservation with core persistence tests. Follow with M1a2 for
revision/lock/atomic-write and migration safety before M1b execution infrastructure.
Use [CODEX_PROMPTS.md](CODEX_PROMPTS.md#m1a1-basic-project-persistence) for the bounded
scope. Do not start FFmpeg, COLMAP, training, GUI or a general scheduler in M1a1.

## Adversarial review — two-year and large-dataset horizon

Reviewed 2026-10-19 after the focused revision. This section audits the proposed
contracts, not working processing code. "Corrected" means documentation corrected;
implementation and integration evidence remain milestone work. The findings below
supersede ambiguous earlier wording in this historical review. Required task reading
does not include this entire review.

### Must fix before implementation

These were design-level blockers to encoding durable contracts. The corrections are
now specified; they do not all belong in M1a1.

| ID | Failure scenario / problem | Correction and implementation boundary |
| --- | --- | --- |
| A1 | Treating the sparse FeatureSet -> MatchSet chain as universal forces detector-free matching or direct images-to-SfM engines to fabricate intermediates. Native fusion can falsely claim independent PairSelection/cache behavior. | The diagram is the initial route. Add only concrete typed alternative routes when needed; fused operations have real inputs/outputs, one complete key and restart boundary, and cannot claim external-pair support they lack. ARCHITECTURE/PIPELINE; M7 and each alternative backend. |
| A2 | Excluding all timestamps breaks chronology-dependent pairing; hashing labels/component IDs misses changed geometry; unresolved auto settings and unversioned validators make stale hits appear valid. A generic metadata-projection framework would hide these mistakes. | Explicit versioned key functions distinguish semantic time/content from bookkeeping. Resolve choices first, preserve actual input lineage, hash selected numerical data, revalidate changed integrity contracts. PIPELINE; M1b1 then each method. |
| A3 | A frozen run cannot contain IDs for outputs that do not exist yet. Later verification/environment evidence would require mutating that supposedly immutable snapshot. | Freeze intent and node/output references; attempts bind actual artifacts and runtime evidence. PROJECT_FORMAT; M1b1. |
| A4 | A run-long writer lock can prevent another CLI from cancelling. Crashing between cancellation, directory move and state commit can resurrect cancelled output; retry can race surviving children. | One bounded token-bearing cancellation request, durable owner acceptance, serialized publication decision, expected manifest digest and recovery checks. Unresolved teardown blocks retry. PROJECT_FORMAT/DEVELOPMENT; M1b2 fake races and M2 process proof. |
| A5 | Strict preflight hashing followed by an unprotected reopen can process different bytes. Rechecking against immutable ingest metadata forever also repeats hashes after a harmless metadata change. | Stable-read lease or explicit budgeted snapshot for Strict consumption; Balanced remains honest weaker evidence. Index the latest completed content-verification evidence separately; changed sources stop/replan affected work, never mutate a frozen run. PROJECT_FORMAT; M2. |
| A6 | A cached native feature database may carry stale camera/priors. Writable reopening or hardlinks can mutate upstream artifacts even when the feature key itself is correct. | Private downstream native assembly refreshes consumed camera metadata and ID mappings. Consistent snapshots, no writable hardlinks, and upstream-integrity tests. ARCHITECTURE/DEVELOPMENT; M7/M8. |
| A7 | M1a1 could grow into schemas/directories for every future stage; M1a2 into an invented migration engine; M1b still combined too many failure-sensitive contracts. | M1a1 persists current settings and opaque envelopes, initializes only needed storage and uses basic temporary replacement. M1a2 proves locking/fault safety with dispatch/backup boundaries, not invented migrations. Split M1b into M1b1 execution/cache and M1b2 interruption/recovery. ROADMAP/CODEX_PROMPTS. |

### Should fix soon

These are required by their affected milestone, not reasons to build extra foundation
infrastructure before M1a1.

| ID | Failure scenario / problem | Correction and implementation boundary |
| --- | --- | --- |
| B1 | A "portable" manifest still leaves validation/dataset code parsing COLMAP; another mapper then requires a rewrite. | A small streaming reconstruction reader exposes camera/view/pose/component conventions. Points/tracks are optional; concrete consumers declare requirements. No universal tensor store. PIPELINE; M8 before M9/M10. |
| B2 | A bad deselected component may force an irrelevant override, while an override tied only to IDs can authorize changed geometry. | Validation remains non-mutating and complete; distinguish component and project-wide rules. Bind overrides to exact evidence/selected content; never silently choose or merge components. PIPELINE; M9. |
| B3 | Retrieval can return many redundant neighbors, appear connected on one overlap, or quietly depend on the reconstruction it is meant to enable. Mutable indexes hide corpus changes. | Immutable corpus-bound representation/index contracts, temporal/group diversity and negative fixtures, query/time/memory budgets. Pose-informed refinement is a separate later pass. PIPELINE/ROADMAP; M7c before M10. |
| B4 | Optional isolation leaves the host exposed to native/CUDA crashes or uncancellable GPU calls. Parent-only termination leaves children holding files/VRAM; OOM retry loops repeat failure. | Native/GPU processing and risky probes use disposable owned workers; bounded teardown and owner-crash containment must be tested. OOM needs an explicit resource/settings decision. DEVELOPMENT; M2/M5 onward. |
| B5 | One-time path resolution does not protect later writes/cleanup after junction changes. Pathlib does not prove backend Unicode/long-path support. PID-only stale-owner cleanup can kill a reused process. | Validate containment/reparse points at operation boundaries, reject ambiguous owned paths, use OS-held stable locks and process start/run identity; test each backend's path limits. No hostile same-user sandbox claim. PROJECT_FORMAT/DEVELOPMENT; M1a2/M2. |
| B6 | Dense candidate extraction, native database copies and permanently pinned history can fill disks before the later large-scene milestone. | Budget candidates before decode and account for peak workspace/snapshot/export space. Start with bounded materialized views; add manual previewed eviction by M10, preserving manifests/lineage and protecting active/pinned/user outputs. Advanced retention stays M13d. |
| B7 | Unknown settings for a known method version can be silently normalized away; migrations may rewrite historical artifacts. Validating every saved method can block dataset work because an unused trainer is missing. | Opaque unsupported settings versions, no lossy top-level saves, target-specific validation, immutable historical runs/native payloads and explicit conversions. Cached inputs do not require their original producer installed. PROJECT_FORMAT/ARCHITECTURE; M1a1 onward. |
| B8 | Perspective projection alone cannot guarantee rig geometry, GPS scale, LiDAR alignment or support for native spherical SfM. | Preserve timing, transforms, conventions and uncertainty when present; geometry/prior inputs are not fake images. Consume only declared constraints and reject unsupported combinations. Extend concrete contracts at M13/M14 without rewriting flat-camera routes. |
| B9 | Whole-document/task-wide reading and unconditional code checks for prose changes create avoidable Codex overhead. | AGENTS plus task-specific contract sections and selected acceptance criteria. Documentation-only checks focus on contracts/links/scope; implementation retains relevant/full default tests and lint. No per-task rereading of this audit. AGENTS/CODEX_PROMPTS/DEVELOPMENT. |

### Acceptable tradeoffs for now

| ID | Remaining limitation | Why retained / revisit trigger |
| --- | --- | --- |
| C1 | Balanced can miss edits preserving all observed metadata/identity indicators. Strict on slow/network storage costs full reads and may need a tested lease or explicit snapshot. | This is an explicit provenance-bearing trust/performance choice, not guaranteed detection. Never silently downgrade; test supported storage in M2. Switching to Strict may require rebuilding weakly evidenced source-consuming artifacts. |
| C2 | Immutable native snapshots and conservative stage/payload keys can copy data and recompute more than necessary; cache integrity checking can itself become I/O-heavy. | Safer than shared writable databases or premature universal storage. Measure copy/hash/disk costs and refine reuse only with invariance tests; manual cleanup arrives by M10. |
| C3 | One writer, one active stage and local tested project storage limit concurrency and network-root convenience. | Suitable for a small desktop team. Cancellation remains available without a second writer; source files can still be external. Revisit only with measured M13 queue/scale needs. |
| C4 | Stage-boundary restart loses partial work, and numerical reruns need not produce identical outputs. | Universal checkpointing/determinism is not credible across changing engines. Preserve recipes and actual artifacts; add tested backend checkpoints and quality tolerances where useful. |
| C5 | The precise retrieval model, COLMAP/learned route, trainer and full packaging matrix remain unresolved. | Capability and real-scene evidence should decide these, not architecture speculation. M5/M7/M7c/M11 must demonstrate them; a successful foundation test suite is not evidence of product quality. |

### Verification of the six requested prior revisions

| Revision | Result after this audit |
| --- | --- |
| Early cross-clip retrieval | Present and preserved: M7c is mandatory for the M10 practical multi-video route; model/embedding/index contracts are explicit and independent of ALIKED by default. M6 remains Sequential/budgeted Exhaustive. |
| Avoid unconditional source rehash | Present and preserved: full ingest hash, Balanced/local later default, Strict option, recorded weaker evidence. This audit adds byte continuity and verification-baseline handling, not full hashing on every Balanced run. |
| Explicit ReconstructionSelection | Present and preserved: immutable decision artifact after full non-mutating validation, manual/policy provenance, no largest default, separate unaligned datasets. Added selected-content keys and scoped gates. |
| M1a1/M1a2 split | Present and preserved; narrowed future-schema/migration scope and clarified basic versus fault-tested saves. M1b now has two reviewable tasks too. |
| Task-specific Codex reading | Present and preserved; narrowed several links to sections and removed contradictory prose-only test requirements. AGENTS remains mandatory. |
| Early legacy 3DGS research | Present and unchanged: optional read-only research in LEGACY_3DGS_RESEARCH.md at any milestone, never a prerequisite; recipe translation/benchmarking remains M11a. No legacy project has been supplied or inspected. |

### Readiness and remaining evidence

Ready to begin **M1a1**, using its bounded prompt. No unresolved architectural decision
requires a plugin SDK, workflow language, distributed scheduler, microservices or
another design pass first. This is readiness for basic persistence, not a durability
release or a claim that the product pipeline works.

The next task must preserve current/opaque settings, create/open/save/show projects,
initialize SQLite metadata, establish ownership/version separation and fix independent
role validation with regression coverage. M1a2 must complete failure/concurrency safety
before M1b/processing uses the format.

Remaining empirical risks are Windows process containment and filesystem guarantees,
supported CUDA/native builds, genuine cross-clip reconstruction quality, peak disk/
memory use, native format conversions and future sensor geometry. Their acceptance
checks are in ROADMAP and DEVELOPMENT; mocks cannot close them.

Post-review baseline verification: **3 pytest tests passed; Ruff still reports the
same 18 pre-existing source violations**. No real FFmpeg/COLMAP/CUDA/training integration
was run. Only documentation was edited; source/tests/configuration remain unchanged.
No commit or push was made.
