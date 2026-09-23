"""Search step for rag-qa-agent: a durable agent with MCP search/readDoc tools,
instead of the direct REST call used in rag_qa's `search()` activity.

`search_via_agent` is deliberately NOT a @workflows.activity(): it's called
directly from the workflow body, matching the SDK's documented pattern where
Runner.run() already schedules its own durable tool calls internally.
"""

import os

import mistralai.workflows.plugins.mistralai as workflows_mistralai

from workflows.rag_qa.activities import MODEL

from .static_prompts import SEARCH_AGENT_INSTRUCTIONS

# TODO: point this at the real MCP server exposing the `search` and `readDoc`
# tools once it's registered/configured. Placeholder for now.
SEARCH_MCP_URL = os.environ.get(
    "SEARCH_MCP_URL", "https://TODO-configure-search-mcp-server/sse"
)

# Name of the worker env var holding the bearer token for the MCP server —
# not the token itself. Only this name is ever persisted in Temporal event
# history; set the real secret in .env under this name once available.
SEARCH_MCP_AUTH_TOKEN_ENV = "SEARCH_MCP_TOKEN"


async def search_via_agent(keywords: str) -> str:
    """Run a durable agent with MCP `search`/`readDoc` tools to gather context."""
    mcp_config = workflows_mistralai.MCPStreamableHTTPConfig(
        url=SEARCH_MCP_URL,
        name="enterprise-search",
        timeout=60,
        auth_token_env=SEARCH_MCP_AUTH_TOKEN_ENV,
    )
    agent = workflows_mistralai.Agent(
        model=MODEL,
        name="search-agent",
        description="Finds and reads the documents relevant to a set of search keywords.",
        instructions=SEARCH_AGENT_INSTRUCTIONS,
        mcp_clients=[mcp_config],
    )
    outputs = await workflows_mistralai.Runner.run(
        agent=agent,
        inputs=keywords,
        session=workflows_mistralai.RemoteSession(),
    )
    texts: list[str] = []
    for output in outputs:
        if isinstance(output, workflows_mistralai.TextChunk):
            texts.append(output.text)
    return "\n".join(texts)
