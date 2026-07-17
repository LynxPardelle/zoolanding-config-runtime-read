# Runtime Read bounded public projection and reads

Scope: local Runtime Read hardening completed on 2026-07-16 CT. This entry does not claim an AWS deployment.

## Problem

The public bundle copied most of `site-config.json`, Content Hub index hydration could continue through every DynamoDB page, a missing article bundle could trigger a duplicate metadata lookup, and shared S3 JSON loading read unbounded bodies. Validation workflows also built from the same mutable workspace in which repository tests had executed.

## Change

- Project `siteConfig`, route, and lifecycle through explicit public contract keys and recursively remove secret, credential, PII, banking, identity, and server-policy key classes. Preserve legitimate JSON `null` values with a distinct blocked-value sentinel.
- Limit Runtime Read to four Content Hubs per request and each Content Hub metadata index to two queries and 400 total items.
- Resolve article bundles only after the handler confirms an article route, avoiding both duplicate misses and article scans on ordinary routes.
- Reject S3 JSON objects larger than 1 MiB using both `ContentLength` and a bounded body read.
- Restore the exact GitHub event SHA in a clean credential-free checkout after tests and before packaging.

## Verification

- Targeted regression tests cover every boundary above.
- The complete local unit suite passed with 68 tests.
- No AWS deployment or live customer-data read was performed as part of this change.
