"""RAG pipeline variant: the workflow launches once and handles several
questions in a row, remembering prior turns so the final answer can refer
back to earlier context (e.g. "and what about last year?").

Reuses check_forbidden_topic / rewrite_query / search / identify_synonyms
from workflows.rag_qa.activities unchanged — only the answer step is
history-aware (see activities.py in this package). Guardrail and rewrite
stay scoped to the current question only, per the stated requirement that
just the answer needs the history.

Uses continue_as_new (workflows.mdx, "Continue-As-New") rather than a fixed
turn limit: execution history is capped at ~51,200 events, so a workflow
meant to loop indefinitely should periodically reset its history instead of
being artificially bounded. continue_as_new's real signature (verified
against the installed SDK, not the docs) takes a single BaseModel, not the
dict shown in workflows.mdx's example.

The entrypoint takes a *union* of two models (RagQaChatInput |
RagQaChatResumeState) rather than one model bundling question+history:
a single model exposing `history` would show up as a fillable field in
Vibe's launch form, which makes no sense for a fresh conversation. Per
core_concepts/workflows and assist-workflows.mdx's "Tagging Input Variants",
a tagged union lets the public launch shape stay clean (just `question`)
while continue_as_new still gets to carry richer state internally.
"""

from datetime import timedelta

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
from .formats import QaTurn, RagQaChatInput, RagQaChatResumeState
from .static_prompts import (
    ASK_FIRST_QUESTION_MESSAGE,
    ASK_NEXT_QUESTION_MESSAGE,
    GENERATION_ERROR_FALLBACK,
)

_DEFAULT_INPUT = RagQaChatInput()


@workflows.workflow.define(
    name="rag-qa-chat",
    workflow_display_name="RAG Q&A (Conversation)",
    workflow_description="Same as RAG Q&A, but keeps running across several questions, with history-aware answers.",
    # Workflows default to a 1-hour execution timeout (see cargo_release
    # example); a chat session that goes quiet between questions for longer
    # than that would otherwise be killed even though continue_as_new keeps
    # resetting its event history. A month comfortably covers any real
    # conversation without leaving the timeout unbounded.
    execution_timeout=timedelta(days=30),
)
class RagQaChatWorkflow(workflows.InteractiveWorkflow):
    """One execution, many turns: asks a question, answers, asks again, ...

    `params` is `RagQaChatInput` (just a question, the normal launch shape)
    on a fresh start, or `RagQaChatResumeState` (question + history) when
    the SDK re-invokes this via continue_as_new — see module docstring.
    """

    @workflows.workflow.entrypoint
    async def run(
        self, params: RagQaChatInput | RagQaChatResumeState = _DEFAULT_INPUT
    ) -> workflows_mistralai.ChatAssistantWorkflowOutput:
        question = params.question
        history = (
            list(params.history) if isinstance(params, RagQaChatResumeState) else []
        )

        while True:
            if not question:
                prompt_message = (
                    ASK_FIRST_QUESTION_MESSAGE
                    if not history
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

            # Reset event history once it grows large, carrying the
            # conversation history forward into a fresh run — see module
            # docstring. Ends this run immediately; nothing after this call
            # in the current run executes once it triggers.
            if workflows.workflow.should_continue_as_new():
                workflows.workflow.continue_as_new(
                    RagQaChatResumeState(question="", history=history)
                )
