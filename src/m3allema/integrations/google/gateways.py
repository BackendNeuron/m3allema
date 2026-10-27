"""Thin gateways over the Gmail, Calendar and Sheets APIs.

Each gateway is a protocol plus one Google implementation. Tool servers depend
only on the protocol, so tests use in-memory fakes and the Google SDK stays at
the edge. The SDK is synchronous; the tool servers call gateways in a thread.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Any, Protocol

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from m3allema.text import html_to_text

CellValue = str | int | float | bool | None


@dataclass(frozen=True, slots=True)
class EmailSummary:
    """One email in a search result."""

    id: str
    thread_id: str
    sender: str
    subject: str
    date: str
    snippet: str


@dataclass(frozen=True, slots=True)
class Email:
    """A full email."""

    id: str
    thread_id: str
    sender: str
    to: str
    subject: str
    date: str
    body: str
    labels: tuple[str, ...] = field(default_factory=tuple)
    message_id: str = ""


@dataclass(frozen=True, slots=True)
class OutgoingEmail:
    """An email to draft or send. ``reply_to`` is the Gmail id of the email answered."""

    to: str
    subject: str
    body: str
    cc: str = ""
    reply_to: str | None = None


@dataclass(frozen=True, slots=True)
class CalendarEvent:
    """One calendar event."""

    id: str
    summary: str
    start: str
    end: str
    location: str = ""
    attendees: tuple[str, ...] = field(default_factory=tuple)
    link: str = ""


class GmailGateway(Protocol):
    """What the Gmail tools need."""

    def search(self, query: str, limit: int) -> list[EmailSummary]:
        """Find emails using Gmail search syntax."""
        ...

    def get(self, email_id: str) -> Email:
        """Fetch one email with its plain-text body."""
        ...

    def create_draft(self, email: OutgoingEmail) -> str:
        """Save a draft; return its id."""
        ...

    def send(self, email: OutgoingEmail) -> str:
        """Send an email; return the sent message id."""
        ...

    def archive(self, email_id: str) -> None:
        """Remove an email from the inbox (it stays in All Mail)."""
        ...


class CalendarGateway(Protocol):
    """What the Calendar tools need."""

    def list_events(self, time_min: str, time_max: str, limit: int) -> list[CalendarEvent]:
        """Events on the primary calendar between two RFC 3339 times."""
        ...

    def create_event(
        self,
        summary: str,
        start: str,
        end: str,
        attendees: list[str],
        description: str,
        location: str,
    ) -> CalendarEvent:
        """Create an event; attendees receive invitations."""
        ...


class SheetsGateway(Protocol):
    """What the Sheets tools need."""

    def read(self, spreadsheet_id: str, cell_range: str) -> list[list[CellValue]]:
        """Values in an A1 range."""
        ...

    def append(self, spreadsheet_id: str, cell_range: str, rows: list[list[CellValue]]) -> int:
        """Append rows after a table; return how many cells were updated."""
        ...

    def update(self, spreadsheet_id: str, cell_range: str, rows: list[list[CellValue]]) -> int:
        """Overwrite an A1 range; return how many cells were updated."""
        ...


class GoogleGmail:
    """Gmail API implementation of :class:`GmailGateway`."""

    def __init__(self, credentials: Credentials) -> None:
        self._messages = build("gmail", "v1", credentials=credentials, cache_discovery=False)

    def search(self, query: str, limit: int) -> list[EmailSummary]:
        """Find emails using Gmail search syntax."""
        users = self._messages.users()
        listing = users.messages().list(userId="me", q=query, maxResults=limit).execute()
        results: list[EmailSummary] = []
        for ref in listing.get("messages", []):
            message = (
                users.messages()
                .get(
                    userId="me",
                    id=ref["id"],
                    format="metadata",
                    metadataHeaders=["From", "Subject", "Date"],
                )
                .execute()
            )
            headers = _headers(message)
            results.append(
                EmailSummary(
                    id=message["id"],
                    thread_id=message["threadId"],
                    sender=headers.get("from", ""),
                    subject=headers.get("subject", ""),
                    date=headers.get("date", ""),
                    snippet=message.get("snippet", ""),
                )
            )
        return results

    def get(self, email_id: str) -> Email:
        """Fetch one email with its plain-text body."""
        message = (
            self._messages.users().messages().get(userId="me", id=email_id, format="full").execute()
        )
        headers = _headers(message)
        return Email(
            id=message["id"],
            thread_id=message["threadId"],
            sender=headers.get("from", ""),
            to=headers.get("to", ""),
            subject=headers.get("subject", ""),
            date=headers.get("date", ""),
            body=extract_body(message.get("payload", {})),
            labels=tuple(message.get("labelIds", [])),
            message_id=headers.get("message-id", ""),
        )

    def create_draft(self, email: OutgoingEmail) -> str:
        """Save a draft; return its id."""
        draft = (
            self._messages.users()
            .drafts()
            .create(userId="me", body={"message": self._encode(email)})
            .execute()
        )
        return str(draft["id"])

    def send(self, email: OutgoingEmail) -> str:
        """Send an email; return the sent message id."""
        sent = (
            self._messages.users().messages().send(userId="me", body=self._encode(email)).execute()
        )
        return str(sent["id"])

    def archive(self, email_id: str) -> None:
        """Remove an email from the inbox (it stays in All Mail)."""
        self._messages.users().messages().modify(
            userId="me", id=email_id, body={"removeLabelIds": ["INBOX"]}
        ).execute()

    def _encode(self, email: OutgoingEmail) -> dict[str, Any]:
        thread_id: str | None = None
        in_reply_to = ""
        if email.reply_to:
            original = self.get(email.reply_to)
            thread_id, in_reply_to = original.thread_id, original.message_id
        return encode_email(email, thread_id=thread_id, in_reply_to=in_reply_to)


class GoogleCalendar:
    """Calendar API implementation of :class:`CalendarGateway`."""

    def __init__(self, credentials: Credentials) -> None:
        self._events = build("calendar", "v3", credentials=credentials, cache_discovery=False)

    def list_events(self, time_min: str, time_max: str, limit: int) -> list[CalendarEvent]:
        """Events on the primary calendar between two RFC 3339 times."""
        response = (
            self._events.events()
            .list(
                calendarId="primary",
                timeMin=time_min,
                timeMax=time_max,
                maxResults=limit,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        return [_to_event(item) for item in response.get("items", [])]

    def create_event(
        self,
        summary: str,
        start: str,
        end: str,
        attendees: list[str],
        description: str,
        location: str,
    ) -> CalendarEvent:
        """Create an event; attendees receive invitations."""
        body = {
            "summary": summary,
            "description": description,
            "location": location,
            "start": {"dateTime": start},
            "end": {"dateTime": end},
            "attendees": [{"email": a} for a in attendees],
        }
        created = (
            self._events.events()
            .insert(calendarId="primary", body=body, sendUpdates="all")
            .execute()
        )
        return _to_event(created)


class GoogleSheets:
    """Sheets API implementation of :class:`SheetsGateway`."""

    def __init__(self, credentials: Credentials) -> None:
        service = build("sheets", "v4", credentials=credentials, cache_discovery=False)
        self._values = service.spreadsheets().values()

    def read(self, spreadsheet_id: str, cell_range: str) -> list[list[CellValue]]:
        """Values in an A1 range."""
        response = self._values.get(spreadsheetId=spreadsheet_id, range=cell_range).execute()
        values: list[list[CellValue]] = response.get("values", [])
        return values

    def append(self, spreadsheet_id: str, cell_range: str, rows: list[list[CellValue]]) -> int:
        """Append rows after a table; return how many cells were updated."""
        response = self._values.append(
            spreadsheetId=spreadsheet_id,
            range=cell_range,
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": rows},
        ).execute()
        return int(response.get("updates", {}).get("updatedCells", 0))

    def update(self, spreadsheet_id: str, cell_range: str, rows: list[list[CellValue]]) -> int:
        """Overwrite an A1 range; return how many cells were updated."""
        response = self._values.update(
            spreadsheetId=spreadsheet_id,
            range=cell_range,
            valueInputOption="USER_ENTERED",
            body={"values": rows},
        ).execute()
        return int(response.get("updatedCells", 0))


def encode_email(
    email: OutgoingEmail, *, thread_id: str | None = None, in_reply_to: str = ""
) -> dict[str, Any]:
    """Build the Gmail API ``message`` resource for an outgoing email."""
    mime = EmailMessage()
    mime["To"] = email.to
    if email.cc:
        mime["Cc"] = email.cc
    mime["Subject"] = email.subject
    if in_reply_to:
        mime["In-Reply-To"] = in_reply_to
        mime["References"] = in_reply_to
    mime.set_content(email.body)
    resource: dict[str, Any] = {"raw": base64.urlsafe_b64encode(mime.as_bytes()).decode()}
    if thread_id:
        resource["threadId"] = thread_id
    return resource


def extract_body(payload: dict[str, Any]) -> str:
    """Return the plain-text body of a Gmail payload, falling back to HTML converted to text."""
    plain = _find_part(payload, "text/plain")
    if plain is not None:
        return plain
    html = _find_part(payload, "text/html")
    return html_to_text(html) if html is not None else ""


def _find_part(payload: dict[str, Any], mime_type: str) -> str | None:
    if payload.get("mimeType") == mime_type and payload.get("body", {}).get("data"):
        data = payload["body"]["data"]
        return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode(
            "utf-8", errors="replace"
        )
    for part in payload.get("parts", []) or []:
        found = _find_part(part, mime_type)
        if found is not None:
            return found
    return None


def _headers(message: dict[str, Any]) -> dict[str, str]:
    return {h["name"].lower(): h["value"] for h in message.get("payload", {}).get("headers", [])}


def _to_event(item: dict[str, Any]) -> CalendarEvent:
    start = item.get("start", {})
    end = item.get("end", {})
    return CalendarEvent(
        id=item.get("id", ""),
        summary=item.get("summary", "(no title)"),
        start=start.get("dateTime") or start.get("date", ""),
        end=end.get("dateTime") or end.get("date", ""),
        location=item.get("location", ""),
        attendees=tuple(a.get("email", "") for a in item.get("attendees", [])),
        link=item.get("htmlLink", ""),
    )
