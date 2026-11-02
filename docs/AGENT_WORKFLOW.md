# Agent workflow

This owns delegation mechanics; [AGENTS](../AGENTS.md) owns engineering rules and
[DEVELOPMENT](DEVELOPMENT.md#verification-workflow) owns verification gates.
Keep the current handoff in [PROJECT_STATE](PROJECT_STATE.md), with detailed UI
evidence in its linked selected plan. Older Materials evidence retains its own plan.
Recheck Git and files each session; saved state is neither acceptance nor a new task.

## Roles and configuration

The main agent uses the user's selected model (requested for this setup: GPT-6.1 Sol,
Max). No project setting pins its model or effort. It retains requirements,
architecture, dependencies, file ownership, integration and final verification.

| Role | Model / effort | Responsibility |
| --- | --- | --- |
| [implementation](../.codex/agents/implementation.toml) | `gpt-6.1-sol` / `high` | Bounded Python/application/QML implementation |
| [reviewer](../.codex/agents/reviewer.toml) | `gpt-6.1-sol` / `high` | Independent review; no edits |
| [ux_reviewer](../.codex/agents/ux_reviewer.toml) | `gpt-6.1-terra` / `medium` | Scenarios and actual GUI screenshots; no edits |
| [tester](../.codex/agents/tester.toml) | `gpt-6.1-sol` / `medium` | Requirements, tests and bounded diagnostics |
| [utility](../.codex/agents/utility.toml) | `gpt-6-luna` / `high` | Narrow searches and mechanical work |

[Project config](../.codex/config.toml) enables subagents, caps concurrent spawned
threads at three (primary excluded), and supplies Sol/medium as a fallback for
unclassified work. Every role explicitly sets both model and effort to prevent
inheritance of the main agent's Max. Do not instantiate every role for every task.
Utility does not own architecture, complex diagnosis or final acceptance.

Local clients discover standalone `.codex/agents/*.toml` files. Required fields are
`name`, `description`, `developer_instructions`; each file here also sets `model`
and `model_reasoning_effort`. No duplicate legacy role registration is needed.
Read-only reviewer behavior is an instruction, not a separate permission sandbox;
custom agents inherit parent permissions, provider and MCP setup.

In this task's tool environment, real agents use `collaboration.spawn_agent` with
explicit `model`, `reasoning_effort` and `fork_turns="none"`. Its interface has no
custom-agent selector: a task name alone does not prove a TOML role was loaded.
Include the relevant role instructions and compact assignment explicitly. Inspect
and steer them with `list_agents`, `send_message`, `followup_task`, `wait_agent`
and `interrupt_agent`. This is separate from local-client custom-agent discovery.

Official sources: [subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents),
[models](https://learn.chatgpt.com/docs/models),
[configuration schema](https://learn.chatgpt.com/docs/config-schema.json).
Check installed version/schema before future configuration changes; do not infer
account access from a model name or install/upgrade a client implicitly.

## Assignment and ownership

Use this compact assignment, without forwarding the whole project history:

```text
Role / goal / ready when:
Relevant AGENTS, contract sections, entry branch/HEAD and dirty-tree facts:
Allowed files (exclusive owner) / prohibited areas:
Dependencies and agreed input/output interfaces:
Checks and owned app/project/cache/process resources:
Return: paths, behavior/findings, commands/results, risks and unverified gates.
```

Before parallel edits, the main agent records a small ownership/resource table in
the selected plan or active task. Shared interfaces are agreed first. One file has
one editor, including fixtures, configuration and documents. Ownership transfers
only after the old owner stops editing and the parent names the new owner. Inspect
the resulting diff at transfer. At most two subagents edit code simultaneously.

Qt runs, test directories, project files, GPU/COLMAP jobs and shared caches also
need exclusive ownership or deliberately independent resources. Schedule conflicting
checks serially. A reviewer may read a frozen diff while the main works elsewhere.
The main does useful independent work instead of repeating delegated investigations.

No nested team without the main agent's specific decision and resource budget.
The two-editor limit and no-nesting policy are coordinator rules, not extra invented
TOML options. Keep routine sequential work local. Do not default to Max/Ultra.
After interruption, account for active agents and owned processes before resuming.

Use the current checkout for shared dirty work when ownership suffices. A new
worktree does not copy uncommitted changes: use one only with a correct common
base and an explicit integration route. Never manufacture a commit/stash to create
that base. Preserve user work; this setup authorizes no Git publication or cleanup.

## Integration and evidence

Verification authorization applies to the main agent, every subagent and future
sessions: full pytest/full verify, broad long-running suites and heavy benchmarks
require a separate direct user request. "Continue", "check" and "implement the next
stage" are not that request. Ordinary work uses short targeted tests and relevant
lint/QML/docs checks; select nodes in known slow files and diagnose/stop a run that
unexpectedly drags. Never simulate a full run by many batches, delegation or background
execution. Prepare an exact command and purpose for any needed long check without
starting it. Explicitly report full verification as unrun; this alone does not block
authorized next development. Include this restriction in every agent assignment.

After meaningful code changes, give a fresh reviewer who did not implement them
the requirements, scope and actual final diff, including new files and task-only
changes relative to the entry tree. With an already dirty tree, a HEAD diff alone
mixes old and new work. Preserve an entry snapshot/hash manifest outside Git as
needed. Do not substitute the implementer's report for inspection.

Findings contain location, trigger and consequence. The main confirms each one,
fixes confirmed defects, freezes the combined tree, and performs the applicable
short affected checks after fixes. Recheck only invalidated evidence; reuse existing
results when their tree/environment still applies. Longer runs require the direct
request above. Separate new
failures, reproduced baseline failures, skips and environment limitations.

For GUI changes, check real scenarios and application screenshots against UX/GUI
owners, including transitions, empty/loading/error states, sizes, focus and actions.
Without running GUI access, leave visual acceptance incomplete. Reference images,
QML reading and agent screenshots do not constitute user acceptance. Tester checks
requirements instead of encoding erroneous implementation behavior.

Record separately: implemented in code; checked automatically; checked with real
data (identify generated fixtures); visually reviewed by an agent; accepted by the
user; unconfirmed. Passing unit tests proves none of the remaining categories.
Update the authoritative owner for changed facts, refresh the compact state after
each completed slice, and select a next milestone only on an authorized task.

## Validation and model claims

TOML parsing checks syntax; schema checks supported fields; local client discovery
checks loading. An actual subagent run is separate evidence. A requested model in
a file or spawn argument is not proof of the model used. Report the exact runtime
metadata if exposed; otherwise say the actual model/effort is unconfirmed. Do not
silently substitute a model or simulate switching when overrides are unsupported.

Report available elapsed times, commands, results and agent counts. Do not invent
task credit/token totals. Account-wide usage limits, when available, are not task
cost measurements. No separate API orchestrator is required.
