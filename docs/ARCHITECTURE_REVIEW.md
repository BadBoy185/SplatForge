# Architecture review of the foundation

Reviewed 2026-10-19 before feature implementation. All 16 tracked files were inspected:
the five original documentation files, package/configuration/CLI modules, two test
files, `pyproject.toml` and `.gitignore`. The working tree was initially clean.
This is a historical review baseline, not a claim that these gaps remain after future
milestones. No source, tests or project configuration were changed in this pass.

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
| `MethodRegistry.validate_pipeline` constructs a dictionary keyed by selected method ID | Reusing an ID in two roles overwrites a role check | Validate slots independently, regression test before persistence; M1a |
| Compatibility checks cover only a descriptor-family string; an empty accepted set skips checking | No dtype/dimension/weight/index/camera/format guarantees | Typed signatures, strict known settings, capability/plan validation; M1/M5/M7 |
| No compatible brute-force matcher is registered despite fallback claims | A documented fallback is not an implemented or even complete catalog route | Explicit SIFT/brute-force integration and availability tests; M7 |
| Original linear pipeline omits geometric verification and dataset preparation | Raw correspondences, reconstruction constraints and trainer-ready cameras/images are conflated | Explicit verification and preparation contracts; M7/M10 |
| Sequential defaults and a generic Vocabulary Tree entry have no cross-clip policy or retrieval compatibility | Unordered photos/multiple clips can be disconnected; ALIKED-compatible retrieval is not established | PairSet coverage/budget rules; basic pairing before matching in M6, retrieval in M13a |
| `PipelineConfig.schema_version` rejects all but 1; no project format or migration path exists; unknown fields can be discarded by current model defaults | Saving a prototype risks locking in incomplete structure or losing future settings | Separate version domains, opaque unknown method envelopes and migration backups; M1a |
| Old persistence prompt prescribes JSON plus SQLite without assigning authority or recovery ordering | Conflicting settings/status, incomplete writes and ambiguous ownership | JSON intent, SQLite attempt/index state, frozen run snapshots, explicit publication protocol; M1 |
| Cache/resume originally follows mapping; no manifests, recipe keys or source identity exist | Early stages would need retrofitting; late changes could rerun the whole pipeline | Fake-stage cache/recovery foundation before media processing; M1b |
| No ownership rules for COLMAP databases or native schemas | Matching/mapping could mutate cached features or mix incompatible branches | Adapter-owned immutable publications and isolated writable workspaces; M7/M8 |
| Hard-coded 2 FPS / 1,800 frames / balanced preset, plus `training.none` | Unbenchmarked defaults and dataset handoff become permanent architecture | Treat as prototype profile; version/resolve presets; explicit dataset-only target; M1/M4/M10/M11 |
| No source/camera/coordinate model or distinction between a clip and shared intrinsics | Mixed devices, zoom, EXIF transforms and later virtual views become fragile | Common view contract, calibration groups and explicit transforms; M2/M3/M14 |
| No application service, process lifecycle or observability contract | Future GUI could own processing; cancellation and errors become backend-specific | Inward dependencies, shared execution context, structured events and owned process trees; M1b/M2 |
| Three tests cover one positive profile, one descriptor mismatch and registry counts | Catalog size is not proof of compatibility, persistence, cache safety or integration | Layered tests, fault injection, Windows checks and opt-in backend/quality fixtures |
| `pyproject.toml` has broad dependency ranges; `.gitignore` excludes only limited data locations | Installed behavior can drift; arbitrary project/model files may enter Git | Record runtime/model identities, explicit provisioning and diff/data review; ignore-rule changes deferred to implementation |
| No policy for the earlier successful 3DGS setup | Valuable recipes could be discarded or imported as tightly coupled code | Read-only inventory, evidence-based translation and versioned training presets; M11a |

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
| Managed trainer and full training recipe | M11 after legacy review and packaging/capability evaluation; external handoff can ship first |
| Per-view cache granularity, database snapshot optimization, cross-project cache and parallel stages | M13 scale measurements; start with stage artifacts and one active stage |
| Adaptive retries, retrieval model/index, batch scheduling and segmentation model | M13 independent acceptance tests; no invisible quality-changing fallbacks |
| 360 projection strategy, rig use, GPS/LiDAR fusion and native spherical SfM | M13/M14 calibration/geometry evidence; retain the common perspective-view contract |
| Installer, bundled CUDA/Python engines, auto-update, remote workers and distributed execution | After CLI/backend support is established; cloud/distributed services are outside initial scope |

No new backend, installation/version matrix, training quality superiority or legacy
project result is asserted without inspection and testing. Upstream integration
references and Windows risks are recorded in [DEVELOPMENT.md](DEVELOPMENT.md).

## Recommended next task

Implement **M1a: project persistence**, including the narrow role-validation fix and
its regression test, create/open/save/inspect, version separation, strict known settings
with unknown-method preservation, atomic saves and migration safety. Use the exact
scope and acceptance criteria in [CODEX_PROMPTS.md](CODEX_PROMPTS.md#m1a-project-persistence).
Do not start FFmpeg, COLMAP, training, GUI or a general scheduler in that task.
