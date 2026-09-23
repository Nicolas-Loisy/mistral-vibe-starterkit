from pydantic import BaseModel, Field


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
