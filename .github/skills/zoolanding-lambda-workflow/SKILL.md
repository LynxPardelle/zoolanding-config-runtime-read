---
name: zoolanding-lambda-workflow
description: 'Zoolanding Lambda workflow for runtime bundle resolution. Use when changing alias lookup, route resolution, lifecycle fallback behavior, payload merging, or SAM deployment for zoolanding-config-runtime-read.'
user-invocable: true
---

# Zoolanding Lambda Workflow

Use this skill for work in the runtime-read Lambda.

## Repo Focus

- Resolve host and route to one effective `TRuntimeBundlePayload`.
- Preserve alias-domain lookup behavior.
- Keep lifecycle fallback behavior professional and predictable.
- Merge shared and page payload files in a stable order.

## Workflow

1. Read the runtime contract.
   - Start with `README.md`, then inspect `lambda_function.py`, `template.yaml`, and shared helpers.

2. Protect resolution order.
   - Host or alias lookup, route selection, lifecycle status, and payload merge order are all contract-sensitive.
   - Avoid changing fallback behavior casually because it affects live site rendering.

3. Keep merge logic boring.
   - Prefer deterministic merge rules over clever abstractions.
   - Preserve the rule that shared files apply first and page-level files override them.

4. Verify with focused runtime scenarios.
   - Check canonical domain and alias requests.
   - Check route resolution for path and language inputs.
   - Check maintenance or suspended lifecycle fallbacks when touched.

5. Update docs with the code.
   - If bundle shape, alias behavior, or request shape changes, update `README.md` immediately.

## Recommended Repo-Local Skills

- Pair this workflow with the repo-local `karpathy-guidelines` skill for scoped implementation, `systematic-debugging` for root-cause analysis, `risk-review` for review-only asks, and `test-driven-development` for behavior-changing code.
- Use the repo-local `zoolanding-pr-followup` skill for CI, reviewer, and merge-readiness work.
- Use the repo-local `sam-deploy-check` prompt before shipping contract or SAM changes.

## Resources

- [Validation Checklist](./references/validation-checklist.md)