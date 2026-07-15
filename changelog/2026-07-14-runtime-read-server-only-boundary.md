# Runtime Read Server-Only Package Boundary — 2026-07-14 CT

Scope: Runtime Read hardening against server-only draft descriptors and its GitHub delivery boundary. Recorded at 2026-07-14 23:39 CT (UTC-06:00).

## Verified gap

The config-bucket loader joined published prefix and relative path and called S3 without an explicit public-path check. A test-first matrix produced 60 expected failures across the existing `auth-profile-registry.json` and `integrations.json` descriptors, the new Data Spaces, Commerce, Integration Bindings, and Notification Policies descriptors, and case, percent-encoded, double-encoded, traversal, backslash, query, `pageId`, `lang`, `domain`, `environment`, query-path, and raw-path variants.

The public HTTP error body was already generic, but runtime and Content Hub error logs still included raw request or exception text in some paths.

## Change

- Validate the fully joined config-bucket key before every Runtime Read S3 request.
- Repeatedly decode percent encoding and fail closed on residual encodings, dot segments, backslashes, query or fragment delimiters, control characters, or a case-insensitive `server` segment.
- Keep the rule directory-based so later descriptor filenames inherit the boundary without a Runtime Read code change.
- Log only bounded context plus exception type on handled storage failures; do not log raw request fields or exception messages.
- Reuse the hub-audited exact merged-PR verifier in test and production deploy workflows. Serialize each complete workflow by environment and Git ref without cancelling an in-progress deployment, then repeat the full PR, repository, source/base, parent, event-predecessor, and current-tip verification after rebuilding and immediately before obtaining AWS credentials.
- Deny canonical lowercase `*/server/*` object reads explicitly in IAM before the bucket-wide allow and remove the unused `s3:ListBucket` permission.
- Keep `dev` local-only at the delivery boundary: repository pushes run CI but no AWS deployment workflow, `samconfig.toml` has no named `dev` profile, and stale README claims about dev AWS resources were removed.

The S3 allow remains read-only but bucket-wide. IAM resource matching is case-sensitive, so the lowercase canonical deny is defense in depth while the case-insensitive application guard handles alternate casing and encodings. Separate public/server prefixes or buckets remain a future coordinated hardening option; this change creates no new infrastructure.

## Local verification

The following checks passed in the dedicated clean clone before commit or promotion:

- `python -m unittest discover -s tests -p "test_*.py"` — 43 tests.
- `node --test tests/promotion_provenance.spec.mjs` — 6 tests covering exact merged-PR provenance, parent order, repository/branch identity, current tip, retry behavior, and the GitHub API 2026 null `merge_commit_sha` contract.
- `python -m compileall -q lambda_function.py zoolanding_lambda_common.py tests`.
- `actionlint` 1.7.12.
- AWS SAM CLI 1.163.0 `validate --lint` and `build --no-cached` for Python 3.13.
- Gitleaks 8.30.1 against the working tree and all 29 reachable commits; no leaks found.

No AWS deployment or environment promotion was performed as part of this local verification record.

## GitHub delivery guard

GitHub branch-protection readback for `dev`, `test`, and `main` matched the existing service-repository pattern at 2026-07-14 23:27 CT: pull requests required with zero required human approvals, conversation resolution required, strict required checks `guard` and `test`, admin enforcement enabled, force pushes disabled, and branch deletion disabled.

GitHub Environment readback at the same checkpoint showed one literal custom branch policy per deploy environment: `test` accepts only `test`, and `production` accepts only `main`. GitHub still reports `can_admins_bypass: true`; the documented environment update API used here does not expose a field to change that value. The workflows and this change do not exercise that bypass, but it remains a platform-level limitation rather than a satisfied control.
