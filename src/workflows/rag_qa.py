"""Classic RAG pipeline: guardrail -> rewrite -> search -> synonyms -> answer.

Kept as a single flat module (not a subpackage like src/examples/*) because
the default worker's auto-discovery (entrypoints/worker.py) only scans
top-level modules directly under src/workflows/ and skips subpackages.
"""

import re
from datetime import timedelta
from pathlib import Path

import mistralai.workflows as workflows
import mistralai.workflows.plugins.mistralai as workflows_mistralai
from pydantic import BaseModel

SYNONYMS_PATH = Path(__file__).parent / "synonyms.txt"

# mistral-small-latest hit the free tier's rate limit on every call; the
# account's "1 req/s" cap appears to be enforced per-model, and this smaller
# model has separate (workable) headroom.
MODEL = "ministral-3b-2512"

FORBIDDEN_TOPICS = [
    "armes et explosifs",
    "fabrication de drogues",
    "activites illegales",
]

# Fixed, not LLM-generated: the refusal message must not be something a
# crafted question could influence via the model's own output.
DEFAULT_FORBIDDEN_ANSWER = (
    "Je ne peux pas repondre a cette question : le sujet n'est pas autorise."
)


class ForbiddenTopicCheck(BaseModel):
    is_forbidden: bool
    matched_topic: str | None = None


class RewriteResult(BaseModel):
    keywords: str


@workflows.activity()
async def check_forbidden_topic(question: str) -> ForbiddenTopicCheck:
    """Ask the LLM whether the question is about one of the forbidden topics."""
    topics = "\n".join(f"- {topic}" for topic in FORBIDDEN_TOPICS)
    request = workflows_mistralai.ChatCompletionRequest(
        model=MODEL,
        messages=[
            workflows_mistralai.SystemMessage(
                content=(
                    "You are a content moderation filter. Forbidden topics:\n"
                    f"{topics}\n\n"
                    "Decide whether the user question is about one of these topics."
                )
            ),
            workflows_mistralai.UserMessage(content=question),
        ],
    )
    return await workflows_mistralai.chat_parse_to_model(ForbiddenTopicCheck, request)


@workflows.activity()
async def rewrite_query(question: str) -> RewriteResult:
    """Reformulate the question into a short list of search keywords."""
    request = workflows_mistralai.ChatCompletionRequest(
        model=MODEL,
        messages=[
            workflows_mistralai.SystemMessage(
                content=(
                    "Rewrite the user question as a short search query: keep only "
                    "the key terms (nouns, names, technical words), drop stop words "
                    "and phrasing. Return the keywords only."
                )
            ),
            workflows_mistralai.UserMessage(content=question),
        ],
    )
    return await workflows_mistralai.chat_parse_to_model(RewriteResult, request)


@workflows.activity(
    retry_policy_max_attempts=3,
    start_to_close_timeout=timedelta(seconds=30),
)
async def search(keywords: str) -> str:
    """Query an external search/retrieval tool for context.

    MOCK: no real endpoint wired yet. Swap this body for an HTTP call (e.g.
    httpx.get(SEARCH_API_URL, params={"q": keywords})) once a real search
    tool is available — the signature (keywords in, context text out) and
    the retry policy above are already set up for that transition.
    """
    return (
        f"[mock context for keywords: {keywords!r}] Lorem ipsum dolor sit amet canin."
    )


@workflows.activity()
async def identify_synonyms(question: str, context: str) -> str:
    """Return every synonyms.txt line sharing a term with the question/context.

    File format: one synonym group per line, forms separated by ';'
    (e.g. "voiture;auto;automobile"). A line matches if any of its forms
    appears (case-insensitive substring) in the question or the context.
    """
    haystack = f"{question} {context}".lower()
    matched_lines: list[str] = []
    for raw_line in SYNONYMS_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        forms = [form.strip().lower() for form in line.split(";") if form.strip()]
        if any(
            # Match a whole word / token, not just an embedded substring.
            # (?<!\w) = previous char is not a word char, so we don't match
            # inside larger words (e.g. "car" in "scar"), and (?!\w) does the
            # same on the right. re.escape(form) keeps the synonym literal safe.
            re.search(rf"(?<!\w){re.escape(form)}(?!\w)", haystack)
            for form in forms
        ):
            matched_lines.append(line)
    return "\n".join(matched_lines)


@workflows.activity()
async def generate_answer(question: str, context: str, synonyms: str) -> str:
    """Produce the final answer from the retrieved context and synonyms list."""
    request = workflows_mistralai.ChatCompletionRequest(
        model=MODEL,
        messages=[
            workflows_mistralai.SystemMessage(
                content=(
                    "You are a helpful assistant. Answer the user's question using "
                    "only the provided context and related terms. If the answer is "
                    "not in the context, say you don't know."
                )
            ),
            workflows_mistralai.UserMessage(
                content=(
                    f"Context:\n{context}\n\n"
                    f"Related terms:\n{synonyms or '(none)'}\n\n"
                    f"Question: {question}"
                )
            ),
        ],
    )
    response = await workflows_mistralai.mistralai_chat_complete(request)
    if not response.choices or not response.choices[0].message:
        raise ValueError("Empty response from answer generation LLM call")
    content = response.choices[0].message.content
    # .content is typed as str | list[...chunk types...] to support multimodal
    # replies; a plain-text prompt like this one always yields a str.
    if not isinstance(content, str):
        raise TypeError(f"Expected plain text answer, got: {type(content).__name__}")
    return content


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
            await workflows_mistralai.send_assistant_message(
                "Pose ta question, je vais chercher la reponse."
            )
            user_input = await self.wait_for_input(workflows_mistralai.ChatInput())
            question = user_input.message[0].text if user_input.message else ""

        # Step 1 — guardrail. Branching on `forbidden.is_forbidden` is
        # deterministic: it comes from a recorded activity result.
        forbidden = await check_forbidden_topic(question)
        if forbidden.is_forbidden:
            # The return value alone is never displayed in chat (see
            # notes-concepts.md) — send_assistant_message() is what the
            # user actually sees.
            await workflows_mistralai.send_assistant_message(DEFAULT_FORBIDDEN_ANSWER)
            return workflows_mistralai.ChatAssistantWorkflowOutput(
                content=[workflows_mistralai.TextOutput(text=DEFAULT_FORBIDDEN_ANSWER)]
            )

        # Step 2 — reformulate the question into search keywords.
        rewritten = await rewrite_query(question)

        # Step 3 — retrieve context (mocked for now, see `search`).
        context = await search(rewritten.keywords)

        # Step 4 — pull in related vocabulary from the synonyms dictionary.
        synonyms = await identify_synonyms(question, context)

        # Step 5 — generate the final answer.
        answer = await generate_answer(question, context, synonyms)

        await workflows_mistralai.send_assistant_message(answer)
        return workflows_mistralai.ChatAssistantWorkflowOutput(
            content=[workflows_mistralai.TextOutput(text=answer)]
        )
