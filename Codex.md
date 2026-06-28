# Zoolanding Config Runtime Read Notes

Durable decisions:

- 2026-06-28 02:56 CT: Public content-hub article routes may hydrate published S3 bundle JSON into the runtime response only after matching environment, hubId, render domain, locale, articleId, and safe revision key. `CONTENT_HUB_PACKAGES_BUCKET_NAME*` must be configured per environment; missing or mismatched bundles render the configured 404 instead of an empty article shell.
