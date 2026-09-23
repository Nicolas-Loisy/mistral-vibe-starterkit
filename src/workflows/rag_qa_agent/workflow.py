"""RAG pipeline variant: same steps as rag_qa, but Search is a durable
agent with MCP tools instead of a direct API/REST call.

Reuses check_forbidden_topic / rewrite_query / identify_synonyms /
generate_answer from workflows.rag_qa.activities as-is — only the Search
step differs (see activities.py in this package).
"""

import mistralai.workflows as workflows
import mistralai.workflows.plugins.mistralai as workflows_mistralai

from workflows.rag_qa.activities import (
    check_forbidden_topic,
    generate_answer,
    identify_synonyms,
    rewrite_query,
)
from workflows.rag_qa.formats import ForbiddenTopicCheck, RewriteResult
from workflows.rag_qa.static_prompts import (
    ASK_QUESTION_MESSAGE,
    DEFAULT_FORBIDDEN_ANSWER,
    GENERATION_ERROR_FALLBACK,
)

from .activities import search_via_agent


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
            await workflows_mistralai.send_assistant_message(ASK_QUESTION_MESSAGE)
            user_input = await self.wait_for_input(workflows_mistralai.ChatInput())
            question = user_input.message[0].text if user_input.message else ""

        # Fails closed: if the guardrail keeps erroring after retries, block
        # rather than silently let a possibly unsafe question through.
        try:
            forbidden = await check_forbidden_topic(question)
        except Exception:  # noqa: BLE001 — deliberate fail-closed fallback
            forbidden = ForbiddenTopicCheck(
                is_forbidden=True, matched_topic="error-fallback"
            )
        if forbidden.is_forbidden:
            await workflows_mistralai.send_assistant_message(DEFAULT_FORBIDDEN_ANSWER)
            return workflows_mistralai.ChatAssistantWorkflowOutput(
                content=[workflows_mistralai.TextOutput(text=DEFAULT_FORBIDDEN_ANSWER)]
            )

        # Rewriting is an optimization, not a hard requirement: degrade to
        # searching with the raw question rather than failing the pipeline.
        try:
            rewritten = await rewrite_query(question)
            if not rewritten.keywords.strip():
                rewritten = RewriteResult(keywords=question)
        except Exception:  # noqa: BLE001 — deliberate graceful degradation
            rewritten = RewriteResult(keywords=question)

        # Step 3 — retrieve context via an agent with MCP search/readDoc tools,
        # instead of the direct REST call used in rag_qa's search().
        context = await search_via_agent(rewritten.keywords)

        synonyms = await identify_synonyms(question, context)

        # No good fallback content is possible for the final answer itself,
        # so fall back to a plain apology message instead of crashing.
        try:
            answer = await generate_answer(question, context, synonyms)
        except Exception:  # noqa: BLE001 — deliberate user-facing fallback
            answer = GENERATION_ERROR_FALLBACK

        await workflows_mistralai.send_assistant_message(answer)
        return workflows_mistralai.ChatAssistantWorkflowOutput(
            content=[workflows_mistralai.TextOutput(text=answer)]
        )
