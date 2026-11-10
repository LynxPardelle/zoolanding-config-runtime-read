# Regional locale fallback — 2026-11-10 CT

Resolve a requested regional locale to its supported base language when the exact regional locale is not published. For example, a site publishing `es` and `en` serves its Spanish dictionaries for `es-419`.

Exact supported locales and fixed-language routes keep precedence. Sites without a matching supported base retain their previous behavior. The runtime remains read-only.
