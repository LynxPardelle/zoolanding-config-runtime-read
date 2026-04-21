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
- For shared workspace customization audits or consolidated cross-repo summaries, use the community prompts [Workspace AI Customization Audit](../../../../zoolandingpage/.github/prompts/workspace-ai-customization-audit.prompt.md) and [Workspace Change Summary](../../../../zoolandingpage/.github/prompts/workspace-change-summary.prompt.md).
- Use the repo-local `zoolanding-production-readiness` agent for deploy-gate review and the repo-local `zoolanding-config-platform-audit` agent when a change may require coordinated updates in the frontend or sibling services.
- Use the repo-local `sam-deploy-check` prompt before shipping contract or SAM changes.

## Resources

- [Validation Checklist](./references/validation-checklist.md)