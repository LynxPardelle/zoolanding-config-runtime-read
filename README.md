# Zoolanding Config Runtime Read

This Lambda resolves the active site by domain and route, checks lifecycle status, and returns one effective `TRuntimeBundlePayload` for the Angular app.

## Responsibilities

- Read site metadata from DynamoDB.
- Resolve alias domains back to the canonical site when `site-config.json.aliases` declares preview or alternate hosts.
- Resolve the current page by host and route.
- Load the published payload set from S3.
- Merge shared and page components.
- Merge shared and page variables, angora combos, and i18n dictionaries.
- Return a professional fallback bundle when the site is in `maintenance` or `suspended` state.

## AWS dependencies

- DynamoDB table: `zoolanding-config-registry`
- S3 bucket: `zoolanding-config-payloads`
- API Gateway: `GET /runtime-bundle`
- CloudWatch Logs

## Environment variables

- `CONFIG_TABLE_NAME`
- `CONFIG_PAYLOADS_BUCKET_NAME`
- `LOG_LEVEL`

## Deploy

For repeatable deployments from this repository:

```bash
sam deploy
```

The checked-in `samconfig.toml` already targets `us-east-1` with the correct stack name and parameter overrides.

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

## Required data shape

The DynamoDB item for each site should look like this:

```json
{
  "pk": "SITE#zoolandingpage.com.mx",
  "sk": "METADATA",
  "type": "site-metadata",
  "version": 1,
  "domain": "zoolandingpage.com.mx",
  "aliases": ["test.zoolandingpage.com.mx"],
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
  "domain": "zoolandingpage.com.mx"
}
```

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
