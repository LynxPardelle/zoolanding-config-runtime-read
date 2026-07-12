# Zoolanding Config Runtime Read

<!-- zoolanding-hub-routing:start -->
## Zoolanding Knowledge Router

Shared procedures are routed through the Zoolandingpage hub. Start with [AGENTS.md](AGENTS.md) and open only the document needed for the current task.

| Task | Read |
| --- | --- |
| Draft lifecycle and runtime publication | [docs/11-draft-lifecycle.md](https://github.com/LynxPardelle/zoolandingpage/blob/main/docs/11-draft-lifecycle.md) |
| Runtime data-source contract | [docs/api-driven-config/15-runtime-api-proxy-data-sources.md](https://github.com/LynxPardelle/zoolandingpage/blob/main/docs/api-driven-config/15-runtime-api-proxy-data-sources.md) |
| Domain and alias behavior | [docs/13-managed-alias-front-door.md](https://github.com/LynxPardelle/zoolandingpage/blob/main/docs/13-managed-alias-front-door.md) |
| Fleet ownership | [docs/repository-map.md](https://github.com/LynxPardelle/zoolandingpage/blob/main/docs/repository-map.md) |

Critical repository-specific safety, deployment, and rollback rules remain local.
<!-- zoolanding-hub-routing:end -->

This Lambda resolves the active site by domain and route, checks lifecycle status, and returns one effective `TRuntimeBundlePayload` for the Angular app.

## Repository Guide

- Start agent work at [AGENTS.md](AGENTS.md); implementation is in [lambda_function.py](lambda_function.py).
- IAM and environments are owned by [template.yaml](template.yaml), [samconfig.toml](samconfig.toml), and [.github/workflows](.github/workflows/).
- Dated evidence belongs in [changelog/](changelog/README.md).
- Shared ownership and contracts live in the hub [documentation index](https://github.com/LynxPardelle/zoolandingpage/blob/main/docs/README.md), [repository map](https://github.com/LynxPardelle/zoolandingpage/blob/main/docs/repository-map.md), [managed-alias guide](https://github.com/LynxPardelle/zoolandingpage/blob/main/docs/13-managed-alias-front-door.md), and [content-hub package contract](https://github.com/LynxPardelle/zoolandingpage/blob/main/docs/api-driven-config/18-content-hub-article-packages.md).

## Responsibilities

- Read site metadata from DynamoDB.
- Resolve alias domains back to the canonical site and environment when `site-config.json.aliases` or `site-config.json.environments.*.aliases` declares alternate hosts.
- Resolve the current page by host and route.
- Resolve exact routes before parameterized route patterns such as `/blog/:categorySlug`.
- Load the published payload set from S3.
- Merge shared and page components.
- Merge shared and page variables, angora combos, and i18n dictionaries.
- Return a professional fallback bundle when the site is in `maintenance` or `suspended` state.
- Return safe public content hub metadata for blog/article-style features.

## AWS dependencies

- DynamoDB table: `zoolanding-config-registry`
- S3 bucket: `zoolanding-config-payloads`
- API Gateway: `GET /runtime-bundle`
- CloudWatch Logs
- Lambda reserved concurrency: `100`

## Environment variables

- `CONFIG_TABLE_NAME`
- `CONFIG_PAYLOADS_BUCKET_NAME`
- `ENVIRONMENT_NAME`
- `LOG_LEVEL`

## Local verification

```powershell
python -m unittest discover -s tests -p "test_*.py"
```

For SAM, IAM, parameter, or workflow changes, also run `sam validate` when SAM is available and `actionlint` for workflows. Unit tests must not call live AWS services.

## Deploy

Pushes to `dev`, `test`, and `main` trigger AWS deployment workflows. Use the workflow-guarded promotion path feature branch -> `dev` -> `test` -> `main`, and do not merge or deploy without explicit approval for the target environment. Plain `sam deploy` uses the default production-oriented profile; do not use it for exploratory validation.

The checked-in `samconfig.toml` includes `dev`, `test`, and `prod` deployment profiles in `us-east-1`.

- `dev` uses `zoolanding-config-registry-dev` and `zoolanding-config-payloads-dev`.
- `test` uses `zoolanding-config-registry-test` and `zoolanding-config-payloads-test`.
- `prod` uses the existing production table and bucket names.

The SAM template owns the runtime-read reserved concurrency guard. Keep `ReservedConcurrentExecutions` at `100` unless a new load test and cost review justify changing it. Use the hub repo script `tools/ops/configure-runtime-observability.mjs` to manage the matching CloudWatch alarms, SNS alert topic, tags, and notification-only budget.

The first non-interactive deployment command used was:

```bash
sam deploy --stack-name zoolanding-config-runtime-read --region us-east-1 --capabilities CAPABILITY_IAM --resolve-s3 --no-confirm-changeset --no-fail-on-empty-changeset --parameter-overrides ConfigTableName=zoolanding-config-registry ConfigPayloadsBucketName=zoolanding-config-payloads LogLevel=INFO
```

Use the output `ApiUrl` value as the runtime base for `configApiUrl` in the Angular app.

Current deployed endpoint:

```text
https://y84vk0v44l.execute-api.us-east-1.amazonaws.com/Prod/runtime-bundle
```

## Manual smoke test

```bash
curl "https://your-api-id.execute-api.us-east-1.amazonaws.com/Prod/runtime-bundle?domain=test.zoolandingpage.com.mx&path=/&lang=es"
```

The request also works without the `domain` query string when the API receives a `Host` or `X-Forwarded-Host` header that matches a configured site or an authored alias.

Runtime requests can use `environment=dev` or `environment=test` on canonical-domain reads when the frontend/API proxy is configured to request non-production bundles.

## Content hub runtime metadata

When `site-config.json` includes `contentHubs`, the runtime bundle includes a safe projection under `metadata.contentHubs`. The projection is allowlisted to `hubId`, `name`, `defaultLanguage`, `canonicalDraftDomain`, `allowedDraftDomains`, and `articleIds`; arbitrary nested authoring fields are not exposed.

## Required data shape

The DynamoDB item for each site should look like this:

```json
{
  "pk": "SITE#zoolandingpage.com.mx",
  "sk": "METADATA",
  "type": "site-metadata",
  "version": 1,
  "domain": "zoolandingpage.com.mx",
  "aliases": ["zoolandingpage.com.mx"],
  "environmentAliases": {
    "test": ["test.zoolandingpage.com.mx"]
  },
  "defaultPageId": "default",
  "routes": [{ "path": "/", "pageId": "default" }],
  "lifecycle": {
    "status": "active",
    "fallbackMode": "system",
    "updatedAt": "2026-03-31T00:00:00Z",
    "updatedBy": "system"
  },
  "published": {
    "versionId": "20260331T000000Z-localabcd1234",
    "prefix": "sites/zoolandingpage.com.mx/versions/20260331T000000Z-localabcd1234",
    "updatedAt": "2026-03-31T00:00:00Z",
    "updatedBy": "system"
  },
  "publishedEnvironments": {
    "production": {
      "versionId": "20260331T000000Z-localabcd1234",
      "prefix": "sites/zoolandingpage.com.mx/versions/20260331T000000Z-localabcd1234"
    },
    "test": {
      "versionId": "20260331T010000Z-testabcd1234",
      "prefix": "sites/zoolandingpage.com.mx/versions/20260331T010000Z-testabcd1234"
    }
  }
}
```

Each alias also gets a lightweight lookup item:

```json
{
  "pk": "ALIAS#test.zoolandingpage.com.mx",
  "sk": "SITE",
  "type": "site-alias",
  "alias": "test.zoolandingpage.com.mx",
  "domain": "zoolandingpage.com.mx",
  "environment": "test"
}
```

If `environment` is missing on an alias item, runtime-read treats it as `production` for backward compatibility. Production uses the legacy `published` pointer first and falls back to `publishedEnvironments.production`. Test aliases require `publishedEnvironments.test`.

The S3 payload prefix must contain:

```text
sites/{domain}/versions/{versionId}/
  {domain}/site-config.json
  {domain}/components.json
  {domain}/variables.json
  {domain}/angora-combos.json
  {domain}/i18n/{lang}.json
  {domain}/{pageId}/page-config.json
  {domain}/{pageId}/components.json
  {domain}/{pageId}/variables.json
  {domain}/{pageId}/angora-combos.json
  {domain}/{pageId}/i18n/{lang}.json
```

Shared domain-level files are optional. When they exist, the Lambda merges them first and then applies page-level overrides.
