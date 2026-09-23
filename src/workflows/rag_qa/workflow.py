"""Classic RAG pipeline: guardrail -> rewrite -> search -> synonyms -> answer."""

import mistralai.workflows as workflows
import mistralai.workflows.plugins.mistralai as workflows_mistralai

from .activities import (
    check_forbidden_topic,
    generate_answer,
    identify_synonyms,
    rewrite_query,
    search,
)
from .formats import ForbiddenTopicCheck, RewriteResult
from .static_prompts import (
    ASK_QUESTION_MESSAGE,
    GENERATION_ERROR_FALLBACK,
    get_forbidden_answer,
)


@workflows.workflow.define(
    name="rag-qa",
    workflow_display_name="RAG Q&A",
    workflow_description="Classic RAG pipeline: guardrail, rewrite, search, synonyms, answer.",
)
class RagQaWorkflow(workflows.InteractiveWorkflow):
    """Interactive so it can be published as a Vibe assistant.

    `question` is optional: when launched with a message already attached
    (e.g. the user types their question when starting the workflow in
    Vibe), that message fills this parameter directly and the chat
    round-trip below is skipped. Only ask if it comes in empty.
    """

    @workflows.workflow.entrypoint
    async def run(
        self, question: str = ""
    ) -> workflows_mistralai.ChatAssistantWorkflowOutput:
        if not question:
            await workflows_mistralai.send_assistant_message(ASK_QUESTION_MESSAGE)
            user_input = await self.wait_for_input(workflows_mistralai.ChatInput())
            question = user_input.message[0].text if user_input.message else ""

        # Step 1 — guardrail. Branching on `forbidden.is_forbidden` is
        # deterministic: it comes from a recorded activity result. The
        # try/except wraps the *await*, not the activity body, so the
        # platform's own retries (see activity decorator defaults) still run
        # first — this only catches the case where every retry failed.
        # Fails closed: if the check keeps erroring, block rather than
        # silently let a possibly unsafe question through.
        try:
            forbidden = await check_forbidden_topic(question)
        except Exception:  # noqa: BLE001 — deliberate fail-closed fallback
            forbidden = ForbiddenTopicCheck(
                is_forbidden=True, matched_topic="error-fallback"
            )
        if forbidden.is_forbidden:
            # The return value alone is never displayed in chat (see
            # notes-concepts.md) — send_assistant_message() is what the
            # user actually sees. The message itself always comes from
            # static config (topic-specific or default), never the LLM.
            forbidden_answer = get_forbidden_answer(forbidden.matched_topic)
            await workflows_mistralai.send_assistant_message(forbidden_answer)
            return workflows_mistralai.ChatAssistantWorkflowOutput(
                content=[workflows_mistralai.TextOutput(text=forbidden_answer)]
            )

        # Step 2 — reformulate the question into search keywords. Rewriting
        # is an optimization, not a hard requirement: degrade to searching
        # with the raw question rather than failing the whole pipeline.
        try:
            rewritten = await rewrite_query(question)
            if not rewritten.keywords.strip():
                rewritten = RewriteResult(keywords=question)
        except Exception:  # noqa: BLE001 — deliberate graceful degradation
            rewritten = RewriteResult(keywords=question)

        # Step 3 — retrieve context (mocked for now, see `search`).
        context = await search(rewritten.keywords)

        # Step 4 — pull in related vocabulary from the synonyms dictionary.
        synonyms = await identify_synonyms(question, context)

        # Step 5 — generate the final answer. No good fallback content is
        # possible here (that's the whole point of this step), so fall back
        # to a plain apology message instead of crashing the workflow.
        try:
            answer = await generate_answer(question, context, synonyms)
        except Exception:  # noqa: BLE001 — deliberate user-facing fallback
            answer = GENERATION_ERROR_FALLBACK

        await workflows_mistralai.send_assistant_message(answer)
        return workflows_mistralai.ChatAssistantWorkflowOutput(
            content=[workflows_mistralai.TextOutput(text=answer)]
        )
