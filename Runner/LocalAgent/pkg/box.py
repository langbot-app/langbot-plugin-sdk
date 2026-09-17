"""LocalAgent's sandbox policy and explicit file preparation/delivery."""

from string import Formatter

from langbot_plugin.api.entities.builtin.provider.message import ContentElement

SANDBOX_TOOLS = frozenset({"exec", "read", "write", "edit", "glob", "grep"})


def resolve_reuse_key(ctx, template: str) -> str:
    if not isinstance(template, str) or not template.strip():
        raise ValueError("Box reuse template must not be empty")
    conversation = ctx.conversation
    target = ctx.delivery.reply_target or {}
    variables = {
        **ctx.variables,
        "global": "global",
        "run_id": ctx.run_id,
        "query_id": ctx.variables.get("query_id", ctx.run_id),
        "event_id": ctx.event.event_id,
        "event_type": ctx.event.event_type,
        "launcher_type": (conversation.launcher_type if conversation else None) or target.get("target_type"),
        "launcher_id": (conversation.launcher_id if conversation else None) or target.get("target_id"),
        "sender_id": (conversation.sender_id if conversation else None) or (ctx.actor.actor_id if ctx.actor else None),
        "conversation_id": ctx.variables.get("conversation_id")
        or (conversation.conversation_id if conversation else None),
        "bot_id": (conversation.bot_id if conversation else None) or ctx.event.data.get("bot_uuid"),
    }
    # Interpolate named scalar fields, never Python expressions or object access.
    for _, name, spec, conversion in Formatter().parse(template):
        if name is not None and (name not in variables or variables[name] is None or spec or conversion):
            raise ValueError(f"Unavailable or invalid Box template variable: {name}")
    key = template.format_map(variables)
    if not key.strip() or len(key) > 1024:
        raise ValueError("Box reuse key must contain 1 to 1024 characters")
    return key


class LocalAgentBox:
    def __init__(self, ctx, api):
        self.ctx = ctx
        self.api = api
        self.binding = None

    def needed(self):
        tools = {t.tool_name for t in self.api.get_allowed_tools()}
        return (
            self.ctx.config.get("box-enabled", True)
            and bool(tools.intersection(SANDBOX_TOOLS))
            and self.ctx.context.available_apis.box
        )

    async def prepare(self):
        status = await self.api.get_box_status()
        if not status.available:
            raise RuntimeError(status.reason or "Box is unavailable")
        template = self.ctx.config.get("box-session-id-template", "{launcher_type}_{launcher_id}")
        key = status.required_reuse_key or resolve_reuse_key(self.ctx, template)
        # Always try acquisition even at zero remaining capacity: reuse does not consume another slot.
        box = await self.api.acquire_box(key)
        self.binding = await self.ctx.bind_box(box.id)
        files = await self.ctx.import_box_attachments() if self.ctx.input.attachments else []
        by_ref = {item.id: item for item in files}
        for attachment in self.ctx.input.attachments:
            if attachment.ref in by_ref:
                item = by_ref[attachment.ref]
                attachment.path, attachment.size = item.path, item.size
        if files:
            self.ctx.input.contents = [c for c in self.ctx.input.contents if c.type not in {"file_url", "file_base64"}]
        self.ctx.input.contents.append(
            ContentElement.from_text(
                f"Sandbox files for this run belong in {self.binding.outbox}/ when they should be delivered "
                "to the user. Create this directory if needed. The runner exports this directory on successful completion."
            )
        )

    async def finish(self):
        if self.binding is None:
            return []
        files = await self.ctx.export_box_files()
        ids = [item.id for item in files]
        if ids and not self.ctx.delivery.automatic_reply:
            await self.ctx.reply_files(ids)
            return []
        return ids
