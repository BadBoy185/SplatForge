# Codex task sequence

Use one task at a time. Review the diff and commit after each successful task.

## Task 01 — project persistence

```text
Read AGENTS.md, ARCHITECTURE.md and ROADMAP.md first.

Implement Milestone 1: project persistence.

Requirements:
- Create/open a SplatForge project.
- Project contains project.json plus SQLite state database.
- Create directories: sources, cache, reconstruction, training, output, logs.
- Store schema version and PipelineConfig.
- Never overwrite an existing project without an explicit flag.
- Use pathlib and support Windows paths.
- Add safe load/save using atomic replacement where practical.
- Add unit tests for create, reopen, duplicate-create refusal and config persistence.

Do not implement FFmpeg, COLMAP, GUI or 3DGS.
Do not refactor unrelated code.
Run pytest and ruff check . before finishing.
```

## Task 02 — media ingest
Implement flat-camera mp4/mov/jpg/jpeg/png ingest, FFprobe adapter, source/camera groups and tests. Do not copy or modify originals.

## Task 03 — frame extraction
Implement FFmpegEngine plus fixed-FPS and sharpest-frame-per-interval extraction, deterministic manifests, progress/cancellation interfaces and stage fingerprints.

## Task 04 — frame quality
Implement blur scoring and perceptual duplicate detection as a replaceable stage. Preserve rejected frames as metadata rather than deleting them.

## Task 05 — COLMAP capability layer
Implement ColmapEngine, executable/version discovery, ONNX learned-feature capability checks, structured process results, logs and cancellation.

## Task 06 — ALIKED + LightGlue
Implement ALIKED feature extraction and compatible LightGlue matching through the engine layer, with SIFT fallback. Keep PairSelection separate from FeatureMatching.

## Task 07 — pair selection
Implement Sequential, Exhaustive, retrieval/Vocabulary Tree abstraction and Spatial/GPS abstraction. Keep API ready for sequential-inside-video + retrieval-across-videos.

## Task 08 — mapping and validation
Implement Global, Incremental and Hierarchical COLMAP mapping plus structured reconstruction metrics and disconnected-component diagnostics.

For tasks larger than one module, inspect the relevant code first and write a concise implementation plan before editing. Keep changes scoped and run tests/lint before finishing.
