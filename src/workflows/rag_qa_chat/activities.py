"""Answer step for rag-qa-chat: same agent-based generation as rag_qa's
generate_answer, but the prompt also includes prior Q&A turns.

Plain function, not @workflows.activity(): called directly from the workflow
body, same as rag_qa's generate_answer — Runner.run() already schedules its
own durable calls internally.
"""

import mistralai.workflows.plugins.mistralai as workflows_mistralai

from workflows.rag_qa.activities import MODEL

from .formats import QaTurn
from .static_prompts import ANSWER_WITH_HISTORY_SYSTEM_PROMPT


async def generate_answer_with_history(
    question: str, context: str, synonyms: str, history: list[QaTurn]
) -> str:
    """Produce the final answer, aware of prior turns, streamed live to the chat."""
    agent = workflows_mistralai.Agent(
        model=MODEL,
        name="answer-agent",
        description="Answers the user's question using the retrieved context and conversation history.",
        instructions=ANSWER_WITH_HISTORY_SYSTEM_PROMPT,
    )
    history_block = (
        "\n".join(f"Q: {turn.question}\nA: {turn.answer}" for turn in history)
        or "(none)"
    )
    prompt = (
        f"Conversation history:\n{history_block}\n\n"
        f"Context:\n{context}\n\n"
        f"Related terms:\n{synonyms or '(none)'}\n\n"
        f"Question: {question}"
    )
    outputs = await workflows_mistralai.Runner.run(
        agent=agent,
        inputs=prompt,
        session=workflows_mistralai.RemoteSession(stream=True),
    )
    texts: list[str] = []
    # A single reply can span several TextChunk entries; keep only the text ones and join them.
    for output in outputs:
        if isinstance(output, workflows_mistralai.TextChunk):
            texts.append(output.text)
    answer = "\n".join(texts)
    if not answer.strip():
        raise ValueError("Empty answer from answer generation agent")
    return answer
