"""
mcp_config.py — Declarative list of MCP (Model Context Protocol) servers
that Truman should mount at boot.

Each entry spawns a subprocess (command + args) and talks to it over stdio
using the MCP protocol. Tools exposed by the server get prefixed with the
entry key (`{server_id}__{tool_name}`) and mounted into the shared TOOLS
list — visible to both voice and text paths, indistinguishable from native
@tool definitions.

Empty by default. Uncomment entries to enable. Boot order: MCP mount
happens in main.py BEFORE agent.get_agent() so the LangChain agent binds
the MCP tools alongside the natives.
"""
# Add MCP server entries here when building project servers (Phase 5).
# Format: {"server_id": {"command": "...", "args": [...]}}
# Each entry mounts its tools into Truman's TOOLS list at boot.
import os as _os

def _is_railway() -> bool:
    return bool(_os.getenv("RAILWAY_ENVIRONMENT") or _os.getenv("RAILWAY_SERVICE_NAME"))

# Gitnexus is a local code-intelligence tool — no Node.js on Railway.
# Mount only in local dev where the gitnexus binary exists.
MCP_SERVERS: dict = {} if _is_railway() else {
    "gitnexus": {
        "command": "gitnexus",
        "args": ["mcp"],
    },
}
