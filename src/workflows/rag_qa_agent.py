"""RAG pipeline variant: same steps as rag_qa.py, but Search is a durable
agent with MCP tools instead of a direct API/REST call.

Reuses check_forbidden_topic / rewrite_query / identify_synonyms /
generate_answer from rag_qa.py as-is — only the Search step differs. Kept as
a separate flat module (not importing rag_qa's workflow class, just its
activities) for the same auto-discovery reason documented in rag_qa.py and
notes-concepts.md: src/workflows/ only scans flat modules, not subpackages.
"""

import os

import mistralai.workflows as workflows
import mistralai.workflows.plugins.mistralai as workflows_mistralai

from workflows.rag_qa import (
    DEFAULT_FORBIDDEN_ANSWER,
    MODEL,
    check_forbidden_topic,
    generate_answer,
    identify_synonyms,
    rewrite_query,
)

# TODO: point this at the real MCP server exposing the `search` and `readDoc`
# tools once it's registered/configured. Placeholder for now.
SEARCH_MCP_URL = os.environ.get(
    "SEARCH_MCP_URL", "https://TODO-configure-search-mcp-server/sse"
)

# Name of the worker env var holding the bearer token for the MCP server —
# not the token itself. Only this name is ever persisted in Temporal event
# history; set the real secret in .env under this name once available.
SEARCH_MCP_AUTH_TOKEN_ENV = "SEARCH_MCP_TOKEN"


async def _search_via_agent(keywords: str) -> str:
    """Run a durable agent with MCP `search`/`readDoc` tools to gather context.

    Called directly from the workflow body (not wrapped in an @activity),
    matching the SDK's documented pattern: Runner.run() already schedules
    its own durable tool calls internally.
    """
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
        instructions=(
            "Use the `search` tool to find documents relevant to the given keywords. "
            "Use the `readDoc` tool to fetch the content of the most relevant results. "
            "Return the combined relevant text as your final answer, with no commentary."
        ),
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


@workflows.workflow.define(
    name="rag-qa-agent",
    workflow_display_name="RAG Q&A (Agent Search)",
    workflow_description="Same as RAG Q&A, but Search runs as an agent with MCP search/readDoc tools.",
)
class RagQaAgentWorkflow(workflows.InteractiveWorkflow):
    """Interactive so it can be published as a Vibe assistant, same as RagQaWorkflow."""

    @workflows.workflow.entrypoint
    async def run(
        self, question: str = ""
    ) -> workflows_mistralai.ChatAssistantWorkflowOutput:
        if not question:
            await workflows_mistralai.send_assistant_message(
                "Pose ta question, je vais chercher la reponse."
            )
            user_input = await self.wait_for_input(workflows_mistralai.ChatInput())
            question = user_input.message[0].text if user_input.message else ""

        forbidden = await check_forbidden_topic(question)
        if forbidden.is_forbidden:
            await workflows_mistralai.send_assistant_message(DEFAULT_FORBIDDEN_ANSWER)
            return workflows_mistralai.ChatAssistantWorkflowOutput(
                content=[workflows_mistralai.TextOutput(text=DEFAULT_FORBIDDEN_ANSWER)]
            )

        rewritten = await rewrite_query(question)

        # Step 3 — retrieve context via an agent with MCP search/readDoc tools,
        # instead of the direct REST call used in rag_qa.py's search().
        context = await _search_via_agent(rewritten.keywords)

        synonyms = await identify_synonyms(question, context)
        answer = await generate_answer(question, context, synonyms)

        await workflows_mistralai.send_assistant_message(answer)
        return workflows_mistralai.ChatAssistantWorkflowOutput(
            content=[workflows_mistralai.TextOutput(text=answer)]
        )
