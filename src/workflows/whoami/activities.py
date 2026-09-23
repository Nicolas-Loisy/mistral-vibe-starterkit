"""Diagnostic probes for the triggering user's identity.

Exploratory only, not meant to ship. Each probe is isolated with its own
try/except, so one failure doesn't stop the others — the workflow reports
every raw result or error back in the chat so we can see empirically what's
actually available in this environment, instead of guessing from docs.
"""
# ruff: noqa: BLE001  # each probe deliberately catches anything, to report it

import os

import mistralai.workflows as workflows


@workflows.activity()
async def probe_execution_id() -> str:
    try:
        return f"OK: {workflows.get_execution_id()}"
    except Exception as exc:
        return f"ERROR ({type(exc).__name__}): {exc}"


@workflows.activity()
async def probe_workflow_context() -> str:
    try:
        # Private/undocumented API, not part of the public SDK surface — imported
        # here (not at module level) so a sandbox/import-path change only breaks
        # this one probe. Never dump ctx.execution_token itself: it's a live
        # credential, only report whether one is present.
        from mistralai.workflows.core.temporal.context_handler_interceptor import (
            retrieve_context,
        )

        ctx = retrieve_context()
        if ctx is None:
            return "OK: no context (not running inside a workflow/activity?)"
        return (
            "OK: "
            f"namespace={ctx.namespace!r} execution_id={ctx.execution_id!r} "
            f"parent={ctx.parent_workflow_exec_id!r} root={ctx.root_workflow_exec_id!r} "
            f"on_behalf_of={ctx.on_behalf_of!r} schedule_id={ctx.schedule_id!r} "
            f"extensions_keys={list(ctx.extensions.keys())!r} "
            f"trusted_extensions_keys={list(ctx.trusted_extensions.keys())!r} "
            f"has_execution_token={ctx.execution_token is not None!r}"
        )
    except Exception as exc:
        return f"ERROR ({type(exc).__name__}): {exc}"


async def _try_users_me(*, use_executor_credentials: bool) -> str:
    try:
        from mistralai.client import models as mistral_models
        from mistralai.workflows.client import get_mistral_client

        client = get_mistral_client(use_executor_credentials=use_executor_credentials)
        # GET /v1/users/me expects an `x-api-key: dashboard_user_context_auth`
        # header (see mistralai/client/models/users_api_get_identityop.py) —
        # a different scheme than the bearer auth used elsewhere in the SDK.
        # Trying the plain API key here mostly to see what error comes back.
        security = mistral_models.UsersAPIGetIdentitySecurity(
            dashboard_user_context_auth=os.environ.get("MISTRAL_API_KEY", "")
        )
        identity = await client.beta.users.get_identity_async(security=security)
        return f"OK: {identity!r}"
    except Exception as exc:
        return f"ERROR ({type(exc).__name__}): {exc}"


@workflows.activity()
async def probe_users_me_as_worker() -> str:
    return await _try_users_me(use_executor_credentials=False)


@workflows.activity()
async def probe_users_me_as_executor() -> str:
    return await _try_users_me(use_executor_credentials=True)
