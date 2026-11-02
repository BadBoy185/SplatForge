# Ignatius Caspar GPU 30k and review collection

Status: active, 2026-10-26. User authorized the proposed Caspar downstream run
and a clean external collection of all completed variants for visual inspection.

## Scope

Reuse exact published Caspar mapping `31c43b0d-1274-4130-aef5-0d14d4dbe4b6`
and PASS M9 `475565ce-dabf-49be-8e3e-11e44e4770ca`. Manually select its sole
263-view component, prepare M10 with the original undistorter runtime/settings,
audit camera/image/pose/XYZ/RGB and original-name split membership. Train exactly
one fresh gsplat.default run, 30,000 steps, seed 42, factor 2, SH3, same explicit
230/33 membership and all settings from the original 30k reference.

No M7/M8 rerun, model/toolchain install, default change or parameter sweep.
Compare same original eval names; report differences in M10 pixels/intrinsics and
dimensions instead of claiming identical target pixels across different mappers.

## Evidence and verification

Use existing CLI/services and external pilot helpers; preserve commands, wall times,
cache/reuse semantics, identities, split, checkpoints, PLY and six-view comparisons.
Require stock PLY validation, independent loading/raw-score agreement and direct
visual review. Retain failures, with no silent fallback or unrequested second fit.
Follow [verification workflow](../../DEVELOPMENT.md#verification-workflow) via the
repo-local verify-change skill. Product-code changes, if needed, require relevant
regressions/full default pytest/Ruff; documentation-only changes need docs/diff checks.

## Review collection

External `C:\SplatForgeData\benchmarks\ReadyToReview\Ignatius`: one named folder
per completed variant, containing only `scene.ply`, `comparison.png` (six source/
render pairs) and `README.md` (recipe, metrics, limitations, provenance). One index
README at the collection root. Copy PLY bytes and verify SHA-256; no writable
hardlinks, artifact mutations, logs, checkpoints or temporary files in the collection.
Build owned staging under external evidence and publish complete directories on the
same volume; refuse nonempty/existing destinations. Preserve originals and user edits.

## Completion

Pending M10, training, validation, six-view inspection and publication of the review
collection. Record the 30k experiment separately from the fixed-7k base matrix.
