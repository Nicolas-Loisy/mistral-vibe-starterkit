"""Activities for three ways to resolve an OBO execution's triggering user email.

All are REAL attempts (unlike workflows.whoami's deliberately conservative
scaffold, which never sets on_behalf_of=True) — see workflow.py for why this
is isolated in its own package.

C) Decode the claims of the identity JWT from executor_identity_token()
   (NOT deprecated) directly — same technique
   ExecutorCredentialsHook._decode_jwt_exp uses for the `exp` claim, just
   reading the whole payload instead of one field. No documented claims
   schema exists for this token, so this probes and reports what's actually
   in there rather than assuming a claim name. Best case: an `email` claim
   is present and neither of the other two calls below is even needed.

B) Try that same JWT as the `x-api-key` value GET /v1/users/me expects
   (UsersAPIGetIdentitySecurity.dashboard_user_context_auth — the ONLY auth
   scheme that operation declares; no bearer alternative exists per
   mistralai/client/models/users_api_get_identityop.py). Likely to fail:
   that scheme looks shaped for the web dashboard's own session token, not a
   server-to-server OBO JWT — worth confirming empirically rather than
   assuming either way.

A) Resolve a user_id — preferably from a claim on the (non-deprecated) JWT
   from C; executor_identity() is used only as a last-resort fallback when
   no usable claim is found, since it's explicitly deprecated ("will be
   removed in a future release") — then call the Admin API's
   GET /v1/admin/users/{user_id} (confirmed via
   docs.mistral.ai/admin/admin-api/manage-users) with a separate Admin API
   key read from the worker's environment. The Admin API is Enterprise-only
   and the key must be created manually via the Admin Panel's Enterprise
   section — this activity cannot provision either.
"""

import base64
import json
import os

import mistralai.workflows as workflows

ADMIN_API_KEY_ENV = "MISTRAL_ADMIN_API_KEY"

# Common OIDC/JWT claim names that might carry a user identifier — checked
# in order, first match wins. Unverified for this specific token (see C
# above), hence checking several plausible names and falling back cleanly
# rather than asserting one.
_USER_ID_CLAIM_NAMES = ("user_id", "sub", "uid")


def _decode_jwt_claims(token: str) -> dict:
    """Decode a JWT's payload (middle segment) without verifying its signature.

    Diagnostic use only — same technique as
    ExecutorCredentialsHook._decode_jwt_exp, generalized to the whole
    payload instead of just `exp`. Never pass the raw token itself back to
    a caller/chat: unlike the decoded claims, it's a live bearer credential.
    """
    payload_segment = token.split(".")[1]
    padded = payload_segment + "=" * (-len(payload_segment) % 4)
    return json.loads(base64.urlsafe_b64decode(padded))


async def _execution_token() -> str:
    # Private/undocumented API, not part of the public SDK surface (same
    # caveat as workflows.whoami's probe_workflow_context) — imported here,
    # not at module level, so a sandbox/import-path change only breaks this.
    # Never log ctx.execution_token itself: it's a live credential.
    from mistralai.workflows.core.temporal.context_handler_interceptor import (
        retrieve_context,
    )

    ctx = retrieve_context()
    if ctx is None or not ctx.execution_token:
        raise ValueError(
            "No execution_token in context: not running inside a real "
            "OBO-triggered execution (needs on_behalf_of=True on "
            "@workflow.define AND a real signed-in triggering user, not "
            "`make execute` / a bare API-key script)."
        )
    if not ctx.on_behalf_of:
        raise ValueError(
            "context.on_behalf_of is falsy even though execution_token is "
            "present — unexpected combination."
        )
    return ctx.execution_token


async def _identity_token() -> str:
    """Exchange execution_token for an identity JWT via executor_identity_token()

    Not deprecated, unlike executor_identity() — see module docstring.
    """
    from mistralai.workflows.core.worker_client import get_worker_client

    execution_token = await _execution_token()
    worker_client = get_worker_client()
    token_response = await worker_client.executor_identity_token_async(
        execution_token=execution_token
    )
    return token_response.token


@workflows.activity()
async def try_email_via_token_claims() -> str:
    """Design C — see module docstring. Never raises: reports the outcome."""
    try:
        claims = _decode_jwt_claims(await _identity_token())
    except Exception as exc:  # noqa: BLE001 — reported as a diagnostic, not raised
        return f"ERROR ({type(exc).__name__}): {exc}"

    if "email" in claims:
        return f"OK: email={claims['email']!r}"
    return f"NO email claim. Claim keys found: {sorted(claims.keys())!r}"


@workflows.activity()
async def try_email_via_users_me() -> str:
    """Design B — see module docstring. Never raises: reports the outcome."""
    try:
        from mistralai.client import models as mistralai_models
        from mistralai.workflows.client import get_mistral_client

        token = await _identity_token()
        client = get_mistral_client()
        security = mistralai_models.UsersAPIGetIdentitySecurity(
            dashboard_user_context_auth=token
        )
        identity = await client.beta.users.get_identity_async(security=security)
        return f"OK: email={identity.email!r}"
    except Exception as exc:  # noqa: BLE001 — reported as a diagnostic, not raised
        return f"ERROR ({type(exc).__name__}): {exc}"


async def _user_id_from_token_claims() -> str | None:
    """Look for a user-id-shaped claim on the (non-deprecated) identity JWT.

    Returns None rather than raising when nothing matches, so the caller can
    fall back to the deprecated executor_identity() call cleanly.
    """
    claims = _decode_jwt_claims(await _identity_token())
    for claim_name in _USER_ID_CLAIM_NAMES:
        if claim_name in claims:
            return str(claims[claim_name])
    return None


@workflows.activity()
async def try_email_via_admin_api() -> str:
    """Design A — see module docstring. Never raises: reports the outcome."""
    try:
        user_id = await _user_id_from_token_claims()
        if user_id is None:
            # Last-resort fallback: the non-deprecated token carried none of
            # _USER_ID_CLAIM_NAMES, so fall back to the deprecated call
            # rather than give up — see module docstring.
            from mistralai.workflows.core.worker_client import get_worker_client

            execution_token = await _execution_token()
            worker_client = get_worker_client()
            identity = await worker_client.executor_identity_async(
                execution_token=execution_token
            )
            user_id = identity.user_id
        if not user_id:
            return "ERROR: no user_id found (anonymous/service execution?)"
    except Exception as exc:  # noqa: BLE001
        return f"ERROR resolving user_id ({type(exc).__name__}): {exc}"

    admin_key = os.environ.get(ADMIN_API_KEY_ENV)
    if not admin_key:
        return (
            f"ERROR: {ADMIN_API_KEY_ENV} is not set in the worker's "
            "environment (.env) — create an Admin API key via the Admin "
            "Panel's Enterprise section (Enterprise plan required) and set "
            f"it as {ADMIN_API_KEY_ENV} in .env."
        )

    base_url = os.environ.get("SERVER_URL", "https://api.mistral.ai").rstrip("/")

    # httpx imported here, not at module level — same reason as rag_qa's
    # search() activity, moot in a real @activity() but kept consistent.
    import httpx

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(
            f"{base_url}/v1/admin/users/{user_id}",
            headers={"x-api-key": admin_key},
        )

    if response.status_code in (401, 403):
        return (
            f"ERROR {response.status_code}: {ADMIN_API_KEY_ENV} was rejected "
            "by the Admin API — check it's a real Admin API key (Enterprise "
            "Panel), not a regular MISTRAL_API_KEY."
        )
    if response.is_error:
        return f"ERROR {response.status_code}: {response.text}"

    email = response.json().get("email")
    return f"OK: email={email!r} (user_id={user_id!r})"
