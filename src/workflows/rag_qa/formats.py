from pydantic import BaseModel, Field


class ForbiddenTopic(BaseModel):
    """Static configuration for one forbidden topic (not LLM output)."""

    name: str = Field(
        description="Short topic name, matched against the LLM's `matched_topic` output."
    )
    explanation: str = Field(
        description="Sentence explaining what counts as this topic, used to build the moderation prompt."
    )
    response_message: str = Field(
        default="",
        description="Custom refusal message for this topic. Empty means: use the default refusal message.",
    )


class ForbiddenTopicCheck(BaseModel):
    is_forbidden: bool = Field(
        description="True if the question is about one of the forbidden topics listed in the prompt."
    )
    matched_topic: str | None = Field(
        default=None,
        description="The specific forbidden topic matched, or null if is_forbidden is False.",
    )


class RewriteResult(BaseModel):
    keywords: str = Field(
        description="Short search query keeping only the key search terms from the question."
    )
