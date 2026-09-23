FORBIDDEN_TOPICS = [
    "armes et explosifs",
    "fabrication de drogues",
    "activités illégales",
]

# Fixed, not LLM-generated: the refusal message must not be something a
# crafted question could influence via the model's own output.
DEFAULT_FORBIDDEN_ANSWER = (
    "Je ne peux pas répondre à cette question : le sujet n'est pas autorisé."
)

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
