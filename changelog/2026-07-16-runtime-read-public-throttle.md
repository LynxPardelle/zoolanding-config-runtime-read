# Runtime Read public method throttle

Scope: local Runtime Read infrastructure hardening completed on 2026-07-16 CT. This entry does not claim an AWS deployment.

## Problem

The anonymous `GET /runtime-bundle` method had no explicit API Gateway stage throttle. It therefore inherited the much broader account-level capacity even though the Lambda already had reserved concurrency and production alarms.

## Change

- Set the API Gateway stage method target for only `GET /runtime-bundle` to 25 requests per second with a burst of 50.
- Keep CORS `OPTIONS` unchanged.
- Use the native `AWS::Serverless::Api` method setting without a WAF, usage plan, or new dependency.

The selected target retains substantial headroom over the supplied operational sample of 1,236 invocations from 02:00 through 05:30 UTC on 2026-07-17, whose peak was 38 requests per minute. API Gateway throttling remains best-effort and does not replace a separately approved WAF policy if attack traffic later warrants one.

## Verification

- A focused contract regression confirms the exact method, encoded resource path, rate, burst, and unchanged CORS methods.
- The complete local unit suite, SAM validation/build, workflow lint, and diff checks passed in three audit rounds.
- No AWS mutation, deployment, or live customer-data read was performed as part of this change.
