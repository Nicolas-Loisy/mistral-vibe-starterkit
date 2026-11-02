"""Multi-turn variant of rag-qa-agent: one workflow execution answers any
number of follow-up questions in the same chat session, instead of ending
after a single answer.

Reuses check_forbidden_topic / rewrite_query / identify_synonyms /
generate_answer from workflows.rag_qa.activities and get_search_mcp_url /
search_via_agent from workflows.rag_qa_agent.activities, same as
rag_qa_agent — only the workflow body loops instead of returning after one
turn.
"""

from datetime import timedelta

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
    GENERATION_ERROR_FALLBACK,
    get_forbidden_answer,
)
from workflows.rag_qa_agent.activities import get_search_mcp_url, search_via_agent

from .static_prompts import GOODBYE_MESSAGE, STOP_WORDS, WELCOME_MESSAGE

# execution_timeout is a wall-clock cap on the WHOLE session, including idle
# time spent waiting between questions — not just active processing. The
# SDK default (1h) would kill an otherwise-healthy but slow-paced
# conversation with WORKFLOW_EXECUTION_TIMED_OUT. Bumped to a full day so a
# real back-and-forth session has room to breathe; tune per deployment.
SESSION_EXECUTION_TIMEOUT = timedelta(days=1)

# Independent of SESSION_EXECUTION_TIMEOUT above: this closes an abandoned
# chat early and cleanly (goodbye message, normal return) instead of
# leaving it idle until execution_timeout hard-kills it with an error.
INACTIVITY_TIMEOUT = timedelta(minutes=30)


@workflows.workflow.define(
    name="rag-qa-chat",
    workflow_display_name="RAG Q&A (Multi-turn Chat)",
    workflow_description=(
        "Same pipeline as RAG Q&A (Agent Search), but stays open for an "
        "arbitrary number of follow-up questions in one chat session."
    ),
    execution_timeout=SESSION_EXECUTION_TIMEOUT,
)
class RagQaChatWorkflow(workflows.InteractiveWorkflow):
    """Interactive so it can be published as a Vibe assistant, same as RagQaAgentWorkflow.

    NOTE on history growth: a very long session (many hundreds of turns)
    could in theory approach the 51 200-event execution history cap (see
    .agents/skills/workflows/references/guides/limitations.mdx). The usual
    fix — continue_as_new() — is deliberately NOT used here: it would
    restart run() with a fresh, empty-state RemoteSession (a new
    `_conversation_id`), silently dropping the Mistral-side conversation
    history this workflow relies on for multi-turn context. That failure
    mode (silently losing context) is worse than the much more remote risk
    of hitting the history cap. Revisit if this ever needs to support
    genuinely long-lived sessions (there's no public API to resume a
    RemoteSession from an existing conversation_id today).
    """

    @workflows.workflow.entrypoint
    async def run(self) -> workflows_mistralai.ChatAssistantWorkflowOutput:
        search_mcp_url = await get_search_mcp_url()

        # One RemoteSession per agent, created ONCE and reused for every
        # turn below. Runner.run() checks session.is_conversation_active()
        # and appends to the existing remote conversation instead of
        # starting a new one — that's what gives each agent memory of the
        # previous turns (past searches / past answers) without having to
        # concatenate the conversation history ourselves.
        search_session = workflows_mistralai.RemoteSession()
        answer_session = workflows_mistralai.RemoteSession(stream=True)

        await workflows_mistralai.send_assistant_message(WELCOME_MESSAGE)

        last_answer = ""
        while True:
            try:
                user_input = await self.wait_for_input(
                    workflows_mistralai.ChatInput(
                        'Pose ta question (ou "stop" pour terminer)',
                        suggestions=[[workflows_mistralai.TextChunk(text="stop")]],
                    ),
                    timeout=INACTIVITY_TIMEOUT,
                )
            except TimeoutError:
                inactivity_minutes = int(INACTIVITY_TIMEOUT.total_seconds() // 60)
                last_answer = (
                    f"Je ferme la session après {inactivity_minutes} minutes "
                    "sans question. À bientôt !"
                )
                await workflows_mistralai.send_assistant_message(last_answer)
                break

            question = user_input.message[0].text if user_input.message else ""
            if not question or question.strip().lower() in STOP_WORDS:
                last_answer = GOODBYE_MESSAGE
                await workflows_mistralai.send_assistant_message(last_answer)
                break

            # Fails closed: if the guardrail keeps erroring after retries,
            # block rather than silently let a possibly unsafe question
            # through.
            try:
                forbidden = await check_forbidden_topic(question)
            except Exception:  # noqa: BLE001 — deliberate fail-closed fallback
                forbidden = ForbiddenTopicCheck(
                    is_forbidden=True, matched_topic="error-fallback"
                )
            if forbidden.is_forbidden:
                last_answer = get_forbidden_answer(forbidden.matched_topic)
                await workflows_mistralai.send_assistant_message(last_answer)
                continue  # only this turn is blocked, the session stays open

            # Rewriting is an optimization, not a hard requirement: degrade
            # to searching with the raw question rather than failing the
            # turn.
            try:
                rewritten = await rewrite_query(question)
                if not rewritten.keywords.strip():
                    rewritten = RewriteResult(keywords=question)
            except Exception:  # noqa: BLE001 — deliberate graceful degradation
                rewritten = RewriteResult(keywords=question)

            context = await search_via_agent(
                rewritten.keywords, search_mcp_url, session=search_session
            )
            synonyms = await identify_synonyms(question, context)

            # generate_answer() streams the answer live to the chat itself
            # (RemoteSession(stream=True)), so on success there's nothing
            # left to send here.
            try:
                last_answer = await generate_answer(
                    question, context, synonyms, session=answer_session
                )
            except Exception:  # noqa: BLE001 — deliberate user-facing fallback
                last_answer = GENERATION_ERROR_FALLBACK
                await workflows_mistralai.send_assistant_message(last_answer)

        return workflows_mistralai.ChatAssistantWorkflowOutput(
            content=[workflows_mistralai.TextOutput(text=last_answer)]
        )
