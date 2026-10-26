---
name: verify-change
description: Select and record affected or full SplatForge verification for a bounded change, including documentation-only and developer-harness changes.
---

# Verify a SplatForge change

Use the repository's [AGENTS](../../../AGENTS.md) first. Read
[verification workflow](../../../docs/DEVELOPMENT.md#verification-workflow) for
commands and full gates; do not load every backend's integration instructions.

1. Inspect Git status/diff; distinguish this task from existing user edits. Map the
   affected responsibilities to tests, including consumers of changed contracts.
2. Select affected, documentation-only or full verification using that owner.
   Choose explicit tests; an empty selection must not accidentally launch all pytest.
3. Run required checks in the project environment. Read a backend-specific section
   only if that integration is in scope and explicitly provisioned. Preserve the
   default offline behavior; never enable heavyweight workloads just for verification.
4. Accept a user-supplied result for the same tree/environment/command when still
   applicable; record its source. Recheck only invalidated evidence after edits.
5. Inspect links and final diff. Report commands, outcomes, skips, unrun checks and
   remaining gates separately. Affected success is not full-suite success.

Done means evidence covers the chosen scope and required gates, or any remaining
failure/gate is stated explicitly. This skill does not change acceptance criteria.
