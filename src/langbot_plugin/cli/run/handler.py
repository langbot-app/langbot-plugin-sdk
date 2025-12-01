from __future__ import annotations

import asyncio
import os
import mimetypes
import typing
import base64
import aiofiles
from copy import deepcopy

from langbot_plugin.api.entities.builtin.pipeline.query import provider_session
from langbot_plugin.runtime.io import connection
from langbot_plugin.entities.io.resp import ActionResponse
from langbot_plugin.runtime.plugin.container import PluginContainer, ComponentContainer
from langbot_plugin.runtime.io.handler import Handler
from langbot_plugin.api.entities import events
from langbot_plugin.api.definition.components.base import NoneComponent
from langbot_plugin.api.definition.components.common.event_listener import EventListener
from langbot_plugin.entities.io.actions.enums import PluginToRuntimeAction
from langbot_plugin.entities.io.actions.enums import RuntimeToPluginAction
from langbot_plugin.api.definition.components.tool.tool import Tool
from langbot_plugin.api.definition.components.command.command import Command
from langbot_plugin.api.definition.components.knowledge_retriever.retriever import KnowledgeRetriever
from langbot_plugin.api.definition.components.base import PolymorphicComponent
from langbot_plugin.api.entities.builtin.rag.context import RetrievalContext
from langbot_plugin.api.proxies.event_context import EventContextProxy
from langbot_plugin.api.proxies.execute_context import ExecuteContextProxy


class PluginRuntimeHandler(Handler):
    """The handler for running plugins."""

    plugin_container: PluginContainer

    shutdown_callback: typing.Callable[[], typing.Coroutine[typing.Any, typing.Any, None]] | None = None
    """Callback to trigger shutdown and reconnect."""

    def __init__(
        self,
        connection: connection.Connection,
        plugin_initialize_callback: typing.Callable[
            [dict[str, typing.Any]], typing.Coroutine[typing.Any, typing.Any, None]
        ],
    ):
        super().__init__(connection)
        self.name = "FromRuntime"

        @self.action(RuntimeToPluginAction.INITIALIZE_PLUGIN)
        async def initialize_plugin(data: dict[str, typing.Any]) -> ActionResponse:
            await plugin_initialize_callback(data["plugin_settings"])
            return ActionResponse.success({})

        @self.action(RuntimeToPluginAction.GET_PLUGIN_CONTAINER)
        async def get_plugin_container(data: dict[str, typing.Any]) -> ActionResponse:
            return ActionResponse.success(self.plugin_container.model_dump())

        @self.action(RuntimeToPluginAction.GET_PLUGIN_ICON)
        async def get_plugin_icon(data: dict[str, typing.Any]) -> ActionResponse:
            icon_path = self.plugin_container.manifest.icon_rel_path
            if icon_path is None:
                return ActionResponse.success({"plugin_icon_file_key": "", "mime_type": ""})
            async with aiofiles.open(icon_path, "rb") as f:
                # icon_base64 = base64.b64encode(f.read()).decode("utf-8")
                icon_bytes = await f.read()

            mime_type = mimetypes.guess_type(icon_path)[0]

            plugin_icon_file_key = await self.send_file(icon_bytes, '')

            return ActionResponse.success(
                {"plugin_icon_file_key": plugin_icon_file_key, "mime_type": mime_type}
            )
        
        @self.action(RuntimeToPluginAction.GET_PLUGIN_README)
        async def get_plugin_readme(data: dict[str, typing.Any]) -> ActionResponse:
            language = data["language"]
            readme_path = os.path.join("readme", f"README_{language}.md") if language != "en" else "README.md"
            if not os.path.exists(readme_path):
                readme_path = "README.md"

            async with aiofiles.open(readme_path, "rb") as f:
                readme_bytes = await f.read()
            readme_file_key = await self.send_file(readme_bytes, "md")
            return ActionResponse.success({"plugin_readme_file_key": readme_file_key, "mime_type": "text/markdown"})

        @self.action(RuntimeToPluginAction.GET_PLUGIN_ASSETS_FILE)
        async def get_plugin_assets_file(data: dict[str, typing.Any]) -> ActionResponse:
            file_key = data["file_key"]
            file_path = os.path.join("assets", file_key)
            if not os.path.exists(file_path):
                return ActionResponse.success({"file_file_key": "", "mime_type": ""})

            async with aiofiles.open(file_path, "rb") as f:
                file_bytes = await f.read()

            mime_type = mimetypes.guess_type(file_path)[0]
            file_file_key = await self.send_file(file_bytes, "")
            return ActionResponse.success({"file_file_key": file_file_key, "mime_type": mime_type})

        @self.action(RuntimeToPluginAction.EMIT_EVENT)
        async def emit_event(data: dict[str, typing.Any]) -> ActionResponse:
            """Emit an event to the plugin.

            {
                "event_context": dict[str, typing.Any],
            }
            """

            event_name = data["event_context"]["event_name"]

            if getattr(events, event_name) is None:
                return ActionResponse.error(f"Event {event_name} not found")

            args = deepcopy(data["event_context"])

            args["plugin_runtime_handler"] = self

            event_context = EventContextProxy.model_validate(args)

            emitted: bool = False

            # check if the event is registered
            for component in self.plugin_container.components:
                if component.manifest.kind == EventListener.__kind__:
                    if component.component_instance is None:
                        return ActionResponse.error("Event listener is not initialized")

                    assert isinstance(component.component_instance, EventListener)

                    if (
                        event_context.event.__class__
                        not in component.component_instance.registered_handlers
                    ):
                        continue

                    for handler in component.component_instance.registered_handlers[
                        event_context.event.__class__
                    ]:
                        await handler(event_context)
                        emitted = True

                    break

            return ActionResponse.success(
                data={
                    "emitted": emitted,
                    "event_context": event_context.model_dump(),
                }
            )

        @self.action(RuntimeToPluginAction.CALL_TOOL)
        async def call_tool(data: dict[str, typing.Any]) -> ActionResponse:
            """Call a tool."""
            tool_name = data["tool_name"]
            tool_parameters = data["tool_parameters"]
            session = data["session"]
            query_id = data["query_id"]

            for component in self.plugin_container.components:
                if component.manifest.kind == Tool.__kind__:
                    if component.manifest.metadata.name != tool_name:
                        continue

                    if isinstance(component.component_instance, NoneComponent):
                        return ActionResponse.error("Tool is not initialized")

                    assert isinstance(component.component_instance, Tool)

                    tool_instance = component.component_instance

                    # 检查 call 方法是否接受 session 和 query_id 参数，如果接受则传入，否则只传 tool_parameters
                    import inspect

                    call_sig = inspect.signature(tool_instance.call)
                    params = call_sig.parameters

                    if "session" in params and "query_id" in params:
                        session = provider_session.Session.model_validate(session)
                        resp = await tool_instance.call(tool_parameters, session=session, query_id=query_id)
                    else:
                        resp = await tool_instance.call(tool_parameters)

                    return ActionResponse.success(
                        data={
                            "tool_response": resp,
                        }
                    )

            return ActionResponse.error(f"Tool {tool_name} not found")

        @self.action(RuntimeToPluginAction.EXECUTE_COMMAND)
        async def execute_command(
            data: dict[str, typing.Any],
        ) -> typing.AsyncGenerator[ActionResponse, None]:
            """Execute a command."""

            args = deepcopy(data["command_context"])
            args["plugin_runtime_handler"] = self
            command_context = ExecuteContextProxy.model_validate(args)

            for component in self.plugin_container.components:
                if component.manifest.kind == Command.__kind__:
                    if component.manifest.metadata.name != command_context.command:
                        continue

                    if isinstance(component.component_instance, NoneComponent):
                        yield ActionResponse.error("Command is not initialized")

                    command_instance = component.component_instance
                    assert isinstance(command_instance, Command)
                    async for return_value in command_instance._execute(
                        command_context
                    ):
                        yield ActionResponse.success(
                            data={
                                "command_response": return_value.model_dump(mode="json")
                            }
                        )
                    break
            else:
                yield ActionResponse.error(
                    f"Command {command_context.command} not found"
                )

        # Polymorphic component actions (generic)
        @self.action(RuntimeToPluginAction.SYNC_POLYMORPHIC_COMPONENT_INSTANCES)
        async def sync_polymorphic_component_instances(data: dict[str, typing.Any]) -> ActionResponse:
            """Sync polymorphic component instances for this plugin.

            This handler receives the complete list of required instances for this plugin,
            and ensures that:
            1. All required instances are created
            2. All unrequired instances are deleted
            """
            required_instances = data["required_instances"]

            # Collect all existing instances across all polymorphic components
            existing_instances: dict[str, tuple[ComponentContainer, str, str]] = {}  # {instance_id: (component_container, component_kind, component_name)}
            for component in self.plugin_container.components:
                if hasattr(component, 'polymorphic_component_instances'):
                    for instance_id in list(component.polymorphic_component_instances.keys()):
                        existing_instances[instance_id] = (
                            component,
                            component.manifest.kind,
                            component.manifest.metadata.name
                        )

            # Build set of required instance IDs
            required_instance_ids = {inst["instance_id"] for inst in required_instances}

            # Delete unrequired instances
            deleted_count = 0
            for instance_id, (component, kind, name) in existing_instances.items():
                if instance_id not in required_instance_ids:
                    try:
                        del component.polymorphic_component_instances[instance_id]
                        deleted_count += 1
                    except Exception as e:
                        pass  # Already deleted or error

            # Create/verify required instances
            created_count = 0
            updated_count = 0
            already_exists_count = 0
            failed_instances = []

            for inst_info in required_instances:
                instance_id = inst_info["instance_id"]
                component_kind = inst_info["component_kind"]
                component_name = inst_info["component_name"]
                config = inst_info["config"]

                # Check if instance already exists in the correct component
                if instance_id in existing_instances:
                    existing_component, existing_kind, existing_name = existing_instances[instance_id]
                    if existing_kind == component_kind and existing_name == component_name:
                        # Instance exists in correct component, check if config changed
                        existing_instance = existing_component.polymorphic_component_instances.get(instance_id)
                        if existing_instance and existing_instance.config != config:
                            # Config changed, need to recreate instance
                            try:
                                del existing_component.polymorphic_component_instances[instance_id]
                                # Will be recreated below with new config
                            except:
                                pass
                        else:
                            # Config unchanged, skip
                            already_exists_count += 1
                            continue
                    else:
                        # Instance exists in wrong component, delete it first
                        try:
                            del existing_component.polymorphic_component_instances[instance_id]
                        except:
                            pass

                # Find the target component
                target_component = None
                for component in self.plugin_container.components:
                    if component.manifest.kind == component_kind:
                        if component.manifest.metadata.name == component_name:
                            target_component = component
                            break

                if target_component is None:
                    failed_instances.append({
                        "instance_id": instance_id,
                        "reason": f"Component {component_kind}/{component_name} not found"
                    })
                    continue

                # Create the instance (either new or recreated with updated config)
                is_update = instance_id in existing_instances
                try:
                    component_class = target_component.manifest.get_python_component_class()
                    if not issubclass(component_class, PolymorphicComponent):
                        failed_instances.append({
                            "instance_id": instance_id,
                            "reason": f"Component {component_name} is not polymorphic"
                        })
                        continue

                    new_instance = component_class()
                    new_instance.instance_id = instance_id
                    new_instance.config = config
                    new_instance.plugin = self.plugin_container.plugin_instance
                    await new_instance.initialize()

                    target_component.polymorphic_component_instances[instance_id] = new_instance
                    if is_update:
                        updated_count += 1
                    else:
                        created_count += 1
                except Exception as e:
                    failed_instances.append({
                        "instance_id": instance_id,
                        "reason": str(e)
                    })

            return ActionResponse.success({
                "deleted_count": deleted_count,
                "created_count": created_count,
                "updated_count": updated_count,
                "already_exists_count": already_exists_count,
                "failed_instances": failed_instances
            })

        @self.action(RuntimeToPluginAction.CREATE_POLYMORPHIC_COMPONENT_INSTANCE)
        async def create_polymorphic_component_instance(data: dict[str, typing.Any]) -> ActionResponse:
            """Create a polymorphic component instance (generic handler for any polymorphic component)."""
            instance_id = data["instance_id"]
            component_kind = data["component_kind"]
            component_name = data["component_name"]
            config = data["config"]

            # Find the component by kind and name
            target_component = None
            for component in self.plugin_container.components:
                if component.manifest.kind == component_kind:
                    if component.manifest.metadata.name == component_name:
                        target_component = component
                        break

            if target_component is None:
                return ActionResponse.error(f"Component {component_kind}/{component_name} not found")

            # Get the component class
            component_class = target_component.manifest.get_python_component_class()
            if not issubclass(component_class, PolymorphicComponent):
                return ActionResponse.error(f"Component {component_name} is not a polymorphic component")

            # Create a new instance
            new_instance = component_class()
            new_instance.instance_id = instance_id
            new_instance.config = config
            new_instance.plugin = self.plugin_container.plugin_instance
            await new_instance.initialize()

            # Store the instance
            target_component.polymorphic_component_instances[instance_id] = new_instance

            return ActionResponse.success({"instance_id": instance_id})

        @self.action(RuntimeToPluginAction.DELETE_POLYMORPHIC_COMPONENT_INSTANCE)
        async def delete_polymorphic_component_instance(data: dict[str, typing.Any]) -> ActionResponse:
            """Delete a polymorphic component instance (generic handler for any polymorphic component)."""
            instance_id = data["instance_id"]
            component_kind = data["component_kind"]
            component_name = data["component_name"]

            # Find the component by kind and name
            target_component = None
            for component in self.plugin_container.components:
                if component.manifest.kind == component_kind:
                    if component.manifest.metadata.name == component_name:
                        target_component = component
                        break

            if target_component is None:
                return ActionResponse.error(f"Component {component_kind}/{component_name} not found")

            if instance_id not in target_component.polymorphic_component_instances:
                return ActionResponse.error(f"Component {component_name} instance {instance_id} not found")

            # Remove the instance
            del target_component.polymorphic_component_instances[instance_id]

            return ActionResponse.success({"success": True})

        @self.action(RuntimeToPluginAction.RETRIEVE_KNOWLEDGE)
        async def retrieve_knowledge(data: dict[str, typing.Any]) -> ActionResponse:
            """Retrieve knowledge using a KnowledgeRetriever instance."""
            retriever_name = data["retriever_name"]
            instance_id = data["instance_id"]
            retrieval_context = RetrievalContext.model_validate(data["retrieval_context"])

            retriever_component = None
            for component in self.plugin_container.components:
                if component.manifest.kind == KnowledgeRetriever.__kind__:
                    if component.manifest.metadata.name == retriever_name:
                        retriever_component = component
                        break

            if retriever_component is None:
                return ActionResponse.error(f"KnowledgeRetriever {retriever_name} not found")

            if instance_id not in retriever_component.polymorphic_component_instances:
                return ActionResponse.error(f"KnowledgeRetriever {retriever_name} instance {instance_id} not found")

            retriever_instance = retriever_component.polymorphic_component_instances[instance_id]
            assert isinstance(retriever_instance, KnowledgeRetriever)

            # Call retrieve method
            results = await retriever_instance.retrieve(retrieval_context)

            return ActionResponse.success({"retrieval_results": [result.model_dump(mode="json") for result in results]})

        @self.action(RuntimeToPluginAction.SHUTDOWN)
        async def shutdown(data: dict[str, typing.Any]) -> ActionResponse:
            """Handle shutdown request from runtime.

            In debug mode (when shutdown_callback is set), this will trigger reconnection.
            In production mode, this will just acknowledge the shutdown.
            """
            if self.shutdown_callback is not None:
                # In debug mode, trigger reconnection
                asyncio.create_task(self.shutdown_callback())

            return ActionResponse.success({})

    async def register_plugin(self, prod_mode: bool = False) -> dict[str, typing.Any]:
        # Read PLUGIN_DEBUG_KEY from environment variable
        plugin_debug_key = os.environ.get("PLUGIN_DEBUG_KEY", "")

        resp = await self.call_action(
            PluginToRuntimeAction.REGISTER_PLUGIN,
            {
                "plugin_container": self.plugin_container.model_dump(),
                "prod_mode": prod_mode,
                "plugin_debug_key": plugin_debug_key,
            },
        )
        return resp

    async def get_plugin_container(self) -> dict[str, typing.Any]:
        """Get the current plugin container data."""
        return self.plugin_container.model_dump()


# {"action": "get_plugin_container", "data": {}, "seq_id": 1}
