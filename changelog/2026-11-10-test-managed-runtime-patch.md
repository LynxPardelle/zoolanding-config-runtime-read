# TEST managed runtime patch postflight

- TEST activation completed its reviewed code and immutable alias update, then AWS applied its managed Python runtime patch.
- Accept the same narrowly validated automatic runtime patch transition in TEST as in production. Runtime management mode, all other function settings, native identities, template, API and storage configuration remain checked.
- Regression coverage requires automatic update mode and rejects unrelated configuration changes, manual mode and malformed runtime metadata.
