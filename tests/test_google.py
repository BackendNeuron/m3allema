import base64
import email
from pathlib import Path

import pytest
from mcp.server.mcpserver import MCPServer

from m3allema.domain.tools import Risk
from m3allema.integrations.google.auth import GoogleAuth, GoogleAuthError, TokenVault
from m3allema.integrations.google.gateways import (
    CalendarEvent,
    CellValue,
    Email,
    EmailSummary,
    OutgoingEmail,
    encode_email,
    extract_body,
)
from m3allema.tools.hub import ToolHub
from m3allema.tools.servers.calendar import create_calendar_server
from m3allema.tools.servers.gmail import create_gmail_server
from m3allema.tools.servers.sheets import create_sheets_server


class FakeGmail:
    def __init__(self) -> None:
        self.drafts: list[OutgoingEmail] = []
        self.sent: list[OutgoingEmail] = []
        self.archived: list[str] = []

    def search(self, query: str, limit: int) -> list[EmailSummary]:
        return [EmailSummary("m1", "t1", "Delta <ap@delta.example>", "Invoice 1041", "Mon", "Hi")]

    def get(self, email_id: str) -> Email:
        return Email(
            email_id,
            "t1",
            "ap@delta.example",
            "me@shop.example",
            "Invoice 1041",
            "Mon",
            "Please find the invoice attached.",
        )

    def create_draft(self, outgoing: OutgoingEmail) -> str:
        self.drafts.append(outgoing)
        return "d1"

    def send(self, outgoing: OutgoingEmail) -> str:
        self.sent.append(outgoing)
        return "s1"

    def archive(self, email_id: str) -> None:
        self.archived.append(email_id)


class FakeCalendar:
    def list_events(self, time_min: str, time_max: str, limit: int) -> list[CalendarEvent]:
        return [CalendarEvent("e1", "Supplier call", "2026-11-02T10:00", "2026-11-02T10:30")]

    def create_event(
        self,
        summary: str,
        start: str,
        end: str,
        attendees: list[str],
        description: str,
        location: str,
    ) -> CalendarEvent:
        return CalendarEvent("e2", summary, start, end, location, tuple(attendees))


class FakeSheets:
    def __init__(self) -> None:
        self.appended: list[list[CellValue]] = []

    def read(self, spreadsheet_id: str, cell_range: str) -> list[list[CellValue]]:
        return [["client", "amount"], ["Delta", 12500]]

    def append(self, spreadsheet_id: str, cell_range: str, rows: list[list[CellValue]]) -> int:
        self.appended.extend(rows)
        return sum(len(r) for r in rows)

    def update(self, spreadsheet_id: str, cell_range: str, rows: list[list[CellValue]]) -> int:
        return sum(len(r) for r in rows)


def hub_for(**servers: MCPServer) -> ToolHub:
    return ToolHub(servers)


async def test_gmail_risk_levels_send_is_external() -> None:
    async with hub_for(gmail=create_gmail_server(FakeGmail())) as hub:
        risks = {s.name: s.risk for s in hub.specs()}
    assert risks == {
        "gmail__search_emails": Risk.READ,
        "gmail__read_email": Risk.READ,
        "gmail__create_draft": Risk.WRITE,
        "gmail__archive_email": Risk.WRITE,
        "gmail__send_email": Risk.EXTERNAL,
    }


async def test_gmail_tools_use_the_gateway() -> None:
    gmail = FakeGmail()
    async with hub_for(gmail=create_gmail_server(gmail)) as hub:
        found = await hub.call("gmail__search_emails", {"query": "invoice"})
        read = await hub.call("gmail__read_email", {"email_id": "m1"})
        draft = await hub.call(
            "gmail__create_draft",
            {
                "to": "ap@delta.example",
                "subject": "Re",
                "body": "Thanks",
                "reply_to_email_id": "m1",
            },
        )
        await hub.call("gmail__archive_email", {"email_id": "m1"})
    assert "[m1]" in found.content
    assert "Please find the invoice" in read.content
    assert "Draft saved" in draft.content
    assert gmail.drafts[0].reply_to == "m1"
    assert gmail.archived == ["m1"]
    assert gmail.sent == []


async def test_calendar_and_sheets_tools() -> None:
    sheets = FakeSheets()
    async with hub_for(
        calendar=create_calendar_server(FakeCalendar()), sheets=create_sheets_server(sheets)
    ) as hub:
        risks = {s.name: s.risk for s in hub.specs()}
        events = await hub.call("calendar__list_events", {})
        table = await hub.call("sheets__read_range", {"spreadsheet_id": "x", "cell_range": "A1:B2"})
        await hub.call(
            "sheets__append_rows",
            {"spreadsheet_id": "x", "cell_range": "A1", "rows": [["Nile", 9800]]},
        )
    assert risks["calendar__create_event"] is Risk.EXTERNAL
    assert risks["sheets__append_rows"] is Risk.WRITE
    assert risks["sheets__update_range"] is Risk.EXTERNAL
    assert "Supplier call" in events.content
    assert table.content == "client,amount\nDelta,12500"
    assert sheets.appended == [["Nile", 9800]]


def test_encode_email_builds_a_threaded_reply() -> None:
    resource = encode_email(
        OutgoingEmail("a@x.example", "Re: Invoice", "Paid today.", cc="b@x.example"),
        thread_id="t1",
        in_reply_to="<abc@mail>",
    )
    assert resource["threadId"] == "t1"
    parsed = email.message_from_bytes(base64.urlsafe_b64decode(resource["raw"]))
    assert parsed["To"] == "a@x.example"
    assert parsed["Cc"] == "b@x.example"
    assert parsed["In-Reply-To"] == "<abc@mail>"
    assert parsed.get_payload().strip() == "Paid today."


def b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def test_extract_body_prefers_plain_text_and_falls_back_to_html() -> None:
    multipart = {
        "mimeType": "multipart/alternative",
        "parts": [
            {"mimeType": "text/html", "body": {"data": b64("<p>HTML</p>")}},
            {"mimeType": "text/plain", "body": {"data": b64("Plain")}},
        ],
    }
    assert extract_body(multipart) == "Plain"
    html_only = {"mimeType": "text/html", "body": {"data": b64("<p>Hello <b>there</b></p>")}}
    assert extract_body(html_only) == "Hello\nthere"


def test_token_vault_encrypts_and_rejects_wrong_key(tmp_path: Path) -> None:
    path = tmp_path / "token.enc"
    vault = TokenVault(path, TokenVault.new_key())
    vault.save('{"token": "secret-value"}')
    assert b"secret-value" not in path.read_bytes()
    assert vault.load() == '{"token": "secret-value"}'
    with pytest.raises(GoogleAuthError, match="cannot decrypt"):
        TokenVault(path, TokenVault.new_key()).load()


def test_not_connected_is_a_clear_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("M3ALLEMA_SECRET_KEY", raising=False)
    auth = GoogleAuth(tmp_path / ".m3allema", tmp_path / ".env")
    assert not auth.is_connected
    with pytest.raises(GoogleAuthError, match="m3allema google connect"):
        auth.credentials()
    assert auth.disconnect() is False
