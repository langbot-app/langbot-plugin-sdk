# Shared runtime candidate (SDK 0.6.0b5)

This source declares the SDK shared-runtime contract. That declaration is not a
certificate or a claim of live vendor acceptance. Exact archives require a separate
independent review, signer approval, and two-Workspace acceptance.

- Configuration and credentials are read per invocation. No SDK process-global
  settings are modified.
- Host-managed state and the SDK connection binding supply authority. User config
  strings and adapter business parameters are not tenant identity.
- Explicit HTTP(S) self-hosted endpoints remain supported, including private service
  addresses. Endpoint validation is syntax validation, NOT an SSRF/network sandbox.
  Shared deployments MUST enforce their own egress policy against metadata/control
  endpoints and foreign tenant services. Do not certify a deployment without that
  network-policy evidence. Environment HTTP proxies are no longer implicitly inherited.
- Redirects are not followed by HTTP clients. Configure the final endpoint/attachment
  URL; redirect-dependent workflows must update their URL rather than forwarding
  credentials to an unreviewed destination.
- Tests use installed SDK types and actual local transports/processes, with explicitly
  simulated vendor replies. They are not paid/live vendor-account tests.

## Upstream identity migration

With a trusted SDK installation binding (or a Host Workspace conversation context),
upstream user IDs are deterministic `lb_` SHA-256 names scoped to that authority.
The same actor/legacy launcher in different installations/Workspaces no longer
collides. Dedicated OSS without either scope retains the existing legacy IDs.
Existing vendor conversations associated with the old unscoped user may require
a new conversation after upgrading; no automatic cross-user memory migration is
performed. Host-scoped state is not copied between tenants.

## Synchronous vendor SDK isolation

Every SDK operation executes in a new killable Python subprocess, using only the
request's credentials and a minimal environment. Linux/Unix `resource` support is
required; native Windows is not supported by this candidate. Worker address-space
budget is 512 MiB; frame budget 1 MiB; stream budget 16 MiB. OS pipes apply bounded
backpressure. Timeout, cancellation and early close kill/reap the child before
returning. Host run concurrency/cgroup limits remain necessary. No daemon threads
or executor uploads survive cancellation. Parent-owned private temporary directories
are removed after reaping, including killed Tbox uploads. This is not proof of the
production nsjail subprocess/rlimit policy; exercise that policy before signing.
