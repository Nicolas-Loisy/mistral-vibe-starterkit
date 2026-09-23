"""Diagnostic workflow: probe every avenue found for the triggering user's identity.

Deliberately does NOT declare on_behalf_of=True on the workflow: per
mistralai/workflows/hooks/executor_credentials_hook.py, use_executor_credentials
only needs on_behalf_of=True at the *request* level (raises a clean, catchable
WorkflowError otherwise) — but on_behalf_of=True on @workflow.define also
triggers a platform *registration* check ("restricted to Mistral-internal
organizations" per connectors.mdx) with undocumented failure behavior. Since
this worker also registers every other workflow, a registration failure here
risks breaking `make start-worker` for all of them. This file tests the safe,
catchable failure mode only.
"""

import mistralai.workflows as workflows
import mistralai.workflows.plugins.mistralai as workflows_mistralai

from .activities import (
    probe_execution_id,
    probe_users_me_as_executor,
    probe_users_me_as_worker,
    probe_workflow_context,
)


@workflows.workflow.define(
    name="whoami",
    workflow_display_name="Whoami (diagnostic)",
    workflow_description="Exploratory: dumps raw results from every user-identity probe we've found.",
)
class WhoAmIWorkflow(workflows.InteractiveWorkflow):
    """Dumps raw probe results to chat. Exploratory tool — not for production."""

    @workflows.workflow.entrypoint
    async def run(self) -> workflows_mistralai.ChatAssistantWorkflowOutput:
        results = {
            "execution_id": await probe_execution_id(),
            "workflow_context (private API)": await probe_workflow_context(),
            "users.me as worker": await probe_users_me_as_worker(),
            "users.me as executor (needs on_behalf_of)": await probe_users_me_as_executor(),
        }
        report = "\n\n".join(
            f"### {label}\n{value}" for label, value in results.items()
        )

        await workflows_mistralai.send_assistant_message(report)
        return workflows_mistralai.ChatAssistantWorkflowOutput(
            content=[workflows_mistralai.TextOutput(text=report)]
        )
