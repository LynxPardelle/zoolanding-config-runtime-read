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
- Honor an optional canonical `routes[].language` before request/default language selection, while leaving language-free routes on their legacy precedence.
- Load the published payload set from S3, rejecting individual JSON objects larger than 1 MiB before parsing.
- Merge shared and page components.
- Merge shared and page variables, angora combos, and i18n dictionaries.
- Return a professional fallback bundle when the site is in `maintenance` or `suspended` state.
- Return safe public content hub metadata for blog/article-style features.

## AWS dependencies

- DynamoDB table: `zoolanding-config-registry`
- S3 bucket: `zoolanding-config-payloads`
- API Gateway: `GET /runtime-bundle`, limited at the stage method to 25 requests/second with a burst of 50
- CloudWatch Logs
- Lambda reserved concurrency: `100`

The API Gateway throttle targets only `GET /runtime-bundle`; CORS `OPTIONS` remains available and is not assigned this method setting. API Gateway throttling is best-effort protection against anonymous amplification, not a guaranteed request ceiling or a replacement for a separately approved WAF policy.

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

Pushes to `dev` run CI only and do not deploy AWS infrastructure. Pushes to `test` and `main` trigger their environment-specific AWS deployment workflows. Use the workflow-guarded promotion path feature branch -> `dev` -> `test` -> `main`, and do not merge or deploy without explicit approval for the target environment. Plain `sam deploy` uses the default production-oriented profile; do not use it for exploratory validation.

Test and production deployment workflows serialize the entire run by environment and Git ref. They do not cancel an in-progress run, because cancellation could interrupt a CloudFormation operation after it has started mutating infrastructure. A validation job without OIDC runs tests, restores a clean checkout of the exact `${{ github.sha }}` with persisted Git credentials disabled, stages `.build/runtime-read` with only `lambda_function.py` and `zoolanding_lambda_common.py`, validates and builds with SAM CLI `1.163.0`, hashes the exact build, and uploads only the built template, those two public runtime files, and their SHA-256 manifest for one day. The privileged job downloads that artifact by the ID emitted by the validation job in the same workflow run, verifies the manifest digest, every file hash, and the exact file set, and does not check out or execute repository code. Immediately before AWS credentials are obtained, an inline pinned-action verifier repeats the full same-repository merged-PR check, including source/base branches and SHAs, parent order, event predecessor, and a final target-tip read. Deployment then uses the verified built template with explicit parameters that match `samconfig.toml` for the target environment.

This runtime repository cannot expand IAM permissions. The Zoolanding infrastructure repository owns the retained permissions boundary and CloudFormation execution role; deployment requires both environment-specific ARNs, and the SAM function must attach the supplied boundary. Each workflow compares its configured, non-secret CloudFormation role ARN with the exact ARN for that environment and will fail closed before requesting AWS credentials if it is absent or different.

CloudFormation stores `--role-arn` on the stack and uses that associated role for future operations. Omitting `--role-arn` from a later deploy does not detach or roll back that association; the workflows still pass it explicitly so configuration drift is visible. Changing only `AWS_ROLE_ARN`, the GitHub OIDC caller, does not change the stack's retained CloudFormation role. This persistence matches the AWS [`UpdateStack --role-arn` contract](https://docs.aws.amazon.com/cli/latest/reference/cloudformation/update-stack.html).

The migration sequence uses the legacy GitHub OIDC caller only for temporary bootstrap and caller rollback: first pass the new retained role to CloudFormation, verify the completed update and runtime smoke tests, and only then switch `AWS_ROLE_ARN` to the scoped caller. Restoring the legacy caller after a failed caller cutover changes only who invokes CloudFormation; it does not remove the retained role or the function permissions boundary. Before any future IAM permission change, role replacement, or deletion, create or update the replacement in `zoolandingpage-aws-infra` first, point `AWS_CLOUDFORMATION_ROLE_ARN` to it, deploy with the new explicit `--role-arn`, verify the stack's `RoleARN` and function boundary, and only then retire the old role.

The checked-in `samconfig.toml` has no `dev` deployment profile. Its named deployment profiles are `test` and `prod` in `us-east-1`.

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

The currently verified test pilot is the authored alias `test.zoositioweb.com.mx`. Keep the response body in memory and print only the contract fields:

```powershell
$publicResponse = Invoke-WebRequest "https://your-api-id.execute-api.us-east-1.amazonaws.com/Prod/runtime-bundle?domain=test.zoositioweb.com.mx&path=/&lang=es"
$publicPayload = $publicResponse.Content | ConvertFrom-Json
[pscustomobject]@{
  httpStatus = [int]$publicResponse.StatusCode
  metadataStatus = $publicPayload.metadata.statusCode
  notFound = $publicPayload.metadata.notFound
  hasSiteConfig = $null -ne $publicPayload.siteConfig
  hasPageConfig = $null -ne $publicPayload.pageConfig
}
```

The public home smoke must return HTTP `200`, `metadata.statusCode` `200`, `metadata.notFound` `false`, and both config flags `true`.

`/server/*` is not a backend descriptor route. For the verified pilot, a request such as `path=%2Fserver%2Fintegrations.json` returns an HTTP `200` public not-found bundle whose `metadata.statusCode` is `404`, whose `metadata.notFound` is `true`, and whose route is `/404`; it does not expose a server descriptor. Inspect only those fields and never print or persist the full response during an operational smoke.

The request also works without the `domain` query string when the API receives a `Host` or `X-Forwarded-Host` header that matches a configured site or an authored alias.

Runtime requests can use `environment=dev` or `environment=test` on canonical-domain reads when the frontend/API proxy is configured to request non-production bundles.

## Fixed-language routes

A route may opt into one supported language:

```json
{
  "routes": [
    { "path": "/campaign/eng", "pageId": "campaign", "language": "en" },
    { "path": "/campaign/zh", "pageId": "campaign", "language": "zh" }
  ],
  "site": {
    "i18n": {
      "defaultLanguage": "es",
      "supportedLanguages": ["es", "en", "zh"]
    }
  }
}
```

Runtime Read resolves an exact site-config route before older metadata and before parameterized matches. A route-bound language is authoritative even when the request supplies a conflicting `lang`; the returned top-level `lang`, matched `route.language`, projected `siteConfig.routes`, and loaded i18n path therefore stay aligned. This also applies when an unknown, missing-article, or missing-taxonomy path ultimately selects an exact fixed-language `/404` route. Older metadata that omits `language` remains compatible because the exact published site-config route supplies it.

The active immutable published pointer and its package are the runtime source of truth. Config Authoring updates the registry's package-derived `defaultPageId`, `routes`, and `contentHubs` fields for a newer draft before that draft is published. When the registry draft pointer does not identify the active published version, Runtime Read removes all three fields from its published-metadata view and relies on the immutable published `site-config.json` plus legacy `default` fallback. Draft-ahead defaults, routes, and hubs are therefore not resolved, validated, or projected until publication moves the environment pointer. Metadata without a draft pointer and metadata whose draft pointer matches the published version retain their compatibility behavior; metadata routes remain limited to paths present in the published site config.

Routes without `language` continue using request `lang`, then the site default, then `en`, including the historical lowercase safe-ID treatment for configured defaults and their payload filenames. Strict canonical normalization is applied only to present `routes[].language` values; it does not rewrite ordinary-route locale behavior.

Every present route language must already be canonical, must appear in `site.i18n.supportedLanguages` (string or `{ "code": "..." }` form), and must have a nonempty, trim-stable string `pageId`. Each `(pageId, language)` must be unique within its route source. Runtime Read validates the published site config and any in-snapshot metadata fallback before loading localized payloads and before returning maintenance or suspension fallbacks. Invalid, unsupported, noncanonical, malformed-page, or duplicate published values fail closed through the generic public `500` response without returning route content or private diagnostics.

## Public draft font faces

Runtime Read preserves an optional `site.fonts` collection from the immutable published site config, following the hub's [draft font-face contract at the validated TEST release](https://github.com/LynxPardelle/zoolandingpage/blob/01b6e9f8dbdbb52532502b78d89b170a96e6000c/docs/api-driven-config/23-draft-font-faces.md). It returns only valid `family`, `src`, optional `weight`, and optional `style` descriptors; it never fetches font files or injects descriptor defaults.

The projection accepts at most eight faces with bounded ASCII family names, root-relative or HTTPS WOFF2 sources, and valid, nonoverlapping weight ranges for each case-insensitive family and style. Source URLs cannot contain credentials, ports, queries, fragments, traversal, or encoded syntax. The existing recursive sensitive-value filter still applies. An invalid or sensitive descriptor causes the entire optional collection to be omitted, not truncated or partially published. An absent field remains absent, and an explicitly empty array remains empty. All other public-field, environment, and server-only boundaries are unchanged.

## Content hub runtime metadata

When `site-config.json` includes `contentHubs`, the runtime bundle includes a safe projection under `metadata.contentHubs`. The legacy projection is allowlisted to `hubId`, `name`, `defaultLanguage`, and `canonicalDraftDomain`; arbitrary nested authoring fields are not exposed. The returned `siteConfig` independently allowlists the fixed object fields in the public `TDraftSiteConfigPayload`, `TDraftSiteRuntimeConfig`, route, lifecycle, auth, data-source, API-action, and `TContentHubRuntimeConfig` contracts. Deliberately dynamic public maps such as `defaults` and data-source input values remain customizable, but sensitive key and value classes are removed recursively. JSON `null` remains a valid public value and is not confused with a blocked value.

Dynamic Content Hub index hydration accepts at most four hubs per request and performs at most two DynamoDB queries of 200 items each for each article or taxonomy index. The worst case is therefore eight indexes, 16 DynamoDB queries, and 400 records per individual index. Article-package resolution reuses the hydrated public article identity, verifies its current published/public metadata with one exact item read, and consults the exact slug pointer only as a legacy bundle-key fallback; it does not query the article index again. Ordinary non-article routes do not attempt an article-package lookup. Hubs that outgrow this bounded compatibility path require a separately designed precomputed paginated index; Runtime Read does not perform unbounded table reads.

When a missing Content Hub path changes from the requested locale to a fixed-language `/404`, Runtime Read reuses the request-scoped bounded metadata reads while rebuilding only the locale-specific public projection. The query limits above therefore do not double during final-route language resolution.

## Server-only package boundary

A published draft package may contain backend policy under `server/` for services such as Auth Admin, API Proxy, Data Spaces, Commerce, Integrations, and Notifications. Runtime Read must never request or return those descriptors. The current descriptor contract is documented in the hub [server-only integration foundation](https://github.com/LynxPardelle/zoolandingpage/blob/main/docs/api-driven-config/22-server-only-integration-microservices.md).

Every config-bucket object key is checked before the S3 request. Validation repeatedly decodes percent-encoded input and rejects dot segments, backslashes, query or fragment delimiters, control characters, encoded residue, and any case-insensitive path segment named `server`. This directory-level deny remains effective when new descriptor filenames are added.

Every JSON object loaded from the config or Content Hub package bucket is limited to 1 MiB. Runtime Read checks S3 `ContentLength` when present and still performs a bounded body read so missing or incorrect metadata cannot bypass the limit. Oversized objects fail closed through the generic runtime error contract.

The Lambda role has an explicit `s3:GetObject` deny for canonical lowercase `*/server/*` objects before its bucket-wide read allow. It also retains `s3:ListBucket` on the config bucket so missing optional payload keys preserve the loader contract: [Amazon S3 returns `403 Access Denied` for a missing `GetObject` key when the caller lacks that permission, and `404 Not Found` when the caller has it](https://docs.aws.amazon.com/AmazonS3/latest/API/API_GetObject.html). Runtime Read does not enumerate the bucket; it uses the 404 result to treat optional shared and language payloads as absent. `s3:ListBucket` does not grant object content access, and the server-only `GetObject` deny remains in force. S3 object keys and IAM resource matching are case-sensitive, so that IAM deny is defense in depth for canonical authoring output; the case-insensitive application guard remains responsible for alternate casing and encoded variants before S3. A future split into separate public and server-only prefixes or buckets could narrow the allow itself, but requires coordinated authoring and migration work and is not part of this change.

Rejected or unexpected runtime reads return the generic `500` error contract. Error logs retain the Lambda request ID and exception type, but omit raw domain, path, exception message, descriptor content, credentials, and customer data.

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
