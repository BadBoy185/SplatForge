# SplatForge engineering constitution

This file owns engineering invariants and context routing. Always read it first;
use [docs/index.md](docs/index.md) as a map, not a mandatory reading list.

## Read by task

Read relevant sections and code, not every document end to end:

- System/dependency boundaries -> [ARCHITECTURE.md](ARCHITECTURE.md).
- Stage/method/compatibility/cache -> [docs/PIPELINE.md](docs/PIPELINE.md).
- Persistence/state/storage/recovery -> [docs/PROJECT_FORMAT.md](docs/PROJECT_FORMAT.md).
- Processes/progress/testing/diagnostics -> [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).
- GUI presentation -> [docs/GUI_DESIGN.md](docs/GUI_DESIGN.md).
- Planned scope/acceptance -> only the relevant [ROADMAP.md](ROADMAP.md) section
  and selected [active plan](docs/plans/active/README.md).
- Technology evaluation -> the relevant research entry in the documentation map.

Completed milestone notes and legacy prompts are optional history/detail lookups,
not startup context. Follow their links only for a concrete dependency.

## Product and scope

- Build a Windows-first, local-first desktop product for photos/videos to 3D Gaussian
  Splatting scenes. Deliver a working CLI/core before a GUI.
- Phase 1 accepts ordinary perspective cameras, including ordinary lens distortion.
  Defer fisheye, equirectangular and 360 inputs to preprocessing that emits the same
  perspective-view contracts. Do not require a rewrite of SfM or training.
- Keep large media, models, checkpoints, generated projects and machine-specific
  configuration outside Git. Use tiny synthetic fixtures in tests.

## Architectural invariants

- Dependencies point inward: CLI/GUI -> application -> core. Adapters implement
  inward-owned interfaces; the composition root injects them. Core imports no UI,
  process runner, filesystem persistence, FFmpeg, COLMAP, PyTorch or trainer library.
- GUI widgets and CLI handlers delegate use cases. Only adapters execute external
  programs or load external processing libraries.
- Separate decoding/preprocessing, quality assessment, frame selection, masking,
  feature extraction, pair selection, descriptor matching, geometric verification,
  mapping, reconstruction validation/selection, dataset preparation, training and export.
- Every major stage is replaceable through explicit typed inputs/outputs. Prefer
  small protocols and injected implementations; do not build a plugin framework or
  universal workflow language before a concrete requirement needs one. Semantic
  boundaries do not require every backend to expose every intermediate result.
- ALIKED + LightGlue and COLMAP Global Mapper are preferred choices, not invariants.
  Preserve compatible SIFT/brute-force and Incremental/Hierarchical Mapper routes.
  Never silently change a selected method or mix incompatible features in a database.
- Distinguish catalog entries, implemented methods, detected capabilities and runnable
  plans. Validate each configuration slot independently, method-specific settings,
  artifact formats, camera support and runtime requirements.

## State, cache and methods

- Separate project intent, immutable run configuration, attempt state and published
  artifacts. Do not store application state in a COLMAP database.
- Fingerprint each stage from its resolved settings, method/adapter versions,
  consumed inputs and output-affecting runtime/model identity. Never hash the entire
  pipeline configuration as every stage's cache key. Invalidate actual consumers.
- Preserve every reconstruction component; record explicit manual/policy selection in
  a fingerprinted artifact before dataset preparation. Never silently select the largest.
- Publish outputs only after validation. A directory, exit code zero or matching
  fingerprint alone is not proof of success. Never mutate a published artifact.
- Every new long-running stage must use progress, cancellation, structured events,
  isolated workspaces and persisted attempts. Stage restart is the minimum resume
  guarantee; claim checkpoint resume only when tested for that backend.
- When adding a method, define its stable ID, settings schema/defaults, consumed
  inputs, compatibility/capability requirements, output contract, fingerprint inputs,
  failure behavior and contract tests. Update documentation and availability reporting.
- Resolve presets into saved settings. New defaults must not silently change existing
  projects. Preserve unsupported method settings on open; refuse targets that need
  them, without blocking unrelated targets such as dataset export.

## Coding and external execution

- Use Python 3.12 as the tested baseline, Pydantic v2, Typer, pytest and Ruff. Public
  APIs have type hints. Prefer small modules, dependency injection and explicit errors;
  avoid global mutable state and unrelated refactors.
- Decompose by independent reasons to change or semantic responsibilities, not a line
  limit. File size is a review signal, never authorization for an unrelated refactor.
- Use `pathlib.Path`. Persist project-owned paths relative to the project; preserve
  external source locators separately from identity. Test spaces, Unicode, drive
  changes, case collisions, long paths and unavailable sources. Never concatenate
  shell commands or assume the working directory is the project directory.
- Process execution uses argument arrays, `shell=False`, an explicit working
  directory and scoped environment, bounded output streaming and timeouts. Resolve
  executables explicitly. Cancellation must stop the owned Windows process tree,
  release file handles before recording successful cancellation; unresolved teardown
  blocks retry and publication.
- Run native/GPU processing and risky capability probes in owned worker processes;
  keep workers disposable and the application process free of CUDA state.
- Probe the installed backend, model files and actual GPU/runtime combination.
  A version string, registry entry or installed CUDA toolkit is not sufficient.
  Keep heavyweight dependencies optional and probe outside core/UI imports.

## User data and Git safety

- Originals are read-only references by default. Never silently move, overwrite,
  delete, rename or recompress source files. Relinking verifies content identity.
- Hash sources fully at ingest. Later verification uses a recorded Balanced/local or
  Strict policy; metadata-based reuse must not be reported as a fresh content check.
- Refuse project creation in a non-empty destination. Back up before migrations;
  refuse unsupported newer formats without rewriting them. Use transactional state
  writes and recoverable atomic file publication on the same volume.
- Cleanup requires explicit scope and authorization, a preview, ownership and path
  containment checks, and protection against symlink/junction traversal. Cache
  invalidation is not deletion. Protect exports and checkpoints from generic cleanup.
- Inspect Git status first, preserve user edits and keep task diffs scoped. Do not
  commit, push, reset or discard changes unless explicitly requested by the user.
  Do not download models, install toolchains or enable telemetry implicitly.

## Before finishing a task

1. Always read AGENTS.md, then the task's listed contract sections and relevant code.
   Follow additional documents only when a concrete dependency requires them.
2. Make the smallest coherent change within the authorized task; flag contradictions.
3. Add/update meaningful tests for changed behavior, especially compatibility,
   dependency invalidation, persistence, migrations and interruption recovery.
   Documentation-only tasks need documentation checks, not artificial code tests.
4. Use affected tests/lint during development; use full verification at completion
   gates defined in [DEVELOPMENT](docs/DEVELOPMENT.md#verification-workflow).
   Documentation-only work needs links/claims/diff checks. Report failures/skips and
   who ran each check; do not repair unrelated code or repeat unchanged full results.
5. Update the authoritative owner of each changed fact; link rather than duplicate.
   Follow [documentation hygiene](docs/DEVELOPMENT.md#documentation-hygiene) and
   close the selected plan when applicable. Check the final diff for scope and data.
6. Report what changed, verification results, limitations and the next useful step.
