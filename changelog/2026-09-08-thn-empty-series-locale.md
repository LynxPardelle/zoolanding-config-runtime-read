# THN empty-series locale isolation - 2026-09-08 CT

The local `published-only` candidate now filters authored public taxonomy by the
selected locale before enrichment, including when the metadata binding is
absent. This allows an explicitly configured empty series without making a
sibling-language path valid. Hubs that omit the option retain existing behavior.

The full 123-test local suite passes, including both bound/unbound metadata and
mixed strict/legacy fixtures. This extends the previously authorized local
locale correction only; no IAM, deployment, alias or live pointer was changed.
