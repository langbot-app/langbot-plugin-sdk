# Event processors

An EventProcessor is a code-defined processor for the unified EBA event set.
It is a separate component kind from EventListener. Legacy EventListener plugins
continue to participate in Pipeline lifecycle hooks; they do not subscribe to
new EBA events automatically.

## Scaffold and activate

Run `lbp comp EventProcessor` in a plugin project. Build and install the plugin,
then create an **Event processor** in LangBot's Processors area, select the
component, configure its parameters and bind a Bot event to that instance.
Installation and instance creation alone do not activate event subscriptions.

The plugin manifest declares the component directory:

```yaml
spec:
  components:
    EventProcessor:
      fromDirs:
        - path: components/event_processor/
```

A component manifest uses this shape:

```yaml
apiVersion: langbot/v1
kind: EventProcessor
metadata:
  name: welcome
  label:
    en_US: Welcome members
    zh_Hans: Welcome members
spec:
  events: [group.member_joined]
  config: []
  capabilities:
    tool_calling: true
  permissions:
    tools: [detail, call]
execution:
  python:
    path: welcome.py
    attr: WelcomeProcessor
```

```python
from langbot_plugin.api.definition.components.event_processor import (
    EventProcessor,
    EventProcessorContext,
)
from langbot_plugin.api.entities.builtin.platform.events import MemberJoinedEvent


class WelcomeProcessor(EventProcessor):
    async def initialize(self):
        @self.handler(MemberJoinedEvent)
        async def welcome(ctx: EventProcessorContext):
            await ctx.log(f"Welcoming {ctx.event.member.id}")
            await ctx.reply(f"Hello, {ctx.event.member.nickname}")
```

## Invocation contract

- `ctx.event` is the typed EBA event, including its full public fields. All built-in
  event types, including `PlatformSpecificEvent`, are supported. Raw platform
  objects and the Host's legacy-event backup are excluded from transport.
- `ctx.config` contains parameters for the selected processor instance. It is
  separate from plugin installation configuration.
- `ctx.run_id` identifies the invocation; `ctx.api` provides the existing
  run-scoped, authorized Host APIs. There is no fabricated Pipeline Query.
- `await ctx.log(text, level='info')` records a log entry. Levels are `debug`,
  `info`, `warning` and `error`; a single entry is limited to 65,536 characters.
  Logs never send platform messages.
- `await ctx.reply(text)` calls the Host's `event_reply` tool. Platform capability
  and resource authorization still apply. Unsupported actions fail explicitly.
- Returning normally completes the run. Exceptions fail it and preserve preceding
  logs. Closing or cancelling the run cancels its handler. There is no implicit
  model loop or automatic retry of side effects.
- Register `EBAEvent` for a catch-all fallback. Exact typed handlers take precedence.
  Multiple handlers of the same type execute in registration order. Concurrent
  runs have separate contexts; do not store invocation state on `self`.

EventProcessor shares AgentRunner's execution transport, timeouts, worker
isolation and run ledger. Its reference is `event_processor:author/plugin/name`;
AgentRunner references retain `plugin:author/plugin/name`. Components of different
kinds may safely share a name in the same plugin.

Use the same development SDK revision in the Host and Plugin Runtime. For local
cross-repository work, install this SDK into LangBot's virtualenv and launch with
`uv run --no-sync` so the pinned release does not replace it.
