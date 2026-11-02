import re
from datetime import timedelta
from pathlib import Path

import mistralai.workflows as workflows
import mistralai.workflows.plugins.mistralai as workflows_mistralai

from .formats import ForbiddenTopicCheck, RewriteResult
from .static_prompts import (
    ANSWER_SYSTEM_PROMPT,
    FORBIDDEN_TOPICS,
    MODERATION_SYSTEM_PROMPT_TEMPLATE,
    REWRITE_SYSTEM_PROMPT,
)

SYNONYMS_PATH = Path(__file__).parent / "synonyms.txt"

# mistral-small-latest hit the free tier's rate limit on every call; the
# account's "1 req/s" cap appears to be enforced per-model, and this smaller
# model has separate (workable) headroom.
MODEL = "ministral-3b-2512"

# Remote agent reused across runs instead of recreated each time — same
# rationale as rag_qa_agent/activities.py's SEARCH_AGENT_ID (see that file
# and notes-concepts.md): without a fixed id, every Agent(...) call below
# creates a NEW remote agent, and conversation isolation between concurrent
# users is unaffected since it happens at the conversation level, not here.
ANSWER_AGENT_ID = "ag_01a11687e3047512a0d5c5ce97d70bd2"


@workflows.activity()
async def check_forbidden_topic(question: str) -> ForbiddenTopicCheck:
    """Ask the LLM whether the question is about one of the forbidden topics."""
    topics = "\n".join(
        f"- {topic.name}: {topic.explanation}" for topic in FORBIDDEN_TOPICS
    )
    request = workflows_mistralai.ChatCompletionRequest(
        model=MODEL,
        messages=[
            workflows_mistralai.SystemMessage(
                content=MODERATION_SYSTEM_PROMPT_TEMPLATE.format(topics=topics)
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
            workflows_mistralai.SystemMessage(content=REWRITE_SYSTEM_PROMPT),
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

    TEST: calls httpbin.org (a public echo service, no auth/config needed)
    to validate that a real outbound HTTP request works correctly from
    inside an activity — network I/O belongs here, never in the workflow
    body. Swap the URL/response parsing for the real search tool once
    available; the signature (keywords in, context text out) and the retry
    policy above are already set up for that transition.
    """
    # return (
    #     f"[mock context for keywords: {keywords!r}] Lorem ipsum dolor sit amet canin."
    # )

    # Imported here, not at module level: httpx subclasses urllib.request.Request
    # at import time (cookie compat), which the workflow sandbox restricts when
    # this module is pulled in transitively via workflow.py's `from .activities
    # import ...`. A function-local import only runs when the activity actually
    # executes (outside the sandbox), so it never triggers that check.
    import httpx

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get("https://httpbin.org/get", params={"q": keywords})
        response.raise_for_status()
        data = response.json()
    return f"[real HTTP call via httpbin.org] origin={data.get('origin')} echoed_query={data.get('args')}"


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


async def generate_answer(
    question: str,
    context: str,
    synonyms: str,
    session: workflows_mistralai.RemoteSession | None = None,
) -> str:
    """Produce the final answer, streamed live to the chat as tokens arrive.

    Plain function, not @workflows.activity(): called directly from the
    workflow body, same as rag_qa_agent's search_via_agent — Runner.run()
    already schedules its own durable calls internally. Using
    RemoteSession(stream=True) makes Vibe display tokens live with no extra
    code (see assist-workflows guide, "Streaming Agent Responses").

    Pass a `session` owned and reused by the caller (e.g. held for the
    lifetime of a multi-turn chat workflow) to give the answer agent memory
    of previous questions/answers — same reused-session mechanism as
    rag_qa_agent's search_via_agent. Omit it (default) for one-shot usage.
    """
    # mistralai.client.models transitively imports httpx, which subclasses
    # urllib.request.Request at import time. Deferring the import to inside
    # the function (rather than module level) isn't enough on its own:
    # generate_answer runs directly in the workflow body (see this
    # function's docstring), so this import still executes inside the
    # determinism sandbox at call time — explicit imports_passed_through()
    # is required, same defensive pattern the SDK itself uses internally for
    # deferred imports of its own modules (see
    # mistralai.workflows.core.temporal.context_handler_interceptor).
    with workflows.workflow.unsafe.imports_passed_through():
        from mistralai.client import models as mistralai_models

    agent = workflows_mistralai.Agent(
        id=ANSWER_AGENT_ID,
        model=MODEL,
        name="answer-agent",
        description="Answers the user's question using the retrieved context.",
        instructions=ANSWER_SYSTEM_PROMPT,
    )
    prompt = (
        f"Context:\n{context}\n\n"
        f"Related terms:\n{synonyms or '(none)'}\n\n"
        f"Question: {question}"
    )
    outputs = await workflows_mistralai.Runner.run(
        agent=agent,
        inputs=prompt,
        session=session or workflows_mistralai.RemoteSession(stream=True),
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
    answer = "\n".join(texts)
    if not answer.strip():
        raise ValueError("Empty answer from answer generation agent")
    return answer
