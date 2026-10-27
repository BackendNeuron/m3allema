"""Gmail MCP server: search, read, draft, send and archive email.

Risk levels follow from the annotations: reading runs on its own, drafting and
archiving are ``write`` (reversible, nobody else sees them), sending is
``external`` and always needs the owner's approval under the default policy.
Email content is untrusted: the system prompt tells the model never to follow
instructions found inside it.
"""

from __future__ import annotations

import asyncio

from mcp.server.mcpserver import MCPServer

from m3allema.integrations.google.gateways import GmailGateway, OutgoingEmail
from m3allema.tools.servers._annotations import LOCAL_WRITE, OUTWARD, READ_ONLY

MAX_RESULTS = 50
MAX_BODY_CHARS = 15_000


def create_gmail_server(gateway: GmailGateway) -> MCPServer:
    """Build a Gmail server on top of ``gateway``."""
    server = MCPServer(
        "gmail",
        instructions="The owner's Gmail. Search with Gmail syntax (from:, subject:, "
        "is:unread, newer_than:7d, has:attachment). Prefer drafts; sending needs approval.",
    )

    @server.tool(annotations=READ_ONLY)
    async def search_emails(query: str, limit: int = 20) -> str:
        """Search emails with Gmail syntax, newest first. Returns ids to use with read_email."""
        results = await asyncio.to_thread(gateway.search, query, max(1, min(limit, MAX_RESULTS)))
        if not results:
            return f"No emails match {query!r}."
        return "\n".join(
            f"[{e.id}] {e.date} | {e.sender} | {e.subject} | {e.snippet}" for e in results
        )

    @server.tool(annotations=READ_ONLY)
    async def read_email(email_id: str) -> str:
        """Read one email in full."""
        email = await asyncio.to_thread(gateway.get, email_id)
        body = email.body
        if len(body) > MAX_BODY_CHARS:
            body = f"{body[:MAX_BODY_CHARS]}\n[body truncated]"
        return (
            f"From: {email.sender}\nTo: {email.to}\nDate: {email.date}\n"
            f"Subject: {email.subject}\nThread: {email.thread_id}\n\n{body}"
        )

    @server.tool(annotations=LOCAL_WRITE)
    async def create_draft(
        to: str, subject: str, body: str, cc: str = "", reply_to_email_id: str | None = None
    ) -> str:
        """Save an email as a draft in Gmail for the owner to review. Nothing is sent.

        Set reply_to_email_id to draft a reply in the same thread.
        """
        draft_id = await asyncio.to_thread(
            gateway.create_draft, OutgoingEmail(to, subject, body, cc, reply_to_email_id)
        )
        return f"Draft saved (id {draft_id}) to {to}: {subject}"

    @server.tool(annotations=OUTWARD)
    async def send_email(
        to: str, subject: str, body: str, cc: str = "", reply_to_email_id: str | None = None
    ) -> str:
        """Send an email now. Set reply_to_email_id to reply in the same thread."""
        message_id = await asyncio.to_thread(
            gateway.send, OutgoingEmail(to, subject, body, cc, reply_to_email_id)
        )
        return f"Sent (id {message_id}) to {to}: {subject}"

    @server.tool(annotations=LOCAL_WRITE)
    async def archive_email(email_id: str) -> str:
        """Archive an email: it leaves the inbox but stays searchable in All Mail."""
        await asyncio.to_thread(gateway.archive, email_id)
        return f"Archived {email_id}"

    return server
