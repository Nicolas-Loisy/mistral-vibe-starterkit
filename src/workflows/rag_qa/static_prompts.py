from .formats import ForbiddenTopic

# Fixed, not LLM-generated: the refusal message must not be something a
# crafted question could influence via the model's own output.
DEFAULT_FORBIDDEN_ANSWER = (
    "Je ne peux pas répondre à cette question : le sujet n'est pas autorisé."
)

FORBIDDEN_TOPICS: list[ForbiddenTopic] = [
    ForbiddenTopic(
        name="armes et explosifs",
        explanation="Questions about weapons, explosives, or how to make or obtain them.",
    ),
    ForbiddenTopic(
        name="fabrication de drogues",
        explanation="Questions about manufacturing or synthesizing illegal drugs.",
    ),
    ForbiddenTopic(
        name="activités illégales",
        explanation="Questions about committing illegal activities in general.",
    ),
]


def get_forbidden_answer(matched_topic: str | None) -> str:
    """Return the topic-specific refusal message, or the default if none/empty.

    Looks up `matched_topic` (the LLM's guess at *which* topic matched) in
    the fixed FORBIDDEN_TOPICS list — the response text itself always comes
    from this static config, never from the LLM, for the same reason as
    DEFAULT_FORBIDDEN_ANSWER above.
    """
    for topic in FORBIDDEN_TOPICS:
        if topic.name == matched_topic and topic.response_message:
            return topic.response_message
    return DEFAULT_FORBIDDEN_ANSWER


ASK_QUESTION_MESSAGE = "Pose ta question, je vais chercher la réponse."

GENERATION_ERROR_FALLBACK = (
    "Désolé, je n'ai pas pu générer de réponse pour le moment. Réessaie plus tard."
)

# {topics} is filled in at call time from FORBIDDEN_TOPICS.
MODERATION_SYSTEM_PROMPT_TEMPLATE = (
    "You are a content moderation filter. Forbidden topics:\n"
    "{topics}\n\n"
    "Decide whether the user question is about one of these topics."
)

REWRITE_SYSTEM_PROMPT = (
    "Rewrite the user question as a short search query: keep only "
    "the key terms (nouns, names, technical words), drop stop words "
    "and phrasing. Return the keywords only."
)

ANSWER_SYSTEM_PROMPT = (
    "You are a helpful assistant. Answer the user's question using "
    "only the provided context and related terms. If the answer is "
    "not in the context, say you don't know."
)
