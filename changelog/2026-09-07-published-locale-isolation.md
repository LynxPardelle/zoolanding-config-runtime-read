# Published locale isolation - 2026-09-07 CT

- Added an optional per-hub `localePolicy: "published-only"` for the locally
  approved The Hair Narrative integration. Existing hubs without the option keep
  the legacy path; no domain-specific branch or global default was introduced.
- Opted-in indexes require a complete published localization for the requested
  language. They do not infer publication or borrow localized fields from another
  language. Static article fallbacks cannot restore missing translations, even
  without a metadata binding. Detail resolution retains exact locale/package
  guards and refuses a stale article that no longer has that translation.
- Added 16 focused regression tests covering ES/EN, malformed records, safe
  projection, mixed hubs, legacy fallback, missing bindings and handler routes.
  All 122 reader tests passed locally, with storage fixtures only.
- No IAM, workflow, environment, published draft, deployment or activation
  changed. This is an uncommitted local candidate, not a release receipt.
