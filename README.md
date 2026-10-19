# SplatForge

SplatForge is an extensible Windows-first pipeline for turning ordinary camera video/photos into datasets ready for 3D Gaussian Splatting.

The first milestone focuses on flat (non-360) cameras. 360/fisheye support is deliberately postponed until the flat-camera pipeline is reliable.

## Design goals

- Local-first processing.
- Every major pipeline task is replaceable by another method/backend.
- Resume/caching is a first-class requirement.
- GUI stays independent from processing logic.
- Command-line pipeline works before the GUI is built.
- External engines (FFmpeg, COLMAP, trainers) are wrapped behind adapters.
- Recommended initial SfM profile: ALIKED features + LightGlue matching + COLMAP global mapper.
- SIFT and alternative matchers/mappers remain available as fallbacks.

## Planned pipeline

Media ingest -> frame selection -> masking (optional) -> feature extraction -> pair selection -> feature matching -> mapping -> validation -> training -> export/viewer

## Quick start (foundation only)

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -e ".[dev]"

splatforge methods
pytest
ruff check .
```

This repository is a foundation. It intentionally does **not** run COLMAP/FFmpeg/3DGS yet. Add those incrementally following `docs/CODEX_PROMPTS.md` and `ROADMAP.md`.
