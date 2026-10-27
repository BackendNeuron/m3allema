from pathlib import Path

import pytest
from pypdf import PdfWriter

from m3allema.domain.tools import Risk
from m3allema.tools.hub import ToolHub
from m3allema.tools.servers.shell import SandboxSettings, docker_command, run_sandboxed


async def test_excel_write_append_and_read(tmp_path: Path) -> None:
    async with ToolHub.from_config(["excel"], {}, tmp_path) as hub:
        risks = {s.name: s.risk for s in hub.specs()}
        assert risks["excel__read_sheet"] is Risk.READ
        assert risks["excel__write_sheet"] is Risk.WRITE

        rows = [["client", "amount"], ["Delta", 12500], ["Nile", 9800.5]]
        written = await hub.call("excel__write_sheet", {"path": "out/summary.xlsx", "rows": rows})
        assert not written.is_error, written.content
        await hub.call("excel__append_rows", {"path": "out/summary.xlsx", "rows": [["Giza", 1]]})

        sheets = await hub.call("excel__list_sheets", {"path": "out/summary.xlsx"})
        assert "Sheet1: 4 rows x 2 columns" in sheets.content
        read = await hub.call("excel__read_sheet", {"path": "out/summary.xlsx"})
        assert read.content.splitlines() == [
            "client,amount",
            "Delta,12500",
            "Nile,9800.5",
            "Giza,1",
        ]


async def test_excel_rejects_other_formats(tmp_path: Path) -> None:
    async with ToolHub.from_config(["excel"], {}, tmp_path) as hub:
        result = await hub.call("excel__read_sheet", {"path": "data.csv"})
    assert result.is_error


async def test_docx_write_then_read(tmp_path: Path) -> None:
    body = "# Overview\nSales grew.\n- Delta paid\n- Nile pending"
    async with ToolHub.from_config(["docs"], {}, tmp_path) as hub:
        written = await hub.call(
            "docs__write_docx", {"path": "report.docx", "title": "Weekly report", "body": body}
        )
        assert not written.is_error, written.content
        read = await hub.call("docs__read_document", {"path": "report.docx"})
    assert read.content.splitlines() == [
        "Weekly report",
        "Overview",
        "Sales grew.",
        "Delta paid",
        "Nile pending",
    ]


async def test_pdf_without_text_is_reported(tmp_path: Path) -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    with (tmp_path / "scan.pdf").open("wb") as handle:
        writer.write(handle)
    async with ToolHub.from_config(["docs"], {}, tmp_path) as hub:
        result = await hub.call("docs__read_document", {"path": "scan.pdf"})
    assert "page 1" in result.content


async def test_read_file_pages_long_files(tmp_path: Path) -> None:
    (tmp_path / "long.txt").write_text("\n".join(f"line {n}" for n in range(1, 1001)), "utf-8")
    async with ToolHub.from_config(["files"], {}, tmp_path) as hub:
        first = await hub.call("files__read_file", {"path": "long.txt"})
        later = await hub.call("files__read_file", {"path": "long.txt", "start_line": 401})
    assert "continue with start_line=401" in first.content
    assert later.content.startswith("line 401")


def test_shell_sandbox_is_locked_down(tmp_path: Path) -> None:
    args = docker_command(tmp_path, "ls", SandboxSettings())
    assert args[:3] == ["docker", "run", "--rm"]
    for flag, value in [("--network", "none"), ("--cap-drop", "ALL"), ("--user", "1000:1000")]:
        assert args[args.index(flag) + 1] == value
    assert args[-3:] == ["sh", "-c", "ls"]


async def test_shell_explains_missing_docker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("m3allema.tools.servers.shell.shutil.which", lambda _name: None)
    with pytest.raises(RuntimeError, match="Docker is not installed"):
        await run_sandboxed(tmp_path, "ls", SandboxSettings())
