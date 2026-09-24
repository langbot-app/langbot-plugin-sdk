# Shared runtime candidate (SDK 0.6.1)

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

## Optional asset gateway

The listener belongs to the SDK-created Runner component (one installation), not
a process-global SDK singleton. Concurrent runs with identical host/port/timeout
share only that component's listener, with distinct expiring tokens. Last release
closes the listener and drains accepted tasks. Conflicting fixed-port settings fail
instead of silently reusing or mutating an active listener. Separate installations
need distinct network namespaces or nonconflicting ports and explicit ingress routing.
Limits: 16 accepted connections, 16 KiB headers, 1 MiB request/response, 32-message
MCP batches, finite request timeout <=120s and token TTL <=3600s. Tool RPC cancellation
does not promise rollback of an already-dispatched Host operation.

## Upstream identity migration

With a trusted SDK installation binding (or a Host Workspace conversation context),
upstream user IDs are deterministic `lb_` SHA-256 names scoped to that authority.
The same actor/legacy launcher in different installations/Workspaces no longer
collides. Dedicated OSS without either scope retains the existing legacy IDs.
Existing vendor conversations associated with the old unscoped user may require
a new conversation after upgrading; no automatic cross-user memory migration is
performed. Host-scoped state is not copied between tenants.

## Human-input continuation migration

New pending forms have an owner binding (Workspace/installation, conversation,
actor and endpoint) and a one-hour expiry. Old ownerless forms must be restarted;
this intentionally fails closed instead of adopting an unscoped form. Storage
denial/transport/decode failures are not reported as “not found”. A submission is
persistently consumed BEFORE dispatching the external approval; ambiguous vendor
failures cannot be replayed. Recover such a workflow at Dify rather than blindly
resubmitting. The component rejects overlapping resumes of the same form. This
relies on SDK single-installation worker fencing, not distributed compare-and-swap.
Expired/consumed failures are retained in scoped plugin storage until normal
installation cleanup; this version does not promise periodic garbage collection.
