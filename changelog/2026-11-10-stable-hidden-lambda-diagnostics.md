# Stable hidden Lambda diagnostics

- Exclude transient KMS denial diagnostic text from native function snapshots and qualified-version comparisons, only when variables are absent with the exact `AccessDeniedException` code.
- Preserve all real configuration, other error codes, revisions, code hashes, aliases and published versions. Native template and qualified ZIP verification remain required.
- Safe rejection diagnostics report allowlisted field names only; no environment values, raw exceptions or credentials are logged.
