# SplatForge Codex instructions

## Product

SplatForge is a Windows-first desktop application for processing ordinary camera photos/videos into 3D Gaussian Splatting datasets and, later, complete splats.

Phase 1 supports flat/pinhole cameras only. 360/fisheye support comes later and must be added without rewriting the flat-camera pipeline.

## Architecture rules

1. GUI must never directly invoke FFmpeg, COLMAP, PyTorch, training executables, or shell commands.
2. External programs/libraries belong behind engine/adapter abstractions.
3. Each processing task must support replaceable methods/backends.
4. Keep these concepts separate: frame selection, masking, feature extraction, image-pair selection, feature matching, mapping/reconstruction, reconstruction validation, training, export/viewing.
5. Do not couple ALIKED to the entire application. ALIKED is one feature extractor.
6. Do not couple LightGlue to the entire application. LightGlue is one matcher.
7. Pair selection is separate from descriptor matching.
8. Every long-running stage must eventually support progress, cancellation, structured logs, retry, resume and caching.
9. Cache invalidation must be stage-aware.
10. Keep core domain logic independent of PySide6.

## Recommended initial methods

Default high-quality flat-camera profile:
- feature extractor: ALIKED
- pair selector: Sequential for ordered video; retrieval/VocabTree for cross-video loop closure when implemented
- feature matcher: LightGlue
- mapper: COLMAP Global Mapper

Fallbacks must remain available: SIFT, compatible brute-force matching, COLMAP Incremental Mapper and COLMAP Hierarchical Mapper.

Do not mix incompatible descriptor and matcher families in one COLMAP database.

## Technology

- Python 3.12
- Windows 10/11 and Windows Server 2022
- pathlib.Path
- Pydantic v2
- Typer
- pytest
- Ruff
- PySide6 later

## Development style

- Prefer small modules and explicit interfaces.
- Public APIs must have type hints.
- Use dependency injection.
- Avoid global mutable state.
- Never silently delete source/user data.
- Never overwrite an existing project unless explicitly requested.
- Preserve user settings via defaults/migrations.
- Write tests for compatibility rules, cache invalidation and project persistence.

## Before finishing a Codex task

1. Inspect existing architecture first.
2. Make the smallest coherent change.
3. Add/update tests.
4. Run relevant tests and full pytest.
5. Run `ruff check .`.
6. Update docs if behavior or architecture changed.
7. Do not refactor unrelated code unless explicitly asked.
