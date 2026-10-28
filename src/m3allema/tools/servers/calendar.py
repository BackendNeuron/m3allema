"""Google Calendar MCP server: list events and create events with invitations."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from mcp.server.mcpserver import MCPServer

from m3allema.integrations.google.gateways import CalendarEvent, CalendarGateway
from m3allema.tools.servers._annotations import OUTWARD, READ_ONLY
from m3allema.tools.servers._tool import tool

MAX_EVENTS = 100


def _format(event: CalendarEvent) -> str:
    parts = [f"[{event.id}] {event.start} -> {event.end} | {event.summary}"]
    if event.location:
        parts.append(f"at {event.location}")
    if event.attendees:
        parts.append(f"with {', '.join(event.attendees)}")
    return " ".join(parts)


def create_calendar_server(gateway: CalendarGateway) -> MCPServer:
    """Build a Calendar server on top of ``gateway``."""
    server = MCPServer(
        "calendar",
        instructions="The owner's primary Google Calendar. Times are RFC 3339, "
        "for example 2026-11-02T10:00:00+02:00.",
    )

    @tool(server, annotations=READ_ONLY)
    async def list_events(start: str | None = None, end: str | None = None, limit: int = 25) -> str:
        """List events between two RFC 3339 times. Defaults to the next 7 days."""
        now = datetime.now(UTC)
        time_min = start or now.isoformat()
        time_max = end or (now + timedelta(days=7)).isoformat()
        events = await asyncio.to_thread(
            gateway.list_events, time_min, time_max, max(1, min(limit, MAX_EVENTS))
        )
        return "\n".join(_format(e) for e in events) or "No events in that period."

    @tool(server, annotations=OUTWARD)
    async def create_event(
        summary: str,
        start: str,
        end: str,
        attendees: list[str] | None = None,
        description: str = "",
        location: str = "",
    ) -> str:
        """Create an event on the primary calendar. Attendees receive email invitations."""
        event = await asyncio.to_thread(
            gateway.create_event, summary, start, end, attendees or [], description, location
        )
        return f"Created: {_format(event)} {event.link}".rstrip()

    return server
