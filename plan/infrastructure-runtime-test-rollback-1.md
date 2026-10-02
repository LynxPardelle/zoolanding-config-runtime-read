---
goal: Recover Runtime Read TEST release after CloudFormation rollback and verify both deployment roles
version: 1.0
date_created: 2026-10-02
last_updated: 2026-10-02
owner: Runtime Read release maintainers
status: 'In progress'
tags: [infrastructure, runtime, release, bug]
---

# Introduction

![Status: In progress](https://img.shields.io/badge/status-In_progress-yellow)

Implement the approved design in `docs/superpowers/specs/2026-10-02-runtime-test-rollback-iam-preflight-design.md`. The failed TEST execution `37076527573` left the stack at `UPDATE_ROLLBACK_COMPLETE` with eight physical resources and alias `live:4`. A new GitHub Action is forbidden until the tests, exact IAM preview, both-role simulation, and live AWS preflight pass.

## 1. Requirements & Constraints

- **REQ-001**: Accept `UPDATE_ROLLBACK_COMPLETE` only for `zoolanding-config-runtime-read-test` after the stable-stack and release invariants pass.
- **REQ-002**: Reject in-progress and failed rollback statuses and any unexpected resource count, resource status, CloudFormation role or active change set.
- **REQ-003**: Revalidate the exact TEST source SHA, ZIP digest, object version and effective permissions of the GitHub and CloudFormation deployment roles before another Action.
- **SEC-001**: IAM candidate changes only the three package resource statements of `zoolanding-config-runtime-read-test-github-deploy` and the one package resource statement of `zoolanding-config-runtime-read-test-cfn-exec`; preserve actions, conditions, other statements and rollback exception.
- **SEC-002**: The allowed object ARN remains under `arn:aws:s3:::zoolanding-config-payloads-test/system/thn-runtime/releases/*`; `PutObject` still requires AES256 and `GetObjectVersion` still requires a non-null version ID.
- **CON-001**: Do not change AWS IAM, CloudFormation, GitHub variables or remote branches without their separate authorizations.
- **CON-002**: Do not call a release GitHub Action until the local tests and read-only AWS preflight pass against the final TEST SHA.
- **GUD-001**: Write regression tests first and observe the relevant failure before production-code edits.

## 2. Implementation Steps

### Implementation Phase 1

- GOAL-001: Reproduce and repair the stable rollback-status guard.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-001 | Add `tests/test_native_runtime_release.py` cases for `baseline()` and `live_test_zip()` with a TEST stack in `UPDATE_ROLLBACK_COMPLETE`, eight complete resources, exact role and no active change sets; assert rejection of production rollback and unsafe TEST variants. | ✅ | 2026-10-02 |
| TASK-002 | Run the new tests with the pinned Python runtime and record their expected failures. | ✅ | 2026-10-02 |
| TASK-003 | Update `tools/native_runtime_release.py` to permit the stable TEST rollback state only after the checks in TASK-001; keep existing source, ZIP, alias, template and digest guards. | ✅ | 2026-10-02 |
| TASK-004 | Run the regression tests and verify both the accepted and rejected cases. | ✅ | 2026-10-02 |

### Implementation Phase 2

- GOAL-002: Detect missing access in either TEST deployment role before a release Action.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-005 | Add `tests/test_runtime_test_preflight.py` cases with captured-style AWS responses: GitHub role allowed while CloudFormation role denied, both allowed, wrong SHA, wrong object version, wrong encryption and outside-prefix denial. | ✅ | 2026-10-02 |
| TASK-006 | Run TASK-005 tests and record their expected failures. | ✅ | 2026-10-02 |
| TASK-007 | Implement `tools/runtime_test_preflight.py` as a read-only CLI requiring 40-character source SHA and 64-character ZIP SHA-256; inspect stack, effective role decisions, bucket/object version and release binding. Emit a compact pass/fail result without credentials or signed URLs. | ✅ | 2026-10-02 |
| TASK-008 | Run TASK-005 tests and a local replay with the captured real AWS responses. | ✅ | 2026-10-02 |

### Implementation Phase 3

- GOAL-003: Prepare a fully reviewed TEST promotion and IAM candidate without executing AWS.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-009 | Run `python -m unittest discover -s tests -p "test_*.py"`, `sam validate`, `actionlint` and `git diff --check`; resolve failures before commit. | ✅ | 2026-10-02 |
| TASK-010 | Compare current AWS policy documents for both TEST roles with candidate documents; require exactly four Resource changes to the release-prefix wildcard and preserve all other JSON fields. Simulate all positive and negative IAM cases. | ✅ | 2026-10-02 |
| TASK-011 | Verify the actual TEST stack, eight physical identities, alias `live:4`, package bytes, bucket version and CloudFormation rollback status with read-only AWS CLI. | ✅ | 2026-10-02 |
| TASK-012 | Prepare a PR preview for the operator patch; obtain required approval before commit/push, CI, `dev→test` promotion or any IAM update. | | |

## 3. Alternatives

- **ALT-001**: Retain per-SHA IAM grants for both roles. This is narrower but requires two IAM edits after every TEST SHA change.
- **ALT-002**: Force `UPDATE_COMPLETE` by a manual stack update. This changes AWS without fixing the release guard.

## 4. Dependencies

- **DEP-001**: AWS CLI access to account `765932874577`, region `us-east-1`, with read access to CloudFormation, Lambda, S3 and IAM simulation.
- **DEP-002**: Pinned local SAM CLI and `actionlint` used by the repository's release validation.
- **DEP-003**: Separate approval for `put-role-policy`, remote Git operations and each protected review/execute Action.

## 5. Files

- **FILE-001**: `tools/native_runtime_release.py` — TEST stable rollback guard.
- **FILE-002**: `tests/test_native_runtime_release.py` — rollback regression cases.
- **FILE-003**: `tools/runtime_test_preflight.py` — read-only pre-Action verification.
- **FILE-004**: `tests/test_runtime_test_preflight.py` — both-role access regression cases.
- **FILE-005**: `changelog/2026-10-02-runtime-test-rollback-preflight.md` — incident and guard chronology.

## 6. Testing

- **TEST-001**: Test rejects TEST `UPDATE_ROLLBACK_IN_PROGRESS` and `UPDATE_ROLLBACK_FAILED`, production `UPDATE_ROLLBACK_COMPLETE`, non-complete resources, active change sets and wrong CloudFormation role.
- **TEST-002**: Test accepts TEST `UPDATE_ROLLBACK_COMPLETE` only when all eight resource statuses and existing release binding pass.
- **TEST-003**: Preflight fails when only the GitHub deployment role can read the object version; both roles must return `allowed` for their required actions.
- **TEST-004**: Preflight denies outside-prefix, wrong encryption and missing/invalid version-context cases.
- **TEST-005**: Full unit suite, SAM validation, workflow lint and real AWS read-only replay pass before any Action.

## 7. Risks & Assumptions

- **RISK-001**: The release-prefix wildcard permits access to any release object under the TEST prefix. The caller remains constrained by its role, existing conditions and the operator's exact SHA, digest and version checks.
- **RISK-002**: IAM simulation does not prove every downstream AWS condition; the protected CloudFormation review and exact inventory remain mandatory.
- **ASSUMPTION-001**: The TEST rollback has completed with the original eight physical identities and alias `live:4`; TASK-011 must revalidate this immediately before a new Action.

## 8. Related Specifications / Further Reading

- [Approved recovery specification](../docs/superpowers/specs/2026-10-02-runtime-test-rollback-iam-preflight-design.md)
- [Runtime Read repository guide](../AGENTS.md)
