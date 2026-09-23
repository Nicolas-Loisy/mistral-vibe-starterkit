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
            workflows_mistralai.SystemMessage(content=ANSWER_SYSTEM_PROMPT),
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
    if not content.strip():
        raise ValueError("Empty answer from answer generation LLM call")
    return content
