# Public draft font-face projection

**Date:** 2026-08-27 CT
**Scope:** Runtime Read projection and local verification; deployment evidence is recorded separately after the guarded TEST promotion.

## Change

- Preserved optional `site.fonts` descriptors that were previously omitted from public runtime bundles even when present in the published draft.
- Added a closed, bounded projection matching the shared frontend font contract: up to eight faces, ASCII family names, public WOFF2 paths, weight ranges, and normal or italic styles.
- Preserved exact valid descriptors without inserting defaults, retained an explicitly empty list, and rejected invalid or overlapping collections as a whole.
- Kept the existing sensitive-key and sensitive-value filters effective; no new trusted exceptions, network requests, AWS reads, routes, or environment-selection behavior were added.
- Left SAM, IAM, deployment workflows, shared helpers, and production configuration unchanged.

## Verification

- Observed failing projection and handler regressions before implementation; the four font faces were absent from the response.
- Added 12 focused projection tests covering valid faces, optional fields, empty collections, unknown fields, source/family boundaries, unsafe sources and values, malformed styles/weights, and inclusive overlap checks.
- Added one handler regression proving that a TEST bundle preserves the four descriptors without attempting to load WOFF2 files from the config bucket.
- Passed the complete Python suite (104 tests) and promotion-provenance suite (6 tests) on three consecutive local audit passes.
- Passed `git diff --check`, `sam validate --lint`, a local SAM build, and exact two-file runtime-artifact verification. Local SAM was 1.164.0; the unchanged CI/deployment workflow pins 1.163.0 and must independently build the promoted revision.

## Rollout boundary

Only the existing feature -> dev -> test workflow is authorized for this correction. No production promotion, draft republish, DNS change, IAM change, or runtime data mutation is part of the fix. Roll back through a scoped revert and the same guarded promotion path if post-deployment TEST checks fail.
