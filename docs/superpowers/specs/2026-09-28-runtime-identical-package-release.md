# Runtime TEST identical-package release

Status: design approved; implemented and verified locally; source integration and
separately authorized native activation pending.

## Evidence and scope

A retained TEST review requested a new SAM version and alias rotation while its
ZIP and full publishable configuration were identical to the active version.
AWS refuses to publish an unchanged version. The preview was not executed.
This correction preserves the approved native provenance operation by updating
only the versioned Code pointer for an identical package. It does not change
application behavior, storage, IAM, API, parameters or production topology.

## Closed classification and projection

- Read the actual published alias, full latest/qualified configurations, qualified
  ZIP, all published versions and runtime-management setting. Bind them to actual
  stack resources. Require Active/Successful health and no weighted alias routing.
- Validate identity metadata separately. Except qualified identity, version,
  revision and last-modified time, full configuration must match.
- Verify bytes and hash of the qualified ZIP through the in-memory download URL
  returned by GetFunction; accept only HTTPS regional Lambda storage origins.
- Compare complete promoted SAM source against previous SAM source except CodeUri
  before evaluating conditions. Inactive branches cannot hide incoming changes.
- Project the full SAM template with the official pinned LanguageExtensions and
  SAM translator, including its Python compatibility entry-point steps. Use only
  actual parameters and validated account, region and stack pseudo parameters.
- Compare complete native projections: resources, metadata, conditions, outputs,
  parameters and references. Normalize only Code and generated version/alias
  identity for comparison. Reject unknown macros and unaccounted differences.

## Identical path

Clone the actual Processed template and replace only Function Code with the
verified bucket/key/object-version of the new package. Preserve every version,
alias, native resource, parameter, output and metadata section. Original and
Processed preview templates must match the complete expected candidate. Require
exactly one Function Code modification with no replacement or derived rotation.

The reviewed digest seals complete state, source/provenance reference, package,
manifest, operation helper, retained preview and inventory. Repeat those reads
before execute. Execute only the exact retained preview and separately approved
digest. Verify all physical identities, complete versions/alias bindings, actual
Code pointer, configurations, bytes and strict TEST runtime after execution.

## Subsequent releases

When Original is already native, recover previous SAM from the immutable Git
revision recorded in its canonical versioned Code pointer. Verify Git blob bytes
and reconstruct only the closed, unchanged release-builder grammar. Require a
successful protected TEST execute and alias postcheck for that source. Seal this
provenance before mutation; do not require the current workflow to be completed
inside its own postflight. A changed package returns to the existing SAM path
after full source and projection checks, with a fresh preview and authorization.

## Operation and gates

The manual TEST workflow uses an isolated pinned projection runtime before AWS
credentials and Actions read permission for protected execution history. The
Lambda two-file package remains unchanged. Missing AWS reader permissions or
source/package access block before a protected review; propose only concrete
minimal TEST changes after effective-policy simulation.

Local negative and lifecycle tests, complete captured-AWS projection, exact Git
package comparison, SAM validation, actionlint and independent review precede
commit/push. Integrate through mandatory CI and exact source-only promotion.
Any IAM adjustment and native execution follow their separate scope approvals.
No speculative runs, article publication or transfer of QA data to production.

AWS Auto can change the managed runtime during UpdateFunctionCode. TEST keeps its
strict postguard and stops for diagnosis on that difference. It does not inherit
the separate production exception or force a new version with artificial changes.

## References

- [AWS Lambda versions](https://docs.aws.amazon.com/lambda/latest/dg/configuration-versions.html)
- [GetFunction](https://docs.aws.amazon.com/lambda/latest/api/API_GetFunction.html)
- [FunctionCodeLocation](https://docs.aws.amazon.com/lambda/latest/api/API_FunctionCodeLocation.html)
