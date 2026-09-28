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
