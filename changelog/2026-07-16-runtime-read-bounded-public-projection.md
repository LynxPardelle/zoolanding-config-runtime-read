# Runtime Read bounded public projection and reads

Scope: local Runtime Read hardening completed on 2026-07-16 CT. This entry does not claim an AWS deployment.

## Problem

The public bundle copied most of `site-config.json`, Content Hub index hydration could continue through every DynamoDB page, a missing article bundle could trigger a duplicate metadata lookup, and shared S3 JSON loading read unbounded bodies. Validation workflows also built from the same mutable workspace in which repository tests had executed.

## Change

- Project `siteConfig`, route, and lifecycle through explicit public contract keys and recursively remove secret, credential, PII, banking, identity, and server-policy key classes. Preserve legitimate JSON `null` values with a distinct blocked-value sentinel.
- Normalize key boundaries before sensitive-key matching so public contract fields such as CSRF cookie names remain available. Permit `mfaSoftwareTokenEnabled` and `piiPolicy` only inside their explicit `mapper.fields` and `analyticsContext` contract locations, without weakening removal elsewhere of tokens, credentials, fiscal identifiers, or private policy fields.
- Limit Runtime Read to four Content Hubs per request and each Content Hub metadata index to two queries and 400 total items.
- Resolve article bundles only after the handler confirms an article route, reusing the hydrated article identity and requiring a current published/public exact item before using its bundle key or a matching legacy slug pointer instead of querying the article index twice.
- Reject S3 JSON objects larger than 1 MiB using both `ContentLength` and a bounded body read.
- Restore the exact GitHub event SHA in a clean credential-free checkout after tests and before packaging.

## Verification

- Targeted regression tests cover every boundary above.
- The complete local unit suite passed with 71 tests.
- No AWS deployment or live customer-data read was performed as part of this change.
