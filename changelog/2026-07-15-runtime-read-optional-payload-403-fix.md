# Runtime Read Optional Payload 403 Fix — 2026-07-15 CT

Scope: Runtime Read S3 IAM regression identified and corrected locally at 2026-07-15 04:56 CT (UTC-06:00). This entry does not claim an AWS deployment.

## Verified regression

The server-only boundary change removed `s3:ListBucket` while `load_json_from_s3` continued treating only `NoSuchKey`, `404`, and `NotFound` as an optional payload miss. Amazon S3 returns `403 Access Denied` instead of `404 Not Found` when a requested object is absent and the caller lacks `s3:ListBucket`. The unrecognized 403 reached the generic handler error path and produced HTTP 500 responses.

Read-only live checks reproduced the boundary in both test and production: an existing Spanish bundle returned HTTP 200, while a deliberately absent language payload returned the generic HTTP 500 contract. IAM simulation confirmed that public config `GetObject` was allowed, server-only `GetObject` was explicitly denied, and config-bucket `ListBucket` was implicitly denied. Production logs first recorded the S3 access error immediately after the role-policy update on 2026-07-15 CT.

## Local correction

- Restore only `s3:ListBucket` on the configured payload bucket so absent optional keys return the 404 contract the loader already handles.
- Preserve the explicit `s3:GetObject` deny for canonical `*/server/*` objects.
- Preserve the case-insensitive application key guard and generic public error response.
- Keep object-content access unchanged; `s3:ListBucket` grants bucket metadata enumeration, not `GetObject` access.

The change must still pass repository validation and the protected feature -> `dev` -> `test` -> `main` promotion flow before it is considered deployed.
