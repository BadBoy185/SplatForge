# SplatForge engineering constitution

This file is authoritative for engineering work. [ARCHITECTURE.md](ARCHITECTURE.md)
defines boundaries; [docs/PIPELINE.md](docs/PIPELINE.md) defines stage contracts;
[docs/PROJECT_FORMAT.md](docs/PROJECT_FORMAT.md) defines persistence and state.
The roadmap describes planned work, not implemented capabilities.

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
  mapping, reconstruction validation, dataset preparation, training and export.
- Every major stage is replaceable through explicit typed inputs/outputs. Prefer
  small protocols and injected implementations; do not build a plugin framework or
  universal workflow language before a concrete requirement needs one.
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
- Publish outputs only after validation. A directory, exit code zero or matching
  fingerprint alone is not proof of success. Never mutate a published artifact.
- Every new long-running stage must use progress, cancellation, structured events,
  isolated workspaces and persisted attempts. Stage restart is the minimum resume
  guarantee; claim checkpoint resume only when tested for that backend.
- When adding a method, define its stable ID, settings schema/defaults, consumed
  inputs, compatibility/capability requirements, output contract, fingerprint inputs,
  failure behavior and contract tests. Update documentation and availability reporting.
- Resolve presets into saved settings. New defaults must not silently change existing
  projects. Preserve unsupported method settings on open; refuse execution clearly.

## Coding and external execution

- Use Python 3.12 as the tested baseline, Pydantic v2, Typer, pytest and Ruff. Public
  APIs have type hints. Prefer small modules, dependency injection and explicit errors;
  avoid global mutable state and unrelated refactors.
- Use `pathlib.Path`. Persist project-owned paths relative to the project; preserve
  external source locators separately from identity. Test spaces, Unicode, drive
  changes, case collisions, long paths and unavailable sources. Never concatenate
  shell commands or assume the working directory is the project directory.
- Process execution uses argument arrays, `shell=False`, an explicit working
  directory and scoped environment, bounded output streaming and timeouts. Resolve
  executables explicitly. Cancellation must stop the owned Windows process tree,
  release file handles and record a terminal attempt state.
- Probe the installed backend, model files and actual GPU/runtime combination.
  A version string, registry entry or installed CUDA toolkit is not sufficient.
  Keep heavyweight dependencies optional and probe outside core/UI imports.

## User data and Git safety

- Originals are read-only references by default. Never silently move, overwrite,
  delete, rename or recompress source files. Relinking verifies content identity.
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

1. Read the relevant architecture and inspect existing code before editing.
2. Make the smallest coherent change within the authorized task; flag contradictions.
3. Add/update meaningful tests for changed behavior, especially compatibility,
   dependency invalidation, persistence, migrations and interruption recovery.
   Documentation-only tasks need documentation checks, not artificial code tests.
4. Run relevant tests, full `pytest`, and `ruff check .` in the project environment.
   Report pre-existing failures and unavailable integration checks honestly; do not
   repair unrelated code to make a documentation task green.
5. Update affected contracts, roadmap/prompts and user documentation. Check links,
   terminology, implemented/planned claims and the final diff for scope and data.
6. Report what changed, verification results, limitations and the next useful step.
