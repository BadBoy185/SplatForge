# Documentation map

Start with [AGENTS](../AGENTS.md), then open only the owner/section needed by the
task. This map routes context; it does not define application contracts or prove
that a planned capability is implemented.

## Authoritative owners

| Document | Owns | Does not own |
| --- | --- | --- |
| [AGENTS](../AGENTS.md) | Engineering invariants, safe work and context routing | Stage schemas or implementation history |
| [ARCHITECTURE](../ARCHITECTURE.md) | System boundaries, dependency direction and responsibility allocation | Backend instructions or milestone acceptance evidence |
| [PIPELINE](PIPELINE.md) | Stage inputs/outputs, method compatibility and fingerprint/invalidation rules | Storage layout or proof of local backend availability |
| [PROJECT_FORMAT](PROJECT_FORMAT.md) | Persistence, paths, versions, attempts, publication and recovery | Processing algorithms or UI state |
| [DEVELOPMENT](DEVELOPMENT.md) | Verification workflow, process/progress/diagnostic engineering and documentation hygiene | Artifact schemas or product scope |
| [ROADMAP](../ROADMAP.md) | Planned capability scope, ordering and milestone acceptance | Proof of implemented or locally runnable support |
| [GUI_DESIGN](GUI_DESIGN.md) | Presentation architecture, design system and visual review | Pipeline, cache or persistence decisions |
| [UX/UI specification](UX_UI_SPEC.md) | Intended product UX, navigation and interaction rules | Proof that future capabilities are implemented |

[README](../README.md) is the user entrypoint for setup, available commands and
limitations. [GPU_RUNTIME](GPU_RUNTIME.md) is the operator guide for an explicitly
provisioned Windows runtime; neither replaces capability probes or numerical contracts.
Use [pyproject.toml](../pyproject.toml) for dependency/tool configuration.
The repo-local [verify-change skill](../.agents/skills/verify-change/SKILL.md)
reuses DEVELOPMENT for verification selection and evidence reporting.

## Current work

- [M12b3 Capture Metadata & Logical Source Groups](plans/active/2026-10-27-m12b3-capture-metadata-groups.md):
  saved capture evidence and portable organization, independent of calibration/recipes.
- [Active plans](plans/active/README.md): selected bounded work only; no M13 task is
  activated by this housekeeping change.
- [Plan template](plans/TEMPLATE.md) and [plan lifecycle](DEVELOPMENT.md#durable-plans):
  create one plan for substantial work instead of appending prompts indefinitely.
- Open evidence gates include production M7c VPR and representative M8 mapper
  recommendations. Read their specific roadmap/research sections only when relevant;
  a pending gate does not make all old milestone instructions active again.

## Technology / research

Research is evidence or a proposal, never implemented support or an adopted default.
Existing paths are retained to preserve links and user work.

- [Technology strategy](TECHNOLOGY_STRATEGY.md): candidate comparisons and adoption gates.
- [M7c benchmark ledger](M7C_BENCHMARK.md): candidate/license audit and missing VPR evidence.
- [M11 evidence](M11_EVIDENCE.md): training candidate/license evidence, no universal preset.
- [Legacy 3DGS research](LEGACY_3DGS_RESEARCH.md): read-only investigation and unavailable evidence.

## Historical / completed implementation slices

These files stay at their existing URLs. Read them for a specific method detail,
decision or recorded result, not as instructions to replay a milestone. They contain
useful implementation detail beyond the high-level contracts; their scope/status is
local to the recorded slice. Contract changes go to the authoritative owner first;
do not reinterpret old acceptance results as current runtime evidence.

| Notes | Classification and lookup purpose |
| --- | --- |
| [M7B](M7B.md) | Delivered matching/verification slice; profile, compatibility and transport details |
| [M7C](M7C.md) | Delivered offline/hybrid slice only; production VPR acceptance remains open |
| [M8A](M8A.md) | Delivered Global mapping foundation and reader details |
| [M8B1](M8B1.md) | Delivered Incremental/Caspar route and recorded gates |
| [M8B2](M8B2.md) | Delivered Hierarchical/Global acceleration/comparison routes; no universal mapper recommendation |
| [M9](M9.md) | Delivered reconstruction validation and explicit selection slice |
| [M10](M10.md) | Delivered dataset-preparation slice; production multi-video acceptance is a separate gate |
| [M11](M11.md) | Delivered handoff/managed-training slice and bounded empirical results |
| [M12](M12.md) | Delivered desktop slice, parity evidence and limitations |
| [M12a project shell](plans/completed/2026-10-27-m12a-project-shell.md) | Accepted Home/Create/Open/Sources shell |
| [M12b2a Source Participation](plans/completed/2026-10-27-m12b2a-source-participation.md) | Accepted portable Exclude/Restore and processing membership |
| [M12b2 Sources workflow](plans/completed/2026-10-27-m12b2-folder-browser.md) | Accepted folder import/browser and corrective UX |
| [M12b1 Sources and preview](plans/completed/2026-10-27-m12b1-sources-preview.md) | Accepted explicit import, source inspection and preview |
| [Housekeeping](plans/completed/2026-10-26-repository-housekeeping.md) | Repository/documentation harness work, not a product milestone |

## Archive / legacy

- [Architecture review](ARCHITECTURE_REVIEW.md): dated foundation review; findings
  are historical, not a current defect list.
- [CODEX_PROMPTS](CODEX_PROMPTS.md): legacy M1–M12 prompts plus unactivated M13/M14
  outlines. Kept intact for provenance; new work uses a selected plan.

No bulk move into `research/` or `archive/` is needed now. Classification here keeps
old links stable; create those folders only when an actual relocation is worthwhile.
History/research/archive are never mandatory context for an ordinary task.
