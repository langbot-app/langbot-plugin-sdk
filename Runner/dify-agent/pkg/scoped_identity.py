"""Namespace upstream identity using trusted connection or Host context only."""

import hashlib
import json


def scoped_identity(runner, ctx, local_id):
    handler = getattr(runner, "_plugin_runtime_handler", None)
    binding = getattr(handler, "bound_action_context", None)
    if binding is not None:
        scope = [binding.instance_uuid, binding.workspace_uuid, binding.installation_uuid]
    else:
        workspace = getattr(ctx.conversation, "workspace_id", None)
        if not workspace:
            # Dedicated OSS has no Workspace; retain its documented legacy IDs.
            return local_id
        scope = [workspace]
    encoded = json.dumps([scope, local_id], ensure_ascii=False, separators=(",", ":")).encode()
    return "lb_" + hashlib.sha256(encoded).hexdigest()
