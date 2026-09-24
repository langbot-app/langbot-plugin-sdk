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
