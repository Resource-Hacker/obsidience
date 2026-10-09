"""One ADK Tool per granted Executive capability, over the shared capability core."""
from __future__ import annotations

from google.adk.tools.base_tool import BaseTool
from google.genai import types

from ..native_turn import tool_schemas


class CapabilityTool(BaseTool):
    """The code-owned native schema; ``run_async`` is one receipt-bound core call.

    The plugin's ``before_tool_callback`` admits the call first (dispatch
    policy, argument validation, strikes); the core pairs the durable receipt
    with dispatch and records an interrupted call as outcome unknown, never
    replayed.
    """

    def __init__(self, schema: dict, plugin):
        super().__init__(name=schema['name'], description=schema['description'])
        self._schema = schema
        self._plugin = plugin

    def _get_declaration(self) -> types.FunctionDeclaration:
        return types.FunctionDeclaration(name=self._schema['name'], description=self._schema['description'],
                                         parameters_json_schema=self._schema['parameters'])

    async def run_async(self, *, args, tool_context):
        return await self._plugin.dispatch(self.name, args)


def capability_tools(allowed, plugin) -> list[CapabilityTool]:
    """Tools in the advertised (sorted) order, with the native transport's exact schemas."""
    return [CapabilityTool(schema, plugin) for schema in tool_schemas(allowed)]


