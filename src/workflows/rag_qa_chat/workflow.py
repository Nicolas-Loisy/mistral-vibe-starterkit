"""RAG pipeline variant: the workflow launches once and handles several
questions in a row, remembering prior turns so the final answer can refer
back to earlier context (e.g. "and what about last year?").

Reuses check_forbidden_topic / rewrite_query / search / identify_synonyms
from workflows.rag_qa.activities unchanged — only the answer step is
history-aware (see activities.py in this package). Guardrail and rewrite
stay scoped to the current question only, per the stated requirement that
just the answer needs the history.

Entrypoint takes a bare `question: str = ""`, same as RagQaWorkflow — NOT a
BaseModel. Confirmed by live-testing in Vibe: any BaseModel-typed entrypoint
(even a minimal, single-field one, even with a tagged union to keep the
schema clean — see git history of this file) renders as a raw JSON form in
Vibe's launch UI, while a bare scalar parameter renders as a clean text
field. Since continue_as_new() requires a BaseModel (verified against the
installed SDK), that mechanism doesn't fit this constraint: history is kept
as in-memory state for the lifetime of a single execution instead, bounded
by MAX_TURNS as a pragmatic safety net against the ~51,200 event execution
history cap (see limitations.mdx) — never realistically reached by an actual
conversation at this scale.
"""

import mistralai.workflows as workflows
import mistralai.workflows.plugins.mistralai as workflows_mistralai

from workflows.rag_qa.activities import (
    check_forbidden_topic,
    identify_synonyms,
    rewrite_query,
    search,
)
from workflows.rag_qa.formats import ForbiddenTopicCheck, RewriteResult
from workflows.rag_qa.static_prompts import get_forbidden_answer

from .activities import generate_answer_with_history
from .formats import QaTurn
from .static_prompts import (
    ASK_FIRST_QUESTION_MESSAGE,
    ASK_NEXT_QUESTION_MESSAGE,
    CONVERSATION_ENDED_MESSAGE,
    GENERATION_ERROR_FALLBACK,
)

MAX_TURNS = 50


@workflows.workflow.define(
    name="rag-qa-chat",
    workflow_display_name="RAG Q&A (Conversation)",
    workflow_description="Same as RAG Q&A, but keeps running across several questions, with history-aware answers.",
)
class RagQaChatWorkflow(workflows.InteractiveWorkflow):
    """One execution, many turns: asks a question, answers, asks again, ...

    `question` is optional, same convention as RagQaWorkflow: fills the
    first turn directly if the launch message already carried it.
    """

    @workflows.workflow.entrypoint
    async def run(
        self, question: str = ""
    ) -> workflows_mistralai.ChatAssistantWorkflowOutput:
        history: list[QaTurn] = []

        for turn in range(MAX_TURNS):
            if not question:
                prompt_message = (
                    ASK_FIRST_QUESTION_MESSAGE
                    if turn == 0
                    else ASK_NEXT_QUESTION_MESSAGE
                )
                await workflows_mistralai.send_assistant_message(prompt_message)
                user_input = await self.wait_for_input(workflows_mistralai.ChatInput())
                question = user_input.message[0].text if user_input.message else ""

            # Guardrail and rewrite operate on the current question only —
            # only the final answer needs the conversation history.
            try:
                forbidden = await check_forbidden_topic(question)
            except Exception:  # noqa: BLE001 — deliberate fail-closed fallback
                forbidden = ForbiddenTopicCheck(
                    is_forbidden=True, matched_topic="error-fallback"
                )

            if forbidden.is_forbidden:
                forbidden_answer = get_forbidden_answer(forbidden.matched_topic)
                await workflows_mistralai.send_assistant_message(forbidden_answer)
                history.append(QaTurn(question=question, answer=forbidden_answer))
            else:
                try:
                    rewritten = await rewrite_query(question)
                    if not rewritten.keywords.strip():
                        rewritten = RewriteResult(keywords=question)
                except Exception:  # noqa: BLE001 — deliberate graceful degradation
                    rewritten = RewriteResult(keywords=question)

                context = await search(rewritten.keywords)
                synonyms = await identify_synonyms(question, context)

                # generate_answer_with_history() streams the answer live to
                # the chat itself, so on success there's nothing left to send.
                try:
                    answer = await generate_answer_with_history(
                        question, context, synonyms, history
                    )
                except Exception:  # noqa: BLE001 — deliberate user-facing fallback
                    answer = GENERATION_ERROR_FALLBACK
                    await workflows_mistralai.send_assistant_message(answer)

                history.append(QaTurn(question=question, answer=answer))

            question = ""

        await workflows_mistralai.send_assistant_message(CONVERSATION_ENDED_MESSAGE)
        return workflows_mistralai.ChatAssistantWorkflowOutput(
            content=[
                workflows_mistralai.TextOutput(
                    text=history[-1].answer if history else ""
                )
            ]
        )
