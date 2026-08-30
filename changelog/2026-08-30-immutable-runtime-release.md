# Immutable Runtime Read release artifact and live alias

Date: 2026-08-30 CT

## Changed

- Configured the TEST-only derived SAM release template to publish retained immutable Lambda versions behind the stable `live` alias; the shared production template remains unaliased.
- Kept the existing public API URL and base function-name output while allowing SAM to bind the API integration and invocation permission to `live`.
- Added `AWS::LanguageExtensions` before the SAM transform only in that derived TEST template so parameter-only function changes participate in version identity.
- Added a deterministic release packager that produces one exact two-file Lambda ZIP, a derived SAM template, and the base64 SHA-256 digest used by Lambda `CodeSha256`.
- Changed guarded deployment artifacts to transfer that exact ZIP without rebuilding or recompressing it in the OIDC-enabled job.
- Added post-deployment verification that `live` points to a numbered version whose `CodeSha256` matches the validated ZIP.

## Scope

This change does not alter Runtime Read handler behavior, draft content, DNS, frontend delivery, or any production environment. The matching narrowly scoped TEST deployment permissions must be promoted from the infrastructure repository before this release reaches TEST.

## Local verification

- Regression tests first failed while the alias, exact ZIP packager, workflow artifact contract, and release documentation were absent.
- Focused packaging and deployment-workflow tests passed after the implementation.
- The full suite, SAM validation, deterministic ZIP comparison, and TEST deployment evidence are recorded separately when executed.
