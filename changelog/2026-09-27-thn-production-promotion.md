# THN production source and release separation

Added closed source-only promotion and reviewed activation selectors, retained native preview/execute, exact real TEST release provenance and explicit THN production profile checks. Existing non-THN TEST automatic provenance remains. Production authorization, IAM and live native inventory are prerequisites, not local test conclusions.

- Independent review repairs: raw duplicate/escaped selector keys fail before credentials; fresh live MAIN/TEST and actual role/trust/inline-policy fingerprints are retained at mutation boundaries; native CreationTime enforces24h expiry. Sealed authority tooling stays outside Lambda ZIP. Authoring retains no-checkout OIDC artifact boundary; Runtime transport includes helper and exact SHA checkout. Existing production CFN execution role identity is preserved.

## TEST activation dependency repair

- Transport the native operator dependency outside the unchanged Lambda ZIP and hash-check it before credentials. Both the parser and operator run from a sealed artifact without a checkout.
- Enforce the exact six-file outer transport, preserving the existing three-file release inventory and code digest.
- Reproduce missing-module failures locally; test isolated parser/operator execution and duplicate selector, absent helper and substituted helper rejection.

- CI dependency correction: the new transport regressions extract unique literal workflow blocks using only the Python standard library. They no longer inherit PyYAML from a local development environment. Both modules pass with site-packages disabled (`python -S`), preserving the actual isolated parser/operator commands and hash-substitution rejection.

## Retain Runtime API metadata in native releases

- Preserve the existing `RuntimeApi` `SamResourceId` metadata in the source template because the bounded manual release does not run `sam package` metadata normalization.
- Exercise the real release-template assembler and native review guard; missing or changed API metadata remains rejected. Lambda ZIP sources, IAM permissions and release guards are unchanged.


## Verify managed production runtime patches after code activation

- Preserve the exact runtime patch ARN in every review digest and fresh pre-execution baseline. Production reads the selected native function's runtime management mode and verifies it against its unchanged processed template.
- After code activation, accept only a well-formed AWS managed patch ARN change under the same verified Auto or FunctionUpdate mode. Runtime identifier, architecture, package type, role, environment and all other configuration stay exact; Manual mode, runtime errors and malformed metadata remain rejected.
- TEST retains its existing strict comparison and makes no new runtime management request. The operator and its transport hash change; Lambda package sources and templates do not.
- The observed Authoring TEST Auto patch change demonstrated the guard risk. Different TEST and production patch ARNs alone do not predict a production patch update, because runtime ARNs also depend on architecture. Production activation still requires its own fresh native review and scoped metadata-read permission.
