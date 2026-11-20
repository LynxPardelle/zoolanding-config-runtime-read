# Runtime TEST exact-alias package verification

The protected TEST release verifier now requests `GetFunction` through the exact
`live` alias. It binds the response alias ARN and numeric version to the captured
CloudFormation/alias identity, retains the full configuration, published-version
and ZIP checks, and rereads the entire alias after verification. A changed
revision rejects the snapshot even when the version number is unchanged.

The operation helper can use a separately approved `lambda:GetFunction` read grant
for that exact alias, avoiding speculative future-version grants. This source
change adds no IAM policy, AWS mutation, runtime code, template or workflow change.
Production's TEST-package verifier retains its numeric-version read.

Offline regressions cover exact request scope, response identity/version mismatch,
alias movement and metadata changes, stable alias success, numeric production
reads, and the existing native review/execute lifecycle. The three packaged Lambda
sources remain identical to the production-registration candidate.
