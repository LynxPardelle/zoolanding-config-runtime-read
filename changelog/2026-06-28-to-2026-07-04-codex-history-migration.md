# Codex History Migration — 2026-06-28 through 2026-07-04 CT

This file preserves dated runtime-read decisions that existed only in `Codex.md` at repository commit `dd9437780a253aaa832880ee77461435b7576697`. These records are historical evidence, not current runtime truth. Use [../README.md](../README.md), code, tests, SAM configuration, and workflows for the current contract.

## 2026-06-28 02:56 CT — Published Article Bundle Context

Public content-hub article routes could hydrate published S3 bundle JSON only after matching environment, hub ID, render domain, locale, article ID, and a safe revision key. Environment-specific `CONTENT_HUB_PACKAGES_BUCKET_NAME*` configuration remained required for enriched article bodies.

## 2026-06-28 19:03 CT — SAM Parameter Preservation

Deploy workflows were required to let `sam deploy --config-env {env}` load the full `samconfig.toml` parameter set. Appending a narrow `--parameter-overrides "EnvironmentName=..."` could drop content-hub table and package-bucket parameters.

## 2026-06-28 20:23 CT — Effective Runtime Language

Requests without an explicit `lang` resolved the effective language from `site.i18n.defaultLanguage` before content-hub index enrichment or article-bundle lookup. Explicit `lang` values remained authoritative.

## 2026-06-29 13:24 CT — Public Article Membership

Published content-hub article membership resolved public article routes even when a published bundle was absent or invalid. Missing `visibility` remained backward-compatible as public. Explicit non-public visibility, unpublished status, locale mismatch, or absent article metadata rendered the configured 404. Invalid or cross-context bundle keys were ignored.

## 2026-06-29 15:14 CT — Metadata Pagination

Public content-hub metadata reads were required to paginate DynamoDB queries through `LastEvaluatedKey`. Runtime bundles and public article, taxonomy, sitemap, feed, search, and SEO helpers could not assume the first 200 items covered a hub.

## 2026-07-03 05:22 CT — Unknown Taxonomy Slugs

Runtime-read returned the configured 404 for public content-hub category and tag routes when a requested slug was not visible in `publicTaxonomy` and was not inferable from published public articles. Stale or mistyped slugs did not render generic listing pages.

## 2026-07-03 11:09 CT — Localized Article Metadata

Locale-specific dynamic content-hub metadata was preferred when `localizations.{lang}` existed, including optional `articleContent`. UTF-8 source data remained canonical; mojibake repair was a compatibility step for legacy published site-config metadata.

## 2026-07-04 CT — Safe Static Cover Fallback

Dynamic article metadata remained authoritative for status, title, summary, path, taxonomy, and publication state. Runtime-read could supplement missing public cover fields from the same article ID in `runtime.contentHubs.publicArticles`. Exposed `imageSrc` values were limited to same-origin paths or HTTPS URLs without userinfo, signed-URL markers, whitespace, control characters, or backslashes. Private URL aliases were not exposed.
