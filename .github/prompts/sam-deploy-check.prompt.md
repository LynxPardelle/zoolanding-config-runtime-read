---
name: "SAM Deploy Check"
description: "Review this runtime-bundle Lambda for AWS SAM deploy readiness. Use when preparing to deploy changes that may affect GET /runtime-bundle, alias lookup, route resolution, payload merge order, lifecycle fallbacks, env vars, IAM, or documentation in zoolanding-config-runtime-read."
argument-hint: "Changed files, diff, or deploy concern"
agent: "agent"
---

Review this repository for deploy readiness after the current change.

Follow [Zoolanding Lambda Workflow](../skills/zoolanding-lambda-workflow/SKILL.md) and inspect the repo contract files:

- [README](../../README.md)
- [Lambda Handler](../../lambda_function.py)
- [SAM Template](../../template.yaml)
- [SAM Config](../../samconfig.toml)

Use the user's arguments plus the current diff or changed files.

Check specifically for:

- handler and template wiring for `GET /runtime-bundle`
- alias-domain lookup and canonical host resolution behavior
- route, path, and language resolution behavior
- shared-first then page-level payload merge order
- lifecycle fallback behavior for maintenance or suspended states
- env var, IAM, or parameter-override mismatches
- docs drift between code, README, and SAM template

Return:

1. findings first, ordered by severity
2. the deploy command to use, or a note that plain `sam deploy` is sufficient
3. the smallest post-deploy smoke test
4. doc or rollout notes still required