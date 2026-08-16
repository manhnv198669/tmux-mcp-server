"""Test automated schema portability (Rule 4 / R2).

Ensures tool schemas are strictly flat with no $ref, $defs, anyOf, allOf, or oneOf.
"""

import re

import pytest

from tmux_mcp.config import Config
from tmux_mcp.server import create_server

FORBIDDEN_SCHEMA_KEYS = {"$ref", "$defs", "anyOf", "allOf", "oneOf"}


def walk_schema_keys(node):
    """Recursively yield all key names present in a JSON schema dictionary/list."""
    if isinstance(node, dict):
        for k, v in node.items():
            yield k
            yield from walk_schema_keys(v)
    elif isinstance(node, list):
        for item in node:
            yield from walk_schema_keys(item)


@pytest.mark.asyncio
async def test_schema_portability_and_naming():
    cfg = Config(tool_profile="full")
    app = create_server(cfg)
    tools = await app.list_tools()

    assert len(tools) > 0, "Server registered zero tools"

    for tool in tools:
        # Check tool name naming convention (a-z0-9_, max 64 chars)
        assert re.fullmatch(
            r"[a-z0-9_]{1,64}", tool.name
        ), f"Tool name '{tool.name}' does not match ^[a-z0-9_]{{1,64}}$"

        # Check for forbidden schema constructs
        schema = tool.input_schema or {}
        found_forbidden = set(walk_schema_keys(schema)) & FORBIDDEN_SCHEMA_KEYS
        assert (
            not found_forbidden
        ), f"Tool '{tool.name}' contains non-portable schema elements: {found_forbidden}"
