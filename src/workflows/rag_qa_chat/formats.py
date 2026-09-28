from pydantic import BaseModel, Field


class QaTurn(BaseModel):
    """One past question/answer pair, fed back into later prompts as history."""

    question: str
    answer: str = Field(description="The answer that was given for this question.")
