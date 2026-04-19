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
MCP_SERVERS: dict = {
    # Example — filesystem sandbox. Uncomment to enable, requires npx.
    # "fs": {
    #     "command": "npx",
    #     "args": [
    #         "-y",
    #         "@modelcontextprotocol/server-filesystem",
    #         "/Users/ompandya/Desktop/mcp-sandbox",
    #     ],
    # },
}
