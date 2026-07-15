# Zoolanding Config Runtime Read Agent Guide

<!-- zoolanding-hub-routing:start -->
## Zoolanding Knowledge Router

Read only the row needed for the current task, then inspect the local executable configuration or workflow that owns the behavior.

| Task | Read |
| --- | --- |
| Draft lifecycle and runtime publication | [docs/11-draft-lifecycle.md](https://github.com/LynxPardelle/zoolandingpage/blob/main/docs/11-draft-lifecycle.md) |
| Runtime data-source contract | [docs/api-driven-config/15-runtime-api-proxy-data-sources.md](https://github.com/LynxPardelle/zoolandingpage/blob/main/docs/api-driven-config/15-runtime-api-proxy-data-sources.md) |
| Domain and alias behavior | [docs/13-managed-alias-front-door.md](https://github.com/LynxPardelle/zoolandingpage/blob/main/docs/13-managed-alias-front-door.md) |
| Fleet ownership | [docs/repository-map.md](https://github.com/LynxPardelle/zoolandingpage/blob/main/docs/repository-map.md) |

Critical repository-specific safety, deployment, and rollback rules remain local.
<!-- zoolanding-hub-routing:end -->

Use this file as the repository entrypoint. `Codex.md` is only a compatibility pointer.

## Task Router

- Runtime request, response, route, alias, merge, or fallback work: read [README.md](README.md), then [lambda_function.py](lambda_function.py).
- IAM, parameters, environments, or release work: read [template.yaml](template.yaml), [samconfig.toml](samconfig.toml), and the relevant [.github/workflows](.github/workflows/).
- Historical implementation, deploy, QA, or incident evidence: read [changelog/README.md](changelog/README.md). History is not the current contract.
- Cross-repository ownership: use the [hub documentation index](https://github.com/LynxPardelle/zoolandingpage/blob/main/docs/README.md) and [repository map](https://github.com/LynxPardelle/zoolandingpage/blob/main/docs/repository-map.md).

The hub owns shared frontend and authored-payload contracts. This repository owns runtime-read implementation, IAM, deployment, rollback, and locally critical trust boundaries. Relevant shared contracts are [managed aliases](https://github.com/LynxPardelle/zoolandingpage/blob/main/docs/13-managed-alias-front-door.md) and [content-hub article packages](https://github.com/LynxPardelle/zoolandingpage/blob/main/docs/api-driven-config/18-content-hub-article-packages.md).

## Non-Negotiable Boundaries

- Keep application data access read-only: DynamoDB and S3 reads only. Runtime writes or AWS mutations require an explicitly approved contract and rollout.
- Resolve aliases only when registry metadata proves the canonical domain and matching environment alias.
- Keep `dev`, `test`, and production pointers separate; canonical-domain overrides must not let aliases bypass their registered environment.
- Preserve exact routes before parameterized routes, configured 404s for unknown routes, and shared payloads before page overrides.
- Keep public content-hub output allowlisted and context-bound. Never expose tokens, credentials, secret refs, private policy, storage names, signed URLs, or cross-environment bundles.
- Never store or print secrets, signed URLs, private customer data, or PII in code, tests, logs, docs, commits, or PR text.

## Release And Verification

- Promotion is feature branch -> `dev` -> `test` -> `main`. Development stays local and pushes to `dev` run CI only; `dev` does not deploy AWS infrastructure. Only pushes to `test` and `main` trigger their environment-specific deployments. Do not merge, push, or deploy without explicit approval.
- Default closeout: `python -m unittest discover -s tests -p "test_*.py"`.
- For SAM, IAM, parameter, or workflow changes, also run `sam validate` when available and `actionlint`. Report unavailable tools; tests must not call live AWS.

## Documentation Boundaries

- Keep current behavior in README, code, tests, SAM config, and workflows; put chronology in `changelog/`, not `Codex.md`.
- Keep critical service rules local and link shared hub contracts instead of copying them.
- Never commit `.superpowers/`, local scans, credentials, or machine-specific paths.
