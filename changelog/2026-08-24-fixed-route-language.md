# Fixed-language route resolution

**Date:** 2026-08-24 CT
**Scope:** Runtime Read contract and local verification only; no deployment or publication was performed.

## Change

- Added the optional public `routes[].language` projection.
- Made exact published site-config routes win before older metadata and parameterized route matches.
- Made a validated fixed route language authoritative for localized payload and Content Hub index selection, while preserving request/default precedence for language-free routes.
- Added fail-closed validation for malformed, noncanonical, unsupported, and duplicate `(pageId, language)` route entries in both stored metadata and published site config.
- Required every language-bound route to carry a nonempty, trim-stable string `pageId`, matching the Config Authoring write contract.
- Kept older metadata compatible by resolving its missing route language from the exact published site-config route.
- Recomputed the effective language from a final fixed-language `/404` after unknown, missing-article, or missing-taxonomy resolution and reused request-scoped Content Hub metadata so bounded query limits remain unchanged.
- Preserved historical language-free default-locale filename behavior, including lowercase regional and underscore forms; canonical normalization remains scoped to explicit route languages.
- Applied the same fail-closed validation before maintenance and suspension fallback responses. The fallback bundle remains English-only and strips fixed-language bindings after validation.
- Bound all package-derived registry metadata (`defaultPageId`, `routes`, and `contentHubs`) to the active immutable published snapshot. A newer registry draft may change those fields before its publication pointer moves; draft-ahead defaults, routes, and hubs no longer affect, resolve from, or appear in the currently published bundle.

## Verification

- Added focused unit coverage for English/Chinese sibling routes with conflicting request languages, public projection agreement, exact-route precedence, metadata backfill, legacy regional/underscore default behavior, final fixed-language 404s, malformed route page IDs, inactive lifecycle validation, bounded Content Hub reads, draft-ahead route/default/hub isolation, and generic public failures before localized reads.
- Reran the complete local unit suite and artifact verification described in the repository README.
