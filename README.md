# SplatForge

SplatForge is a Windows-first, local-first application in early development for
turning photos and videos into high-quality 3D Gaussian Splatting scenes. The product
aims for the breadth and convenience of desktop tools such as 360 Gaussian / 360
Gaussian Pro, while keeping processing methods replaceable. This is a product goal,
not a claim of current feature parity.

Phase 1 targets drone and phone video, DSLR/mirrorless photographs, multiple clips
and mixed ordinary-camera sources. "Flat camera" means a perspective camera, with
ordinary lens distortion supported through an explicit camera model; it does not
mean every input must already be distortion-free. 360, fisheye and equirectangular
inputs come later through preprocessing into perspective views.

## Current status

The repository contains configuration models, a method catalog, safe local project
persistence, the M1b2 fake-stage execution/recovery slice, M2 media ingest and the M3
candidate-view/fixed-FPS route. The CLI
can create/show projects, upgrade historical state v1/v2/v3 to v4, register/list/verify/
relink ordinary JPEG/PNG/MP4/MOV sources, and execute or inspect the deterministic fake
route. `views prepare` materializes bounded JPEG/PNG candidate pixels from registered
photos and independent video timelines, then publishes a metadata-only fixed-FPS
selection. Saved intent lives in `project.json`; immutable input inventories live under
`sources/`; state v4 stores execution history and durable source-verification evidence.

Project saves and fake runs share one OS-held Windows writer lock. Fake outputs are
validated before immutable publication and cache reuse rechecks manifests and payload
digests. A second CLI can create the bounded `cancel.request` without taking that lock;
the owner durably accepts it before stopping, publishing or succeeding. Recovery and
manual bounded retry remain specific to in-process fake stages; an interrupted M3 route
restarts as a new command and reuses only completed stage artifacts. M2 streams source
hashes, normalizes FFprobe metadata and runs external processes with bounded output,
timeouts, cancellation and Windows Job Object containment. M3 uses that boundary for
FFmpeg, preserves selected input presentation timestamps, applies orientation explicitly,
and validates every published image without modifying originals. Quality scoring,
sharpest-per-interval selection, COLMAP, training and GUI remain planned.
Catalog entries describe intended methods, not installed or implemented capabilities.

These commands work in the foundation:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\splatforge.exe version
.\.venv\Scripts\splatforge.exe methods
.\.venv\Scripts\splatforge.exe show-default-config
.\.venv\Scripts\splatforge.exe project create "C:\SplatForge Projects\First scene" --label "First scene"
.\.venv\Scripts\splatforge.exe project show "C:\SplatForge Projects\First scene"
.\.venv\Scripts\splatforge.exe project upgrade-state "C:\SplatForge Projects\First scene"
.\.venv\Scripts\splatforge.exe media add "C:\SplatForge Projects\First scene" "D:\Media\photo.jpg" "D:\Media\clip.mp4" --ffprobe "C:\ffmpeg\bin\ffprobe.exe"
.\.venv\Scripts\splatforge.exe media list "C:\SplatForge Projects\First scene"
.\.venv\Scripts\splatforge.exe media verify "C:\SplatForge Projects\First scene" --policy balanced
.\.venv\Scripts\splatforge.exe media verify "C:\SplatForge Projects\First scene" --policy strict
.\.venv\Scripts\splatforge.exe media relink "C:\SplatForge Projects\First scene" <source-id> "E:\Moved\photo.jpg"
.\.venv\Scripts\splatforge.exe views prepare "C:\SplatForge Projects\First scene" --target-fps 2 --candidate-fps 4 --ffmpeg "C:\ffmpeg\bin\ffmpeg.exe" --image-format jpeg --jpeg-qscale 2 --max-candidates 10000 --max-disk-gib 20
.\.venv\Scripts\splatforge.exe run fake "C:\SplatForge Projects\First scene" --start 0 --count 3 --factor 2
.\.venv\Scripts\splatforge.exe run show "C:\SplatForge Projects\First scene" <run-id>
.\.venv\Scripts\splatforge.exe run cancel "C:\SplatForge Projects\First scene" <run-id>
.\.venv\Scripts\splatforge.exe run recover "C:\SplatForge Projects\First scene" <run-id>
.\.venv\Scripts\splatforge.exe run retry "C:\SplatForge Projects\First scene" <run-id>
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
```

Creation requires a missing or empty directory. It creates `project.json`,
`project.lock` and state schema v4 in `state.sqlite`; source and execution directories
are created only by their operations. Existing state v1/v2/v3 projects remain
open/show/save compatible. The M1b fake route remains usable on v3, while M2 mutation and
verification and M3 execution require explicit upgrade to v4. `SPLATFORGE_FFPROBE`
may provide the FFprobe path instead of `--ffprobe`; `SPLATFORGE_FFMPEG` similarly
provides the FFmpeg path instead of `--ffmpeg`. M3's explicit command uses
`frame_selection.fixed_fps` run settings and does not reinterpret or rewrite a
project's saved `frame_selection.sharpest_interval` intent.

For programmatic editing:

```python
from pathlib import Path
from splatforge.bootstrap import build_project_service

projects = build_project_service()
root = Path("C:/SplatForge Projects/First scene")
document = projects.open(root)
document.label = "Renamed scene"
document = projects.save(root, document)
```

Python 3.12 is the tested baseline. Windows tests exercise Job Object cancellation,
timeout, owner-death descendant cleanup and local fixed-volume read leases that deny
write/delete while allowing readers. Default tests require no FFmpeg installation; set
`SPLATFORGE_TEST_FFPROBE` for the generated-PNG real FFprobe test and
`SPLATFORGE_TEST_FFMPEG` to an FFmpeg executable (or `1` for configured PATH lookup)
for the generated VFR/rotation candidate-view integration test. COLMAP, CUDA and trainer
installation remain unnecessary.

## Intended workflow

Create project -> register sources -> decode/preprocess candidate views -> assess
quality and select views -> optional masks -> extract features and select pairs ->
match and geometrically verify -> reconstruct -> validate -> select reconstruction
components -> prepare training dataset -> optional training -> export/view.

Feature extraction and pair selection have independent inputs; this summary is not
a mandatory linear execution order. A project can stop at a validated training
dataset for use in an external trainer.

- Preferred learned route: ALIKED + compatible LightGlue, then COLMAP Global Mapper,
  where the installed backend supports the complete route.
- Fallback routes: SIFT with compatible matching, COLMAP Incremental Mapper and
  Hierarchical Mapper. A fallback is an explicit, recorded choice.
- Ordered video starts with within-clip Sequential pairs. Practical multi-video
  support combines these with cross-clip retrieval from M7c, before the complete CLI.
  Retrieval has explicit representation/index requirements independent of ALIKED.
- Preserve originals; show progress, failures and reconstruction quality; resume
  valid work. Training changes must not rerun decoding or SfM.

The first usable release is a complete CLI pipeline producing a validated dataset.
Training integration follows, then a GUI using the same application services.
Later work includes masks/segmentation, GPS, LiDAR, alternative SfM/training methods,
large-scene automation, batch jobs and 360 workflows. Previously successful 3DGS work
may be researched read-only earlier without blocking implementation; official preset
translation/benchmarking stays with training integration.

## Documentation

| Document | Responsibility |
| --- | --- |
| [AGENTS.md](AGENTS.md) | Authoritative engineering rules and task completion checks |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Product boundaries, dependency direction and decisions |
| [Pipeline contracts](docs/PIPELINE.md) | Stage inputs/outputs, compatibility and invalidation |
| [Project format and state](docs/PROJECT_FORMAT.md) | Storage ownership, migrations, attempts and recovery |
| [Development guide](docs/DEVELOPMENT.md) | Testing, diagnostics and Windows/backend risks |
| [Architecture review](docs/ARCHITECTURE_REVIEW.md) | Evidence from the original foundation and deferred decisions |
| [Legacy research](docs/LEGACY_3DGS_RESEARCH.md) | Optional read-only evidence gathering before later preset evaluation |
| [ROADMAP.md](ROADMAP.md) | Incremental, verifiable milestones |
| [Codex prompts](docs/CODEX_PROMPTS.md) | Scoped implementation tasks aligned with the roadmap |

Keep source media, generated projects, model weights and training output outside the
repository. Next is **M4 — frame quality and selection**.
