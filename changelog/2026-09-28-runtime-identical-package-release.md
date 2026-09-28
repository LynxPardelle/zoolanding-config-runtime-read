# Runtime identical-package release — 2026-09-28 CT

An unexecuted TEST preview exposed redundant version publication for an identical
package. Added a closed Code-pointer-only path that preserves all published
versions and the live alias, full SAM source/projection comparison, sealed actual
qualified package/configuration/provenance, and strict postflight checks.

The manual TEST operation uses a pinned isolated SAM projection runtime and reads
protected execution history when the previous Original template is native. The
qualified package reader also accepts the regional Lambda task origin observed
through actual GetFunction, retaining HTTPS, origin and byte/hash validation.

No Lambda runtime source or production topology is changed by this patch. Source
integration does not activate AWS. A new protected preview and separate exact
digest authorization remain required before execution.
