# Completed native TEST review recovery

- A managed Python patch caused workflow postflight to fail after the reviewed CloudFormation update completed. The next source promotion must independently recover that executed native provenance.
- A successful protected review is accepted only when its exact run and attempt own the current stack's change set, CloudFormation reports `EXECUTE_COMPLETE`, and both retained templates equal the actual stack templates.
- Review-only plans, foreign or stale change sets, failed review jobs, nested/paginated inventories and template differences remain rejected. Qualified live ZIP verification and the complete promoted SAM projection remain mandatory before a new review or activation.
