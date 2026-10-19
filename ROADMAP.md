# Roadmap

## Milestone 0 — foundation
Package/CLI skeleton, method registry, compatibility model, presets, tests and Codex instructions.

## Milestone 1 — project persistence
Create/open project, project.json, SQLite stage state, standard directories and schema versioning.

## Milestone 2 — media ingest
Flat video/photos, ffprobe metadata, source groups and camera groups.

## Milestone 3 — frame extraction/selection
FFmpeg, fixed FPS, sharpest frame per interval, blur and duplicate filtering, later adaptive motion-aware selection.

## Milestone 4 — COLMAP engine
Executable discovery, version/capability detection, ONNX learned-feature support, logging, cancellation and isolated command builder.

## Milestone 5 — learned features
ALIKED extraction, LightGlue matching, compatibility validation and SIFT fallback.

## Milestone 6 — pair selection
Sequential, exhaustive, retrieval/vocabulary tree, spatial/GPS and later hybrid multi-video policies.

## Milestone 7 — mapping/validation
Global Mapper default, Incremental/Hierarchical fallbacks, component diagnostics, registration and reprojection metrics.

## Milestone 8 — cache/resume
Stage fingerprints, downstream invalidation, resume/retry and crash recovery.

## Milestone 9 — CLI MVP
Video/photos -> selected frames -> SfM -> validated COLMAP training dataset.

## Milestone 10 — trainers
External LichtFeld/Brush adapters and optional native gsplat/Nerfstudio backend.

## Milestone 11 — PySide6 GUI
Guided automatic mode plus advanced per-stage method/settings controls.

## Later
Masking, 360/fisheye, GPS/telemetry, LiDAR alignment, detail-photo registration, plugin SDK, batch/queue and benchmark-driven automatic retry policies.
