"""Google Sheets MCP server: read ranges, append rows, overwrite ranges."""

from __future__ import annotations

import asyncio

from mcp.server.mcpserver import MCPServer

from m3allema.integrations.google.gateways import CellValue, SheetsGateway
from m3allema.tools.servers._annotations import LOCAL_DESTRUCTIVE, LOCAL_WRITE, READ_ONLY
from m3allema.tools.servers.excel import rows_to_csv

MAX_CELLS = 10_000


def create_sheets_server(gateway: SheetsGateway) -> MCPServer:
    """Build a Sheets server on top of ``gateway``."""
    server = MCPServer(
        "sheets",
        instructions="Google Sheets. The spreadsheet id is the long code in its URL "
        "(docs.google.com/spreadsheets/d/<id>/). Ranges use A1 notation, e.g. 'Sales!A1:D50'.",
    )

    @server.tool(annotations=READ_ONLY)
    async def read_range(spreadsheet_id: str, cell_range: str) -> str:
        """Read an A1 range as CSV, for example 'Invoices!A1:F200'."""
        rows = await asyncio.to_thread(gateway.read, spreadsheet_id, cell_range)
        cells = sum(len(r) for r in rows)
        if cells > MAX_CELLS:
            raise ValueError(f"the range has {cells} cells; read a smaller range")
        return rows_to_csv(rows) or "(empty range)"

    @server.tool(annotations=LOCAL_WRITE)
    async def append_rows(spreadsheet_id: str, cell_range: str, rows: list[list[CellValue]]) -> str:
        """Add rows after the last row of a table (existing cells are not changed)."""
        updated = await asyncio.to_thread(gateway.append, spreadsheet_id, cell_range, rows)
        return f"Appended {len(rows)} rows ({updated} cells)"

    @server.tool(annotations=LOCAL_DESTRUCTIVE)
    async def update_range(
        spreadsheet_id: str, cell_range: str, rows: list[list[CellValue]]
    ) -> str:
        """Overwrite the cells of an A1 range with new values."""
        updated = await asyncio.to_thread(gateway.update, spreadsheet_id, cell_range, rows)
        return f"Updated {updated} cells in {cell_range}"

    return server
