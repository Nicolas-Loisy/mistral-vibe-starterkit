"""Search step for rag-qa-agent: a durable agent with MCP search/readDoc tools,
instead of the direct REST call used in rag_qa's `search()` activity.

`search_via_agent` is deliberately NOT a @workflows.activity(): it's called
directly from the workflow body, matching the SDK's documented pattern where
Runner.run() already schedules its own durable tool calls internally.
"""

import os

import mistralai.workflows as workflows
import mistralai.workflows.plugins.mistralai as workflows_mistralai

from workflows.rag_qa.activities import MODEL

from .static_prompts import SEARCH_AGENT_INSTRUCTIONS

# Name of the worker env var holding the bearer token for the MCP server —
# not the token itself. Only this name is ever persisted in Temporal event
# history; set the real secret in .env under this name once available.
SEARCH_MCP_AUTH_TOKEN_ENV = "SEARCH_MCP_TOKEN"

# Remote agent reused across runs instead of recreated each time: without a
# fixed id, every Agent(...) call below creates a NEW remote agent (confirmed
# via docs.mistral.ai/studio/workflows/building-workflows/durable_agents —
# "a new remote agent will be created on every workflow execution" — and by
# ~10 accumulated "search-agent" entries observed on the account). Safe to
# share across concurrent users: isolation happens at the conversation level
# (a fresh conversation_id per run), not the agent level — see
# notes-concepts.md.
SEARCH_AGENT_ID = "ag_01a0fc9793a170379576dd2ba24c9138"


@workflows.activity()
async def get_search_mcp_url() -> str:
    """Resolve the MCP server URL from the worker's environment.

    A dedicated activity, not inlined into search_via_agent: os.environ
    access is non-deterministic, and the SDK's determinism rules forbid it
    anywhere in the workflow body — which includes search_via_agent, since
    that function is called directly from workflow.py rather than dispatched
    as its own activity (see this module's docstring). Only code that
    actually runs inside an activity may read the environment.
    """
    # TODO: point this at the real MCP server exposing the `search` and
    # `readDoc` tools once it's registered/configured. Placeholder for now.
    return os.environ.get(
        "SEARCH_MCP_URL", "https://TODO-configure-search-mcp-server/sse"
    )


async def search_via_agent(
    keywords: str,
    search_mcp_url: str,
    session: workflows_mistralai.RemoteSession | None = None,
) -> str:
    """Run a durable agent with MCP `search`/`readDoc` tools to gather context.

    Pass a `session` owned and reused by the caller (e.g. held for the
    lifetime of a multi-turn chat workflow) to give the search agent memory
    of its previous searches: Runner.run() checks
    `session.is_conversation_active()` and appends to the existing remote
    conversation instead of starting a new one when the same instance comes
    back in. Omit it (default) for one-shot usage — a fresh RemoteSession()
    is created internally, exactly as before.
    """
    # mistralai.client.models transitively imports httpx, which subclasses
    # urllib.request.Request at import time. Deferring the import to inside
    # the function (rather than module level) isn't enough on its own:
    # search_via_agent runs directly in the workflow body (see this
    # function's docstring), so this import still executes inside the
    # determinism sandbox at call time — explicit imports_passed_through()
    # is required, same defensive pattern the SDK itself uses internally for
    # deferred imports of its own modules (see
    # mistralai.workflows.core.temporal.context_handler_interceptor).
    with workflows.workflow.unsafe.imports_passed_through():
        from mistralai.client import models as mistralai_models

    mcp_config = workflows_mistralai.MCPStreamableHTTPConfig(
        url=search_mcp_url,
        name="enterprise-search",
        timeout=60,
        auth_token_env=SEARCH_MCP_AUTH_TOKEN_ENV,
    )
    agent = workflows_mistralai.Agent(
        id=SEARCH_AGENT_ID,
        model=MODEL,
        name="search-agent",
        description="Finds and reads the documents relevant to a set of search keywords.",
        instructions=SEARCH_AGENT_INSTRUCTIONS,
        mcp_clients=[mcp_config],
    )
    outputs = await workflows_mistralai.Runner.run(
        agent=agent,
        inputs="keywords to search : " + keywords,
        session=session or workflows_mistralai.RemoteSession(),
        # Needs at least 3 rounds (search, readDoc, final synthesis);
        # max_turns=2 was confirmed (empirically) to cut the agent off
        # before it could write its answer, returning an empty string.
        max_turns=5,
    )
    # A reply can span several chunks (e.g. text mixed with other content
    # types); keep only the text ones and join them. Must be
    # mistralai_models.TextChunk (mistralai.client.models), NOT
    # workflows_mistralai.TextChunk (mistralai.workflows.conversational) —
    # the two are unrelated same-named classes, and Runner.run()'s
    # FinalOutputs is typed, and every Session.format_final_outputs()
    # implementation confirmed, to only ever produce mistralai_models ones.
    texts = [
        output.text
        for output in outputs
        if isinstance(output, mistralai_models.TextChunk)
    ]
    return "\n".join(texts)
