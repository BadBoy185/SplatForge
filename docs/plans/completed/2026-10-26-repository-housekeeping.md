# Repository housekeeping after M12

Status: completed, 2026-10-26. This is not a product milestone.

## Goal

Route agent context by responsibility, preserve decision history and make affected
verification practical as the repository grows.

## Non-goals

No production refactoring, product/runtime/GUI changes, contract/schema/identity
changes, dependency updates, backend execution, downloads, commits or pushes.

## Relevant contracts

- [AGENTS routing and invariants](../../../AGENTS.md)
- [Dependency boundaries](../../../ARCHITECTURE.md#dependency-direction)
- [Pipeline ownership](../../PIPELINE.md#stage-inputs-and-outputs)
- [Storage ownership](../../PROJECT_FORMAT.md#storage-layout-and-ownership)
- [Verification workflow](../../DEVELOPMENT.md#verification-workflow)

## Affected areas

Engineering routing, documentation map, plan lifecycle/template, one repo-local
verification skill, local Markdown checker and architecture acceptance tests.
Existing user edits to adapters/tests, contracts and benchmark evidence were present
before this task and are outside its implementation scope.

## Acceptance criteria

The [map](../../index.md) classifies every existing documentation family, including
partial M7c delivery and research. AGENTS routes selective reading. Verification has
affected/full gates and attributable evidence reuse. Old prompts/history keep their
URLs; plans have an active/completed lifecycle. Harness checks stay offline and small.

## Verification

Affected checks: `tests/test_check_docs.py`, `tests/test_gui_architecture.py`, Ruff
and `scripts/check_docs.py`. Full pytest is not required for this bounded harness
change; no product milestone, merge or release is being completed.

## Decisions / unknowns

- 2026-10-26: classify old milestone/research documents in place. They retain useful
  method details; moving/extracting all of them would expand the diff and risk links.
- One owner per fact going forward. Selectively consolidate live method details
  when that area is next changed; do not rewrite old evidence to match later knowledge.
- Use explicit commands rather than new fast/full wrappers or a second test matrix.
- One `verify-change` skill is sufficient now; other workflows remain in their owners
  until repetition demonstrates that another skill is useful.
- Static import tests are intentionally limited; Core I/O/indirect execution still
  need review. No custom architecture framework was introduced.

## Final status

Documentation/harness structure delivered. Existing milestone files and research
remain at stable locations; no M13 scope is activated.

Agent-run evidence on Windows / project Python 3.12.10:

- `python -m pytest tests/test_check_docs.py tests/test_gui_architecture.py`:
  19 passed, no skips (1.65 s in the final affected run).
- `python -m ruff check scripts/check_docs.py tests/test_check_docs.py tests/test_gui_architecture.py`:
  passed. Full `python -m ruff check .` finds the pre-existing E501 in
  `src/splatforge/core/registry.py:52`, also present in HEAD; left untouched.
- `python scripts/check_docs.py`: 31 Markdown files, no local-link errors.
- Python AST and project TOML parse; `git diff --check` passes. Baseline SHA-256
  comparison confirms all existing production files and unrelated user files stayed
  byte-identical. No tracked source media, model weights or large binaries found.
- The skill's bundled `quick_validate.py` cannot start without PyYAML in the available
  Python environments. Required frontmatter fields/name/description and absence of
  scaffold placeholders were checked separately; local links passed the docs checker.
  No dependency was installed.

Remaining debt: selectively consolidate live normative method details still embedded
in old milestone notes when that area is next touched. Large README/DEVELOPMENT and
historical status prose need ownership discipline, not a bulk rewrite. Static
guardrails do not detect arbitrary dynamic execution or filesystem effects.
