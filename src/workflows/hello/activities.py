import mistralai.workflows as workflows

from .static_prompts import GREETING_TEMPLATE


@workflows.activity()
async def greet(name: str) -> str:
    """A simple activity that returns a greeting."""
    return GREETING_TEMPLATE.format(name=name)
