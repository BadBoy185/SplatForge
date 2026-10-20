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

The repository contains configuration models, a method catalog, compatibility
validation, a default profile and safe local project persistence (M1a2). The CLI can
create/show projects; the application API can open/save them. Saved intent lives
in `project.json`; `state.sqlite` contains only metadata.

Project saves use revision checks, one OS-held Windows writer lock and validated
same-volume replacement. Media ingest, runs/attempts/artifacts, FFmpeg/COLMAP
execution, training and GUI remain planned.
Catalog entries describe intended methods, not installed or implemented capabilities.
The existing `PipelineConfig` remains a prototype and is explicitly converted when
creating a project; it is not itself the project file format.

These commands work in the foundation:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\splatforge.exe version
.\.venv\Scripts\splatforge.exe methods
.\.venv\Scripts\splatforge.exe show-default-config
.\.venv\Scripts\splatforge.exe project create "C:\SplatForge Projects\First scene" --label "First scene"
.\.venv\Scripts\splatforge.exe project show "C:\SplatForge Projects\First scene"
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
```

Creation requires a missing or empty directory. Only `project.json`, `project.lock`
and `state.sqlite` are created. Projects open from their saved settings, never by
reapplying a preset. Unknown method/settings versions and extra envelope fields
survive save/reopen as equivalent JSON values.

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

Python 3.12 is the tested baseline. Windows 10/11 and Windows Server 2022 are target
platforms; support must be established by tests as adapters are added. FFmpeg, COLMAP,
CUDA and trainer installation are not required for the foundation. At the architecture
review baseline, the three tests pass and Ruff reports 18 existing source violations.

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

Keep source media, generated projects, model weights and training output outside
the repository. Next is **M1b1: execution and cache happy path**. Review each diff;
commit only on request.
