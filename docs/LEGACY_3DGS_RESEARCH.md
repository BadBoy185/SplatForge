# Legacy 3DGS research

## Status and timing

The M11 read-only repository and ignored local-evidence search on 2026-10-24 found no
historical training recipes, checkpoints, LichtFeld or Nerfstudio/Splatfacto settings:
`legacy_evidence_unavailable`. Existing Russian-dacha evidence covers SfM/M10 only.
No recovered legacy parameters or official quality presets are claimed. Independently
verified gsplat candidates and sources are in [M11 evidence](M11_EVIDENCE.md).

Read-only inspection may happen at any milestone when the project becomes available.
It is optional, non-blocking research: early persistence, ingest, SfM and CLI work do
not depend on it. Record missing evidence and continue. M11a owns translation and
benchmarking before any recipe becomes an official SplatForge preset; M11b owns
training integration. Research alone does not authorize running old scripts, installing
dependencies or changing the legacy project.

## Evidence to record when available

Keep media, checkpoints and large outputs outside Git. Reference exact files/config
keys, code revisions or supplied measurements; avoid private machine paths in shared
notes where a descriptive locator suffices.

| Area | Evidence to collect |
| --- | --- |
| Setup identity | Project/revision, trainer/library versions, environment and model/weight identity |
| Input preparation | Source types, frame selection, resolution/crop, masks, camera models, distortion and coordinate/scale conventions |
| Training recipe | Explicit values/defaults for optimizer, losses, schedules, densification/pruning, iterations, seed and checkpoint/resume behavior |
| Hardware/resources | OS, GPU/runtime, VRAM/RAM, measured runtime and dataset size |
| Results | Scene/view identities, held-out evaluation protocol where present, metrics, visual evidence and known failure cases |
| Design lessons | Useful boundaries/workflow choices and constraints that matter to SplatForge |

## Research entries

The M11 search result above is an evidence gap, not a judgment about earlier results.
Each future recovered entry should state:

- What was directly observed and its exact evidence reference.
- What remains a hypothesis or missing information, including hidden defaults.
- A candidate lesson/recipe and how it maps to existing SplatForge stage contracts.
- The benchmark or compatibility check required before official adoption in M11a.

Do not dismiss the old implementation as obsolete or copy its internals into core.
Preserve useful settings as evidence first; keep later presets versioned, explicit
and independent of the legacy project's runtime/code layout.
