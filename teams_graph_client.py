"""
MS Teams group-chat ingestion via the Microsoft Graph API.

PHASE 2 — deferred. Stub only so the rest of the Requirement
Management dimension can import without breaking. Uncomment + fill
in the real implementation once the Azure AD app is registered.

Setup required before Phase 2 can ship:

  1. Register an Azure AD application (Azure portal → App registrations
     → New registration). Note the tenant ID, client ID.
  2. Grant API permissions on Microsoft Graph:
        - Chat.Read.All      (application permission) for unattended
                             polling across all chats, OR
        - Chat.Read          (delegated permission) for a user-bound
                             token via device-code flow.
     Application permissions require an AAD admin to grant consent.
  3. Create a client secret (if using application permissions) or
     complete the device-code flow on the VM that will poll.
  4. Add to this project's .env:
        GRAPH_TENANT_ID=...
        GRAPH_CLIENT_ID=...
        GRAPH_CLIENT_SECRET=...      # app permissions path
        GRAPH_CHAT_IDS=chat-id-1,... # specific chats to poll; or
        GRAPH_USER_ID=...            # to enumerate the user's chats
  5. pip install msal  (added to requirements.txt when this ships)

When implemented, poll_chat_messages() will:
  - Acquire a token via MSAL (client-credentials or device-code).
  - For each chat ID in GRAPH_CHAT_IDS, fetch new messages since the
    checkpoint timestamp stored in data/requirements/state.json.
  - Write each message as a .txt file under
    data/requirements/inbox/chat/{iso_ts}-{chat_id_short}.txt
    with the standard 4-line header preface.
  - Update the checkpoint on success.
"""
from __future__ import annotations


class TeamsGraphNotConfigured(RuntimeError):
    """Raised when poll_chat_messages is called before Phase 2 setup."""


def poll_chat_messages(dry_run: bool = False) -> dict:
    """Phase 2 entry point. Currently raises TeamsGraphNotConfigured.
    See the module docstring for the setup steps required to
    implement this."""
    raise TeamsGraphNotConfigured(
        "Teams group-chat ingestion is a Phase 2 feature. Complete the "
        "Azure AD app setup in the module docstring, then replace this "
        "stub with the real MSAL + Graph polling loop."
    )
