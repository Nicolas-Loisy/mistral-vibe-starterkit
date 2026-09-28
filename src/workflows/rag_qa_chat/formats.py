from mistralai.workflows.plugins.mistralai import input_tag
from pydantic import BaseModel, ConfigDict, Field


class QaTurn(BaseModel):
    """One past question/answer pair, fed back into later prompts as history."""

    question: str
    answer: str = Field(description="The answer that was given for this question.")


@input_tag("question")
class RagQaChatInput(BaseModel):
    """Clean launch shape: just the question, nothing else.

    This is the variant a human (or Vibe) sees and fills in when starting a
    fresh conversation. `extra="forbid"` means a payload carrying `history`
    (see RagQaChatResumeState) can never accidentally match this one instead.
    """

    model_config = ConfigDict(extra="forbid")
    question: str = ""


class RagQaChatResumeState(BaseModel):
    """Internal continue_as_new carry-forward state — never meant to be
    filled in by hand. continue_as_new() requires a single BaseModel (see
    workflow.py); bundling question+history here is what makes that
    possible without polluting the public launch schema above.
    """

    model_config = ConfigDict(extra="forbid")
    question: str = ""
    history: list[QaTurn] = Field(default_factory=list)
