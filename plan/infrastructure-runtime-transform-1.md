---
goal: Normalize the sealed Runtime Read candidate to the production SAM transform contract
version: 1.0
date_created: 2026-10-02
last_updated: 2026-10-02
owner: The Hair Narrative release
status: 'In progress'
tags: [infrastructure, runtime-read, production]
---

# Introduction

![Status: In progress](https://img.shields.io/badge/status-In%20progress-yellow)

This plan implements the approved production-only transform conversion in `tools/native_runtime_release.py`. The sealed TEST template and ZIP stay byte-identical.

## 1. Requirements & Constraints

- **REQ-001**: The production candidate has exactly `Transform: AWS::Serverless-2016-10-31` and no TEST alias publication properties.
- **REQ-002**: The candidate differs from the sealed TEST template only in the transform, three alias properties, and versioned `CodeUri`.
- **REQ-003**: Reject duplicate or unknown transforms, nested macros, and `Fn::ForEach`, `Fn::Length`, or `Fn::ToJsonString` before any S3 or CloudFormation write.
- **REQ-004**: The protected production review accepts only `ConfigRuntimeReadFunction.Code` as a direct non-replacing change, preserving six physical identities.
- **SEC-001**: Keep credentials, package bytes, and production template contents out of commits and logs.
- **CON-001**: `test` keeps its existing transform, version, alias, and sealed artifact.
- **CON-002**: Do not push, merge, run Actions, or mutate AWS without the separate authorization required by `AGENTS.md`.

## 2. Implementation Steps

### Implementation Phase 1

- GOAL-001: Specify and implement the fail-closed production conversion.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-001 | Add cases in `tests/test_identical_runtime_release.py` that assert the exact production `Transform`, preserved TEST source, and rejection of altered alias, transform, and macro forms. Run the focused tests to observe the expected failure. | ✅ | 2026-10-02 |
| TASK-002 | Add a production-only conversion helper in `tools/native_runtime_release.py` and call it before the candidate is written in `main()`. Validate the fixed sealed packaging grammar and reject any unknown transform or alias form. | ✅ | 2026-10-02 |
| TASK-003 | Run the focused tests, then the full repository unit suite. Verify the TEST path still writes the original transform and alias. | ✅ | 2026-10-02 |

### Implementation Phase 2

- GOAL-002: Prove that the candidate matches the live production stack before any remote run.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-004 | Run `sam validate` and `actionlint` with pinned local tools, recording any unavailable tool. | ✅ | 2026-10-02 |
| TASK-005 | Compare the captured sealed TEST artifact, current production Original/Processed templates, stack parameters, runtime configuration, and six resource identities with read-only AWS CLI calls. | ✅ | 2026-10-02 |
| TASK-006 | Replay `tools/native_runtime_release.py` to the CloudFormation write barrier with an existing sealed object; reject any projected change beyond `ConfigRuntimeReadFunction.Code` using the current six-resource template and pinned SAM libraries. | ✅ | 2026-10-02 |

### Implementation Phase 3

- GOAL-003: Promote and release only after separately approved exact previews.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-007 | Prepare a PR preview for `dev`, then separate exact `dev → test` and `test → main` previews; obtain the approvals required by `AGENTS.md` before remote writes. | | |
| TASK-008 | Require the new TEST SHA to produce a successful `Deploy test` and `Verify immutable live alias`, then verify the immutable artifact coordinates before the production review. | | |
| TASK-009 | Obtain separate authorization for production `review`; inspect its exact inventory and digest, then obtain separate authorization for `execute` and verify six physical identities afterward. | | |

## 3. Alternatives

- **ALT-001**: Grant CloudFormation access to the LanguageExtensions transform. Rejected because production does not need that transform and the policy expansion would require an additional IAM rollout.
- **ALT-002**: Replace the SAM candidate with a handwritten native CloudFormation template. Rejected because it increases translation and comparison risk.

## 4. Dependencies

- **DEP-001**: `aws-sam-cli==1.163.0` and `aws-sam-translator==1.111.0` for the projection replay.
- **DEP-002**: A current, eligible TEST artifact from the promoted SHA and a successful protected TEST deploy.
- **DEP-003**: AWS CLI read access to the production Runtime Read stack and exact resource identities.

## 5. Files

- **FILE-001**: `tools/native_runtime_release.py` contains the conversion and release guard.
- **FILE-002**: `tests/test_identical_runtime_release.py` contains the behavioral and rejection cases.
- **FILE-003**: `docs/superpowers/specs/2026-10-01-runtime-production-transform-contract-design.md` is the approved design.
- **FILE-004**: `changelog/README.md` and a dated changelog entry record this release correction.

## 6. Testing

- **TEST-001**: Focused tests fail before and pass after implementation for the production-only transform conversion.
- **TEST-002**: `python -m unittest discover -s tests -p "test_*.py"` passes offline.
- **TEST-003**: `sam validate` and `actionlint` pass if available.
- **TEST-004**: The local replay stops before writes and projects one production code pointer change.

## 7. Risks & Assumptions

- **RISK-001**: A future TEST template may introduce a LanguageExtensions-only intrinsic; the conversion must reject it before writing.
- **RISK-002**: Runtime-managed Lambda patch metadata may change independently; the production guard must compare actual runtime management state before a review.
- **ASSUMPTION-001**: The production stack remains stable with six-resource native topology until the exact review.
- **RISK-003**: CloudFormation termination protection is currently disabled on this production stack; this source correction does not modify stack settings.

## 8. Related Specifications / Further Reading

- [Approved Runtime Read design](../docs/superpowers/specs/2026-10-01-runtime-production-transform-contract-design.md)
- [Runtime Read agent rules](../AGENTS.md)
