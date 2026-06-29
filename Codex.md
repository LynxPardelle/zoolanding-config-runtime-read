# Zoolanding Config Runtime Read Notes

Durable decisions:

- 2026-06-28 02:56 CT: Public content-hub article routes may hydrate published S3 bundle JSON into the runtime response only after matching environment, hubId, render domain, locale, articleId, and safe revision key. `CONTENT_HUB_PACKAGES_BUCKET_NAME*` must be configured per environment; missing or mismatched bundles render the configured 404 instead of an empty article shell.
- 2026-06-28 19:03 CT: Deploy workflows must let `sam deploy --config-env {env}` load the full `samconfig.toml` parameter set. Do not append a narrow `--parameter-overrides "EnvironmentName=..."` because it can drop content-hub table and package bucket parameters during deployment.
- 2026-06-28 20:23 CT: Runtime requests without an explicit `lang` must resolve the effective language from `site.i18n.defaultLanguage` before content-hub index enrichment or article bundle lookup. Explicit `lang` query values stay authoritative for multi-language drafts.
