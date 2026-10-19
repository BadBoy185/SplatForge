# Codex implementation tasks

Use one bounded task at a time. Milestones and acceptance criteria are owned by
[ROADMAP.md](../ROADMAP.md); the contracts below are linked, not redefined here.
Review the diff after each task. Do not commit or push unless explicitly requested.
All commands mentioned in future tasks are proposed until implemented.

## Common instructions for every implementation task

Prepend this to the selected task:

```text
Read AGENTS.md, README.md, ARCHITECTURE.md, ROADMAP.md, docs/PIPELINE.md,
docs/PROJECT_FORMAT.md and docs/DEVELOPMENT.md. Inspect relevant implementation and
tests before editing. Check Git status and preserve unrelated user changes.

Implement only the selected milestone/subtask. Give a concise implementation plan
when it crosses boundaries. Keep core independent of UI and external engines; inject
adapters through application services. Do not create future-method stubs as if they
were runnable. Preserve existing user settings and originals.

Add meaningful tests for changed behavior, including compatibility, persistence,
cache invalidation or recovery where affected. Use fakes by default; real tools and
GPU tests are opt-in and must report prerequisites/skips. Never download models or
install toolchains implicitly. Do not hide unavailable capabilities with a fallback.

Run relevant tests, full pytest and ruff check . in the project environment. Identify
pre-existing failures separately; fix unrelated baseline lint only in an explicitly
scoped cleanup task. Review the diff and update affected documentation. Report what
works, evidence, limitations and the next task. Do not commit automatically.
```

## M1a Project persistence

Recommended next implementation task:

```text
Implement M1a: safe project persistence, not pipeline execution.

- Add application use cases and an injected local storage adapter for create/open/
  save/inspect. CLI handlers delegate; core models do not perform filesystem I/O.
- Implement the project document, separate format/config/state versions, revisioned
  saved stage settings and directory ownership from docs/PROJECT_FORMAT.md.
- Initialize state.sqlite with schema metadata only; no COLMAP database or scheduler.
- Resolve/preserve prototype PipelineConfig defaults through an explicit conversion.
  Keep stable method IDs and user values. Known settings are strict; opaque unknown
  method/version settings round-trip without execution. A preset label is not enough.
- Fix the confirmed role-validation collision by checking each selected slot
  independently. Add a regression test for training.none used as the mapper.
- Refuse creation in non-empty destinations and saves based on stale revisions.
  Implement validated atomic JSON saves, writer exclusion and explicit version errors.
- Establish migration dispatch and backup/recovery boundaries. If supporting an older
  format, add a fixture proving preservation and recovery; never rewrite newer formats.
- Add proposed project create/show commands and API save/reopen coverage. Test Unicode
  and spaces, moving a project, invalid/unknown settings, save interruption, non-empty
  destination refusal, stale writers and preservation of the previous valid document.

Do not implement media ingest, FFmpeg, COLMAP, GPU probes, training, GUI, an artifact
scheduler or a plugin framework. Leave run/attempt tables and fake-stage execution
for M1b. Do not opportunistically reformat unrelated source files.
```

## M1b Execution state and fake stages

```text
Implement M1b using injected fake stages only. Add run snapshots, attempt transitions,
artifact manifests, canonical stage fingerprints, a minimal dependency plan, progress/
cancellation/events and safe publication. Keep one writer and one active stage.

Prove unchanged reuse, training-like late-setting invalidation, missing/corrupt output
rejection, cancellation races, retry history and crash recovery before/after rename
and database commit. A directory or zero exit code is never sufficient for success.
Preserve cancelled results as incomplete; do not promote them during recovery.
No external tools, workflow DSL, distributed queue or cross-project cache.
```

## M2 Media ingest

```text
Implement M2: read-only photo/video source registration, immutable inventory revisions,
streaming digests and relinking. Separate source and camera groups. Preserve actual
video time bases, orientation and calibration assumptions. Unsupported/missing inputs
produce structured diagnostics and do not corrupt the inventory.

Add the shared process adapter and an FFprobe adapter with argument arrays, scoped
working directory/environment, bounded output, timeout and Windows process-tree
cancellation. Test with fakes/helpers and one opt-in generated-media integration.
Do not copy originals or implement frame extraction in this task.
```

## M3 Candidate views and fixed-FPS selection

```text
Implement M3 with FFmpeg behind an adapter. Publish candidate images and provenance
from video and photos, then a fixed-FPS selected-view manifest. Record actual frame
identity/timestamps, dimensions and transforms; do not infer a constant frame rate.
Use the existing attempt/cache/cancellation/publication mechanisms from the start.
Test VFR/orientation, immutable originals, cancellation/restart and cache reuse.
No blur scoring, learned features, mapping or GUI.
```

## M4 Quality and frame selection

```text
Implement M4 as separate quality measurement and selection operations. Add blur and
duplicate metrics, sharpest-per-interval selection, deterministic ties and rejection
reasons. Check candidate-pool sufficiency. Threshold changes reuse existing scores
and images; score-method changes invalidate their consumers. Keep rejected images
available as metadata-backed artifacts. Do not implement adaptive motion selection.
```

## M5 COLMAP and GPU capabilities

```text
Implement M5 capability discovery and doctor output, not feature execution. Probe the
selected binary, supported operations/formats, learned model/runtime availability and
backend-specific GPU health with timeouts. Record evidence and distinguish available,
unavailable and unknown. Core/GUI must not import PyTorch or pycolmap to list methods.
Test missing ONNX/model/Global Mapper support, CPU-only paths and failed CUDA/DLL probes.
Do not promise compatibility from a version string or download missing components.
```

## M6 Minimal pair selection

```text
Implement M6 before descriptor matching. Add PairSet and independent Sequential and
budgeted Exhaustive selectors, plus an explicit cross-group pair list. Test chronology,
canonical pair ordering, duplicates, self-pairs, pair budgets and multi-source coverage.
Use source groups, not assumed filename chronology. Declare future retrieval/spatial
requirements in documentation; do not register placeholder implementations as runnable.
```

## M7 Features, matching and geometric verification

Split M7 into reviewable tasks, keeping the full milestone acceptance gate:

```text
M7a: implement feature artifacts and the verified ALIKED and SIFT extraction routes.
Validate descriptor signatures, model digests and pixel/keypoint conventions. Isolate
native databases by feature identity. Publish immutable results and availability.

M7b: implement compatible LightGlue and SIFT/brute-force matching of an explicit
PairSet, followed by geometric verification with independent settings. Test actual
pair preservation and raw-match versus verified-geometry semantics. If a backend
fuses operations, expose the real execution/cache granularity instead of implying
independent reuse. Test mismatch rejection and native database integrity.

Run tiny opt-in integration fixtures on supported builds. Report missing learned/GPU
support rather than passing the whole milestone using only mocks or SIFT. No mapping.
```

## M8 Mapping

```text
Implement M8 behind mapping adapters: preferred supported Global Mapper and explicit
Incremental/Hierarchical alternatives. Publish all components, transforms and native
ID mappings; never silently discard disconnected models. Preserve upstream databases.
Test mapper-only invalidation, cancellation, invalid output and supported real routes.
Do not merge reconstruction quality policy into command execution.
```

## M9 Reconstruction validation

```text
Implement M9 structured metrics and quality gates independently from mapping. Include
per-source registration/coverage, components, tracks, reprojection and camera/geometry
checks with units, denominators and unknown measurements. Use configurable threshold
profiles. Controlled fixtures must trigger pass/warn/fail; changing thresholds must
not rerun mapping. Record explicit overrides of failed gates. Do not rewrite models.
```

## M10 Complete flat-camera CLI

```text
Implement M10 DatasetPreparation and dataset export with explicit undistortion/resize,
consistent cameras/poses/image references and a validation gate. Compose the complete
application/CLI workflow, dry-run resource/capability/cache reasons and status/retry.
Demonstrate video, photos, multiple clips and mixed sources using bounded pair policies;
state limits for large collections. Verify exported data with a consumer/independent
reader. Exercise interruption, relocation, corruption, disk-full and Windows paths.
No GUI or managed Gaussian training yet.
```

## M11 Legacy evaluation and training

```text
M11a: inspect the provided legacy 3DGS project read-only. Record useful versions,
parameters, preprocessing, camera/scale assumptions, hardware and results. Translate
candidate recipes into versioned presets with provenance and explicit overrides.
Evaluate on controlled scenes; do not import the old implementation into core.
If the project is not provided, report the missing evidence without dismissing it.

M11b: implement a tested external LichtFeld dataset handoff, then one deliberately
selected managed trainer adapter. Separate manual handoff from managed execution.
Verify a loadable scene, progress/cancellation, checkpoint compatibility where supported,
training metrics and scene export. Trainer-setting changes must reuse earlier SfM.
A gsplat-based option needs an explicit training recipe, not just a library wrapper.
```

## M12 GUI

```text
Implement M12 PySide6 screens as clients of existing application services. Cover
project/source management, guided profiles, advanced stage settings, plan/progress,
cancel/retry, diagnostics and inspection. Keep processing off the UI thread. Test
CLI/GUI project interchange and architecture rules preventing direct backend calls.
Do not duplicate pipeline, cache or persistence logic in widgets.
```

## M13 Advanced methods and automation

Select exactly one M13 submilestone from ROADMAP.md, then narrow it to one executable
slice with its fixture, resource budget and comparison criteria. Implement retrieval/
hybrid/GPS (M13a), masks/segmentation (M13b), local queue/retry (M13c), measured scale/
cleanup work (M13d), or a concrete alternative backend/LiDAR adapter (M13e). Preserve
existing flat-camera contracts and add tests for new dependency edges. Do not implement
all advanced features in one task or introduce a speculative plugin SDK.

## M14 360 input preprocessing

```text
Implement M14 as an input/preprocessing adapter producing existing perspective-view
contracts. Preserve parent capture, projection, virtual calibration, timestamps, masks
and rig metadata. Verify geometry requirements for mixed drone + 360 workflows; do not
pretend multiple projections provide translational baseline. Demonstrate calibrated
fixtures and a mixed-source integration scene through the existing SfM/training path.
Run the full flat-camera regressions. No rewrite of the flat pipeline or unverified
native spherical mapper support.
```
