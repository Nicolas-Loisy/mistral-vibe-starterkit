ASK_FIRST_QUESTION_MESSAGE = "Pose ta question, je vais chercher la réponse."
ASK_NEXT_QUESTION_MESSAGE = "Autre question ?"

CONVERSATION_ENDED_MESSAGE = (
    "On a atteint la limite de tours pour cette conversation. "
    "Relance le workflow pour continuer."
)

GENERATION_ERROR_FALLBACK = (
    "Désolé, je n'ai pas pu générer de réponse pour le moment. Réessaie plus tard."
)

ANSWER_WITH_HISTORY_SYSTEM_PROMPT = (
    "You are a helpful assistant having a multi-turn conversation. Answer the "
    "user's question using only the provided context, related terms, and the "
    "conversation history so far. If the answer is not in the context, say "
    "you don't know."
)
