# AgentRunner Structured Interactions

Structured interactions are a provider-neutral AgentRunner Protocol v1
capability. Dify human input, deployment approval, a remote harness question,
and a CLI permission confirmation all use the same Host contract.

## Manifest

Only runners that actually emit and resume interactions should opt in:

```yaml
spec:
  capabilities:
    interactions: true
  permissions:
    interactions: [request]
    storage: [plugin]
```

The Host also applies the binding delivery policy. A manifest declaration does
not bypass Host authorization.

## Request

Emit an SDK `InteractionRequest` through the whitelisted result factory:

```python
from langbot_plugin.api.entities.builtin.agent_runner import (
    AgentRunResult,
    InteractionAction,
    InteractionRequest,
)

yield AgentRunResult.interaction_requested(
    ctx.run_id,
    InteractionRequest(
        interaction_id="provider-neutral-correlation-id",
        kind="confirmation",
        title="Approve this operation?",
        actions=[
            InteractionAction(id="approve", label="Approve", style="primary"),
            InteractionAction(id="deny", label="Deny", style="danger"),
        ],
        fallback_text="Approval is required to continue.",
    ),
)
```

Use `ctx.delivery.interactions` to inspect the current surface's supported
field types, action styles, update support, and field limit. Always provide a
plain-text fallback.

## Continuation

Provider-private values must not cross the Host interaction boundary. Store
tokens, workflow IDs, CLI checkpoints, and provider user tags in authorized
plugin storage or Host state, keyed by the public `interaction_id`.

On a later run, the Host sets both:

```python
ctx.event.event_type == "interaction.submitted"
ctx.input.interaction  # InteractionSubmission
```

Load the private continuation using `interaction_id`, validate the submitted
action and values against the provider mapping, resume the provider, and delete
the continuation after a successful terminal event. If the provider pauses
again, persist a new continuation and emit a new interaction request before
deleting the old one.

Do not keep the only continuation copy in a module-level dictionary. Plugin
process restarts and multi-process runtimes make in-memory correlation
unreliable.

## Long-Lived Processes

Some CLI or harness permission protocols wait for a response on the same live
stdin/stdout channel. A Host interaction callback arrives as a later AgentRun,
so such runners need a durable daemon or checkpoint/resume mechanism before
declaring interaction support. Do not enable the capability solely because the
CLI can display an interactive terminal prompt.
