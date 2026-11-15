"""Diagnostic workflow: given a real OBO-triggered execution, try every way
discussed to resolve the triggering user's email. Companion to
workflows.whoami, but — unlike that file — actually declares
on_behalf_of=True, since context.execution_token is never populated
without it. See activities.py for what each probe does and why it might
fail.

RISK: on_behalf_of=True triggers a platform *registration* check per
.agents/skills/workflows/references/guides/connectors.mdx ("restricted to
Mistral-internal organizations unless ON_BEHALF_WORKFLOWS_ENABLED is set"),
with undocumented failure behavior. Kept in its own package, separate from
every other workflow, so that if registering this one breaks
`make start-worker`, deleting this single directory is enough to recover —
no other workflow is touched by this file.

Must be triggered by a real signed-in user (Studio console or Vibe), not
`make execute` or a bare API-key script: on_behalf_of requires "a
triggering user" per the same doc, and a CLI/script trigger carries no user
session — it would be rejected before ever reaching these probes.
"""

import mistralai.workflows as workflows
import mistralai.workflows.plugins.mistralai as workflows_mistralai

from .activities import (
    try_email_via_admin_api,
    try_email_via_token_claims,
    try_email_via_users_me,
)


@workflows.workflow.define(
    name="executor-email",
    workflow_display_name="Executor Email (diagnostic)",
    workflow_description=(
        "Tries to resolve the triggering user's email via OBO. Must be run "
        "as a real signed-in user (Studio/Vibe), not via CLI."
    ),
    on_behalf_of=True,
)
class ExecutorEmailWorkflow(workflows.InteractiveWorkflow):
    """Dumps raw probe results to chat. Exploratory tool — not for production."""

    @workflows.workflow.entrypoint
    async def run(self) -> workflows_mistralai.ChatAssistantWorkflowOutput:
        results = {
            "C: identity JWT claims (decoded, no API call)": await try_email_via_token_claims(),
            "B: GET /v1/users/me, OBO JWT as x-api-key": await try_email_via_users_me(),
            "A: GET /v1/admin/users/{user_id}, MISTRAL_ADMIN_API_KEY": await try_email_via_admin_api(),
        }
        report = "\n\n".join(
            f"### {label}\n{value}" for label, value in results.items()
        )

        await workflows_mistralai.send_assistant_message(report)
        return workflows_mistralai.ChatAssistantWorkflowOutput(
            content=[workflows_mistralai.TextOutput(text=report)]
        )
